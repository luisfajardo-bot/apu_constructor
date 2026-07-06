import pytest
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo
from apu_tool.dominio.pricing import PricingEngine


@pytest.fixture()
def alm(tmp_path):
    a = Almacen(tmp_path / "p.db", tmp_path / "a.db")
    a.reset()
    a.precios.insert_insumos([Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU")])
    # sub-APU B: 2 KG de cemento = 2000
    a.apus.insert_apus([Apu("B", "SUBAPU", "M3", "DIURNO")])
    a.apus.insert_components([ApuComponent("B", "DIURNO", "100", "CEMENTO", "KG", 2.0, 0.0)])
    # APU A usa 3 de B (sub-APU) => 6000
    a.apus.insert_apus([Apu("A", "COMP", "M2", "DIURNO")])
    a.apus.insert_components([ApuComponent(
        "A", "DIURNO", "B", "SUBAPU", "M3", 3.0, 999, tipo="apu", ref_shift="DIURNO")])
    return a


def test_subapu_se_costea_en_vivo(alm):
    eng = PricingEngine(alm)
    costed, total = eng.cost_apu("A", "DIURNO")
    assert total == pytest.approx(6000)
    assert costed[0].tipo == "apu"
    assert costed[0].fuente_precio == "APU"
    assert costed[0].calidad_cruce == "apu"
    assert costed[0].costo == pytest.approx(6000)


def test_subapu_refleja_cambio_de_precio(alm):
    alm.precios.set_precio("100", 2000, nombre="CEMENTO")
    eng = PricingEngine(alm)
    _, total = eng.cost_apu("A", "DIURNO")
    assert total == pytest.approx(12000)   # 3 * (2 * 2000)


def test_anidamiento_dos_niveles(alm):
    alm.apus.insert_apus([Apu("C", "NIVEL2", "M2", "DIURNO")])
    alm.apus.insert_components([ApuComponent(
        "C", "DIURNO", "A", "COMP", "M2", 1.0, 0.0, tipo="apu", ref_shift="DIURNO")])
    eng = PricingEngine(alm)
    costed, total = eng.cost_apu("C", "DIURNO")
    assert total == pytest.approx(6000)
    assert costed[0].tipo == "apu"
    assert costed[0].fuente_precio == "APU"
    assert costed[0].calidad_cruce == "apu"
    assert costed[0].ref_shift == "DIURNO"


def test_ciclo_self_ref_no_cuelga(alm):
    alm.apus.insert_apus([Apu("Z", "Z", "M2", "DIURNO")])
    alm.apus.insert_components([ApuComponent(
        "Z", "DIURNO", "Z", "Z", "M2", 1.0, 500, tipo="apu", ref_shift="DIURNO")])
    eng = PricingEngine(alm)
    costed, total = eng.cost_apu("Z", "DIURNO")
    assert total == pytest.approx(500)          # el back-edge cae a histórico
    assert costed[0].calidad_cruce == "ciclo"


def test_componente_insumo_sin_cambio(alm):
    alm.apus.insert_apus([Apu("M", "MAT", "M2", "DIURNO")])
    alm.apus.insert_components([ApuComponent("M", "DIURNO", "100", "CEMENTO", "KG", 5.0, 0.0)])
    eng = PricingEngine(alm)
    costed, total = eng.cost_apu("M", "DIURNO")
    assert total == pytest.approx(5000)         # 5 * 1000
    assert costed[0].tipo == "insumo" and costed[0].calidad_cruce == "exacto"
