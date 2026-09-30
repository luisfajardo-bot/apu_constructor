# tests/test_api_notas.py
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.dominio import privacy
from apu_tool.nucleo.models import Apu, Insumo, Perfil
from apu_tool.servicio.app import create_app
from apu_tool.servicio.auth import usuario_actual
from fastapi.testclient import TestClient


def _app(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo("4520", 'DUCTO PVC TIPO TDP D=3"', "ML", "DUCTOS", 10747.0, "COSTO INTERNO")])
    alm.apus.insert_apus([Apu("4859", "EXCAVACION MANUAL", "M3", "NOCTURNO", "EXCAV")])
    return create_app(almacen=alm), alm


def _como(app, user_id="u-ed", rol="editor"):
    app.dependency_overrides[usuario_actual] = lambda: Perfil(
        user_id=user_id, email=f"{user_id}@obra.co", rol=rol, estado="activo")
    return TestClient(app)


INS = {"entidad": "insumo", "codigo": "4520", "nombre": 'ducto pvc tipo tdp d=3"'}
APU = {"entidad": "apu", "codigo": "4859", "turno": "nocturno"}


def test_crear_y_listar_insumo_por_codigo_y_nombre_normalizado(tmp_path):
    app, _ = _app(tmp_path)
    cli = _como(app)
    r = cli.post("/api/notas", json={**INS, "texto": "  Cotización Ferretería X  "})
    assert r.status_code == 200, r.text
    n = r.json()
    assert n["texto"] == "Cotización Ferretería X" and n["es_mia"] is True
    assert n["etiqueta"] == '4520 · DUCTO PVC TIPO TDP D=3"'
    assert n["puede_editar"] is True and n["puede_borrar"] is True
    assert n["dueno"] == {"entidad": "insumo", "codigo": "4520",
                          "nombre": 'DUCTO PVC TIPO TDP D=3"', "turno": ""}
    lista = cli.get("/api/notas", params=INS).json()
    assert [x["texto"] for x in lista] == ["Cotización Ferretería X"]


def test_apu_por_turno_diurno_y_nocturno_separados(tmp_path):
    app, _ = _app(tmp_path)
    cli = _como(app)
    assert cli.post("/api/notas", json={**APU, "texto": "medido en obra"}).status_code == 200
    assert cli.get("/api/notas", params=APU).json()[0]["etiqueta"] == \
        "4859 · NOCTURNO · EXCAVACION MANUAL"
    # el diurno no existe como APU: no se puede anotar
    r = cli.post("/api/notas", json={**APU, "turno": "DIURNO", "texto": "x"})
    assert r.status_code == 400


@pytest.mark.parametrize("texto", ["", "   ", "x" * 4001])
def test_texto_invalido_es_400(tmp_path, texto):
    app, _ = _app(tmp_path)
    assert _como(app).post("/api/notas", json={**INS, "texto": texto}).status_code == 400


def test_dueno_inexistente_o_entidad_rara_es_400(tmp_path):
    app, _ = _app(tmp_path)
    cli = _como(app)
    assert cli.post("/api/notas", json={**INS, "nombre": "OTRO", "texto": "x"}).status_code == 400
    assert cli.post("/api/notas", json={**INS, "entidad": "corrida", "texto": "x"}).status_code == 400


def test_permisos(tmp_path):
    app, alm = _app(tmp_path)
    nid = _como(app, "u-ed").post("/api/notas", json={**INS, "texto": "mía"}).json()["id"]

    # consulta lee pero no escribe
    consulta = _como(app, "u-c", "consulta")
    assert consulta.get("/api/notas", params=INS).status_code == 200
    assert consulta.post("/api/notas", json={**INS, "texto": "x"}).status_code == 403

    # otro editor ve la nota sin botones, y no puede editarla ni borrarla
    otro = _como(app, "u-otro", "editor")
    vista = otro.get("/api/notas", params=INS).json()[0]
    assert vista["es_mia"] is False and vista["puede_editar"] is False
    assert vista["puede_borrar"] is False
    assert otro.patch(f"/api/notas/{nid}", json={"texto": "pisada"}).status_code == 403
    assert otro.delete(f"/api/notas/{nid}").status_code == 403

    # el Admin no edita lo ajeno, pero sí lo borra
    admin = _como(app, "u-adm", "admin")
    assert admin.get("/api/notas", params=INS).json()[0]["puede_borrar"] is True
    assert admin.patch(f"/api/notas/{nid}", json={"texto": "pisada"}).status_code == 403
    assert admin.delete(f"/api/notas/{nid}").status_code == 200
    assert admin.get("/api/notas", params=INS).json() == []
    assert admin.delete(f"/api/notas/{nid}").status_code == 404     # ya borrada


def test_editar_propia_y_auditoria(tmp_path):
    app, alm = _app(tmp_path)
    cli = _como(app)
    nid = cli.post("/api/notas", json={**INS, "texto": "v1"}).json()["id"]
    r = cli.patch(f"/api/notas/{nid}", json={"texto": "v2"})
    assert r.status_code == 200 and r.json()["texto"] == "v2" and r.json()["editada_en"]
    assert cli.patch("/api/notas/99999", json={"texto": "x"}).status_code == 404
    assert cli.delete(f"/api/notas/{nid}").status_code == 200
    items, _ = alm.auditoria.listar(entidad_tipo="nota")
    assert [i["accion"] for i in items] == ["nota.borrar", "nota.editar", "nota.crear"]
    assert items[1]["antes"] == {"texto": "v1"} and items[1]["despues"] == {"texto": "v2"}


def test_todas_solo_admin_con_filtros(tmp_path):
    app, _ = _app(tmp_path)
    _como(app, "u1").post("/api/notas", json={**INS, "texto": "cotización"})
    _como(app, "u2").post("/api/notas", json={**APU, "texto": "rendimiento"})
    assert _como(app, "u1", "editor").get("/api/notas/todas").status_code == 403
    admin = _como(app, "u-adm", "admin")
    r = admin.get("/api/notas/todas").json()
    assert r["total"] == 2 and r["items"][0]["texto"] == "rendimiento"
    assert r["items"][0]["dueno"] == {"entidad": "apu", "codigo": "4859",
                                      "nombre": "", "turno": "NOCTURNO"}
    assert admin.get("/api/notas/todas", params={"entidad": "insumo"}).json()["total"] == 1
    assert admin.get("/api/notas/todas", params={"autor": "u2"}).json()["total"] == 1
    assert admin.get("/api/notas/todas", params={"q": "COTIZ"}).json()["total"] == 1


def test_las_notas_no_pueden_ir_a_la_ia():
    for clave in ("nota", "notas", "ultima_nota"):
        with pytest.raises(privacy.PrivacyViolation):
            privacy.assert_no_money({"insumo": {"codigo": "1", clave: "cotización $45.000"}})
