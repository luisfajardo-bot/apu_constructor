"""Listas de precios: tabla, semilla de Principal y CRUD."""
import sqlite3

import pytest

from apu_tool import config
from apu_tool.datos.precios_db import PreciosDB
from apu_tool.nucleo.models import Insumo


@pytest.fixture()
def precios(tmp_path):
    p = PreciosDB(tmp_path / "precios.db")
    p.init_schema()
    return p


def test_principal_existe_con_id_1(precios):
    listas = precios.listar_listas()
    assert [(l.id, l.nombre) for l in listas] == [(config.LISTA_PRINCIPAL_ID, "Principal")]


def test_init_schema_es_idempotente(precios):
    precios.init_schema()
    precios.init_schema()
    assert len(precios.listar_listas()) == 1


def test_crear_lista_devuelve_id_y_aparece_en_listar(precios):
    lid = precios.crear_lista("NP Calle 13", creado_por="u1")
    assert lid != config.LISTA_PRINCIPAL_ID
    lista = precios.get_lista(lid)
    assert lista.nombre == "NP Calle 13" and lista.creado_por == "u1"
    assert lista.creada_en                      # fecha ISO no vacía
    assert {l.nombre for l in precios.listar_listas()} == {"Principal", "NP Calle 13"}


def test_crear_lista_rechaza_nombre_vacio(precios):
    with pytest.raises(ValueError):
        precios.crear_lista("   ")


def test_crear_lista_rechaza_duplicado_sin_importar_mayusculas(precios):
    precios.crear_lista("NP Calle 13")
    with pytest.raises(ValueError):
        precios.crear_lista("np calle 13")


def test_renombrar_lista(precios):
    lid = precios.crear_lista("NP Calle 13")
    precios.renombrar_lista(lid, "NP Calle 13 - Acta 2")
    assert precios.get_lista(lid).nombre == "NP Calle 13 - Acta 2"


def test_renombrar_principal_esta_prohibido(precios):
    with pytest.raises(ValueError):
        precios.renombrar_lista(config.LISTA_PRINCIPAL_ID, "Otra cosa")


def test_renombrar_lista_inexistente_lanza(precios):
    with pytest.raises(ValueError):
        precios.renombrar_lista(999, "X")


def test_get_lista_inexistente_devuelve_none(precios):
    assert precios.get_lista(999) is None


def test_reset_deja_principal_de_nuevo(precios):
    precios.crear_lista("NP Calle 13")
    precios.reset()
    assert [l.nombre for l in precios.listar_listas()] == ["Principal"]


# ---------------------------------------------------------------------------
# Hallazgo 1 — migración de una base PREEXISTENTE (anterior a lista_precios).
# Los tests de arriba corren sobre tmp_path nuevo: CREATE TABLE ya crea
# insumo_precios CON lista_id, así que nunca ejercitan el ALTER TABLE de
# init_schema. Este test arma a mano el esquema viejo (sin lista_id, sin
# lista_precios) con filas de precio adentro, y verifica que init_schema
# migra sin perder nada.
# ---------------------------------------------------------------------------
def test_init_schema_migra_base_preexistente_sin_lista_id(tmp_path):
    db_path = tmp_path / "precios_vieja.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE insumos (
            id          INTEGER PRIMARY KEY,
            codigo      TEXT NOT NULL,
            nombre      TEXT NOT NULL,
            nombre_norm TEXT NOT NULL,
            unidad      TEXT,
            grupo       TEXT,
            oculto      INTEGER NOT NULL DEFAULT 0,
            UNIQUE (codigo, nombre_norm)
        );
        CREATE INDEX idx_insumo_cod ON insumos(codigo);

        CREATE TABLE insumo_precios (
            id            INTEGER PRIMARY KEY,
            insumo_id     INTEGER NOT NULL,
            precio        REAL NOT NULL,
            fuente        TEXT,
            clasificacion TEXT,
            fecha         TEXT,
            vigente       INTEGER NOT NULL DEFAULT 1,
            creado_por    TEXT,
            FOREIGN KEY (insumo_id) REFERENCES insumos(id)
        );

        CREATE TABLE meta (
            clave TEXT PRIMARY KEY,
            valor TEXT
        );

        CREATE INDEX idx_precio_ins ON insumo_precios(insumo_id, vigente);
        """
    )
    conn.execute(
        "INSERT INTO insumos (id, codigo, nombre, nombre_norm, unidad, grupo) "
        "VALUES (1, 'C1', 'Cemento gris', 'CEMENTO GRIS', 'kg', 'materiales')")
    conn.execute(
        "INSERT INTO insumos (id, codigo, nombre, nombre_norm, unidad, grupo) "
        "VALUES (2, 'C2', 'Arena de rio', 'ARENA DE RIO', 'm3', 'materiales')")
    conn.execute(
        "INSERT INTO insumo_precios "
        "(id, insumo_id, precio, fuente, clasificacion, fecha, vigente, creado_por) "
        "VALUES (1, 1, 1234.5, 'PRECIO IDU', 'publico', '2026-01-01', 1, NULL)")
    conn.execute(
        "INSERT INTO insumo_precios "
        "(id, insumo_id, precio, fuente, clasificacion, fecha, vigente, creado_por) "
        "VALUES (2, 2, 987.0, 'COSTO INTERNO', 'interno', '2026-02-02', 0, 'u1')")
    conn.commit()
    conn.close()

    p = PreciosDB(db_path)
    p.init_schema()

    with p.connect() as c:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(insumo_precios)").fetchall()}
        assert "lista_id" in cols  # (a)

        indices = {r["name"] for r in c.execute("PRAGMA index_list(insumo_precios)").fetchall()}
        assert "idx_precio_ins_lista" in indices  # (b)

        filas = c.execute(
            "SELECT insumo_id, precio, fuente, clasificacion, fecha, vigente, creado_por, "
            "lista_id FROM insumo_precios ORDER BY id").fetchall()
    assert len(filas) == 2
    assert (filas[0]["insumo_id"], filas[0]["precio"], filas[0]["fuente"],
            filas[0]["clasificacion"], filas[0]["fecha"], filas[0]["vigente"],
            filas[0]["creado_por"], filas[0]["lista_id"]) == (
                1, 1234.5, "PRECIO IDU", "publico", "2026-01-01", 1, None, 1)
    assert (filas[1]["insumo_id"], filas[1]["precio"], filas[1]["fuente"],
            filas[1]["clasificacion"], filas[1]["fecha"], filas[1]["vigente"],
            filas[1]["creado_por"], filas[1]["lista_id"]) == (
                2, 987.0, "COSTO INTERNO", "interno", "2026-02-02", 0, "u1", 1)  # (c)

    listas = p.listar_listas()
    assert [(l.id, l.nombre) for l in listas] == [(config.LISTA_PRINCIPAL_ID, "Principal")]  # (d)


# ---------------------------------------------------------------------------
# Hallazgo 2 — el NOT NULL DEFAULT 1 de lista_id es el ancla del invariante:
# insert_insumos y set_precio_por_id omiten la columna a propósito. Si el
# DEFAULT se pierde (p.ej. columna nullable sin DEFAULT), estos inserts
# quedarían con lista_id NULL y las consultas futuras que filtran
# lista_id = 1 no encontrarían el precio (costeo en $0 silencioso).
# ---------------------------------------------------------------------------
def test_insert_insumos_y_set_precio_por_id_dejan_lista_id_principal(precios):
    insumo = Insumo(codigo="X1", nombre="Insumo de prueba", unidad="kg",
                     grupo="materiales", precio=100.0, fuente_precio="PRECIO IDU")
    precios.insert_insumos([insumo])

    with precios.connect() as c:
        fila = c.execute(
            "SELECT i.id AS iid, p.lista_id FROM insumo_precios p "
            "JOIN insumos i ON i.id = p.insumo_id WHERE i.codigo=?", ("X1",)).fetchone()
    assert fila["lista_id"] == config.LISTA_PRINCIPAL_ID  # insert_insumos
    insumo_id = fila["iid"]

    precios.set_precio_por_id(insumo_id, 150.0, fuente="COSTO INTERNO")

    with precios.connect() as c:
        fila2 = c.execute(
            "SELECT lista_id FROM insumo_precios WHERE insumo_id=? AND vigente=1",
            (insumo_id,)).fetchone()
    assert fila2["lista_id"] == config.LISTA_PRINCIPAL_ID  # set_precio_por_id


# ---------------------------------------------------------------------------
# Hallazgo 3 — guard de duplicado en renombrar_lista (sin test hasta ahora).
# ---------------------------------------------------------------------------
def test_renombrar_lista_rechaza_duplicado(precios):
    precios.crear_lista("NP Calle 13")
    lid2 = precios.crear_lista("NP Otra obra")
    with pytest.raises(ValueError):
        precios.renombrar_lista(lid2, "np calle 13")


# ---------------------------------------------------------------------------
# Hallazgo 4 — la detección de duplicados debe funcionar con tildes/ñ, no
# solo ASCII (UPPER() de SQLite no pliega ñ/tildes).
# ---------------------------------------------------------------------------
def test_crear_lista_rechaza_duplicado_con_tildes_y_ene(precios):
    precios.crear_lista("NP Peñón")
    with pytest.raises(ValueError):
        precios.crear_lista("NP PEÑÓN")


def test_renombrar_lista_rechaza_duplicado_con_tildes_y_ene(precios):
    precios.crear_lista("NP Peñón")
    lid2 = precios.crear_lista("NP Otra obra")
    with pytest.raises(ValueError):
        precios.renombrar_lista(lid2, "NP PEÑÓN")
