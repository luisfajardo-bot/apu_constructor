import apu_tool.servicio.app as app_module
from apu_tool.datos.almacen import Almacen
from apu_tool.servicio.app import create_app
from fastapi.testclient import TestClient


def _app(tmp_path, monkeypatch):
    # Forzamos que NO se monte el catch-all de la SPA: si hay un web/dist
    # compilado localmente, ensombrecería /openapi.json y el test no podría
    # distinguir un 404 real de un 200 servido por index.html.
    monkeypatch.setattr(app_module, "WEB_DIST", tmp_path / "no-existe-dist")
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return create_app(almacen=alm)


def test_docs_habilitados_por_defecto(tmp_path, monkeypatch):
    assert TestClient(_app(tmp_path, monkeypatch)).get("/openapi.json").status_code == 200


def test_docs_desactivados_en_prod(tmp_path, monkeypatch):
    monkeypatch.setenv("APU_DOCS_ENABLED", "false")
    assert TestClient(_app(tmp_path, monkeypatch)).get("/openapi.json").status_code == 404
