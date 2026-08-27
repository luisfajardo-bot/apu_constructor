"""Persistencia de la clasificación de transporte de la biblioteca."""
from apu_tool.datos.apus_db import ApusDB
from apu_tool.nucleo.models import Apu, ApuComponent, ClaseTransporte


def _db(tmp_path):
    db = ApusDB(tmp_path / "apus.db")
    db.init_schema()
    db.insert_apus([Apu(codigo="4200", nombre="MEZCLA MD20", unidad="M3",
                        shift="DIURNO", grupo="PAVIMENTOS")])
    db.insert_components([
        ApuComponent(apu_codigo="4200", shift="DIURNO", insumo_codigo="6878",
                     insumo_nombre="TRANSPORTE DE BASES ASFALTICAS", unidad="M3-KM",
                     rendimiento=26.25, precio_unitario_hist=900.0),
        ApuComponent(apu_codigo="4200", shift="DIURNO", insumo_codigo="7172",
                     insumo_nombre="MEZCLA ASFALTICA MD20", unidad="M3",
                     rendimiento=1.0, precio_unitario_hist=500000.0),
    ])
    return db


def test_clasificacion_vacia_al_inicio(tmp_path):
    assert _db(tmp_path).get_clasificacion_transporte() == []


def test_upsert_y_lectura(tmp_path):
    db = _db(tmp_path)
    fila = ClaseTransporte(apu_codigo="4200", shift="DIURNO", insumo_codigo="6878",
                           insumo_nombre="TRANSPORTE DE BASES ASFALTICAS",
                           categoria="mezclas", volumen=1.05, km_base=25.0)
    assert db.set_clasificacion_transporte([fila], actualizado_por="yo@test.co") == 1
    leidas = db.get_clasificacion_transporte()
    assert len(leidas) == 1
    assert (leidas[0].categoria, leidas[0].volumen, leidas[0].km_base) == ("mezclas", 1.05, 25.0)
    # Reescribir la misma clave actualiza, no duplica.
    db.set_clasificacion_transporte([ClaseTransporte(
        apu_codigo="4200", shift="DIURNO", insumo_codigo="6878",
        insumo_nombre="TRANSPORTE DE BASES ASFALTICAS", categoria="mezclas",
        volumen=1.30, km_base=20.0)])
    leidas = db.get_clasificacion_transporte()
    assert len(leidas) == 1 and leidas[0].volumen == 1.30


def test_candidatos_solo_las_filas_m3_km(tmp_path):
    db = _db(tmp_path)
    cands = db.componentes_transporte_candidatos()
    assert [c["insumo_codigo"] for c in cands] == ["6878"]
    c = cands[0]
    assert c["apu_codigo"] == "4200" and c["apu_nombre"] == "MEZCLA MD20"
    assert c["rendimiento"] == 26.25 and c["unidad"] == "M3-KM"
