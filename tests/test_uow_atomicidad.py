import sqlite3
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Insumo


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def _cuenta_auditoria(alm):
    with alm.auditoria.connect() as c:
        return c.execute("SELECT COUNT(*) FROM auditoria").fetchone()[0]


def _precios_de(alm, iid):
    with alm.precios.connect() as c:
        return c.execute("SELECT COUNT(*) FROM insumo_precios WHERE insumo_id=?", (iid,)).fetchone()[0]


def test_transaccion_precios_commit_escribe_ambas_tablas(tmp_path):
    alm = _alm(tmp_path)
    iid = alm.precios.crear_insumo(Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU"))
    n_precio0 = _precios_de(alm, iid)
    with alm.transaccion("precios") as conn:
        conn.execute("UPDATE insumo_precios SET vigente=0 WHERE insumo_id=?", (iid,))
        conn.execute("INSERT INTO insumo_precios (insumo_id, precio, fuente, clasificacion, fecha, vigente) "
                     "VALUES (?,?,?,?,?,1)", (iid, 2000, "COSTO INTERNO", "interno", "2026-07-01"))
        conn.execute("INSERT INTO auditoria (ts, rol, accion, entidad_tipo, entidad_id) "
                     "VALUES (?,?,?,?,?)", ("2026-07-01T00:00:00+00:00", "admin", "precio.editar", "insumo", str(iid)))
    assert _precios_de(alm, iid) == n_precio0 + 1     # el precio nuevo persiste
    assert _cuenta_auditoria(alm) == 1                # la auditoría persiste (misma tx, otra base)


def test_transaccion_rollback_revierte_ambas(tmp_path):
    alm = _alm(tmp_path)
    iid = alm.precios.crear_insumo(Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU"))
    n_precio0 = _precios_de(alm, iid)
    with pytest.raises(RuntimeError):
        with alm.transaccion("precios") as conn:
            conn.execute("INSERT INTO insumo_precios (insumo_id, precio, fuente, clasificacion, fecha, vigente) "
                         "VALUES (?,?,?,?,?,1)", (iid, 2000, "X", "interno", "2026-07-01"))
            conn.execute("INSERT INTO auditoria (ts, rol, accion, entidad_tipo, entidad_id) "
                         "VALUES (?,?,?,?,?)", ("2026-07-01T00:00:00+00:00", "admin", "precio.editar", "insumo", str(iid)))
            raise RuntimeError("falla la auditoría a mitad")
    assert _precios_de(alm, iid) == n_precio0         # el precio NO persiste (rollback)
    assert _cuenta_auditoria(alm) == 0                # la auditoría NO persiste (rollback)


def test_transaccion_seguridad_sin_attach(tmp_path):
    alm = _alm(tmp_path)
    with alm.transaccion("seguridad") as conn:
        conn.execute("INSERT INTO auditoria (ts, rol, accion, entidad_tipo, entidad_id) "
                     "VALUES (?,?,?,?,?)", ("2026-07-01T00:00:00+00:00", "sistema", "usuario.invitar", "usuario", "u1"))
    assert _cuenta_auditoria(alm) == 1
