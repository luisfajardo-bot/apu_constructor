"""Adopción por email: el invitado entra con Google aunque Supabase le dé otro user_id.

Spec: docs/superpowers/specs/2026-08-10-login-google-design.md
"""
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Perfil
from apu_tool.servicio.auth import ErrorAuth, identidad_verificada, resolver_perfil


def _alm(tmp_path, monkeypatch):
    monkeypatch.delenv("APU_ADMIN_EMAILS", raising=False)
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def test_perfil_por_user_id_no_pasa_por_la_adopcion(tmp_path, monkeypatch):
    """El camino de siempre no cambia: si el user_id ya tiene perfil, no se toca nada."""
    alm = _alm(tmp_path, monkeypatch)
    alm.perfiles.upsert(Perfil("u1", "ana@obra.co", "editor", "activo"))
    assert resolver_perfil(alm, "u1", "ana@obra.co", True).rol == "editor"
    _items, total = alm.auditoria.listar(accion="usuario.vincular_identidad")
    assert total == 0


def test_adopta_cuando_el_email_esta_verificado(tmp_path, monkeypatch):
    alm = _alm(tmp_path, monkeypatch)
    alm.perfiles.upsert(Perfil("viejo", "ana@obra.co", "editor", "activo", "Ana"))
    p = resolver_perfil(alm, "nuevo-de-google", "ana@obra.co", True)
    assert p.user_id == "nuevo-de-google" and p.rol == "editor" and p.nombre == "Ana"
    assert alm.perfiles.get("viejo") is None
    assert alm.perfiles.get("nuevo-de-google").rol == "editor"
    items, total = alm.auditoria.listar(accion="usuario.vincular_identidad")
    assert total == 1 and items[0]["entidad_id"] == "nuevo-de-google"


def test_email_sin_verificar_no_adopta_nada(tmp_path, monkeypatch):
    """El test de la escalada de privilegios: sin esta guarda, cualquiera que se registre
    con el correo del Admin y no lo confirme se queda con su perfil."""
    alm = _alm(tmp_path, monkeypatch)
    alm.perfiles.upsert(Perfil("el-jefe", "jefe@obra.co", "admin", "activo"))
    with pytest.raises(ErrorAuth):
        resolver_perfil(alm, "impostor", "jefe@obra.co", False)
    assert alm.perfiles.get("el-jefe").rol == "admin"      # intacto
    assert alm.perfiles.get("impostor") is None


def test_dos_perfiles_con_el_mismo_email_no_se_adivina(tmp_path, monkeypatch):
    alm = _alm(tmp_path, monkeypatch)
    alm.perfiles.upsert(Perfil("u1", "ana@obra.co", "editor", "activo"))
    alm.perfiles.upsert(Perfil("u2", "ana@obra.co", "admin", "activo"))
    with pytest.raises(ErrorAuth):
        resolver_perfil(alm, "nuevo", "ana@obra.co", True)
    assert alm.perfiles.get("u1") is not None and alm.perfiles.get("u2") is not None


def test_perfil_adoptado_inactivo_no_se_cuela(tmp_path, monkeypatch):
    """Un perfil inactivo no se adopta: no se re-clava una fila muerta. Cae en el mismo
    403 de "no invitado" de siempre (no en "Usuario inactivo.", porque nunca llegó a
    resolverse ningún perfil), y el perfil viejo queda intacto, sin moverse."""
    alm = _alm(tmp_path, monkeypatch)
    alm.perfiles.upsert(Perfil("viejo", "ana@obra.co", "editor", "inactivo"))
    with pytest.raises(ErrorAuth, match="no invitado"):
        resolver_perfil(alm, "nuevo", "ana@obra.co", True)
    assert alm.perfiles.get("viejo").estado == "inactivo"   # intacto, no se movió
    assert alm.perfiles.get("nuevo") is None


def test_email_con_otro_caso_y_espacios_igual_adopta(tmp_path, monkeypatch):
    alm = _alm(tmp_path, monkeypatch)
    alm.perfiles.upsert(Perfil("viejo", "ana@obra.co", "consulta", "activo"))
    assert resolver_perfil(alm, "nuevo", " Ana@Obra.CO ", True).rol == "consulta"


def test_bootstrap_admin_sigue_funcionando_sin_perfil_previo(tmp_path, monkeypatch):
    """La adopción va ANTES del bootstrap, pero sin perfil que adoptar no lo estorba."""
    alm = _alm(tmp_path, monkeypatch)
    monkeypatch.setenv("APU_ADMIN_EMAILS", "jefe@obra.co")
    assert resolver_perfil(alm, "u-jefe", "jefe@obra.co", True).rol == "admin"


def test_sin_perfil_y_sin_ser_admin_sigue_denegando(tmp_path, monkeypatch):
    alm = _alm(tmp_path, monkeypatch)
    with pytest.raises(ErrorAuth):
        resolver_perfil(alm, "ajeno", "ajeno@gmail.com", True)


@pytest.mark.parametrize("claims, esperado", [
    # El ataque que rompía la guarda vieja: user_metadata lo escribe el propio usuario
    # con la anon key (updateUser({data})), así que declararse verificado ahí no cuenta.
    ({"user_metadata": {"email_verified": True}}, False),
    ({"amr": [{"method": "oauth"}]}, True),
    ({"amr": [{"method": "password"}]}, False),
    ({"app_metadata": {"providers": ["google"]}}, True),
    ({"app_metadata": {"provider": "email"}}, False),
    ({}, False),
    ({"amr": "no-es-lista"}, False),           # claim con forma inesperada: no revienta
    ({"app_metadata": None}, False),           # idem
])
def test_identidad_verificada_ignora_user_metadata_y_exige_proveedor_externo(claims, esperado):
    assert identidad_verificada(claims) is esperado
