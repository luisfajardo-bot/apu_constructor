from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Perfil
from apu_tool.servicio import auditoria as svc


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def test_registrar_con_actor(tmp_path):
    alm = _alm(tmp_path)
    actor = Perfil("u1", "a@obra.co", "editor", "activo")
    with alm.transaccion("seguridad") as conn:
        svc.registrar_auditoria(alm, conn, actor, "usuario.invitar", "usuario", "u9",
                                despues={"rol": "consulta"})
    items, total = alm.auditoria.listar()
    assert total == 1
    ev = items[0]
    assert ev["user_id"] == "u1" and ev["user_email"] == "a@obra.co" and ev["rol"] == "editor"
    assert ev["accion"] == "usuario.invitar" and ev["entidad_id"] == "u9"
    assert ev["despues"] == {"rol": "consulta"} and ev["ts"]  # ts no vacío


def test_registrar_sin_actor_es_sistema(tmp_path):
    alm = _alm(tmp_path)
    with alm.transaccion("seguridad") as conn:
        svc.registrar_auditoria(alm, conn, None, "insumo.crear", "insumo", "5")
    ev = alm.auditoria.listar()[0][0]
    assert ev["user_id"] is None and ev["rol"] == "sistema"


def test_listar_devuelve_paginacion(tmp_path):
    alm = _alm(tmp_path)
    with alm.transaccion("seguridad") as conn:
        svc.registrar_auditoria(alm, conn, None, "insumo.crear", "insumo", "1")
    out = svc.listar(alm, limit=10, offset=0)
    assert out["total"] == 1 and out["limit"] == 10 and len(out["items"]) == 1


def test_nuevo_lote_unico():
    assert svc.nuevo_lote() != svc.nuevo_lote()
