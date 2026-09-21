"""El origen de importación de una corrida (entidad, hoja, parser, conciliación)."""
import json

from apu_tool.datos.corridas_db import CorridasDB
from apu_tool.nucleo.models import CorridaMeta

ORIGEN = {
    "entidad": "IDU", "formato": "idu_formulario_1",
    "hoja": "PROPUESTA ECONÓMICA", "fila_encabezado": 10,
    "parser_version": "idu-f1/1", "estructura_confirmada": True,
    "capitulos": 14, "actividades": 1939,
    "conciliacion": {"contractual_con_aiu": 158456072140, "diferencia": 0},
}


def _db(tmp_path) -> CorridasDB:
    db = CorridasDB(tmp_path / "corridas.db")
    db.init_schema()
    return db


def _crear(db) -> int:
    return db.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-09-11T09:00:00", archivo="f1.xlsx",
        turno_def="DIURNO", use_ai=False, estado="armando", cuadro_path=None))


def test_origen_se_guarda_y_se_relee(tmp_path):
    db = _db(tmp_path)
    cid = _crear(db)
    db.set_origen(cid, json.dumps(ORIGEN, ensure_ascii=False))
    assert json.loads(db.get_origen(cid)) == ORIGEN


def test_origen_llega_en_la_meta(tmp_path):
    db = _db(tmp_path)
    cid = _crear(db)
    db.set_origen(cid, json.dumps(ORIGEN, ensure_ascii=False))
    meta = db.get_corrida(cid)
    assert meta.origen["entidad"] == "IDU"
    assert meta.origen["capitulos"] == 14
    # Y también en el listado, que es otra ruta de hidratación.
    assert db.listar_corridas()[0].origen["hoja"] == "PROPUESTA ECONÓMICA"


def test_corrida_vieja_sin_origen_abre_igual(tmp_path):
    # Es el caso de TODA corrida anterior a esta feature: la columna llega en NULL.
    db = _db(tmp_path)
    cid = _crear(db)
    assert db.get_origen(cid) is None
    assert db.get_corrida(cid).origen is None
    assert db.listar_corridas()[0].origen is None


def test_origen_con_json_corrupto_no_tumba_el_listado(tmp_path):
    # Una corrida con basura en la columna no puede impedir abrir "Mis corridas".
    db = _db(tmp_path)
    cid = _crear(db)
    db.set_origen(cid, "{esto no es json")
    assert db.get_corrida(cid).origen is None
    assert db.listar_corridas()[0].origen is None


def test_migracion_idempotente(tmp_path):
    # init_schema corre en cada arranque: dos veces no puede romper nada.
    db = _db(tmp_path)
    cid = _crear(db)
    db.set_origen(cid, json.dumps(ORIGEN, ensure_ascii=False))
    db.init_schema()
    db.init_schema()
    assert json.loads(db.get_origen(cid)) == ORIGEN


def test_origen_de_una_corrida_inexistente_es_none(tmp_path):
    assert _db(tmp_path).get_origen(9999) is None


def test_el_contrato_de_corridas_incluye_el_origen():
    # `test_paridad_backends` ya compara firmas entre SQLite y Postgres; esto fija que
    # además esté en el Protocol, que es lo que hace el reemplazo de backend limpio.
    from apu_tool.datos.repositorio import RepositorioCorridas
    assert hasattr(RepositorioCorridas, "set_origen")
    assert hasattr(RepositorioCorridas, "get_origen")


def test_el_esquema_pg_trae_origen_json():
    from pathlib import Path
    sql = Path("db/pg/corridas.sql").read_text(encoding="utf-8")
    assert "origen_json   TEXT," in sql
    # La migración idempotente para bases que ya existen (Supabase corre esto al boot).
    assert "ADD COLUMN IF NOT EXISTS origen_json TEXT" in sql


def test_el_esquema_sqlite_trae_origen_json():
    from pathlib import Path
    sql = Path("db/corridas.sql").read_text(encoding="utf-8")
    assert "origen_json   TEXT," in sql
