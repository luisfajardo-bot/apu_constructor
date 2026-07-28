"""Editar e importar precios apuntando a una lista concreta."""
import io

import openpyxl
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Insumo
from apu_tool.servicio import autoria
from apu_tool.servicio import insumos as insumos_svc


@pytest.fixture()
def alm(tmp_path):
    a = Almacen(tmp_path / "p.db", tmp_path / "a.db", tmp_path / "c.db")
    a.reset()
    a.corridas.init_schema()
    a.precios.insert_insumos([
        Insumo("6140", "ACERO 60000 PSI", "KG", "MATERIAL", 3500.0, "PRECIO IDU"),
        Insumo("9", "CEMENTO GRIS", "KG", "MATERIAL", 900.0, "COSTO INTERNO"),
    ])
    return a


@pytest.fixture()
def np(alm):
    return alm.precios.crear_lista("NP Calle 13")


def _xlsx(filas: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    for f in filas:
        wb.active.append(f)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_listar_marca_sin_precio(alm, np):
    res = insumos_svc.listar(alm, lista_id=np)
    assert res["total"] == 2
    assert all(i["sin_precio"] for i in res["items"])
    assert all(not i["sin_precio"] for i in insumos_svc.listar(alm)["items"])


def test_listar_filtro_sin_precio(alm, np):
    iid = alm.precios.get_candidatos("6140")[0].id
    alm.precios.set_precio_por_id(iid, 4200.0, "ACTA NP", lista_id=np)
    res = insumos_svc.listar(alm, lista_id=np, sin_precio=True)
    assert [i["codigo"] for i in res["items"]] == ["9"]


def test_aplicar_cambios_escribe_en_la_lista(alm, np):
    iid = alm.precios.get_candidatos("6140")[0].id
    res = insumos_svc.aplicar_cambios(
        alm, [{"insumo_id": iid, "precio": 4200.0, "fuente": "ACTA NP"}], lista_id=np)
    assert res["aplicados"] == 1
    assert alm.precios.get_insumo_por_id(iid, lista_id=np).precio == 4200.0
    assert alm.precios.get_insumo_por_id(iid).precio == 3500.0        # Principal intacto


def test_detalle_trae_historial_de_la_lista(alm, np):
    iid = alm.precios.get_candidatos("6140")[0].id
    alm.precios.set_precio_por_id(iid, 4200.0, "ACTA NP", lista_id=np)
    d = insumos_svc.detalle(alm, iid, lista_id=np)
    assert d["insumo"]["precio"] == 4200.0
    assert [h["precio"] for h in d["historial"]] == [4200.0]


def test_crear_insumo_en_la_lista_np(alm, np):
    out = autoria.crear_insumo(alm, {"codigo": "NP-INS-1", "nombre": "GEOTEXTIL NT 2500",
                                     "unidad": "M2", "grupo": "MATERIAL",
                                     "precio": 8000.0, "fuente": "ACTA NP"}, lista_id=np)
    assert out["precio"] == 8000.0
    assert alm.precios.get_insumo_por_id(out["id"]).sin_precio is True


def test_import_preview_compara_contra_la_lista(alm, np):
    contenido = _xlsx([["codigo", "nombre", "precio", "fuente"],
                       ["6140", "ACERO 60000 PSI", 4200, "ACTA NP"]])
    prev = autoria.preview_importar_insumos(alm, contenido, "np.xlsx", lista_id=np)
    assert prev["actualizar"][0]["precio_actual"] == 0.0      # sin tarifa aún en NP
    assert prev["actualizar"][0]["precio_nuevo"] == 4200.0


def test_import_aplica_en_la_lista_y_crea_los_nuevos(alm, np):
    contenido = _xlsx([["codigo", "nombre", "precio", "fuente"],
                       ["6140", "ACERO 60000 PSI", 4200, "ACTA NP"],
                       ["NP-INS-1", "GEOTEXTIL NT 2500", 8000, "ACTA NP"]])
    res = autoria.aplicar_importar_insumos(alm, contenido, "np.xlsx", lista_id=np)
    assert res["creados"] == 1 and res["actualizados"] == 1 and res["errores"] == []
    assert alm.precios.get_candidatos("6140", lista_id=np)[0].precio == 4200.0
    assert alm.precios.get_candidatos("6140")[0].precio == 3500.0
    assert alm.precios.get_candidatos("NP-INS-1")[0].sin_precio is True


def test_import_rechaza_precio_no_positivo_en_la_lista(alm, np):
    contenido = _xlsx([["codigo", "nombre", "precio", "fuente"],
                       ["NP-INS-2", "MATERIAL DEL CLIENTE", 0, "ACTA NP"]])
    res = autoria.aplicar_importar_insumos(alm, contenido, "np.xlsx", lista_id=np)
    assert res["creados"] == 0 and len(res["errores"]) == 1
