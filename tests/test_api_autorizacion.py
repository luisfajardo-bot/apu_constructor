from apu_tool.datos.almacen import Almacen
from apu_tool.servicio.app import create_app
from tests.conftest import cliente


def _app(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return create_app(almacen=alm)


def test_consulta_puede_ver_pero_no_editar(tmp_path):
    app = _app(tmp_path)
    cli = cliente(app, rol="consulta")
    assert cli.get("/api/insumos").status_code == 200            # ver: OK
    r = cli.post("/api/insumos/crear",
                 json={"codigo": "9", "nombre": "X", "unidad": "U", "grupo": "G",
                       "precio": 1.0, "fuente_precio": "COSTO INTERNO"})
    assert r.status_code == 403                                   # editar: prohibido


def test_editor_puede_editar_catalogo(tmp_path):
    app = _app(tmp_path)
    cli = cliente(app, rol="editor")
    r = cli.post("/api/insumos/crear",
                 json={"codigo": "9", "nombre": "X", "unidad": "U", "grupo": "G",
                       "precio": 1.0, "fuente_precio": "COSTO INTERNO"})
    assert r.status_code == 200, r.text


def test_sin_override_no_autenticado_da_401(tmp_path):
    # sin dependency_overrides: no hay token → 401
    from fastapi.testclient import TestClient
    app = _app(tmp_path)
    cli = TestClient(app)
    assert cli.get("/api/insumos").status_code == 401
