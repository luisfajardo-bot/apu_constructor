# tests/test_servicio_rebuscar.py
"""Volver a buscar APU: el re-match de una corrida activa contra la biblioteca de hoy."""
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo, LicitacionItem
from apu_tool.servicio import corridas


def _almacen(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo("100", "Concreto 3000 PSI", "M3", "CONCRETOS", 350000.0, "COSTO INTERNO")])
    alm.apus.insert_apus([Apu("A1", "Concreto clase D", "M3", "DIURNO", "ESTRUCTURAS")])
    alm.apus.insert_components([
        ApuComponent("A1", "DIURNO", "100", "Concreto 3000 PSI", "M3", 1.0, 350000.0)])
    return alm


def _agregar_apu(alm, codigo, nombre, rendimiento=2.0, shift="DIURNO"):
    alm.apus.insert_apus([Apu(codigo, nombre, "M3", shift, "ESTRUCTURAS")])
    alm.apus.insert_components([
        ApuComponent(codigo, shift, "100", "Concreto 3000 PSI", "M3",
                     rendimiento, 350000.0)])


def _item(desc, n="1"):
    return LicitacionItem(item=n, descripcion=desc, unidad="M3", cantidad=10.0,
                          precio_contractual=900000.0, shift="DIURNO")


def test_rebuscar_encuentra_un_apu_creado_despues_del_armado(tmp_path):
    alm = _almacen(tmp_path)
    cid = corridas.construir_corrida(
        alm, "lic.xlsx", [_item("Pantalla acustica modular en aluminio")],
        "DIURNO", use_ai=False)
    assert corridas.vista_corrida(alm, cid)["items"][0]["apu_codigo"] is None

    _agregar_apu(alm, "A9", "Pantalla acustica modular en aluminio")

    previa = corridas.rebuscar(alm, cid)
    assert previa["escaneadas"] == 1
    assert len(previa["propuestas"]) == 1
    p = previa["propuestas"][0]
    assert p["seq"] == 0
    assert p["apu_actual"] is None
    assert p["apu_propuesto"]["codigo"] == "A9"
    assert p["sin_apu"] is True                      # el frontend la marca por defecto
    assert p["status"] == "auto"
    assert p["costo_unitario"] == 2.0 * 350000.0     # ya viene costeada
    assert p["margen_unitario"] == 900000.0 - 700000.0


def test_rebuscar_no_escribe_nada(tmp_path):
    alm = _almacen(tmp_path)
    cid = corridas.construir_corrida(
        alm, "lic.xlsx", [_item("Pantalla acustica modular en aluminio")],
        "DIURNO", use_ai=False)
    _agregar_apu(alm, "A9", "Pantalla acustica modular en aluminio")
    # Los candidatos de ANTES, no una lista vacía: el armado nunca deja la lista
    # vacía — `_full_scan` guarda todo lo que puntúe > 0, y `SequenceMatcher` da > 0
    # para casi cualquier par de textos. La fila nace con un candidato basura de 0,09.
    # Lo que se prueba acá es que la previa no los TOCA: refrescarlos es del aplicar.
    antes = alm.corridas.get_items(cid)[0].candidatos
    corridas.rebuscar(alm, cid)
    fila = alm.corridas.get_items(cid)[0]
    assert fila.apu_codigo is None                   # la previa propone, no aplica
    assert fila.candidatos == antes
    assert "A9" not in [c["apu_codigo"] for c in fila.candidatos]


def test_rebuscar_no_toca_las_confirmadas(tmp_path):
    alm = _almacen(tmp_path)
    cid = corridas.construir_corrida(alm, "lic.xlsx", [_item("Concreto clase D")],
                                     "DIURNO", use_ai=False)
    corridas.confirmar_item(alm, cid, 0, apu_codigo="A1")
    _agregar_apu(alm, "A9", "Concreto clase D")      # gemelo con el mismo nombre
    previa = corridas.rebuscar(alm, cid)
    assert previa["escaneadas"] == 0
    assert previa["propuestas"] == []


def test_rebuscar_no_propone_lo_que_la_fila_ya_tiene(tmp_path):
    alm = _almacen(tmp_path)
    cid = corridas.construir_corrida(alm, "lic.xlsx", [_item("Concreto clase D")],
                                     "DIURNO", use_ai=False)
    previa = corridas.rebuscar(alm, cid)             # sin crear nada nuevo
    assert previa["escaneadas"] == 1
    assert previa["propuestas"] == []


def test_rebuscar_bloqueado_si_congelada(tmp_path):
    alm = _almacen(tmp_path)
    cid = corridas.construir_corrida(alm, "lic.xlsx", [_item("Concreto clase D")],
                                     "DIURNO", use_ai=False)
    corridas.congelar(alm, cid)
    with pytest.raises(corridas.CorridaCongelada):
        corridas.rebuscar(alm, cid)


def test_rebuscar_bloqueado_si_el_plan_esta_a_medias(tmp_path):
    alm = _almacen(tmp_path)
    cid = corridas.construir_corrida(alm, "lic.xlsx", [_item("Concreto clase D")],
                                     "DIURNO", use_ai=False)
    alm.corridas.set_estado(cid, "armado_detenido")
    with pytest.raises(ValueError, match="por armar"):
        corridas.rebuscar(alm, cid)


def test_rebuscar_corrida_inexistente(tmp_path):
    assert corridas.rebuscar(_almacen(tmp_path), 999) is None
