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


def test_no_se_edita_una_nota_borrada(repo):
    r, tx = repo
    nid = _crear(r, tx)
    _escribir(tx, lambda c: r.borrar(c, nid))
    _escribir(tx, lambda c: r.editar(c, nid, "tarde", "2026-09-30T12:00:00+00:00"))
    assert r.get(nid).texto == "cotización X" and r.get(nid).editada_en is None


def test_buscar_ignora_mayusculas_con_tildes(repo):
    r, tx = repo
    if os.environ.get("TEST_DATABASE_URL") and not isinstance(r, __import__("apu_tool.datos.notas_db", fromlist=["NotasDB"]).NotasDB):
        pytest.skip("solo SQLite: ILIKE de Postgres depende del locale de la BD (en la de prueba no pliega Í/í)")
    _crear(r, tx, texto="Cotización FERRETERÍA")
    assert len(r.buscar(q="ferretería")[0]) == 1


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


# ---- Fase 2: menciones ----

def _mencionar(r, tx, nid, uids, ts="2026-09-30T10:00:00+00:00"):
    return _escribir(tx, lambda c: r.set_menciones(c, nid, uids, ts))


def test_set_menciones_sincroniza_y_devuelve_los_nuevos(repo):
    r, tx = repo
    nid = _crear(r, tx)
    assert _mencionar(r, tx, nid, ["ana", "beto"]) == ["ana", "beto"]
    assert sorted(r.menciones_de_notas([nid])[nid]) == ["ana", "beto"]
    # editar: se va beto, llega caro; ana sigue y NO es "nueva"
    assert _mencionar(r, tx, nid, ["ana", "caro"]) == ["caro"]
    assert sorted(r.menciones_de_notas([nid])[nid]) == ["ana", "caro"]
    assert _mencionar(r, tx, nid, []) == []
    assert r.menciones_de_notas([nid]) == {}
    assert r.menciones_de_notas([]) == {}


def test_contar_listar_y_marcar_leidas(repo):
    r, tx = repo
    a = _crear(r, tx, texto="primera", ts="2026-09-30T10:00:00+00:00")
    b = _crear(r, tx, texto="segunda", ts="2026-09-30T11:00:00+00:00")
    _mencionar(r, tx, a, ["ana"], ts="2026-09-30T10:00:00+00:00")
    _mencionar(r, tx, b, ["ana", "beto"], ts="2026-09-30T11:00:00+00:00")
    assert r.contar_sin_leer("ana") == 2 and r.contar_sin_leer("beto") == 1
    lista = r.listar_menciones("ana")
    assert [(n.texto, leida) for n, leida in lista] == [("segunda", None), ("primera", None)]

    _escribir(tx, lambda c: r.marcar_leida(c, "ana", a, "2026-09-30T12:00:00+00:00"))
    assert r.contar_sin_leer("ana") == 1
    assert dict((n.id, l) for n, l in r.listar_menciones("ana"))[a] == "2026-09-30T12:00:00+00:00"
    # marcar otra vez no pisa la fecha de lectura
    _escribir(tx, lambda c: r.marcar_leida(c, "ana", a, "2026-09-30T13:00:00+00:00"))
    assert dict((n.id, l) for n, l in r.listar_menciones("ana"))[a] == "2026-09-30T12:00:00+00:00"

    _escribir(tx, lambda c: r.marcar_todas_leidas(c, "ana", "2026-09-30T14:00:00+00:00"))
    assert r.contar_sin_leer("ana") == 0 and r.contar_sin_leer("beto") == 1


def test_una_nota_borrada_no_cuenta_ni_se_lista(repo):
    r, tx = repo
    nid = _crear(r, tx)
    _mencionar(r, tx, nid, ["ana"])
    _escribir(tx, lambda c: r.borrar(c, nid))
    assert r.contar_sin_leer("ana") == 0
    assert r.listar_menciones("ana") == []


def test_listar_menciones_respeta_el_limite(repo):
    r, tx = repo
    for i in range(3):
        nid = _crear(r, tx, texto=f"n{i}", ts=f"2026-09-30T1{i}:00:00+00:00")
        _mencionar(r, tx, nid, ["ana"], ts=f"2026-09-30T1{i}:00:00+00:00")
    assert [n.texto for n, _ in r.listar_menciones("ana", limit=2)] == ["n2", "n1"]


def test_ddl_crea_nota_mencion_en_los_dos_backends():
    for ruta in (("db", "seguridad.sql"), ("db", "pg", "seguridad.sql")):
        sql = config.PROJECT_ROOT.joinpath(*ruta).read_text(encoding="utf-8")
        assert "nota_mencion" in sql and "UNIQUE (nota_id, user_id)" in sql


def test_reasignar_mencionado_mueve_las_menciones(repo):
    r, tx = repo
    a = _crear(r, tx, texto="a")
    b = _crear(r, tx, texto="b", ts="2026-09-30T11:00:00+00:00")
    _mencionar(r, tx, a, ["viejo", "ana"])
    _mencionar(r, tx, b, ["viejo"])
    _escribir(tx, lambda c: r.reasignar_mencionado(c, "viejo", "nuevo"))
    assert r.contar_sin_leer("viejo") == 0 and r.contar_sin_leer("nuevo") == 2
    assert r.contar_sin_leer("ana") == 1


def test_mencion_que_se_queda_conserva_su_lectura(repo):
    r, tx = repo
    nid = _crear(r, tx)
    _mencionar(r, tx, nid, ["ana", "beto"])
    _escribir(tx, lambda c: r.marcar_leida(c, "ana", nid, "2026-09-30T12:00:00+00:00"))
    assert _mencionar(r, tx, nid, ["ana", "caro"]) == ["caro"]
    leidas = {u: dict((n.id, l) for n, l in r.listar_menciones(u))[nid]
              for u in ("ana", "caro")}
    assert leidas == {"ana": "2026-09-30T12:00:00+00:00", "caro": None}
    assert r.listar_menciones("beto") == []
    # quitarla y volverla a poner es una mención nueva: vuelve a estar sin leer
    _mencionar(r, tx, nid, ["caro"])
    _mencionar(r, tx, nid, ["ana", "caro"])
    assert r.contar_sin_leer("ana") == 1


# ---- Fase 3: respuestas ----

def test_crear_respuesta_y_listar_con_borradas(repo):
    r, tx = repo
    raiz = _crear(r, tx, texto="raíz")
    resp = _escribir(tx, lambda c: r.crear(c, "insumo", "4520|DUCTO PVC", "4520 · DUCTO PVC",
                                           "respuesta", "u2", "u2@obra.co",
                                           "2026-09-30T11:00:00+00:00", responde_a=raiz))
    assert r.get(resp).responde_a == raiz and r.get(raiz).responde_a is None
    _escribir(tx, lambda c: r.borrar(c, raiz))
    assert [n.id for n in r.listar("insumo", "4520|DUCTO PVC")] == [resp]
    todas = r.listar("insumo", "4520|DUCTO PVC", incluir_borradas=True)
    assert [(n.id, n.borrada) for n in todas] == [(raiz, True), (resp, False)]
