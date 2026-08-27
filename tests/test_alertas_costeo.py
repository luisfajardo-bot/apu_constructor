# tests/test_alertas_costeo.py
from apu_tool.dominio.alertas import alertas_costeo
from apu_tool.nucleo.models import AssembledApu, CostedComponent, LicitacionItem, MatchStatus


def _item():
    return LicitacionItem(item="1", descripcion="X", unidad="m3", cantidad=1.0,
                          precio_contractual=100.0, shift="DIURNO")


def _ensamble(comps, costo_unitario):
    return AssembledApu(item=_item(), apu_codigo="A", apu_nombre="A", unidad="m3",
                        shift="DIURNO", componentes=comps, costo_unitario=costo_unitario,
                        status=MatchStatus.AUTO, confianza=1.0)


def _comp(costo=10.0, precio=10.0, calidad="exacto"):
    return CostedComponent(insumo_codigo="7", insumo_nombre="Cemento", unidad="kg",
                           rendimiento=1.0, precio_unitario=precio, fuente_precio="X",
                           costo=costo, calidad_cruce=calidad)


def test_item_limpio_sin_alertas():
    assert alertas_costeo(_ensamble([_comp()], 10.0)) == []


def test_componente_en_cero_es_alerta():
    motivos = alertas_costeo(_ensamble([_comp(costo=0.0, precio=0.0)], 0.0))
    assert len(motivos) == 1 and "en $0" in motivos[0]


def test_cruce_ambiguo_con_precio_positivo():
    motivos = alertas_costeo(_ensamble([_comp(calidad="ambiguo")], 10.0))
    assert motivos == ["7 Cemento: cruce ambiguo"]


def test_cero_tiene_prioridad_sobre_cruce():
    # $0 + ambiguo -> solo reporta "en $0", no dobla el motivo
    motivos = alertas_costeo(_ensamble([_comp(costo=0.0, precio=0.0, calidad="ambiguo")], 0.0))
    assert len(motivos) == 1 and "en $0" in motivos[0]


def test_subapu_vacio_y_ciclo():
    assert alertas_costeo(_ensamble([_comp(calidad="apu_vacio")], 10.0)) == \
        ["7 Cemento: sub-APU sin composición"]
    assert alertas_costeo(_ensamble([_comp(calidad="ciclo")], 10.0)) == \
        ["7 Cemento: ciclo de sub-APUs"]


def test_item_sin_componentes_en_cero():
    assert alertas_costeo(_ensamble([], 0.0)) == ["APU en $0 (sin composición o sin costo)"]


def test_cruce_huerfano_con_precio_positivo():
    motivos = alertas_costeo(_ensamble([_comp(calidad="huerfano")], 10.0))
    assert motivos == ["7 Cemento: sin insumo en catálogo"]


def test_alerta_de_distancia_no_aplicada():
    item = LicitacionItem(item="1", descripcion="RELLENO", unidad="M3", cantidad=1,
                          precio_contractual=1000.0, shift="DIURNO")
    comp = CostedComponent(insumo_codigo="7462", insumo_nombre="TRANSPORTE DE PETREOS",
                           unidad="M3-KM", rendimiento=26.25, precio_unitario=1000.0,
                           fuente_precio="COSTO INTERNO", costo=26250)
    ens = AssembledApu(item=item, apu_codigo="4390", apu_nombre="RELLENO", unidad="M3",
                       shift="DIURNO", componentes=[comp], costo_unitario=26250,
                       status=MatchStatus.CONFIRMED, confianza=1.0)
    assert alertas_costeo(ens) == []                     # sin proyecto: sin alerta
    motivos = alertas_costeo(ens, sin_distancia=("7462",))
    assert motivos == ["7462 TRANSPORTE DE PETREOS: distancia del proyecto no aplicada"]


def test_alerta_de_pendiente_que_vive_en_un_subapu():
    """El pendiente del sub-APU no está entre los componentes del ítem, y aún así
    tiene que alertar: es el caso del botadero."""
    item = LicitacionItem(item="1", descripcion="RELLENO", unidad="M3", cantidad=1,
                          precio_contractual=1000.0, shift="DIURNO")
    sub = CostedComponent(insumo_codigo="3017", insumo_nombre="TTE ESCOMBROS",
                          unidad="M3", rendimiento=1.0, precio_unitario=26500.0,
                          fuente_precio="APU", costo=26500, calidad_cruce="apu",
                          tipo="apu", ref_shift="DIURNO")
    ens = AssembledApu(item=item, apu_codigo="4390", apu_nombre="RELLENO", unidad="M3",
                       shift="DIURNO", componentes=[sub], costo_unitario=26500,
                       status=MatchStatus.CONFIRMED, confianza=1.0)
    motivos = alertas_costeo(ens, en_subapus=(("3017", "7462"),))
    assert motivos == ["7462: distancia del proyecto no aplicada (en el sub-APU 3017)"]


def test_el_codigo_repetido_no_confunde_las_dos_lineas():
    """Arriba clasificado, abajo no: la alerta tiene que hablar del sub-APU y no
    manchar la linea de arriba, que esta bien."""
    from apu_tool.dominio.alertas import alertas_costeo
    from apu_tool.nucleo.models import (
        AssembledApu, CostedComponent, LicitacionItem, MatchStatus)
    item = LicitacionItem(item="1", descripcion="RELLENO", unidad="M3", cantidad=1,
                          precio_contractual=1000.0, shift="DIURNO")
    arriba = CostedComponent(insumo_codigo="7462", insumo_nombre="TRANSPORTE DE PETREOS",
                             unidad="M3-KM", rendimiento=33.6, precio_unitario=1000.0,
                             fuente_precio="COSTO INTERNO", costo=33600)
    sub = CostedComponent(insumo_codigo="3017", insumo_nombre="TTE ESCOMBROS",
                          unidad="M3", rendimiento=1.0, precio_unitario=26500.0,
                          fuente_precio="APU", costo=26500, calidad_cruce="apu",
                          tipo="apu", ref_shift="DIURNO")
    ens = AssembledApu(item=item, apu_codigo="4390", apu_nombre="RELLENO", unidad="M3",
                       shift="DIURNO", componentes=[arriba, sub], costo_unitario=60100,
                       status=MatchStatus.CONFIRMED, confianza=1.0)
    motivos = alertas_costeo(ens, sin_distancia=(), en_subapus=(("3017", "7462"),))
    assert motivos == ["7462: distancia del proyecto no aplicada (en el sub-APU 3017)"]
