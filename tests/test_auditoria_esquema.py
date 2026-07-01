import sqlite3

from apu_tool import config
from apu_tool.nucleo.models import EventoAuditoria


def test_seguridad_sql_crea_tabla_auditoria(tmp_path):
    db = tmp_path / "seg.db"
    conn = sqlite3.connect(db)
    conn.executescript((config.PROJECT_ROOT / "db" / "seguridad.sql").read_text(encoding="utf-8"))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(auditoria)").fetchall()}
    conn.close()
    assert cols == {"id", "ts", "user_id", "user_email", "rol", "accion",
                    "entidad_tipo", "entidad_id", "antes", "despues", "contexto"}


def test_evento_auditoria_campos():
    ev = EventoAuditoria(ts="2026-07-01T00:00:00+00:00", rol="admin",
                         accion="precio.editar", entidad_tipo="insumo", entidad_id="42")
    assert ev.user_id is None and ev.rol == "admin" and ev.entidad_id == "42"
    assert ev.antes is None and ev.despues is None and ev.contexto is None
