"""Los endpoints de la ruta IDU: previsualizar y crear con confirmación."""
import json

import openpyxl
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu
from apu_tool.servicio.app import create_app
from tests.conftest import cliente
from tests.fixtures_idu import escribir_formulario

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture
def app_y_alm(tmp_path, monkeypatch):
    monkeypatch.setenv("APU_RATELIMIT_ENABLED", "false")
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    # Biblioteca mínima para que `_asegurar_biblioteca` no rebote.
    alm.apus.insert_apus([Apu(codigo="3007", nombre="REPLANTEO GENERAL",
                              unidad="M2", shift="DIURNO")])
    app = create_app()
    app.state.almacen = alm
    return app, alm


def _carpeta(alm) -> int:
    from apu_tool.servicio import carpetas as carpetas_svc
    return carpetas_svc.carpeta_sin_clasificar_id(alm)


def _subida(tmp_path, **kw):
    p = escribir_formulario(tmp_path / "f1.xlsx", **kw)
    return {"archivo": ("f1.xlsx", p.read_bytes(), XLSX)}


def test_previsualizar_devuelve_la_estructura(app_y_alm, tmp_path):
    app, _alm = app_y_alm
    r = cliente(app, "consulta").post("/api/corridas/previsualizar",
                                      data={"entidad": "IDU"}, files=_subida(tmp_path))
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["actividades"] == 5
    assert len(cuerpo["capitulos"]) == 2
    assert cuerpo["puede_aprobar"] is True


def test_previsualizar_no_crea_ninguna_corrida(app_y_alm, tmp_path):
    app, alm = app_y_alm
    cliente(app, "consulta").post("/api/corridas/previsualizar",
                                  data={"entidad": "IDU"}, files=_subida(tmp_path))
    assert alm.corridas.listar_corridas() == []


def test_previsualizar_rechaza_una_entidad_inventada(app_y_alm, tmp_path):
    app, _alm = app_y_alm
    r = cliente(app, "consulta").post("/api/corridas/previsualizar",
                                      data={"entidad": "ALCALDIA DE CHIA"},
                                      files=_subida(tmp_path))
    assert r.status_code == 400
    assert "Entidad desconocida" in r.json()["detail"]


def test_crear_idu_sin_confirmar_es_400(app_y_alm, tmp_path):
    app, alm = app_y_alm
    r = cliente(app, "consulta").post(
        "/api/corridas",
        data={"entidad": "IDU", "carpeta_id": _carpeta(alm), "turno": "DIURNO"},
        files=_subida(tmp_path))
    assert r.status_code == 400
    assert "confirm" in r.json()["detail"].lower()
    assert alm.corridas.listar_corridas() == []


def test_crear_idu_confirmada_encola_y_sella_el_origen(app_y_alm, tmp_path):
    app, alm = app_y_alm
    r = cliente(app, "consulta").post(
        "/api/corridas",
        data={"entidad": "IDU", "confirmada": "true",
              "carpeta_id": _carpeta(alm), "turno": "DIURNO"},
        files=_subida(tmp_path))
    assert r.status_code == 200
    assert r.json()["estado"] == "armando"
    origen = json.loads(alm.corridas.get_origen(r.json()["id"]))
    assert origen["entidad"] == "IDU"
    assert origen["estructura_confirmada"] is True


def test_crear_idu_con_error_bloqueante_es_400_aunque_diga_confirmada(app_y_alm, tmp_path):
    # El cliente puede mentir con `confirmada=true`: el servidor relee y revalida.
    app, alm = app_y_alm
    r = cliente(app, "consulta").post(
        "/api/corridas",
        data={"entidad": "IDU", "confirmada": "true",
              "carpeta_id": _carpeta(alm), "turno": "DIURNO"},
        files=_subida(tmp_path, sin_columna_cantidad=True))
    assert r.status_code == 400
    assert "falta_columna" in r.json()["detail"]
    assert alm.corridas.listar_corridas() == []


def test_el_doble_clic_no_crea_dos_corridas(app_y_alm, tmp_path):
    app, alm = app_y_alm
    c = cliente(app, "consulta")
    datos = {"entidad": "IDU", "confirmada": "true",
             "carpeta_id": _carpeta(alm), "turno": "DIURNO"}
    primera = c.post("/api/corridas", data=datos, files=_subida(tmp_path))
    segunda = c.post("/api/corridas", data=datos, files=_subida(tmp_path))
    assert primera.status_code == 200
    assert segunda.status_code == 409
    assert segunda.json()["detail"]["corrida_id"] == primera.json()["id"]
    assert len(alm.corridas.listar_corridas()) == 1


def test_sin_entidad_el_endpoint_se_comporta_como_siempre(app_y_alm, tmp_path):
    # Compatibilidad: el formulario viejo no manda `entidad` y sigue funcionando.
    app, alm = app_y_alm
    p = tmp_path / "plana.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["ITEM", "DESCRIPCION", "UNIDAD", "CANTIDAD", "PRECIO", "TURNO"])
    ws.append(["1", "REPLANTEO GENERAL", "M2", 10, 1000, "DIURNO"])
    wb.save(p)
    r = cliente(app, "consulta").post(
        "/api/corridas", data={"carpeta_id": _carpeta(alm), "turno": "DIURNO"},
        files={"archivo": ("plana.xlsx", p.read_bytes(), XLSX)})
    assert r.status_code == 200
    assert alm.corridas.get_origen(r.json()["id"]) is None


def test_la_lista_ilegible_sigue_dando_400(app_y_alm, tmp_path):
    # El comportamiento de siempre para un archivo que no se puede leer.
    app, alm = app_y_alm
    malo = tmp_path / "no-es.xlsx"
    malo.write_bytes(b"esto no es un zip")
    r = cliente(app, "consulta").post(
        "/api/corridas", data={"carpeta_id": _carpeta(alm), "turno": "DIURNO"},
        files={"archivo": ("no-es.xlsx", malo.read_bytes(), XLSX)})
    assert r.status_code == 400
    assert alm.corridas.listar_corridas() == []


def test_previsualizar_exige_estar_autenticado(app_y_alm, tmp_path):
    # Mismo rol que crear una corrida: `consulta`. Sin override de auth, 401.
    app, _alm = app_y_alm
    from fastapi.testclient import TestClient
    r = TestClient(app).post("/api/corridas/previsualizar",
                             data={"entidad": "IDU"}, files=_subida(tmp_path))
    assert r.status_code in (401, 403)
