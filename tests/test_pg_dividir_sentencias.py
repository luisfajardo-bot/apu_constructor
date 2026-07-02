"""Prueba local (sin Postgres) del particionador de scripts DDL de Postgres.

Regresión: un ';' dentro de un comentario '-- ...' en db/pg/precios.sql hacía
que el split ingenuo por ';' cortara un CREATE TABLE por la mitad -> Postgres
recibía una tabla sin cerrar ('syntax error at end of input'). Invisible en
local (los tests Postgres se saltan sin TEST_DATABASE_URL); solo el CI lo veía.

Estos tests analizan texto puro, así que corren SIEMPRE (no necesitan un
Postgres real) y cazan esta clase de bug antes de llegar al CI.
"""
from apu_tool import config
from apu_tool.datos.pg.conexion import dividir_sentencias


def test_punto_y_coma_en_comentario_no_corta_sentencia():
    sql = """
    CREATE TABLE t (
        id INT,
        x  INT  -- nota con ; adentro; no debe cortar la sentencia
    );
    CREATE INDEX i ON t(id);
    """
    sents = dividir_sentencias(sql)
    assert len(sents) == 2, f"esperaba 2 sentencias, obtuve {len(sents)}: {sents}"
    assert sents[0].startswith("CREATE TABLE t")
    # el CREATE TABLE quedó completo: paréntesis balanceados
    assert sents[0].count("(") == sents[0].count(")")
    assert "CREATE INDEX" in sents[1]


def test_comentario_de_linea_completo_se_ignora():
    sql = "-- solo un comentario; con punto y coma\nSELECT 1;"
    sents = dividir_sentencias(sql)
    assert sents == ["SELECT 1"]


def test_esquemas_pg_reales_se_parten_en_sentencias_completas():
    """Cada db/pg/*.sql debe partirse en sentencias con paréntesis balanceados.

    Es el proxy local más fiel a "este esquema cargará en Postgres": con el bug
    original (';' en comentario) el CREATE TABLE quedaba con paréntesis
    desbalanceados y este test habría fallado localmente.
    """
    pg_dir = config.PROJECT_ROOT / "db" / "pg"
    archivos = sorted(pg_dir.glob("*.sql"))
    assert archivos, "no se encontraron esquemas en db/pg/*.sql"
    for sql_file in archivos:
        for sent in dividir_sentencias(sql_file.read_text("utf-8")):
            assert sent.count("(") == sent.count(")"), (
                f"paréntesis desbalanceados al partir {sql_file.name} "
                f"(¿';' dentro de un comentario?): {sent[:70]!r}"
            )
