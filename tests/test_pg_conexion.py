import os
import pytest
from apu_tool import config


def test_db_backend_por_defecto_es_sqlite(monkeypatch):
    monkeypatch.delenv("APU_DB_BACKEND", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert config.db_backend() == "sqlite"


def test_db_backend_postgres_por_database_url(monkeypatch):
    monkeypatch.delenv("APU_DB_BACKEND", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    assert config.db_backend() == "postgres"


def test_db_backend_postgres_explicito(monkeypatch):
    monkeypatch.setenv("APU_DB_BACKEND", "postgres")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert config.db_backend() == "postgres"


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"),
                    reason="sin TEST_DATABASE_URL: se omite la prueba contra Postgres real")
def test_conexion_hace_ping():
    from apu_tool.datos.pg.conexion import Conexion
    cx = Conexion(os.environ["TEST_DATABASE_URL"])
    try:
        with cx.connection() as conn:
            r = conn.execute("SELECT 1 AS uno").fetchone()
            assert r["uno"] == 1
    finally:
        cx.cerrar()
