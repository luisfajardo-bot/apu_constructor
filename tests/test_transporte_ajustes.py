"""Ajustes puntuales del proyecto: las 4 acciones y su precedencia sobre la regla."""
from apu_tool.dominio import transporte
from apu_tool.nucleo.models import (
    AjusteProyecto, ApuComponent, ClaseTransporte, ParametrosProyecto)


def _comp(cod, nombre, unidad="M3", rend=1.0, hist=500.0):
    return ApuComponent(apu_codigo="4390", shift="DIURNO", insumo_codigo=cod,
                        insumo_nombre=nombre, unidad=unidad, rendimiento=rend,
                        precio_unitario_hist=hist)


BASE = [_comp("6722", "SUBBASE GRANULAR B-400"), _comp("7231", "DERECHOS DE BOTADERO")]


def _aj(accion, **kw):
    return AjusteProyecto(apu_codigo="4390", shift="DIURNO", accion=accion, **kw)


def test_quitar():
    out = transporte.aplicar(BASE, "4390", "DIURNO", ajustes=[
        _aj("quitar", insumo_codigo="6722", insumo_nombre="SUBBASE GRANULAR B-400")])
    assert [c.insumo_codigo for c in out] == ["7231"]


def test_rendimiento():
    out = transporte.aplicar(BASE, "4390", "DIURNO", ajustes=[
        _aj("rendimiento", insumo_codigo="6722",
            insumo_nombre="SUBBASE GRANULAR B-400", rendimiento=1.25)])
    assert out[0].rendimiento == 1.25 and out[1].rendimiento == 1.0


def test_agregar():
    out = transporte.aplicar(BASE, "4390", "DIURNO", ajustes=[
        _aj("agregar", insumo_codigo="9001", insumo_nombre="GEOTEXTIL NT 2000",
            unidad="M2", rendimiento=1.1)])
    assert len(out) == 3
    nuevo = out[-1]
    assert (nuevo.insumo_codigo, nuevo.rendimiento, nuevo.unidad) == ("9001", 1.1, "M2")
    assert nuevo.precio_unitario_hist == 0.0     # sin histórico ajeno


def test_agregar_es_idempotente():
    aj = _aj("agregar", insumo_codigo="6722", insumo_nombre="SUBBASE GRANULAR B-400",
             unidad="M3", rendimiento=2.0)
    out = transporte.aplicar(BASE, "4390", "DIURNO", ajustes=[aj])
    assert len(out) == 2 and out[0].rendimiento == 2.0


def test_reemplazar_borra_el_historico_del_viejo():
    out = transporte.aplicar(BASE, "4390", "DIURNO", ajustes=[
        _aj("reemplazar", insumo_codigo="6722", insumo_nombre="SUBBASE GRANULAR B-400",
            insumo_nuevo_codigo="7004", insumo_nuevo_nombre="BASE GRANULAR B-600")])
    assert out[0].insumo_codigo == "7004"
    assert out[0].insumo_nombre == "BASE GRANULAR B-600"
    assert out[0].precio_unitario_hist == 0.0


def test_ajuste_de_otro_apu_no_aplica():
    aj = AjusteProyecto(apu_codigo="9999", shift="DIURNO", accion="quitar",
                        insumo_codigo="6722", insumo_nombre="SUBBASE GRANULAR B-400")
    assert transporte.aplicar(BASE, "4390", "DIURNO", ajustes=[aj]) == BASE


def test_el_ajuste_gana_sobre_la_regla():
    comps = [ApuComponent(apu_codigo="4390", shift="DIURNO", insumo_codigo="7462",
                          insumo_nombre="TRANSPORTE DE PETREOS", unidad="M3-KM",
                          rendimiento=26.25, precio_unitario_hist=900.0)]
    cls = {("4390", "DIURNO", "7462"): ClaseTransporte(
        apu_codigo="4390", shift="DIURNO", insumo_codigo="7462",
        insumo_nombre="TRANSPORTE DE PETREOS", categoria="granulares",
        volumen=1.05, km_base=25.0)}
    out = transporte.aplicar(
        comps, "4390", "DIURNO", ParametrosProyecto(km_granulares=32), cls,
        [_aj("rendimiento", insumo_codigo="7462",
             insumo_nombre="TRANSPORTE DE PETREOS", rendimiento=40.0)])
    assert out[0].rendimiento == 40.0     # la regla habría puesto 33.6


def test_quitar_lo_que_la_regla_conservo():
    comps = [_comp("INT3", "PEAJE", unidad="GLB")]
    out = transporte.aplicar(
        comps, "4390", "DIURNO", ParametrosProyecto(peaje_aplica=True, peaje_valor=100),
        {}, [_aj("quitar", insumo_codigo="INT3", insumo_nombre="PEAJE")])
    assert out == []


def test_no_muta_la_lista_de_entrada():
    entrada = list(BASE)
    transporte.aplicar(entrada, "4390", "DIURNO", ajustes=[
        _aj("quitar", insumo_codigo="6722", insumo_nombre="SUBBASE GRANULAR B-400")])
    assert entrada == BASE
