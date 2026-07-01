import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Perfil
from apu_tool.servicio.auth import ErrorAuth, resolver_perfil, RANGO


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def test_bootstrap_admin_por_env(tmp_path, monkeypatch):
    monkeypatch.setenv("APU_ADMIN_EMAILS", "jefe@obra.co")
    alm = _alm(tmp_path)
    p = resolver_perfil(alm, "u1", "Jefe@Obra.CO")   # case-insensitive
    assert p.rol == "admin" and p.estado == "activo"
    assert alm.perfiles.get("u1").rol == "admin"      # persistió


def test_invitado_existente_se_devuelve(tmp_path, monkeypatch):
    monkeypatch.delenv("APU_ADMIN_EMAILS", raising=False)
    alm = _alm(tmp_path)
    alm.perfiles.upsert(Perfil("u2", "e@obra.co", "editor", "activo"))
    assert resolver_perfil(alm, "u2", "e@obra.co").rol == "editor"


def test_inactivo_deniega(tmp_path, monkeypatch):
    monkeypatch.delenv("APU_ADMIN_EMAILS", raising=False)
    alm = _alm(tmp_path)
    alm.perfiles.upsert(Perfil("u3", "x@obra.co", "consulta", "inactivo"))
    with pytest.raises(ErrorAuth):
        resolver_perfil(alm, "u3", "x@obra.co")


def test_desconocido_no_admin_deniega(tmp_path, monkeypatch):
    monkeypatch.delenv("APU_ADMIN_EMAILS", raising=False)
    alm = _alm(tmp_path)
    with pytest.raises(ErrorAuth):
        resolver_perfil(alm, "u4", "ajeno@obra.co")


def test_jerarquia_rangos():
    assert RANGO["admin"] > RANGO["editor"] > RANGO["consulta"]
