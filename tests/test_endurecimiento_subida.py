from apu_tool.datos.almacen import Almacen
from apu_tool.servicio.app import create_app
from fastapi.testclient import TestClient


def _app(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return create_app(almacen=alm)


def test_subida_sobre_limite_da_413(tmp_path, monkeypatch):
    monkeypatch.setenv("APU_MAX_UPLOAD_MB", "1")   # límite 1 MB para el test
    cli = TestClient(_app(tmp_path))
    grande = b"x" * (2 * 1024 * 1024)              # 2 MB > 1 MB
    r = cli.post("/api/insumos/importar/preview",
                 files={"archivo": ("grande.xlsx", grande,
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 413, r.text
