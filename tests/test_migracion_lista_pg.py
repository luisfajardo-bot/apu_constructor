"""La migración de `lista_id` sobre una base Postgres PREEXISTENTE (el deploy real).

Los demás tests de Postgres hacen `DROP SCHEMA ... CASCADE` antes de aplicar
`db/pg/precios.sql`, así que crean `precios.insumo_precios` ya con la columna
`lista_id` y el bloque de migración (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`) les
queda como **no-op**: nunca se ejecuta el camino que sí va a ocurrir en producción.

Este módulo recorre el camino de producción: levanta el esquema ANTERIOR a las listas
(sin `lista_id`), lo llena con datos del orden de magnitud de la base real y sólo
entonces aplica el script nuevo, como haría el arranque del servicio tras el deploy.

Lo que se protege es el peor escenario del despliegue: que la columna quede sin el
DEFAULT (filas con `lista_id` nulo o ajeno = costeo en $0 silencioso, ver
`regla nada en $0`), que la lista Principal no quede sembrada con id 1, o que la
secuencia de `lista_precios` arranque en 1 y `crear_lista` reutilice el id de
Principal — con `corrida.lista_precios_id` guardado deliberadamente SIN FK, un id
reciclado le cambia la tarifa a corridas ya emitidas.
"""
import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="sin TEST_DATABASE_URL")

# Esquema de `precios` tal como estaba ANTES de las listas (d4530b8^). Se copia acá
# en vez de leerlo de git para que el test no dependa del historial del repo.
SQL_PREVIO = """
CREATE SCHEMA IF NOT EXISTS precios;

CREATE TABLE IF NOT EXISTS precios.insumos (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    codigo      TEXT NOT NULL,
    nombre      TEXT NOT NULL,
    nombre_norm TEXT NOT NULL,
    unidad      TEXT,
    grupo       TEXT,
    oculto      BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (codigo, nombre_norm)
);
CREATE INDEX IF NOT EXISTS idx_insumo_cod ON precios.insumos(codigo);

CREATE TABLE IF NOT EXISTS precios.insumo_precios (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    insumo_id     BIGINT NOT NULL REFERENCES precios.insumos(id) ON DELETE CASCADE,
    precio        DOUBLE PRECISION NOT NULL,
    fuente        TEXT,
    clasificacion TEXT,
    fecha         TEXT,
    vigente       INTEGER NOT NULL DEFAULT 1,
    creado_por    TEXT
);
CREATE INDEX IF NOT EXISTS idx_precio_ins ON precios.insumo_precios(insumo_id, vigente);

CREATE TABLE IF NOT EXISTS precios.meta (
    clave TEXT PRIMARY KEY,
    valor TEXT
);
"""

N_INSUMOS = 8200        # del orden de los 8157 de producción
PRECIOS_POR_INSUMO = 3  # historial por insumo; el último es el vigente
PRECIO_VIGENTE = 1000 + PRECIOS_POR_INSUMO * 10


@pytest.fixture(scope="module")
def base_migrada():
    """Base con el esquema viejo + datos, ya migrada por el script nuevo.

    Scope de módulo: la siembra es lo caro y todos los tests miran el resultado de
    la MISMA migración (es un solo evento de deploy, no uno por aserción).
    """
    from apu_tool import config
    from apu_tool.datos.pg.conexion import Conexion, ejecutar_script
    cx = Conexion(os.environ["TEST_DATABASE_URL"])
    sql_nuevo = (config.PROJECT_ROOT / "db" / "pg" / "precios.sql").read_text("utf-8")

    with cx.connection() as conn:
        conn.execute("DROP SCHEMA IF EXISTS precios CASCADE")
        ejecutar_script(conn, SQL_PREVIO)
        # Precondición del test: si el esquema previo YA tuviera lista_id, el ALTER
        # sería no-op y este módulo no probaría nada (el agujero que vino a tapar).
        assert all(c["column_name"] != "lista_id" for c in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='precios' AND table_name='insumo_precios'").fetchall())
        conn.execute(
            "INSERT INTO precios.insumos (codigo, nombre, nombre_norm, unidad, grupo) "
            "SELECT 'C'||g, 'INSUMO '||g, 'insumo '||g, 'UN', 'MATERIAL' "
            "FROM generate_series(1, %s) g", (N_INSUMOS,))
        conn.execute(
            "INSERT INTO precios.insumo_precios "
            "(insumo_id, precio, fuente, clasificacion, fecha, vigente) "
            "SELECT i.id, 1000 + h*10, 'PRECIO IDU', 'publico', now(), "
            "       CASE WHEN h = %s THEN 1 ELSE 0 END "
            "FROM precios.insumos i, generate_series(1, %s) h",
            (PRECIOS_POR_INSUMO, PRECIOS_POR_INSUMO))
        filas = conn.execute(
            "SELECT count(*) n FROM precios.insumo_precios").fetchone()["n"]

    with cx.connection() as conn:          # el deploy: arranque con el código nuevo
        ejecutar_script(conn, sql_nuevo)

    yield cx, filas, sql_nuevo
    cx.cerrar()


def test_migracion_no_pierde_precios(base_migrada):
    cx, filas, _ = base_migrada
    with cx.connection() as conn:
        assert conn.execute(
            "SELECT count(*) n FROM precios.insumo_precios").fetchone()["n"] == filas


def test_toda_fila_preexistente_queda_en_principal(base_migrada):
    """El chequeo del runbook: `WHERE lista_id <> 1` debe dar 0 tras migrar."""
    from apu_tool import config
    cx, _, _ = base_migrada
    with cx.connection() as conn:
        assert conn.execute(
            "SELECT count(*) n FROM precios.insumo_precios WHERE lista_id <> %s",
            (config.LISTA_PRINCIPAL_ID,)).fetchone()["n"] == 0
        assert conn.execute(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_schema='precios' AND table_name='insumo_precios' "
            "AND column_name='lista_id'").fetchone()["is_nullable"] == "NO"


def test_principal_sembrada_con_id_1(base_migrada):
    from apu_tool import config
    cx, _, _ = base_migrada
    with cx.connection() as conn:
        listas = conn.execute(
            "SELECT id, nombre FROM precios.lista_precios ORDER BY id").fetchall()
    assert [(l["id"], l["nombre"]) for l in listas] == [
        (config.LISTA_PRINCIPAL_ID, "Principal")]


def test_fk_validada_e_indice_por_lista(base_migrada):
    """La FK se agrega con datos ya cargados: tiene que quedar VALIDATED, no NOT VALID."""
    cx, _, _ = base_migrada
    with cx.connection() as conn:
        fk = conn.execute(
            "SELECT convalidated FROM pg_constraint "
            "WHERE conrelid = 'precios.insumo_precios'::regclass AND contype = 'f' "
            "AND confrelid = 'precios.lista_precios'::regclass").fetchone()
        assert fk is not None and fk["convalidated"] is True
        assert conn.execute(
            "SELECT 1 FROM pg_indexes WHERE schemaname='precios' "
            "AND indexname='idx_precio_ins_lista'").fetchone() is not None


def test_segundo_boot_es_idempotente(base_migrada):
    """Un redeploy (o dos workers arrancando a la vez) reaplica el script."""
    cx, filas, sql_nuevo = base_migrada
    from apu_tool.datos.pg.conexion import ejecutar_script
    with cx.connection() as conn:
        ejecutar_script(conn, sql_nuevo)
        assert conn.execute(
            "SELECT count(*) n FROM precios.lista_precios").fetchone()["n"] == 1
        assert conn.execute(
            "SELECT count(*) n FROM precios.insumo_precios").fetchone()["n"] == filas


def test_crear_lista_no_recicla_el_id_de_principal(base_migrada):
    """La secuencia quedó adelantada por el setval del script.

    Sin él, el primer `crear_lista` post-migración devolvería 1 = Principal, y como
    `corrida.lista_precios_id` no tiene FK, una corrida vieja apuntaría de golpe a
    otra tarifa.
    """
    from apu_tool import config
    from apu_tool.datos.pg.precios_pg import PreciosPg
    cx, _, _ = base_migrada
    lid = PreciosPg(cx).crear_lista("NP migracion", creado_por="test")
    assert lid != config.LISTA_PRINCIPAL_ID


def test_precio_por_lista_sobre_base_migrada(base_migrada):
    """El código nuevo lee y escribe bien sobre datos que venían del esquema viejo."""
    from apu_tool.datos.pg.precios_pg import PreciosPg
    cx, _, _ = base_migrada
    pg = PreciosPg(cx)
    lid = pg.crear_lista("NP Calle 13", creado_por="test")
    with cx.connection() as conn:
        ins_id = conn.execute(
            "SELECT id FROM precios.insumos WHERE codigo='C1'").fetchone()["id"]

    # el precio migrado se lee como vigente en Principal
    cand = pg.get_candidatos("C1")
    assert [c.precio for c in cand] == [PRECIO_VIGENTE]

    pg.set_precio_por_id(ins_id, 5555.0, fuente="COSTO INTERNO", lista_id=lid)
    assert [c.precio for c in pg.get_candidatos("C1", lista_id=lid)] == [5555.0]
    # y la tarifa contractual de Principal no se movió
    assert [c.precio for c in pg.get_candidatos("C1")] == [PRECIO_VIGENTE]


def test_insumo_migrado_sin_tarifa_en_la_lista_no_hereda_principal(base_migrada):
    """El invariante de la feature, sobre datos migrados: sin tarifa en la lista NO
    se cae al precio de Principal ni al histórico embebido; queda marcado."""
    from apu_tool.datos.pg.precios_pg import PreciosPg
    cx, _, _ = base_migrada
    pg = PreciosPg(cx)
    lid = pg.crear_lista("NP sin tarifas", creado_por="test")
    cand = pg.get_candidatos("C2", lista_id=lid)
    assert len(cand) == 1
    assert cand[0].sin_precio is True
    assert not cand[0].precio          # 0.0 / None, nunca el de Principal
