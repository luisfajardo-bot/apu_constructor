"""Servicio de autoría de base: crear insumos/APUs (individual + Excel)."""
import io
import openpyxl
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo
from apu_tool.servicio import autoria


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo("100", "CEMENTO GRIS", "KG", "MAT", 1000, "PRECIO IDU"),
        Insumo("200", "ARENA", "M3", "MAT", 50000, "PRECIO IDU")])
    alm.apus.insert_apus([Apu("A1", "MURO EXISTENTE", "M2", "DIURNO", "ESTR")])
    return alm


# ---------------------------------------------------------------- individual
def test_crear_insumo_ok(tmp_path):
    alm = _alm(tmp_path)
    out = autoria.crear_insumo(alm, {"codigo": "300", "nombre": "GRAVA", "unidad": "M3",
                                     "grupo": "MAT", "precio": 80000, "fuente": "PRECIO IDU"})
    assert out["codigo"] == "300" and out["precio"] == 80000
    assert any(i.codigo == "300" for i in alm.precios.get_candidatos("300"))


def test_crear_insumo_duplicado_y_validacion(tmp_path):
    alm = _alm(tmp_path)
    with pytest.raises(ValueError):
        autoria.crear_insumo(alm, {"codigo": "100", "nombre": "CEMENTO GRIS", "precio": 1})
    with pytest.raises(ValueError):
        autoria.crear_insumo(alm, {"codigo": "", "nombre": "X", "precio": 1})
    with pytest.raises(ValueError):
        autoria.crear_insumo(alm, {"codigo": "9", "nombre": "X", "precio": -5})


def test_crear_apu_con_composicion(tmp_path):
    alm = _alm(tmp_path)
    out = autoria.crear_apu(alm, {"codigo": "B2", "turno": "DIURNO", "nombre": "PISO",
        "unidad": "M2", "grupo": "ACAB",
        "componentes": [{"insumo_codigo": "100", "rendimiento": 2.0},
                        {"insumo_codigo": "200", "rendimiento": 0.5}]})
    assert out["codigo"] == "B2" and out["n_componentes"] == 2
    comps = alm.apus.get_components("B2", "DIURNO")
    # nombre/unidad se resolvieron desde la base
    assert comps[0].insumo_nombre == "CEMENTO GRIS" and comps[0].unidad == "KG"


def test_crear_apu_validaciones(tmp_path):
    alm = _alm(tmp_path)
    with pytest.raises(ValueError):  # turno inválido
        autoria.crear_apu(alm, {"codigo": "Z", "turno": "TARDE", "nombre": "X"})
    with pytest.raises(ValueError):  # rendimiento <= 0
        autoria.crear_apu(alm, {"codigo": "Z", "turno": "DIURNO", "nombre": "X",
            "componentes": [{"insumo_codigo": "100", "rendimiento": 0}]})
    with pytest.raises(ValueError):  # duplicado (A1, DIURNO)
        autoria.crear_apu(alm, {"codigo": "A1", "turno": "DIURNO", "nombre": "MURO"})


# ---------------------------------------------------------------- import insumos
def _xlsx_insumos() -> bytes:
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["codigo", "nombre", "unidad", "grupo", "precio", "fuente"])
    ws.append(["300", "GRAVA COMUN", "M3", "MAT", 80000, "PRECIO IDU"])   # crear
    ws.append(["100", "CEMENTO GRIS", "KG", "MAT", 1200, "PRECIO IDU"])   # ya existe
    ws.append(["", "SIN CODIGO", "UN", "", 10, ""])                       # inválida
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def test_import_insumos_preview_y_aplicar(tmp_path):
    alm = _alm(tmp_path)
    data = _xlsx_insumos()
    prev = autoria.preview_importar_insumos(alm, data, "insumos.xlsx")
    assert [c["codigo"] for c in prev["crear"]] == ["300"]
    assert [c["codigo"] for c in prev["ya_existe"]] == ["100"]
    assert len(prev["invalida"]) == 1
    res = autoria.aplicar_importar_insumos(alm, data, "insumos.xlsx")
    assert res["creados"] == 1
    assert any(i.codigo == "300" for i in alm.precios.get_candidatos("300"))


# ---------------------------------------------------------------- import APUs
def _xlsx_apus() -> bytes:
    wb = openpyxl.Workbook(); ws = wb.active
    # formato hoja APUS: actividad(0) cod_idu(1) unidad(2) insumo(3) cod(4) und(5)
    #                    rendimiento(6) inv(7) precio(8) costo(9) turno(10)
    ws.title = "APUS"
    ws.append(["ACTIVIDAD","COD IDU","UN","INSUMO","COD","UND","RENDIMIENTO","INV","PRECIO","COSTO","TURNO"])
    ws.append(["MURO NUEVO ESPECIAL","7777","M2","","","","","","","","DIURNO"])  # cabecera APU
    ws.append(["","","","CEMENTO","100","KG",2.5,"",900,"",""])                   # componente
    ws.append(["","","","ARENA","200","M3",0.5,"",50,"",""])                      # componente
    ws.append(["MURO EXISTENTE","A1","M2","","","","","","","","DIURNO"])         # ya existe
    ws.append(["","","","CEMENTO","100","KG",1.0,"",900,"",""])
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def test_import_apus_preview_y_aplicar(tmp_path):
    alm = _alm(tmp_path)
    data = _xlsx_apus()
    prev = autoria.preview_importar_apus(alm, data)
    codigos_crear = {c["codigo"] for c in prev["crear"]}
    assert "7777" in codigos_crear
    assert any(c["codigo"] == "A1" for c in prev["ya_existe"])
    nuevo = next(c for c in prev["crear"] if c["codigo"] == "7777")
    assert nuevo["n_componentes"] == 2 and nuevo["turno"] == "DIURNO"
    res = autoria.aplicar_importar_apus(alm, data)
    assert res["creados"] == 1
    assert alm.apus.get_apu("7777", "DIURNO").nombre == "MURO NUEVO ESPECIAL"
    assert len(alm.apus.get_components("7777", "DIURNO")) == 2


def test_import_apus_sin_hoja_apus(tmp_path):
    alm = _alm(tmp_path)
    wb = openpyxl.Workbook(); wb.active.append(["x"]); buf = io.BytesIO(); wb.save(buf)
    with pytest.raises(ValueError):
        autoria.preview_importar_apus(alm, buf.getvalue())
