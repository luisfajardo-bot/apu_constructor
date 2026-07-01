import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Perfil
from apu_tool.servicio import usuarios as svc
from apu_tool.servicio.supabase_admin import AdminSupabaseFake


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def _actor_admin():
    return Perfil("admin-0", "root@obra.co", "admin", "activo")


def test_invitar_crea_perfil(tmp_path):
    alm = _alm(tmp_path)
    admin = AdminSupabaseFake(id_por_email={"nuevo@obra.co": "u-nuevo"})
    out = svc.invitar(alm, admin, "nuevo@obra.co", "editor", "Nuevo")
    assert out["user_id"] == "u-nuevo"
    p = alm.perfiles.get("u-nuevo")
    assert p.rol == "editor" and p.estado == "activo" and p.email == "nuevo@obra.co"


def test_invitar_rol_invalido(tmp_path):
    alm = _alm(tmp_path)
    with pytest.raises(ValueError):
        svc.invitar(alm, AdminSupabaseFake(), "x@obra.co", "superuser", "X")


def test_cambiar_rol(tmp_path):
    alm = _alm(tmp_path)
    alm.perfiles.upsert(Perfil("u1", "a@obra.co", "consulta", "activo"))
    svc.cambiar_rol(alm, _actor_admin(), "u1", "editor")
    assert alm.perfiles.get("u1").rol == "editor"


def test_guardrail_no_degradar_ultimo_admin(tmp_path):
    alm = _alm(tmp_path)
    alm.perfiles.upsert(Perfil("u1", "a@obra.co", "admin", "activo"))  # único admin
    with pytest.raises(ValueError):
        svc.cambiar_rol(alm, _actor_admin(), "u1", "editor")
    with pytest.raises(ValueError):
        svc.cambiar_estado(alm, _actor_admin(), "u1", "inactivo")
    assert alm.perfiles.get("u1").rol == "admin" and alm.perfiles.get("u1").estado == "activo"


def test_guardrail_permite_si_hay_otro_admin(tmp_path):
    alm = _alm(tmp_path)
    alm.perfiles.upsert(Perfil("u1", "a@obra.co", "admin", "activo"))
    alm.perfiles.upsert(Perfil("u2", "b@obra.co", "admin", "activo"))
    svc.cambiar_estado(alm, _actor_admin(), "u1", "inactivo")   # queda u2 admin activo
    assert alm.perfiles.get("u1").estado == "inactivo"
