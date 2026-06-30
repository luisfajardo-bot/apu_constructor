"""
Prueba de regresión: seed(force=True) NO debe reventar cuando precios.db tiene un
esquema viejo (sin columna insumo_id en insumo_precios).

El bug original: seed() llamaba alm.init_schema() ANTES de alm.reset(), y
init_schema() creaba un índice sobre insumo_precios.insumo_id que no existía en el
esquema viejo → sqlite3.OperationalError antes de que reset() pudiera reconstruirlo.
"""
import sqlite3

import openpyxl
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.datos.seed import seed


@pytest.fixture()
def old_schema_precios(tmp_path):
    """Crea un precios.db con el esquema VIEJO (sin insumo_id en insumo_precios)."""
    p = tmp_path / "precios.db"
    con = sqlite3.connect(p)
    con.executescript(
        "CREATE TABLE insumos (codigo TEXT PRIMARY KEY, nombre TEXT, unidad TEXT, grupo TEXT);"
        "CREATE TABLE insumo_precios (id INTEGER PRIMARY KEY, codigo TEXT NOT NULL, precio REAL,"
        " fuente TEXT, clasificacion TEXT, fecha TEXT, vigente INTEGER NOT NULL DEFAULT 1);"
        "CREATE TABLE meta (clave TEXT PRIMARY KEY, valor TEXT);"
        "INSERT INTO insumos VALUES ('100','VIEJO','KG','MAT');"
        "INSERT INTO insumo_precios (codigo,precio,vigente) VALUES ('100',1,1);"
    )
    con.commit()
    con.close()
    return p


@pytest.fixture()
def mini_xlsx(tmp_path):
    """Crea un Excel mínimo con la pestaña INSUMOS_IDU-INT que seed sabe leer.

    La config de InsumoSheet para esa pestaña:
        col_grupo=1, col_codigo=2, col_nombre=3, col_unidad=4, col_precio=5, col_fuente=6
    Así que cada fila necesita al menos 7 celdas (índices 0–6).
    """
    path = tmp_path / "mini.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "INSUMOS_IDU-INT"
    # Fila de cabecera (fila 1): seed arranca en start_row=2, así que esta se salta.
    ws.append(["x", "Grupo", "Codigo", "Nombre", "Und", "Precio", "Fuente"])
    # Fila de datos (fila 2): insumo nuevo que debe ganar tras el re-seed.
    ws.append(["", "MAT", "100", "CEMENTO", "KG", 1000, "PRECIO IDU"])
    wb.save(path)
    return path


def test_seed_force_sobre_esquema_viejo(old_schema_precios, mini_xlsx, tmp_path):
    """
    Dado un precios.db con esquema viejo y datos,
    seed(force=True) debe completar sin error y reconstruir con el nuevo esquema.
    """
    p_apus = tmp_path / "apus.db"
    alm = Almacen(old_schema_precios, p_apus)

    # No debe lanzar sqlite3.OperationalError ni ninguna otra excepción.
    result = seed(alm, xlsx_path=mini_xlsx, force=True)

    # El resultado debe indicar al menos un insumo insertado.
    assert result.get("insumos", 0) >= 1, f"Se esperaba al menos 1 insumo, got: {result}"

    # Los datos del esquema viejo desaparecieron; el nuevo insumo está presente.
    alm2 = Almacen(old_schema_precios, p_apus)
    cands = alm2.precios.get_candidatos("100")
    assert len(cands) == 1, f"Se esperaba 1 candidato, got: {len(cands)}"
    assert cands[0].nombre == "CEMENTO", f"Nombre esperado CEMENTO, got: {cands[0].nombre}"
    assert cands[0].id is not None, "El insumo del nuevo esquema debe tener id surrogate"


def test_seed_preserva_corridas(mini_xlsx, tmp_path):
    """Re-sembrar el catálogo NO debe borrar las corridas guardadas (regresión:
    'las corridas se borran después de un rato' = seed reseteaba corridas.db)."""
    from apu_tool.nucleo.models import CorridaMeta
    alm = Almacen(tmp_path / "p.db", tmp_path / "a.db", tmp_path / "c.db")
    alm.init_schema()
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="x", archivo="lic.xlsx", turno_def="DIURNO",
        use_ai=False, estado="en_revision"))

    seed(alm, xlsx_path=mini_xlsx, force=True)

    assert alm.corridas.get_corrida(cid) is not None    # la corrida sobrevive al re-seed
    assert alm.counts()["insumos"] >= 1                 # y el catálogo sí se sembró
