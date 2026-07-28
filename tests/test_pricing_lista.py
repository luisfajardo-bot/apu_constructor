"""Costeo contra una lista de precios distinta de Principal.

Decisión de negocio: en una lista NP NO se cae al precio histórico embebido — eso
sería cobrar con la tarifa contractual sin que nadie se entere. Falta el precio ->
$0 con alerta explícita.
"""
import pytest

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.dominio.alertas import alertas_costeo
from apu_tool.dominio.pricing import PricingEngine
from apu_tool.nucleo.models import (
    Apu, ApuComponent, AssembledApu, Insumo, LicitacionItem, MatchStatus,
)


@pytest.fixture()
def alm(tmp_path):
    a = Almacen(tmp_path / "p.db", tmp_path / "a.db", tmp_path / "c.db")
    a.reset()
    a.precios.insert_insumos([
        Insumo("6140", "ACERO 60000 PSI", "KG", "MATERIAL", 3500.0, "PRECIO IDU"),
        Insumo("9", "CEMENTO GRIS", "KG", "MATERIAL", 900.0, "COSTO INTERNO"),
    ])
    a.apus.insert_apus([Apu("NP-3002", "DEMOLICION MURO", "M3", "DIURNO")])
    a.apus.insert_components([
        ApuComponent("NP-3002", "DIURNO", "6140", "ACERO 60000 PSI", "KG", 2.0, 3000.0),
        ApuComponent("NP-3002", "DIURNO", "9", "CEMENTO GRIS", "KG", 1.0, 800.0),
    ])
    return a


@pytest.fixture()
def np(alm):
    lid = alm.precios.crear_lista("NP Calle 13")
    iid = alm.precios.get_candidatos("6140")[0].id
    alm.precios.set_precio_por_id(iid, 4200.0, "ACTA NP", lista_id=lid)
    return lid


def _ensamblado(costed, total) -> AssembledApu:
    item = LicitacionItem("1", "DEMOLICION", "M3", 1.0, 0.0, "DIURNO")
    return AssembledApu(item=item, apu_codigo="NP-3002", apu_nombre="DEMOLICION MURO",
                        unidad="M3", shift="DIURNO", componentes=costed,
                        costo_unitario=total, status=MatchStatus.AUTO, confianza=1.0)


def test_costea_con_el_precio_de_la_lista(alm, np):
    costed, _ = PricingEngine(alm, lista_id=np).cost_apu("NP-3002", "DIURNO")
    acero = [c for c in costed if c.insumo_codigo == "6140"][0]
    assert acero.precio_unitario == 4200.0 and acero.fuente_precio == "ACTA NP"
    assert acero.calidad_cruce == "exacto"


def test_sin_precio_en_la_lista_no_cae_al_historico(alm, np):
    costed, _ = PricingEngine(alm, lista_id=np).cost_apu("NP-3002", "DIURNO")
    cem = [c for c in costed if c.insumo_codigo == "9"][0]
    assert cem.precio_unitario == 0.0                 # NO 800 (histórico) ni 900 (Principal)
    assert cem.fuente_precio == "sin precio en lista"
    assert cem.calidad_cruce == "sin_precio_lista"
    assert cem.costo == 0


def test_en_principal_si_cae_al_historico(alm):
    # Mismo APU, pero con un insumo huérfano: en Principal el respaldo histórico sigue vivo.
    alm.apus.insert_components([
        ApuComponent("NP-3002", "DIURNO", "0000", "INSUMO INEXISTENTE", "UN", 1.0, 700.0)])
    costed, _ = PricingEngine(alm).cost_apu("NP-3002", "DIURNO")
    h = [c for c in costed if c.insumo_codigo == "0000"][0]
    assert h.precio_unitario == 700.0 and h.fuente_precio == "histórico"
    assert h.calidad_cruce == "huerfano"


def test_huerfano_en_lista_np_tampoco_usa_historico(alm, np):
    alm.apus.insert_components([
        ApuComponent("NP-3002", "DIURNO", "0000", "INSUMO INEXISTENTE", "UN", 1.0, 700.0)])
    costed, _ = PricingEngine(alm, lista_id=np).cost_apu("NP-3002", "DIURNO")
    h = [c for c in costed if c.insumo_codigo == "0000"][0]
    assert h.precio_unitario == 0.0 and h.calidad_cruce == "sin_precio_lista"


def test_none_y_principal_dan_exactamente_lo_mismo(alm):
    a, _ = PricingEngine(alm).cost_apu("NP-3002", "DIURNO")
    b, _ = PricingEngine(alm, lista_id=config.LISTA_PRINCIPAL_ID).cost_apu("NP-3002", "DIURNO")
    assert [(c.precio_unitario, c.fuente_precio, c.costo, c.calidad_cruce) for c in a] == \
           [(c.precio_unitario, c.fuente_precio, c.costo, c.calidad_cruce) for c in b]


def test_subapu_vacio_en_lista_np_no_usa_historico(alm, np):
    alm.apus.insert_apus([Apu("SUB", "SUB VACIO", "M3", "DIURNO")])
    alm.apus.insert_components([
        ApuComponent("NP-3002", "DIURNO", "SUB", "SUB VACIO", "M3", 1.0, 5000.0,
                     tipo="apu", ref_shift="DIURNO")])
    costed, _ = PricingEngine(alm, lista_id=np).cost_apu("NP-3002", "DIURNO")
    sub = [c for c in costed if c.insumo_codigo == "SUB"][0]
    assert sub.precio_unitario == 0.0 and sub.fuente_precio == "sin precio en lista"
    assert sub.calidad_cruce == "apu_vacio"           # el problema real es estructural


def test_dos_motores_con_listas_distintas_no_se_contaminan(alm, np):
    principal = PricingEngine(alm)
    lista_np = PricingEngine(alm, lista_id=np)
    _, t_np = lista_np.cost_apu("NP-3002", "DIURNO")
    _, t_pr = principal.cost_apu("NP-3002", "DIURNO")
    assert t_np == 8400                               # 2 * 4200 + 0
    assert t_pr == 7900                               # 2 * 3500 + 1 * 900


def test_precargar_respeta_la_lista(alm, np):
    eng = PricingEngine(alm, lista_id=np)
    eng.precargar([("NP-3002", "DIURNO")])
    costed, _ = eng.cost_apu("NP-3002", "DIURNO")
    assert [c for c in costed if c.insumo_codigo == "6140"][0].precio_unitario == 4200.0


def test_alerta_dice_sin_precio_en_la_lista(alm, np):
    costed, total = PricingEngine(alm, lista_id=np).cost_apu("NP-3002", "DIURNO")
    motivos = alertas_costeo(_ensamblado(costed, total))
    assert any("sin precio en la lista" in m for m in motivos)
    assert not any("en $0" in m for m in motivos)     # mensaje específico, no el genérico


def test_alerta_en_cero_genuino_sigue_diciendo_en_0(alm):
    # $0 genuino en Principal: el insumo existe con precio 0 Y el histórico embebido
    # también es 0, así que no hay respaldo que lo tape. La regla dura debe delatarlo
    # con "en $0" — el mensaje de lista NO aplica aquí.
    alm.precios.insert_insumos([
        Insumo("777", "MATERIAL DEL CLIENTE", "UN", "MATERIAL", 0.0, "PRECIO IDU")])
    alm.apus.insert_components([
        ApuComponent("NP-3002", "DIURNO", "777", "MATERIAL DEL CLIENTE", "UN", 1.0, 0.0)])
    costed, total = PricingEngine(alm).cost_apu("NP-3002", "DIURNO")
    motivos = alertas_costeo(_ensamblado(costed, total))
    assert any("777" in m and "en $0" in m for m in motivos)
    assert not any("sin precio en la lista" in m for m in motivos)
