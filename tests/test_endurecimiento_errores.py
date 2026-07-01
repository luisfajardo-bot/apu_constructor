from apu_tool.datos.almacen import Almacen
from apu_tool.servicio.app import create_app
from fastapi.testclient import TestClient


def _app(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return create_app(almacen=alm)


def test_health_publico_sin_token(tmp_path):
    r = TestClient(_app(tmp_path)).get("/api/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_error_interno_es_generico_sin_traza(tmp_path, monkeypatch):
    import apu_tool.servicio.app as app_module

    # Forzamos que NO se monte el catch-all de la SPA (que ensombrecería la ruta
    # de prueba agregada abajo), independientemente de si existe un web/dist
    # local compilado en esta máquina.
    monkeypatch.setattr(app_module, "WEB_DIST", tmp_path / "no-existe-dist")

    app = _app(tmp_path)

    @app.get("/api/_boom")
    def _boom():
        raise RuntimeError("detalle-secreto-interno")

    cli = TestClient(app, raise_server_exceptions=False)
    r = cli.get("/api/_boom")
    assert r.status_code == 500
    assert r.json() == {"detail": "Error interno."}
    assert "secreto" not in r.text   # no se filtra el detalle interno
