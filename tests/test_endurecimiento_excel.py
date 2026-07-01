from apu_tool.datos.almacen import Almacen
from apu_tool.servicio.app import create_app
from tests.conftest import cliente


def _app(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return create_app(almacen=alm)


def test_excel_corrupto_da_400_no_500(tmp_path):
    cli = cliente(_app(tmp_path), rol="editor")
    basura = b"esto no es un xlsx"
    r = cli.post("/api/insumos/importar/preview",
                 files={"archivo": ("lista.xlsx", basura,
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 400, r.text


def test_apus_importar_excel_corrupto_da_400(tmp_path):
    cli = cliente(_app(tmp_path), rol="editor")
    r = cli.post("/api/apus/importar/preview",
                 files={"archivo": ("apus.xlsx", b"xx", "application/octet-stream")})
    assert r.status_code == 400, r.text
