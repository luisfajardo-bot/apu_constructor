"""El endpoint de presencia. Marca al que pregunta: el latido ES el poll.

Ojo con el patrón de estos tests: overridean la dependencia `usuario_actual`, así que
cualquier cosa metida DENTRO de esa dependencia no se ejecuta acá. Por eso `marcar`
vive en el endpoint y no en auth.py.
"""
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Perfil
from apu_tool.servicio import presencia
from apu_tool.servicio.app import create_app
from apu_tool.servicio.auth import usuario_actual
from fastapi.testclient import TestClient


def _app(tmp_path, perfil):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    app = create_app(almacen=alm)
    app.dependency_overrides[usuario_actual] = lambda: perfil
    return app


def setup_function():
    presencia._vistos.clear()


def test_pedir_la_lista_te_deja_en_la_lista(tmp_path):
    """Sin endpoint de latido: preguntar quién está en línea te marca presente."""
    ana = Perfil(user_id="u1", email="ana@obra.co", rol="consulta", estado="activo",
                 nombre="Ana")
    cli = TestClient(_app(tmp_path, ana))
    r = cli.get("/api/presencia")
    assert r.status_code == 200
    assert r.json() == {"en_linea": [{"email": "ana@obra.co", "nombre": "Ana"}]}


def test_dos_usuarios_se_ven_entre_si(tmp_path):
    ana = Perfil(user_id="u1", email="ana@obra.co", rol="consulta", estado="activo",
                 nombre="Ana")
    beto = Perfil(user_id="u2", email="beto@obra.co", rol="editor", estado="activo",
                  nombre="Beto")
    TestClient(_app(tmp_path, ana)).get("/api/presencia")
    r = TestClient(_app(tmp_path, beto)).get("/api/presencia")
    assert [p["nombre"] for p in r.json()["en_linea"]] == ["Ana", "Beto"]


def test_sin_token_da_401(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    cli = TestClient(create_app(almacen=alm))
    assert cli.get("/api/presencia").status_code == 401
