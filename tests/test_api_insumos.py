# tests/test_api_insumos.py
import io, openpyxl

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Insumo
from apu_tool.servicio.app import create_app
from tests.conftest import cliente


def _cli(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo("100", "Concreto 3000 PSI", "M3", "CONCRETOS", 350000.0, "COSTO INTERNO"),
        Insumo("200", "Acero de refuerzo", "KG", "ACEROS", 4500.0, "PRECIO IDU")])
    return cliente(create_app(almacen=alm), rol="admin"), alm


def test_listar_filtros_grupos_fuentes(tmp_path):
    cli, _ = _cli(tmp_path)
    r = cli.get("/api/insumos?q=acero")
    assert r.status_code == 200 and r.json()["total"] == 1
    assert "ACEROS" in cli.get("/api/insumos/grupos").json()
    assert "PRECIO IDU" in cli.get("/api/insumos/fuentes").json()


def test_cambios_y_detalle(tmp_path):
    cli, alm = _cli(tmp_path)
    iid = alm.precios.get_candidatos("100")[0].id
    r = cli.post("/api/insumos/cambios", json={"cambios": [
        {"insumo_id": iid, "precio": 410000.0, "fuente": "COMPRAS"}]})
    assert r.status_code == 200 and r.json()["aplicados"] == 1
    d = cli.get(f"/api/insumos/{iid}")
    assert d.status_code == 200 and d.json()["insumo"]["precio"] == 410000.0
    assert cli.get("/api/insumos/99999").status_code == 404


def test_importar_preview(tmp_path):
    cli, _ = _cli(tmp_path)
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["CODIGO", "PRECIO", "FUENTE"]); ws.append(["100", 390000, "COMPRAS"])
    buf = io.BytesIO(); wb.save(buf)
    r = cli.post("/api/insumos/importar/preview",
                 files={"archivo": ("l.xlsx", buf.getvalue(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200 and len(r.json()["cambios"]) == 1


_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_plantilla_precios_endpoint(tmp_path):
    cli, _ = _cli(tmp_path)
    r = cli.get("/api/insumos/importar/plantilla")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == _XLSX
    assert "attachment" in r.headers["content-disposition"]
    assert len(r.content) > 0
