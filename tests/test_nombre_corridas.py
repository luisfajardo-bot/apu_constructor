from apu_tool.servicio.corridas import nombre_desde_archivo
from apu_tool.nucleo.models import CorridaMeta
from apu_tool.datos.corridas_db import CorridasDB
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo, LicitacionItem
import apu_tool.servicio.corridas as svc
import pytest


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


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([Insumo("100", "CEMENTO", "KG", "MAT", 1000.0, "PRECIO IDU")])
    alm.apus.crear_apu(Apu("A1", "MURO", "M2", "DIURNO", "ESTR"),
                       [ApuComponent("A1", "DIURNO", "100", "CEMENTO", "KG", 2.0, 0.0)])
    sc = alm.carpetas.crear("Obra")
    return alm, sc


def _items():
    return [LicitacionItem(item="1", descripcion="muro", unidad="M2", cantidad=1.0,
                           precio_contractual=10000.0, shift="DIURNO")]


def test_construir_corrida_usa_nombre_explicito(tmp_path):
    alm, sc = _alm(tmp_path)
    cid = svc.construir_corrida(alm, "lic.xlsx", _items(), "DIURNO", False,
                                carpeta_id=sc, nombre="Presupuesto A")
    assert alm.corridas.get_corrida(cid).nombre == "Presupuesto A"


def test_construir_corrida_default_sin_extension(tmp_path):
    alm, sc = _alm(tmp_path)
    cid = svc.construir_corrida(alm, "Obra Lote SL5.xlsx", _items(), "DIURNO", False,
                                carpeta_id=sc)  # sin nombre
    assert alm.corridas.get_corrida(cid).nombre == "Obra Lote SL5"


def test_renombrar_corrida_ok(tmp_path):
    alm, sc = _alm(tmp_path)
    cid = svc.construir_corrida(alm, "lic.xlsx", _items(), "DIURNO", False, carpeta_id=sc)
    v = svc.renombrar_corrida(alm, cid, "  Nuevo nombre  ")
    assert v is not None and v["nombre"] == "Nuevo nombre"
    assert alm.corridas.get_corrida(cid).nombre == "Nuevo nombre"


def test_renombrar_corrida_inexistente_devuelve_none(tmp_path):
    alm, _ = _alm(tmp_path)
    assert svc.renombrar_corrida(alm, 999, "X") is None


def test_renombrar_corrida_vacio_lanza(tmp_path):
    alm, sc = _alm(tmp_path)
    cid = svc.construir_corrida(alm, "lic.xlsx", _items(), "DIURNO", False, carpeta_id=sc)
    with pytest.raises(ValueError):
        svc.renombrar_corrida(alm, cid, "   ")


def test_vista_y_listar_incluyen_nombre(tmp_path):
    alm, sc = _alm(tmp_path)
    cid = svc.construir_corrida(alm, "lic.xlsx", _items(), "DIURNO", False,
                                carpeta_id=sc, nombre="Mi corrida")
    assert svc.vista_corrida(alm, cid)["nombre"] == "Mi corrida"
    fila = next(f for f in svc.listar_corridas(alm) if f["id"] == cid)
    assert fila["nombre"] == "Mi corrida"


def test_construir_corrida_cap_120(tmp_path):
    alm, sc = _alm(tmp_path)
    nombre_largo = "A" * 130
    cid = svc.construir_corrida(alm, "lic.xlsx", _items(), "DIURNO", False,
                                carpeta_id=sc, nombre=nombre_largo)
    assert len(alm.corridas.get_corrida(cid).nombre) == 120


def test_renombrar_corrida_cap_120(tmp_path):
    alm, sc = _alm(tmp_path)
    cid = svc.construir_corrida(alm, "lic.xlsx", _items(), "DIURNO", False, carpeta_id=sc)
    nombre_largo = "B" * 130
    v = svc.renombrar_corrida(alm, cid, nombre_largo)
    assert len(v["nombre"]) == 120
