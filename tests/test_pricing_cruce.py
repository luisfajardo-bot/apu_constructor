import pytest
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo
from apu_tool.dominio.pricing import PricingEngine


@pytest.fixture()
def alm(tmp_path):
    a = Almacen(tmp_path / "p.db", tmp_path / "a.db")
    a.reset()
    # código 4513 repetido: ducto (barato) vs base granular (caro)
    a.precios.insert_insumos([
        Insumo("4513", "DUCTO TELEFONICO LIVIANO PVC TIPO EB D=3", "ML", "MAT", 16925, "PRECIO IDU"),
        Insumo("4513", "BASE GRANULAR CLASE C", "M3", "MAT", 190300, "PRECIO IDU"),
    ])
    a.apus.insert_apus([Apu("A1", "RED", "ML", "DIURNO")])
    a.apus.insert_components([
        ApuComponent("A1", "DIURNO", "4513", "DUCTO TELEFONICO LIVIANO PVC TIPO EB D=3", "ML", 1.0, 9999),
    ])
    return a


def test_elige_precio_por_nombre_no_por_codigo(alm):
    eng = PricingEngine(alm)
    costed, total = eng.cost_apu("A1", "DIURNO")
    assert total == pytest.approx(16925)        # ducto, NO base granular
    assert costed[0].calidad_cruce == "exacto"

def test_codigo_ambiguo_cae_al_historico_y_avisa(alm):
    # un componente cuyo nombre no casa con ninguno de los dos -> ambiguo -> histórico
    alm.apus.insert_components([
        ApuComponent("A1", "DIURNO", "4513", "TORNILLO HEXAGONAL 1 PULGADA", "UN", 2.0, 500),
    ])
    eng = PricingEngine(alm)
    costed, _ = eng.cost_apu("A1", "DIURNO")
    amb = [c for c in costed if c.insumo_nombre.startswith("TORNILLO")][0]
    assert amb.precio_unitario == 500 and amb.fuente_precio == "histórico"
    assert amb.calidad_cruce == "ambiguo"

def test_huerfano_avisa(alm):
    alm.apus.insert_components([
        ApuComponent("A1", "DIURNO", "0000", "INSUMO INEXISTENTE", "UN", 1.0, 700),
    ])
    eng = PricingEngine(alm)
    costed, _ = eng.cost_apu("A1", "DIURNO")
    h = [c for c in costed if c.insumo_codigo == "0000"][0]
    assert h.precio_unitario == 700 and h.calidad_cruce == "huerfano"
