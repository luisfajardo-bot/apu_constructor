import os
import pytest

from apu_tool.nucleo.models import Perfil


def _sqlite(tmp_path):
    from apu_tool.datos.perfiles_db import PerfilesDB
    r = PerfilesDB(tmp_path / "seg.db"); r.init_schema(); return r, None


def _postgres(tmp_path):
    from apu_tool.datos.pg.conexion import Conexion
    from apu_tool.datos.pg.perfiles_pg import PerfilesPg
    cx = Conexion(os.environ["TEST_DATABASE_URL"])
    r = PerfilesPg(cx); r.reset(); return r, cx


_BACKENDS = ["sqlite"] + (["postgres"] if os.environ.get("TEST_DATABASE_URL") else [])


@pytest.fixture(params=_BACKENDS)
def repo(request, tmp_path):
    r, cx = _sqlite(tmp_path) if request.param == "sqlite" else _postgres(tmp_path)
    yield r
    if cx is not None:
        cx.cerrar()


def test_upsert_y_get(repo):
    repo.upsert(Perfil("u1", "a@obra.co", "editor", "activo", "Ana"))
    p = repo.get("u1")
    assert p.email == "a@obra.co" and p.rol == "editor" and p.estado == "activo"
    assert repo.get("noexiste") is None


def test_upsert_actualiza(repo):
    repo.upsert(Perfil("u1", "a@obra.co", "consulta", "activo"))
    repo.upsert(Perfil("u1", "a@obra.co", "editor", "activo"))
    assert repo.get("u1").rol == "editor"
    assert len(repo.listar()) == 1


def test_set_rol_y_estado(repo):
    repo.upsert(Perfil("u1", "a@obra.co", "consulta", "activo"))
    repo.set_rol("u1", "admin")
    repo.set_estado("u1", "inactivo")
    p = repo.get("u1")
    assert p.rol == "admin" and p.estado == "inactivo"


def test_contar_admins_activos(repo):
    repo.upsert(Perfil("u1", "a@obra.co", "admin", "activo"))
    repo.upsert(Perfil("u2", "b@obra.co", "admin", "inactivo"))
    repo.upsert(Perfil("u3", "c@obra.co", "editor", "activo"))
    assert repo.contar_admins_activos() == 1
