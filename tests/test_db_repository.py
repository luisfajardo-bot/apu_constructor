"""Pruebas de precios vigentes, clasificación, meta y búsqueda usando Almacen."""
import pytest

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo
from apu_tool.dominio.pricing import PricingEngine


@pytest.fixture()
def alm(tmp_path):
    a = Almacen(tmp_path / "precios.db", tmp_path / "apus.db")
    a.reset()
    a.precios.insert_insumos([
        Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU"),
        Insumo("200", "ACERO", "KG", "MAT", 5000, "COSTO INTERNO"),
    ])
    a.apus.insert_apus([Apu("A1", "MURO", "M2", "DIURNO")])
    a.apus.insert_components([ApuComponent("A1", "DIURNO", "100", "CEMENTO", "KG", 3.0, 900)])
    return a


def test_price_classification(alm):
    assert config.classify_price_source("PRECIO IDU") == "publico"
    assert config.classify_price_source("COMPRAS 2026") == "interno"
    assert alm.precios.get_candidatos("100")[0].es_confidencial is False
    assert alm.precios.get_candidatos("200")[0].es_confidencial is True


def test_set_precio_changes_current_and_keeps_history(alm):
    alm.precios.set_precio("100", 1500, fuente="COMPRAS 2026")
    ins = alm.precios.get_candidatos("100")[0]
    assert ins.precio == 1500
    assert ins.fuente_precio == "COMPRAS 2026"
    hist = alm.precios.price_history("100")
    assert len(hist) == 2
    assert sum(h["vigente"] for h in hist) == 1   # exactamente uno vigente


def test_apu_cost_uses_current_price(alm):
    eng = PricingEngine(alm)
    _, c0 = eng.cost_apu("A1", "DIURNO")
    assert c0 == pytest.approx(3000)            # 3 * 1000
    alm.precios.set_precio("100", 2000)
    eng2 = PricingEngine(alm)                   # nueva instancia (sin cache previa)
    _, c1 = eng2.cost_apu("A1", "DIURNO")
    assert c1 == pytest.approx(6000)            # 3 * 2000


def test_meta_roundtrip(alm):
    alm.precios.set_meta("fuente", "archivo.xlsx")
    assert alm.precios.get_meta()["fuente"] == "archivo.xlsx"


def test_search(alm):
    assert any(i.codigo == "100" for i in alm.precios.search_insumos("CEMENTO"))
    assert any(a.codigo == "A1" for a in alm.apus.search_apus("MURO"))
