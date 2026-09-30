"""Contrato del repo de notas: la MISMA batería contra los dos backends.

SQLite siempre; Postgres solo con TEST_DATABASE_URL (OJO: hace DROP SCHEMA seguridad,
nunca apuntarlo a producción)."""
import os
import sqlite3

import pytest

from apu_tool import config


def _sqlite(tmp_path):
    from apu_tool.datos.notas_db import NotasDB
    seg = tmp_path / "seg.db"
    conn = sqlite3.connect(seg)
    conn.executescript((config.PROJECT_ROOT / "db" / "seguridad.sql").read_text(encoding="utf-8"))
    conn.commit(); conn.close()
    repo = NotasDB(seg)

    def tx():
        c = sqlite3.connect(seg)
        c.row_factory = sqlite3.Row
        return c
    return repo, tx, None


def _postgres(tmp_path):
    from apu_tool.datos.pg.conexion import Conexion
    from apu_tool.datos.pg.notas_pg import NotasPg
    from apu_tool.datos.pg.perfiles_pg import PerfilesPg
    cx = Conexion(os.environ["TEST_DATABASE_URL"])
    PerfilesPg(cx).reset()  # recrea schema seguridad (perfiles + auditoria + nota)
    return NotasPg(cx), cx.transaccion, cx


_BACKENDS = ["sqlite"] + (["postgres"] if os.environ.get("TEST_DATABASE_URL") else [])


@pytest.fixture(params=_BACKENDS)
def repo(request, tmp_path):
    r, tx, cx = (_sqlite if request.param == "sqlite" else _postgres)(tmp_path)
    yield r, tx
    if cx is not None:
        cx.cerrar()


def _escribir(tx, fn):
    """Corre `fn(conn)` en una transacción y hace commit (sqlite3 o psycopg)."""
    ctx = tx()
    if hasattr(ctx, "__enter__") and not isinstance(ctx, sqlite3.Connection):
        with ctx as conn:
            return fn(conn)
    try:
        out = fn(ctx)
        ctx.commit()
        return out
    finally:
        ctx.close()


def _crear(repo, tx, clave="4520|DUCTO PVC", texto="cotización X", autor="u1",
           entidad="insumo", ts="2026-09-30T10:00:00+00:00"):
    return _escribir(tx, lambda c: repo.crear(
        c, entidad, clave, "4520 · DUCTO PVC", texto, autor, f"{autor}@obra.co", ts))


def test_crear_get_listar(repo):
    r, tx = repo
    nid = _crear(r, tx)
    n = r.get(nid)
    assert n.texto == "cotización X" and n.autor_id == "u1" and n.etiqueta == "4520 · DUCTO PVC"
    assert n.editada_en is None and n.borrada is False and n.responde_a is None
    _crear(r, tx, texto="segunda", ts="2026-09-30T11:00:00+00:00")
    _crear(r, tx, clave="otra|X", texto="de otro dueño")
    assert [x.texto for x in r.listar("insumo", "4520|DUCTO PVC")] == ["cotización X", "segunda"]


def test_editar_y_borrar_suave(repo):
    r, tx = repo
    nid = _crear(r, tx)
    _escribir(tx, lambda c: r.editar(c, nid, "corregida", "2026-09-30T12:00:00+00:00"))
    assert r.get(nid).texto == "corregida"
    assert r.get(nid).editada_en == "2026-09-30T12:00:00+00:00"
    _escribir(tx, lambda c: r.borrar(c, nid))
    assert r.get(nid).borrada is True                       # la fila sigue ahí
    assert r.listar("insumo", "4520|DUCTO PVC") == []       # pero no se lista


def test_resumen_por_claves_da_la_ultima_no_borrada(repo):
    r, tx = repo
    _crear(r, tx, texto="vieja", ts="2026-09-30T10:00:00+00:00")
    ultima = _crear(r, tx, texto="nueva", ts="2026-09-30T11:00:00+00:00")
    _crear(r, tx, clave="B|B", texto="de B")
    _crear(r, tx, clave="4520|DUCTO PVC", texto="es de APU", entidad="apu")
    res = r.resumen_por_claves("insumo", ["4520|DUCTO PVC", "B|B", "SIN|NOTAS"])
    assert res == {"4520|DUCTO PVC": "nueva", "B|B": "de B"}
    _escribir(tx, lambda c: r.borrar(c, ultima))
    assert r.resumen_por_claves("insumo", ["4520|DUCTO PVC"]) == {"4520|DUCTO PVC": "vieja"}
    assert r.resumen_por_claves("insumo", []) == {}


def test_buscar_filtra_pagina_y_ordena_reciente_primero(repo):
    r, tx = repo
    _crear(r, tx, texto="cotización ferretería", autor="u1", ts="2026-09-30T10:00:00+00:00")
    _crear(r, tx, texto="precio nuevos negocios", autor="u2", ts="2026-09-30T11:00:00+00:00")
    b = _crear(r, tx, clave="A|DIURNO", texto="rendimiento medido", autor="u1",
               entidad="apu", ts="2026-09-30T12:00:00+00:00")
    items, total = r.buscar()
    assert total == 3 and items[0].id == b                  # más reciente primero
    assert r.buscar(entidad="apu")[1] == 1
    assert r.buscar(autor_id="u1")[1] == 2
    assert [n.texto for n in r.buscar(q="NEGOCIOS")[0]] == ["precio nuevos negocios"]
    assert len(r.buscar(limit=1, offset=1)[0]) == 1
    _escribir(tx, lambda c: r.borrar(c, b))
    assert r.buscar()[1] == 2                               # las borradas no salen


def test_reset_catalogo_no_borra_notas(tmp_path):
    from apu_tool.datos.almacen import Almacen
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    with alm.transaccion("seguridad") as conn:
        alm.notas.crear(conn, "insumo", "1|X", "1 · X", "sigue", "u1", "u1@obra.co",
                        "2026-09-30T10:00:00+00:00")
    alm.reset_catalogo()              # lo que hace seed --force
    assert [n.texto for n in alm.notas.listar("insumo", "1|X")] == ["sigue"]


def test_notas_pg_cumple_el_protocolo():
    from apu_tool.datos.pg.notas_pg import NotasPg
    from apu_tool.datos.repositorio import RepositorioNotas
    assert issubclass(NotasPg, RepositorioNotas) or isinstance(NotasPg(None), RepositorioNotas)


def test_ddl_pg_crea_la_tabla_nota():
    sql = (config.PROJECT_ROOT / "db" / "pg" / "seguridad.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS seguridad.nota" in sql
