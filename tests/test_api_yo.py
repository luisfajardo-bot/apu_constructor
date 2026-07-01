from apu_tool.datos.almacen import Almacen
from apu_tool.servicio.app import create_app
from apu_tool.servicio.auth import usuario_actual
from apu_tool.nucleo.models import Perfil
from fastapi.testclient import TestClient


def _app(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return create_app(almacen=alm)


def test_yo_devuelve_perfil_del_usuario(tmp_path):
    app = _app(tmp_path)
    app.dependency_overrides[usuario_actual] = lambda: Perfil(
        user_id="u1", email="ana@obra.co", rol="editor", estado="activo", nombre="Ana")
    cli = TestClient(app)
    r = cli.get("/api/yo")
    assert r.status_code == 200
    assert r.json() == {"email": "ana@obra.co", "rol": "editor", "nombre": "Ana"}


def test_yo_sin_token_da_401(tmp_path):
    cli = TestClient(_app(tmp_path))
    assert cli.get("/api/yo").status_code == 401
