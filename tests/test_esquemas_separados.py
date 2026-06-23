"""Los dos esquemas SQL separados existen y crean sus tablas."""
import sqlite3
from apu_tool import config

def _tablas(sql_path, tmp):
    con = sqlite3.connect(tmp)
    con.executescript(sql_path.read_text(encoding="utf-8"))
    t = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    return t

def test_esquema_precios(tmp_path):
    p = config.PROJECT_ROOT / "db" / "precios.sql"
    assert p.exists()
    assert {"insumos", "insumo_precios", "meta"} <= _tablas(p, tmp_path / "p.db")

def test_esquema_apus(tmp_path):
    p = config.PROJECT_ROOT / "db" / "apus.sql"
    assert p.exists()
    assert {"apus", "apu_componentes", "meta"} <= _tablas(p, tmp_path / "a.db")

def test_rutas_config():
    assert config.PRECIOS_DB_PATH.name == "precios.db"
    assert config.APUS_DB_PATH.name == "apus.db"
