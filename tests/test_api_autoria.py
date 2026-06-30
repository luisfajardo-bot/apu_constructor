"""API de autoría: crear/importar insumos y APUs + listar/detalle de APUs."""
import io
import openpyxl
from fastapi.testclient import TestClient

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, Insumo
from apu_tool.servicio.app import create_app

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _cli(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([Insumo("100", "CEMENTO GRIS", "KG", "MAT", 1000, "PRECIO IDU")])
    alm.apus.insert_apus([Apu("A1", "MURO EXISTENTE", "M2", "DIURNO", "ESTR")])
    return TestClient(create_app(almacen=alm)), alm


def test_crear_insumo_endpoint(tmp_path):
    cli, _ = _cli(tmp_path)
    r = cli.post("/api/insumos/crear", json={"codigo": "300", "nombre": "GRAVA",
                 "unidad": "M3", "grupo": "MAT", "precio": 80000, "fuente": "PRECIO IDU"})
    assert r.status_code == 200, r.text
    assert r.json()["codigo"] == "300"
    # duplicado -> 400
    r2 = cli.post("/api/insumos/crear", json={"codigo": "100", "nombre": "CEMENTO GRIS",
                  "precio": 1})
    assert r2.status_code == 400


def test_crear_apu_endpoint(tmp_path):
    cli, alm = _cli(tmp_path)
    r = cli.post("/api/apus/crear", json={"codigo": "B2", "turno": "DIURNO",
        "nombre": "PISO", "unidad": "M2", "grupo": "ACAB",
        "componentes": [{"insumo_codigo": "100", "rendimiento": 2.0}]})
    assert r.status_code == 200, r.text
    det = cli.get("/api/apus/B2/DIURNO")
    assert det.status_code == 200
    assert det.json()["composicion"][0]["insumo_codigo"] == "100"
    # duplicado -> 400
    assert cli.post("/api/apus/crear", json={"codigo": "A1", "turno": "DIURNO",
                    "nombre": "MURO"}).status_code == 400


def test_listar_apus_endpoint(tmp_path):
    cli, _ = _cli(tmp_path)
    r = cli.get("/api/apus")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1 and body["items"][0]["codigo"] == "A1"


def _xlsx_insumos() -> bytes:
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["codigo", "nombre", "unidad", "grupo", "precio", "fuente"])
    ws.append(["300", "GRAVA COMUN", "M3", "MAT", 80000, "PRECIO IDU"])
    ws.append(["100", "CEMENTO GRIS", "KG", "MAT", 1200, "PRECIO IDU"])  # ya existe
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def test_import_insumos_endpoint(tmp_path):
    cli, _ = _cli(tmp_path)
    data = _xlsx_insumos()
    pv = cli.post("/api/insumos/importar-crear/preview",
                  files={"archivo": ("insumos.xlsx", data, _XLSX)})
    assert pv.status_code == 200
    assert [c["codigo"] for c in pv.json()["crear"]] == ["300"]
    ap = cli.post("/api/insumos/importar-crear",
                  files={"archivo": ("insumos.xlsx", data, _XLSX)})
    assert ap.status_code == 200 and ap.json()["creados"] == 1


def _xlsx_apus() -> bytes:
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "APUS"
    ws.append(["ACT","COD IDU","UN","INSUMO","COD","UND","REND","INV","PRECIO","COSTO","TURNO"])
    ws.append(["MURO NUEVO","7777","M2","","","","","","","","DIURNO"])
    ws.append(["","","","CEMENTO","100","KG",2.5,"",900,"",""])
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def test_import_apus_endpoint(tmp_path):
    cli, alm = _cli(tmp_path)
    data = _xlsx_apus()
    pv = cli.post("/api/apus/importar/preview", files={"archivo": ("apus.xlsx", data, _XLSX)})
    assert pv.status_code == 200
    assert any(c["codigo"] == "7777" for c in pv.json()["crear"])
    ap = cli.post("/api/apus/importar", files={"archivo": ("apus.xlsx", data, _XLSX)})
    assert ap.status_code == 200 and ap.json()["creados"] == 1
    assert alm.apus.get_apu("7777", "DIURNO") is not None


def test_import_apus_archivo_malo_400(tmp_path):
    cli, _ = _cli(tmp_path)
    wb = openpyxl.Workbook(); wb.active.append(["x"]); buf = io.BytesIO(); wb.save(buf)
    r = cli.post("/api/apus/importar/preview",
                 files={"archivo": ("malo.xlsx", buf.getvalue(), _XLSX)})
    assert r.status_code == 400
