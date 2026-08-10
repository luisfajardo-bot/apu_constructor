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


def test_set_rol_protegido_bloquea_ultimo_admin(repo):
    repo.upsert(Perfil("u1", "a@obra.co", "admin", "activo"))
    aplicado = repo.set_rol_protegido("u1", "editor")
    assert aplicado is False
    assert repo.get("u1").rol == "admin"        # no cambió


def test_set_rol_protegido_permite_si_hay_otro_admin(repo):
    repo.upsert(Perfil("u1", "a@obra.co", "admin", "activo"))
    repo.upsert(Perfil("u2", "b@obra.co", "admin", "activo"))
    assert repo.set_rol_protegido("u1", "editor") is True
    assert repo.get("u1").rol == "editor"


def test_set_estado_protegido_bloquea_ultimo_admin(repo):
    repo.upsert(Perfil("u1", "a@obra.co", "admin", "activo"))
    assert repo.set_estado_protegido("u1", "inactivo") is False
    assert repo.get("u1").estado == "activo"


def test_get_por_email_devuelve_lista(repo):
    """Lista y no Optional a propósito: `perfiles.email` NO es UNIQUE, y esconder el
    caso ambiguo es justo lo que no queremos (ver el spec)."""
    repo.upsert(Perfil("u1", "ana@obra.co", "editor", "activo"))
    assert [p.user_id for p in repo.get_por_email("ana@obra.co")] == ["u1"]
    assert repo.get_por_email("nadie@obra.co") == []


def test_get_por_email_ignora_caso_y_espacios(repo):
    repo.upsert(Perfil("u1", "Ana@Obra.CO", "editor", "activo"))
    assert len(repo.get_por_email("  ana@obra.co ")) == 1


def test_get_por_email_puede_devolver_varios(repo):
    repo.upsert(Perfil("u1", "ana@obra.co", "editor", "activo"))
    repo.upsert(Perfil("u2", "ana@obra.co", "consulta", "activo"))
    assert len(repo.get_por_email("ana@obra.co")) == 2


def test_reasignar_user_id_mueve_el_perfil(repo):
    repo.upsert(Perfil("viejo", "ana@obra.co", "editor", "activo", "Ana"))
    assert repo.reasignar_user_id("viejo", "nuevo") is True
    assert repo.get("viejo") is None
    p = repo.get("nuevo")
    assert p.email == "ana@obra.co" and p.rol == "editor" and p.nombre == "Ana"
    assert len(repo.listar()) == 1        # se movió, no se duplicó


def test_reasignar_user_id_inexistente_no_mueve_nada(repo):
    """Un `user_id` que no existe no mueve ninguna fila: `False`, y sin efectos.

    Es la base del arreglo del auditoría-fantasma: `_adoptar_por_email` solo escribe
    `usuario.vincular_identidad` si esto da `True` (ver auth.py)."""
    repo.upsert(Perfil("otro", "otro@obra.co", "consulta", "activo"))
    assert repo.reasignar_user_id("noexiste", "nuevo") is False
    assert repo.get("nuevo") is None
    assert len(repo.listar()) == 1
