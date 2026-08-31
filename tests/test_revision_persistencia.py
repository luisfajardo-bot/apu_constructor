"""`revision_json`: el veredicto de la IA por fila, y su invalidación.

Un veredicto sobre un APU que la fila ya no tiene es peor que ninguno: se borra en
el mismo punto donde se cambia el APU (`actualizar_eleccion`).

El mismo cuerpo corre contra los dos backends. SQLite siempre; Postgres solo con
TEST_DATABASE_URL (base desechable: `reset()` hace DROP SCHEMA).
"""
import os
import sqlite3

import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.datos.corridas_db import CorridasDB
from apu_tool.nucleo.models import CorridaItemRow, CorridaMeta, LicitacionItem

_BACKENDS = ["sqlite"]
if os.environ.get("TEST_DATABASE_URL"):
    _BACKENDS.append("postgres")


@pytest.fixture(params=_BACKENDS)
def corridas(request, tmp_path):
    """Repositorio de corridas de cada backend, con esquema limpio."""
    if request.param == "sqlite":
        alm = Almacen(tmp_path / "p.db", tmp_path / "a.db", tmp_path / "c.db")
        alm.init_schema()
        yield alm.corridas
        return
    from apu_tool.datos.pg.conexion import Conexion
    from apu_tool.datos.pg.corridas_pg import CorridasPg
    cx = Conexion(os.environ["TEST_DATABASE_URL"])
    repo = CorridasPg(cx)
    repo.reset()
    yield repo
    cx.cerrar()


def _corrida(corridas) -> int:
    cid = corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-08-31T10:00:00", archivo="x.xlsx",
        turno_def="DIURNO", use_ai=None, estado="en_revision", cuadro_path=None,
        nombre="x"))
    corridas.agregar_item(cid, CorridaItemRow(
        seq=0, item=LicitacionItem(item="1", descripcion="A", unidad="M3", cantidad=1,
                                   precio_contractual=0, shift="DIURNO"),
        status="auto", apu_codigo="100", apu_nombre="A", unidad="M3", shift="DIURNO",
        origen="historico", confianza=1.0, explicacion="", componentes=[], candidatos=[]))
    return cid


def test_fila_nueva_no_tiene_veredicto(corridas):
    cid = _corrida(corridas)
    assert corridas.get_revisiones(cid) == {}
    assert corridas.get_items(cid)[0].revision is None


def test_guarda_y_lee_el_veredicto(corridas):
    cid = _corrida(corridas)
    v = {"seq": 0, "dictamen": "cambiar", "apu_sugerido": "200",
         "turno_sugerido": "DIURNO", "confianza": 0.8,
         "justificacion": "la unidad no coincide", "nivel": "profundo"}
    corridas.set_revision(cid, 0, v)
    assert corridas.get_revisiones(cid) == {0: v}
    assert corridas.get_items(cid)[0].revision == v
    assert corridas.get_item(cid, 0).revision == v


def test_set_revision_none_borra_el_veredicto(corridas):
    """La forma explícita de invalidar: nadie tiene que ir a tocar la columna."""
    cid = _corrida(corridas)
    corridas.set_revision(cid, 0, {"seq": 0, "dictamen": "dudoso", "apu_sugerido": None,
                                   "turno_sugerido": None, "confianza": 0.4,
                                   "justificacion": "", "nivel": "barrido"})
    corridas.set_revision(cid, 0, None)
    assert corridas.get_revisiones(cid) == {}
    assert corridas.get_items(cid)[0].revision is None


def test_cambiar_el_apu_borra_el_veredicto(corridas):
    cid = _corrida(corridas)
    corridas.set_revision(cid, 0, {"seq": 0, "dictamen": "ok", "apu_sugerido": None,
                                   "turno_sugerido": None, "confianza": 1.0,
                                   "justificacion": "", "nivel": "barrido"})
    corridas.actualizar_eleccion(
        cid, 0, status="confirmed", apu_codigo="200", apu_nombre="B", unidad="M3",
        shift="DIURNO", origen="historico", confianza=1.0, explicacion="", componentes=[])
    assert corridas.get_revisiones(cid) == {}
    assert corridas.get_items(cid)[0].revision is None


def test_migracion_agrega_revision_json(tmp_path):
    """Una base vieja sin la columna se migra sola al arrancar, dos veces sin romper."""
    p = tmp_path / "old.db"
    conn = sqlite3.connect(p)
    conn.executescript(
        "CREATE TABLE corrida (id INTEGER PRIMARY KEY AUTOINCREMENT, creada_en TEXT, "
        "archivo TEXT, turno_def TEXT, use_ai INTEGER, estado TEXT, cuadro_path TEXT, "
        "duracion_ms INTEGER);"
        "CREATE TABLE corrida_item (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "corrida_id INTEGER NOT NULL REFERENCES corrida(id) ON DELETE CASCADE, seq INTEGER, "
        "item_json TEXT, status TEXT, apu_codigo TEXT, apu_nombre TEXT, unidad TEXT, "
        "shift TEXT, origen TEXT, confianza REAL, explicacion TEXT, componentes_json TEXT, "
        "candidatos_json TEXT);")
    conn.commit(); conn.close()
    db = CorridasDB(p)
    db.init_schema()
    db.init_schema()   # 2ª vez: idempotente
    cid = _corrida(db)
    assert db.get_items(cid)[0].revision is None
    db.set_revision(cid, 0, {"dictamen": "ok"})
    assert db.get_revisiones(cid) == {0: {"dictamen": "ok"}}
