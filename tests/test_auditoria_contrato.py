import os
import sqlite3
import pytest

from apu_tool import config
from apu_tool.nucleo.models import EventoAuditoria


def _ev(accion="precio.editar", entidad_id="1", lote=None):
    return EventoAuditoria(
        ts="2026-07-01T10:00:00+00:00", rol="admin", accion=accion,
        entidad_tipo="insumo", entidad_id=entidad_id, user_id="u1",
        user_email="a@obra.co", antes={"precio": 10.0}, despues={"precio": 20.0},
        contexto={"origen": "edicion", "lote_id": lote} if lote else {"origen": "edicion"})


def _sqlite(tmp_path):
    from apu_tool.datos.auditoria_db import AuditoriaDB
    seg = tmp_path / "seg.db"
    conn = sqlite3.connect(seg)
    conn.executescript((config.PROJECT_ROOT / "db" / "seguridad.sql").read_text(encoding="utf-8"))
    conn.commit(); conn.close()
    return AuditoriaDB(seg), None


def _postgres(tmp_path):
    from apu_tool.datos.pg.conexion import Conexion
    from apu_tool.datos.pg.auditoria_pg import AuditoriaPg
    from apu_tool.datos.pg.perfiles_pg import PerfilesPg
    cx = Conexion(os.environ["TEST_DATABASE_URL"])
    PerfilesPg(cx).reset()  # recrea schema seguridad con perfiles + auditoria
    return AuditoriaPg(cx), cx


_BACKENDS = ["sqlite"] + (["postgres"] if os.environ.get("TEST_DATABASE_URL") else [])


@pytest.fixture(params=_BACKENDS)
def repo_conn(request, tmp_path):
    if request.param == "sqlite":
        repo, _ = _sqlite(tmp_path)
        conn = sqlite3.connect(repo.path)
        conn.row_factory = sqlite3.Row
        yield repo, conn
        conn.commit(); conn.close()
    else:
        repo, cx = _postgres(tmp_path)
        with cx.transaccion() as conn:
            yield repo, conn
        cx.cerrar()


def test_registrar_y_listar(repo_conn):
    repo, conn = repo_conn
    repo.registrar(conn, _ev(entidad_id="7"))
    conn.commit() if hasattr(conn, "commit") else None
    items, total = repo.listar()
    assert total == 1
    assert items[0]["entidad_id"] == "7"
    assert items[0]["antes"] == {"precio": 10.0}          # JSON parseado a dict
    assert items[0]["contexto"]["origen"] == "edicion"
    assert items[0]["rol"] == "admin"


def test_listar_filtra_por_accion_y_lote(repo_conn):
    repo, conn = repo_conn
    repo.registrar(conn, _ev(accion="precio.editar", lote="L1"))
    repo.registrar(conn, _ev(accion="usuario.invitar", entidad_id="u9"))
    conn.commit() if hasattr(conn, "commit") else None
    solo_precio, n = repo.listar(accion="precio.editar")
    assert n == 1 and solo_precio[0]["accion"] == "precio.editar"
    por_lote, nl = repo.listar(lote_id="L1")
    assert nl == 1 and por_lote[0]["contexto"]["lote_id"] == "L1"
