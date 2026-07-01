from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Perfil
from apu_tool.servicio.app import create_app
from apu_tool.servicio import rutas
from apu_tool.servicio.supabase_admin import AdminSupabaseFake
from tests.conftest import cliente


def _app(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    app = create_app(almacen=alm)
    fake = AdminSupabaseFake(id_por_email={"nuevo@obra.co": "u-nuevo"})
    app.dependency_overrides[rutas.get_admin_supabase] = lambda: fake
    return app, alm


def test_invitar_y_listar_como_admin(tmp_path):
    app, alm = _app(tmp_path)
    cli = cliente(app, rol="admin")
    r = cli.post("/api/usuarios/invitar",
                 json={"email": "nuevo@obra.co", "rol": "editor", "nombre": "Nuevo"})
    assert r.status_code == 200, r.text
    assert r.json()["user_id"] == "u-nuevo"
    lst = cli.get("/api/usuarios")
    assert lst.status_code == 200 and any(u["email"] == "nuevo@obra.co" for u in lst.json())


def test_usuarios_prohibido_para_editor(tmp_path):
    app, _ = _app(tmp_path)
    cli = cliente(app, rol="editor")
    assert cli.get("/api/usuarios").status_code == 403
    assert cli.post("/api/usuarios/invitar",
                    json={"email": "x@obra.co", "rol": "editor"}).status_code == 403


def test_cambiar_rol_y_estado(tmp_path):
    app, alm = _app(tmp_path)
    alm.perfiles.upsert(Perfil("u1", "a@obra.co", "consulta", "activo"))
    cli = cliente(app, rol="admin")
    assert cli.patch("/api/usuarios/u1/rol", json={"rol": "editor"}).status_code == 200
    assert alm.perfiles.get("u1").rol == "editor"
    assert cli.patch("/api/usuarios/u1/estado", json={"estado": "inactivo"}).status_code == 200
    assert alm.perfiles.get("u1").estado == "inactivo"
