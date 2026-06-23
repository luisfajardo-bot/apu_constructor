"""Pruebas de ingesta y motor de precios usando Almacen con bases temporales."""
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo
from apu_tool.dominio.pricing import PricingEngine


@pytest.fixture()
def alm(tmp_path):
    a = Almacen(tmp_path / "precios.db", tmp_path / "apus.db")
    a.reset()
    a.precios.insert_insumos([
        Insumo("4279", "CUADRILLA", "HR", "MO", 40000, "PRECIO IDU"),
        Insumo("6092", "HERRAMIENTA MENOR", "GLB", "EQ", 2000, "PRECIO IDU"),
        Insumo("9999", "INSUMO INTERNO", "UN", "X", 500000, "COSTO INTERNO"),
    ])
    a.apus.insert_apus([Apu("3010", "DEMOLICION", "M3", "DIURNO")])
    a.apus.insert_components([
        ApuComponent("3010", "DIURNO", "4279", "CUADRILLA", "HR", 0.5, 37000),
        ApuComponent("3010", "DIURNO", "6092", "HERRAMIENTA MENOR", "GLB", 1.0, 2000),
    ])
    return a


def test_counts(alm):
    c = alm.counts()
    assert c["insumos"] == 3 and c["apus"] == 1 and c["apu_componentes"] == 2


def test_pricing_uses_catalog_price(alm):
    eng = PricingEngine(alm)
    costed, total = eng.cost_apu("3010", "DIURNO")
    # 0.5*40000 + 1.0*2000 = 22000
    assert total == pytest.approx(22000)
    assert costed[0].fuente_precio == "PRECIO IDU"


def test_pricing_falls_back_to_historical(alm):
    eng = PricingEngine(alm)
    # componente con insumo inexistente -> usa precio histórico embebido
    alm.apus.insert_components([ApuComponent("3010", "DIURNO", "0000", "X", "UN", 2.0, 1000)])
    costed, total = eng.cost_apu("3010", "DIURNO")
    fb = [c for c in costed if c.insumo_codigo == "0000"][0]
    assert fb.precio_unitario == 1000 and fb.fuente_precio == "histórico"


def test_insumo_confidencial_flag(alm):
    assert alm.precios.get_insumo("9999").es_confidencial is True
    assert alm.precios.get_insumo("4279").es_confidencial is False


def test_depriced_apu_has_no_price_fields(alm):
    dp = alm.apus.get_depriced_apu("3010", "DIURNO")
    # las vistas depriced no tienen atributo de precio
    assert not any(hasattr(c, "precio") or hasattr(c, "precio_unitario_hist")
                   for c in dp.componentes)
