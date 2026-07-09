import sqlite3

import pytest

from apu_tool.nucleo.models import Carpeta, CorridaMeta
from apu_tool.datos.almacen import Almacen


def test_carpeta_dataclass_defaults():
    c = Carpeta(id=None, nombre="Calle 13", parent_id=None, creada_en="2026-07-09")
    assert c.parent_id is None
    assert c.creado_por is None


def test_corrida_meta_tiene_carpeta_id():
    m = CorridaMeta(id=None, creada_en="2026-07-09", archivo="x.xlsx",
                    turno_def="DIURNO", use_ai=False, estado="armando")
    assert m.carpeta_id is None


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def test_schema_crea_tabla_carpeta_y_columna(tmp_path):
    alm = _alm(tmp_path)
    with alm.corridas.connect() as conn:
        tablas = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "carpeta" in tablas
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(corrida)").fetchall()}
        assert "carpeta_id" in cols


def test_crud_carpeta_sqlite(tmp_path):
    alm = _alm(tmp_path)
    cid = alm.carpetas.crear("Calle 13", parent_id=None, creado_por="u1")
    c = alm.carpetas.get(cid)
    assert c.nombre == "Calle 13" and c.parent_id is None
    sub = alm.carpetas.crear("Lote 3", parent_id=cid, creado_por="u1")
    assert alm.carpetas.contar_hijas(cid) == 1
    alm.carpetas.renombrar(cid, "Calle 13 SL5")
    assert alm.carpetas.get(cid).nombre == "Calle 13 SL5"
    assert {cid, sub}.issubset({c.id for c in alm.carpetas.listar()})
    assert alm.carpetas.eliminar(sub) is True
    assert alm.carpetas.contar_hijas(cid) == 0


def test_unicidad_hermanas_sqlite(tmp_path):
    alm = _alm(tmp_path)
    alm.carpetas.crear("Obra", parent_id=None)
    with pytest.raises(sqlite3.IntegrityError):
        alm.carpetas.crear("Obra", parent_id=None)


def test_backfill_sin_clasificar(tmp_path):
    # Simula una base vieja: crea una corrida sin carpeta_id insertándola directo.
    alm = _alm(tmp_path)
    with alm.corridas.connect() as conn:
        conn.execute("INSERT INTO corrida (creada_en, archivo, turno_def, estado) "
                     "VALUES ('2026-01-01', 'vieja.xlsx', 'DIURNO', 'finalizada')")
    # Re-init: debe crear "Sin clasificar" y backfillear.
    alm.corridas.init_schema()
    with alm.corridas.connect() as conn:
        sc = conn.execute("SELECT id FROM carpeta WHERE nombre='Sin clasificar' "
                          "AND parent_id IS NULL").fetchone()
        assert sc is not None
        row = conn.execute("SELECT carpeta_id FROM corrida WHERE archivo='vieja.xlsx'").fetchone()
        assert row["carpeta_id"] == sc["id"]


def test_set_carpeta(tmp_path):
    alm = _alm(tmp_path)
    dest = alm.carpetas.crear("Destino", parent_id=None)
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-07-09", archivo="x.xlsx", turno_def="DIURNO",
        use_ai=False, estado="armando", carpeta_id=dest))
    otra = alm.carpetas.crear("Otra", parent_id=None)
    alm.corridas.set_carpeta(cid, otra)
    assert alm.corridas.get_corrida(cid).carpeta_id == otra
