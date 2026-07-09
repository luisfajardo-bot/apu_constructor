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
    assert {c.id for c in alm.carpetas.listar()} == {cid, sub}
    assert alm.carpetas.eliminar(sub) is True
    assert alm.carpetas.contar_hijas(cid) == 0


def test_unicidad_hermanas_sqlite(tmp_path):
    alm = _alm(tmp_path)
    alm.carpetas.crear("Obra", parent_id=None)
    with pytest.raises(sqlite3.IntegrityError):
        alm.carpetas.crear("Obra", parent_id=None)
