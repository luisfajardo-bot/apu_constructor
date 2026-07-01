from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import CorridaMeta, Perfil
from apu_tool.servicio import corridas as corridas_svc
from apu_tool.servicio import usuarios as usuarios_svc
from apu_tool.servicio.supabase_admin import AdminSupabaseFake


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def _admin():
    return Perfil("admin-0", "root@obra.co", "admin", "activo")


def test_eliminar_corrida_audita(tmp_path):
    alm = _alm(tmp_path)
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="x", archivo="lic.xlsx", turno_def="DIURNO",
        use_ai=False, estado="en_revision"))
    ok = corridas_svc.eliminar_corrida(alm, cid, actor=_admin())
    assert ok is True and alm.corridas.get_corrida(cid) is None
    items, total = alm.auditoria.listar(accion="corrida.eliminar")
    assert total == 1 and items[0]["antes"]["archivo"] == "lic.xlsx" and items[0]["despues"] is None


def test_eliminar_corrida_inexistente_no_audita(tmp_path):
    alm = _alm(tmp_path)
    assert corridas_svc.eliminar_corrida(alm, 999, actor=_admin()) is False
    assert alm.auditoria.listar()[1] == 0


def test_invitar_audita(tmp_path):
    alm = _alm(tmp_path)
    admin = AdminSupabaseFake(id_por_email={"nuevo@obra.co": "u-nuevo"})
    usuarios_svc.invitar(alm, admin, "nuevo@obra.co", "editor", "Nuevo", actor=_admin())
    items, total = alm.auditoria.listar(accion="usuario.invitar")
    assert total == 1 and items[0]["entidad_id"] == "u-nuevo" and items[0]["despues"]["rol"] == "editor"


def test_cambiar_rol_audita_antes_despues(tmp_path):
    alm = _alm(tmp_path)
    alm.perfiles.upsert(Perfil("u1", "a@obra.co", "consulta", "activo"))
    usuarios_svc.cambiar_rol(alm, _admin(), "u1", "editor")
    items, total = alm.auditoria.listar(accion="usuario.cambiar_rol")
    assert total == 1 and items[0]["antes"]["rol"] == "consulta" and items[0]["despues"]["rol"] == "editor"


def test_cambiar_estado_audita(tmp_path):
    alm = _alm(tmp_path)
    alm.perfiles.upsert(Perfil("u1", "a@obra.co", "admin", "activo"))
    alm.perfiles.upsert(Perfil("u2", "b@obra.co", "admin", "activo"))
    usuarios_svc.cambiar_estado(alm, _admin(), "u1", "inactivo")
    items, total = alm.auditoria.listar(accion="usuario.cambiar_estado")
    assert total == 1 and items[0]["despues"]["estado"] == "inactivo"
