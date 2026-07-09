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


def test_ejecutar_script_parte_en_sentencias():
    from apu_tool.datos.pg.conexion import ejecutar_script

    class _StubConn:
        def __init__(self):
            self.ejecutadas = []
        def execute(self, sql):
            self.ejecutadas.append(sql.strip())

    stub = _StubConn()
    ejecutar_script(stub, "CREATE TABLE a (id int);\nCREATE INDEX ix ON a(id);\n")
    assert len(stub.ejecutadas) == 2
    assert stub.ejecutadas[0].startswith("CREATE TABLE a")
    assert stub.ejecutadas[1].startswith("CREATE INDEX ix")


class _FakeConn:
    """Conexión falsa: puede fallar en ejecutar según un guion de errores."""
    def __init__(self, error=None):
        self._error = error
        self.ejecutadas = []
    def execute(self, sql):
        if self._error is not None and not sql.strip().lower().startswith("set local"):
            raise self._error
        self.ejecutadas.append(sql.strip())
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def test_aplicar_migracion_reintenta_ante_lock_y_luego_pasa():
    import psycopg
    from apu_tool.datos.pg.conexion import aplicar_migracion

    # Dos intentos fallan por lock, el tercero funciona.
    guion = [psycopg.errors.LockNotAvailable("bloqueado"),
             psycopg.errors.LockNotAvailable("bloqueado"),
             None]
    conns = []
    def abrir():
        conn = _FakeConn(guion.pop(0))
        conns.append(conn)
        return conn
    dormidas = []
    aplicar_migracion(abrir, "CREATE TABLE x (id int);", intentos=5,
                      espera_s=0.0, dormir=lambda s: dormidas.append(s))
    assert len(conns) == 3                 # reintentó hasta que pasó
    assert conns[-1].ejecutadas[0].lower().startswith("set local lock_timeout")
    assert any(s.startswith("CREATE TABLE x") for s in conns[-1].ejecutadas)
    assert len(dormidas) == 2              # esperó entre los intentos fallidos


def test_aplicar_migracion_relanza_si_agota_intentos():
    import psycopg
    from apu_tool.datos.pg.conexion import aplicar_migracion

    def abrir():
        return _FakeConn(psycopg.errors.QueryCanceled("statement timeout"))
    with pytest.raises(psycopg.errors.QueryCanceled):
        aplicar_migracion(abrir, "CREATE TABLE x (id int);", intentos=3,
                          espera_s=0.0, dormir=lambda s: None)
