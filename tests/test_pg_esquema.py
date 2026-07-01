import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="sin TEST_DATABASE_URL: se omite la prueba contra Postgres real")


def _aplicar_todo(conn):
    from apu_tool import config
    from apu_tool.datos.pg.conexion import ejecutar_script
    for archivo in ("precios.sql", "apus.sql", "corridas.sql"):
        sql = (config.PROJECT_ROOT / "db" / "pg" / archivo).read_text(encoding="utf-8")
        ejecutar_script(conn, sql)


def test_esquema_crea_tablas_calificadas():
    from apu_tool.datos.pg.conexion import Conexion
    cx = Conexion(os.environ["TEST_DATABASE_URL"])
    try:
        with cx.connection() as conn:
            _aplicar_todo(conn)
            r = conn.execute(
                "SELECT count(*) AS n FROM information_schema.tables "
                "WHERE table_schema IN ('precios','apus','corridas')").fetchone()
            assert r["n"] >= 8
    finally:
        cx.cerrar()
