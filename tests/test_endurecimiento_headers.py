from apu_tool.datos.almacen import Almacen
from apu_tool.servicio.app import create_app
from fastapi.testclient import TestClient


def _app(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return create_app(almacen=alm)


def test_cabeceras_presentes(tmp_path):
    # /openapi.json no requiere auth → sirve para inspeccionar cabeceras.
    r = TestClient(_app(tmp_path)).get("/openapi.json")
    assert r.status_code == 200
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "Strict-Transport-Security" in r.headers
    assert r.headers["Referrer-Policy"] == "no-referrer"
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]


def test_csp_incluye_host_supabase(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "abcxyz")
    csp = TestClient(_app(tmp_path)).get("/openapi.json").headers["Content-Security-Policy"]
    assert "connect-src 'self' https://abcxyz.supabase.co wss://abcxyz.supabase.co" in csp
