from apu_tool.datos.correcciones import CORRECCIONES_CODIGO, aplicar
from apu_tool.nucleo.models import ApuComponent

def test_remapea_4613_a_3017():
    assert CORRECCIONES_CODIGO["4613"] == "3017"
    comps = [ApuComponent("A", "DIURNO", "4613", "TRANSPORTE", "M3", 6.0, 0),
             ApuComponent("A", "DIURNO", "100", "CEMENTO", "KG", 1.0, 0)]
    out = aplicar(comps)
    assert out[0].insumo_codigo == "3017"   # remapeado
    assert out[1].insumo_codigo == "100"    # intacto
