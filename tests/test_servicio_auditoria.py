from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import EventoAuditoria, Perfil
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


def test_listar_hasta_fecha_sola_incluye_todo_el_dia(tmp_path):
    # Regresión: `hasta` con fecha sin hora (p.ej. "2026-07-01" desde el visor) debe
    # incluir todos los eventos de ese día, no excluirlos por comparación lexicográfica.
    alm = _alm(tmp_path)
    ev_mismo_dia = EventoAuditoria(
        ts="2026-07-01T10:00:00+00:00", rol="admin", accion="precio.editar",
        entidad_tipo="insumo", entidad_id="1", user_id="u1", user_email="a@obra.co")
    ev_dia_siguiente = EventoAuditoria(
        ts="2026-07-02T09:00:00+00:00", rol="admin", accion="precio.editar",
        entidad_tipo="insumo", entidad_id="2", user_id="u1", user_email="a@obra.co")
    with alm.transaccion("seguridad") as conn:
        alm.auditoria.registrar(conn, ev_mismo_dia)
        alm.auditoria.registrar(conn, ev_dia_siguiente)

    out = svc.listar(alm, hasta="2026-07-01")
    ids = {item["entidad_id"] for item in out["items"]}
    assert "1" in ids, "evento del mismo día del `hasta` no debería excluirse"
    assert "2" not in ids, "evento del día siguiente al `hasta` sí debe excluirse"


def test_listar_hasta_con_hora_no_se_modifica(tmp_path):
    # Si el llamador ya manda un timestamp completo, no se debe tocar.
    alm = _alm(tmp_path)
    ev_justo_antes = EventoAuditoria(
        ts="2026-07-01T09:59:59+00:00", rol="admin", accion="precio.editar",
        entidad_tipo="insumo", entidad_id="3", user_id="u1", user_email="a@obra.co")
    ev_justo_despues = EventoAuditoria(
        ts="2026-07-01T10:00:01+00:00", rol="admin", accion="precio.editar",
        entidad_tipo="insumo", entidad_id="4", user_id="u1", user_email="a@obra.co")
    with alm.transaccion("seguridad") as conn:
        alm.auditoria.registrar(conn, ev_justo_antes)
        alm.auditoria.registrar(conn, ev_justo_despues)

    out = svc.listar(alm, hasta="2026-07-01T10:00:00+00:00")
    ids = {item["entidad_id"] for item in out["items"]}
    assert "3" in ids
    assert "4" not in ids
