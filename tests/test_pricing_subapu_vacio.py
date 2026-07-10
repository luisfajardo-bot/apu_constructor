# tests/test_pricing_subapu_vacio.py
from apu_tool.dominio.pricing import PricingEngine
from apu_tool.nucleo.models import ApuComponent


class _ApusFake:
    def __init__(self, comps_por_clave):
        self._m = comps_por_clave
    def get_components(self, codigo, shift):
        return self._m.get((codigo, shift), [])


class _PreciosFake:
    def get_candidatos(self, codigo):
        return []


class _AlmFake:
    def __init__(self, comps_por_clave):
        self.apus = _ApusFake(comps_por_clave)
        self.precios = _PreciosFake()


def _sub(hist):
    return ApuComponent(apu_codigo="PADRE", shift="DIURNO", insumo_codigo="SUB",
                        insumo_nombre="Sub", unidad="un", rendimiento=2.0,
                        precio_unitario_hist=hist, tipo="apu", ref_shift="DIURNO")


def test_subapu_vacio_cae_a_historico_y_marca_apu_vacio():
    eng = PricingEngine(_AlmFake({}))          # ("SUB","DIURNO") no existe -> vacío
    costed = eng.cost_component(_sub(hist=50.0))
    assert costed.calidad_cruce == "apu_vacio"
    assert costed.fuente_precio == "histórico"
    assert costed.precio_unitario == 50.0
    assert costed.costo == 100.0               # rendimiento 2 * 50


def test_subapu_vacio_sin_historico_queda_en_cero():
    eng = PricingEngine(_AlmFake({}))
    costed = eng.cost_component(_sub(hist=0.0))
    assert costed.calidad_cruce == "apu_vacio"
    assert costed.costo == 0.0                 # lo atrapará alertas_costeo como "en $0"
