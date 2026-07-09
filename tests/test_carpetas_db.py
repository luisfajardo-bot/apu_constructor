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
