# tests/test_servicio_insumos.py
import io

import openpyxl
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Insumo
from apu_tool.servicio import insumos as svc


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo("100", "Concreto 3000 PSI", "M3", "CONCRETOS", 350000.0, "COSTO INTERNO"),
        Insumo("200", "Acero de refuerzo", "KG", "ACEROS", 4500.0, "PRECIO IDU")])
    return alm


def test_listar_y_clasificacion(tmp_path):
    alm = _alm(tmp_path)
    out = svc.listar(alm)
    assert out["total"] == 2
    by_cod = {i["codigo"]: i for i in out["items"]}
    assert by_cod["200"]["clasificacion"] == "publico"      # PRECIO IDU
    assert by_cod["100"]["clasificacion"] == "interno"      # COSTO INTERNO


def test_detalle_con_historial(tmp_path):
    alm = _alm(tmp_path)
    iid = alm.precios.get_candidatos("100")[0].id
    d = svc.detalle(alm, iid)
    assert d["insumo"]["codigo"] == "100" and len(d["historial"]) >= 1
    assert svc.detalle(alm, 99999) is None


def test_aplicar_cambios_ok_y_errores(tmp_path):
    alm = _alm(tmp_path)
    iid = alm.precios.get_candidatos("100")[0].id
    iid2 = alm.precios.get_candidatos("200")[0].id
    res = svc.aplicar_cambios(alm, [
        {"insumo_id": iid, "precio": 380000.0, "fuente": "COMPRAS"},
        {"insumo_id": 99999, "precio": 1.0, "fuente": "X"},      # id malo
        {"insumo_id": iid2, "precio": -5.0, "fuente": "Y"}])     # precio inválido
    assert res["aplicados"] == 1 and len(res["errores"]) == 2
    assert alm.precios.get_insumo_por_id(iid).precio == 380000.0


def _xlsx_bytes(filas):
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["CODIGO", "PRECIO", "FUENTE"])
    for f in filas:
        ws.append(f)
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def test_preview_import_reconocido_y_no_encontrado(tmp_path):
    alm = _alm(tmp_path)
    contenido = _xlsx_bytes([["100", 390000, "COMPRAS"], ["999", 10, "X"]])
    out = svc.preview_import(alm, contenido, "lista.xlsx")
    assert len(out["cambios"]) == 1 and out["cambios"][0]["codigo"] == "100"
    assert out["cambios"][0]["precio_nuevo"] == 390000
    assert len(out["no_encontrados"]) == 1 and out["no_encontrados"][0]["codigo"] == "999"


def test_preview_transformar_operaciones(tmp_path):
    alm = _alm(tmp_path)
    out = svc.preview_transformar(alm, {"grupo": "CONCRETOS"},
                                  {"tipo": "precio_pct", "valor": 10})
    assert out["afectados"] == 1
    c = out["cambios"][0]
    assert c["codigo"] == "100" and c["precio_nuevo"] == 385000.0    # 350000 * 1.10

    out2 = svc.preview_transformar(alm, {"fuente": "PRECIO IDU"},
                                   {"tipo": "fuente", "valor": "IDU 2026"})
    assert out2["afectados"] == 1 and out2["cambios"][0]["fuente_nueva"] == "IDU 2026"


def test_preview_transformar_precio_factor(tmp_path):
    alm = _alm(tmp_path)
    out = svc.preview_transformar(alm, {"grupo": "CONCRETOS"},
                                  {"tipo": "precio_factor", "valor": 2.0})
    assert out["afectados"] == 1
    assert out["cambios"][0]["precio_nuevo"] == 700000.0   # 350000 * 2.0


def test_preview_transformar_precio_set(tmp_path):
    alm = _alm(tmp_path)
    out = svc.preview_transformar(alm, {"grupo": "CONCRETOS"},
                                  {"tipo": "precio_set", "valor": 999.0})
    assert out["afectados"] == 1
    assert out["cambios"][0]["precio_nuevo"] == 999.0


def _xlsx_bytes_headers(headers, filas):
    """Construye un xlsx con encabezados arbitrarios."""
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(headers)
    for f in filas:
        ws.append(f)
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def test_preview_transformar_filtro_clasificacion(tmp_path):
    alm = _alm(tmp_path)
    # Solo debería afectar al insumo "200" (PRECIO IDU = publico), no a "100" (COSTO INTERNO)
    out = svc.preview_transformar(alm, {"clasificacion": "publico"},
                                  {"tipo": "precio_pct", "valor": 10})
    assert out["afectados"] == 1
    assert out["cambios"][0]["codigo"] == "200"


def test_parse_tabla_sin_codigo_lanza_valueerror(tmp_path):
    contenido = _xlsx_bytes_headers(["NOMBRE", "PRECIO"], [["Arena", 5000]])
    with pytest.raises(ValueError):
        svc._parse_tabla(contenido, "x.xlsx")


def test_preview_import_ambiguos(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    # Dos insumos con el mismo código pero distinto nombre → candidatos ambiguos
    alm.precios.insert_insumos([
        Insumo("300", 'Tubería PVC 4"', "ML", "TUBERIAS", 10000.0, "COSTO INTERNO"),
        Insumo("300", 'Tubería PVC 6"', "ML", "TUBERIAS", 20000.0, "COSTO INTERNO")])
    contenido = _xlsx_bytes([["300", 15000, "COMPRAS"]])
    out = svc.preview_import(alm, contenido, "lista.xlsx")
    assert len(out["ambiguos"]) == 1
    assert out["ambiguos"][0]["codigo"] == "300"
    assert len(out["ambiguos"][0]["candidatos"]) == 2
