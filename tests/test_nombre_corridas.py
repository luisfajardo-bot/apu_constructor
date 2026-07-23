from apu_tool.servicio.corridas import nombre_desde_archivo
from apu_tool.nucleo.models import CorridaMeta
from apu_tool.datos.corridas_db import CorridasDB


def _corridas_db(tmp_path):
    db = CorridasDB(tmp_path / "c.db")
    db.init_schema()
    return db


def test_nombre_desde_archivo_quita_extension():
    assert nombre_desde_archivo("Licitacion Calle 13.xlsx") == "Licitacion Calle 13"


def test_nombre_desde_archivo_csv_y_espacios():
    assert nombre_desde_archivo("  Obra Lote SL5.csv  ") == "Obra Lote SL5"


def test_nombre_desde_archivo_sin_extension():
    assert nombre_desde_archivo("presupuesto") == "presupuesto"


def test_nombre_desde_archivo_puntos_intermedios():
    assert nombre_desde_archivo("v1.2.final.xlsx") == "v1.2.final"


def test_nombre_desde_archivo_vacio():
    assert nombre_desde_archivo("") == ""


def test_sqlite_persiste_nombre_y_set_nombre(tmp_path):
    db = _corridas_db(tmp_path)
    cid = db.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-07-23T10:00:00", archivo="lic.xlsx",
        turno_def="DIURNO", use_ai=False, estado="en_revision", nombre="Obra Norte"))
    assert db.get_corrida(cid).nombre == "Obra Norte"
    db.set_nombre(cid, "Obra Sur")
    assert db.get_corrida(cid).nombre == "Obra Sur"


def test_sqlite_nombre_vacio_cae_a_archivo(tmp_path):
    db = _corridas_db(tmp_path)
    cid = db.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-07-23T10:00:00", archivo="lic.xlsx",
        turno_def="DIURNO", use_ai=False, estado="en_revision"))  # nombre=""
    assert db.get_corrida(cid).nombre == "lic.xlsx"
