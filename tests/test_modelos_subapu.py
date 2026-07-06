from apu_tool.nucleo.models import (
    ApuComponent, CostedComponent, DePricedComponent, DePricedApu,
)
from apu_tool.dominio.privacy import depriced_apu_to_dict, assert_no_money


def test_apucomponent_default_es_insumo():
    c = ApuComponent("A", "DIURNO", "100", "CEMENTO", "KG", 3.0, 900)
    assert c.tipo == "insumo" and c.ref_shift == ""


def test_apucomponent_como_subapu():
    c = ApuComponent("A", "DIURNO", "3017", "SUB APU", "M3", 1.0, 0.0,
                     tipo="apu", ref_shift="DIURNO")
    assert c.tipo == "apu" and c.ref_shift == "DIURNO"


def test_costedcomponent_default_es_insumo():
    c = CostedComponent("100", "CEMENTO", "KG", 3.0, 900, "PRECIO IDU", 2700)
    assert c.tipo == "insumo" and c.ref_shift == ""


def test_depriced_incluye_tipo_y_sigue_sin_dinero():
    apu = DePricedApu("A", "MURO", "M2", "DIURNO", "", (
        DePricedComponent("3017", "SUB APU", "M3", 1.0, tipo="apu"),))
    d = depriced_apu_to_dict(apu)
    assert d["componentes"][0]["tipo"] == "apu"
    assert_no_money(d)  # no debe lanzar PrivacyViolation
