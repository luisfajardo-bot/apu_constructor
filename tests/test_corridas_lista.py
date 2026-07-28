"""La corrida recuerda contra qué lista de precios se costea. Fijada al crear, inmutable."""
import sqlite3

import pytest

from apu_tool.datos.corridas_db import CorridasDB
from apu_tool.nucleo.models import CorridaMeta


@pytest.fixture()
def corridas(tmp_path):
    c = CorridasDB(tmp_path / "corridas.db")
    c.init_schema()
    return c


def _meta(lista_precios_id=None) -> CorridaMeta:
    return CorridaMeta(id=None, creada_en="2026-07-27T10:00:00", archivo="lic.xlsx",
                       turno_def="DIURNO", use_ai=False, estado="en_revision",
                       nombre="Acta NP 1", lista_precios_id=lista_precios_id)


def test_corrida_guarda_y_devuelve_la_lista(corridas):
    cid = corridas.crear_corrida(_meta(lista_precios_id=7))
    assert corridas.get_corrida(cid).lista_precios_id == 7


def test_corrida_sin_lista_queda_en_none(corridas):
    cid = corridas.crear_corrida(_meta())
    assert corridas.get_corrida(cid).lista_precios_id is None


def test_listar_corridas_incluye_la_lista(corridas):
    corridas.crear_corrida(_meta(lista_precios_id=7))
    assert [m.lista_precios_id for m in corridas.listar_corridas()] == [7]


def test_init_schema_idempotente_conserva_la_lista(corridas):
    cid = corridas.crear_corrida(_meta(lista_precios_id=7))
    corridas.init_schema()
    assert corridas.get_corrida(cid).lista_precios_id == 7


def test_migracion_agrega_lista_precios_id_sobre_base_preexistente(tmp_path):
    # Base "vieja" (esquema previo a esta tarea: ya tiene modo/carpeta_id/nombre pero
    # NO lista_precios_id) con una fila real dentro. init_schema() debe agregar la
    # columna sin romper ni perder valores, y dejarla en NULL (= Principal).
    p = tmp_path / "old.db"
    conn = sqlite3.connect(p)
    conn.executescript(
        "CREATE TABLE corrida (id INTEGER PRIMARY KEY AUTOINCREMENT, creada_en TEXT, "
        "archivo TEXT, turno_def TEXT, use_ai INTEGER, estado TEXT, cuadro_path TEXT, "
        "duracion_ms INTEGER, modo TEXT NOT NULL DEFAULT 'activa', carpeta_id INTEGER, "
        "nombre TEXT);"
        "CREATE TABLE corrida_item (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "corrida_id INTEGER NOT NULL REFERENCES corrida(id) ON DELETE CASCADE, seq INTEGER, "
        "item_json TEXT, status TEXT, apu_codigo TEXT, apu_nombre TEXT, unidad TEXT, shift TEXT, "
        "origen TEXT, confianza REAL, explicacion TEXT, componentes_json TEXT, "
        "candidatos_json TEXT, snapshot_json TEXT);")
    conn.execute(
        "INSERT INTO corrida (creada_en, archivo, turno_def, use_ai, estado, cuadro_path, "
        "duracion_ms, modo, carpeta_id, nombre) "
        "VALUES ('2026-07-01T09:00:00','acta-np.xlsx','NOCTURNO',1,'finalizada',"
        "'salidas/x.xlsx',1234,'congelada',5,'Acta NP vieja')")
    conn.commit(); conn.close()

    cols_antes = {r[1] for r in sqlite3.connect(p).execute("PRAGMA table_info(corrida)")}
    assert "lista_precios_id" not in cols_antes  # confirma que el fixture simula la base vieja

    db = CorridasDB(p)
    db.init_schema()  # debe agregar lista_precios_id (idempotente) sin perder la fila
    db.init_schema()  # 2ª vez: no falla

    cols_despues = {r[1] for r in sqlite3.connect(p).execute("PRAGMA table_info(corrida)")}
    assert "lista_precios_id" in cols_despues

    metas = db.listar_corridas()
    assert len(metas) == 1
    m = metas[0]
    assert m.lista_precios_id is None
    # El resto de los valores de la fila vieja se preserva intacto.
    assert m.creada_en == "2026-07-01T09:00:00"
    assert m.archivo == "acta-np.xlsx"
    assert m.turno_def == "NOCTURNO"
    assert m.use_ai is True
    assert m.estado == "finalizada"
    assert m.cuadro_path == "salidas/x.xlsx"
    assert m.duracion_ms == 1234
    assert m.modo == "congelada"
    assert m.carpeta_id == 5
    assert m.nombre == "Acta NP vieja"
