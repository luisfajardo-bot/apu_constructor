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
    # "sin respaldo", no "sin precio en lista": un sub-APU sin composición no puede
    # tener tarifa en NINGUNA lista, así que culpar a "la lista" es falso en la
    # columna FUENTE del Excel (hallazgo 7 de la revisión sobre 5944478 — esta
    # aserción encodeaba exactamente el texto que el hallazgo marcó como engañoso).
    assert sub.precio_unitario == 0.0 and sub.fuente_precio == "sin respaldo"
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


# --- Hallazgo 1 (CRITICAL): insumo creado SOLO en una lista NP, costeado en
# Principal, no debe colar el histórico contractual sin alerta ---------------

def test_insumo_creado_solo_en_np_en_principal_cae_a_historico_pero_alerta(alm, np):
    """Reproduce el hallazgo: crear_insumo(insumo, lista_id=NP) deja el insumo SIN
    fila de precio en Principal (estado C, antes inalcanzable). Costeado en
    Principal, debe seguir usando el histórico (no dejar el total en 0) pero con
    calidad_cruce == sin_precio_catalogo, que SÍ genera alerta."""
    alm.precios.crear_insumo(
        Insumo("555", "TUBERIA PVC 4\"", "ML", "MATERIAL", 12000.0, "ACTA NP"),
        lista_id=np)
    alm.apus.insert_components([
        ApuComponent("NP-3002", "DIURNO", "555", "TUBERIA PVC 4\"", "ML", 1.0, 9500.0)])

    costed, _ = PricingEngine(alm).cost_apu("NP-3002", "DIURNO")
    tub = [c for c in costed if c.insumo_codigo == "555"][0]

    assert tub.precio_unitario == 9500.0 and tub.fuente_precio == "histórico"
    assert tub.calidad_cruce == "sin_precio_catalogo"
    assert tub.costo == 9500                          # NO 0: el respaldo sigue vivo

    motivos = alertas_costeo(_ensamblado(costed, sum(c.costo for c in costed)))
    assert any("555" in m and "sin precio en el catálogo" in m for m in motivos)


def test_mismo_insumo_creado_solo_en_np_costeado_en_esa_lista_dice_sin_precio_lista(alm, np):
    """El mismo insumo del test anterior, pero costeado en la lista NP donde SÍ
    tiene fila de precio: debe usar esa tarifa normalmente (estado 'encuentra,
    sin_precio=False'), sin ninguna de las dos alertas de ausencia."""
    alm.precios.crear_insumo(
        Insumo("555", "TUBERIA PVC 4\"", "ML", "MATERIAL", 12000.0, "ACTA NP"),
        lista_id=np)
    alm.apus.insert_components([
        ApuComponent("NP-3002", "DIURNO", "555", "TUBERIA PVC 4\"", "ML", 1.0, 9500.0)])

    costed, _ = PricingEngine(alm, lista_id=np).cost_apu("NP-3002", "DIURNO")
    tub = [c for c in costed if c.insumo_codigo == "555"][0]
    assert tub.precio_unitario == 12000.0 and tub.fuente_precio == "ACTA NP"
    assert tub.calidad_cruce == "exacto"


# --- Hallazgo 2 (Important): tarifa de $0 GENUINA en una lista NP no debe
# tragarse la regla del $0 (no confundirla con "sin precio en la lista") -----

def test_tarifa_cero_en_principal_no_se_tapa_con_el_historico(alm):
    """Decisión de negocio (no un accidente): fijamos que un $0 en Principal NO
    se tapa con el histórico, aunque el histórico sea > 0.

    Esto CAMBIÓ con 179db00. Antes de esa feature (listas de precios), el motor
    decidía "hay tarifa" con `r.insumo.precio > 0`; un insumo con FILA de precio
    en 0 en Principal (sin_precio=False: hay fila, no es una ausencia) caía a la
    rama "sin tarifa" y usaba `comp.precio_unitario_hist` (la tarifa CONTRACTUAL
    embebida en el APU) sin ninguna alerta. Desde 179db00 la condición es `not
    r.insumo.sin_precio`: como SÍ hay fila de precio, el 0 es un DATO (p. ej. un
    material que pone el cliente), no una ausencia, y se usa tal cual — delatado
    por la regla dura de alertas.py ("nada en $0"). CLAUDE.md es explícito: el
    histórico embebido es SOLO respaldo para cuando NO hay precio vigente; si hay
    precio vigente -aunque sea 0- ese manda. Tapar el 0 real con un número
    contractual plausible es justo la clase de underbid silencioso que el
    proyecto documenta como su riesgo dominante (regla "nada en $0").

    El caso es alcanzable desde ANTES de la feature de listas: `insert_insumos`
    (lo que corre `seed`) escribe precio=0.0 con sin_precio=False para cualquier
    celda del Excel histórico que venga vacía o en 0. hist=5000 (>0) es la clave
    del caso: es el único valor de histórico con el que el comportamiento viejo
    y el nuevo difieren (con hist=0 ambos coinciden y no probarían nada)."""
    alm.precios.insert_insumos([
        Insumo("444", "MATERIAL EN CERO", "UN", "MATERIAL", 0.0, "PRECIO IDU")])
    alm.apus.insert_components([
        ApuComponent("NP-3002", "DIURNO", "444", "MATERIAL EN CERO", "UN", 1.0, 5000.0)])

    costed, total = PricingEngine(alm).cost_apu("NP-3002", "DIURNO")
    mat = [c for c in costed if c.insumo_codigo == "444"][0]

    assert mat.precio_unitario == 0.0                  # la tarifa de $0, NO los 5000 del histórico
    assert mat.fuente_precio == "PRECIO IDU"           # la fuente del catálogo, NO "histórico"
    assert mat.calidad_cruce == "exacto"               # el cruce fue bueno; el problema es el monto

    motivos = alertas_costeo(_ensamblado(costed, total))
    assert any("444" in m and "en $0" in m for m in motivos)


def test_tarifa_cero_genuina_en_lista_np_sigue_alertando_en_0(alm, np):
    """Insumo con tarifa de $0 puesta A PROPÓSITO en la lista NP (material que pone
    el cliente): debe seguir detectándose como 'en $0' (regla dura), no como
    'sin precio en la lista' (que sería un diagnóstico falso: la tarifa YA está
    cargada, en 0)."""
    alm.precios.insert_insumos([
        Insumo("888", "MATERIAL DEL CLIENTE", "UN", "MATERIAL", 500.0, "PRECIO IDU")])
    iid = alm.precios.get_candidatos("888")[0].id
    alm.precios.set_precio_por_id(iid, 0.0, "ACTA NP", lista_id=np)
    alm.apus.insert_components([
        ApuComponent("NP-3002", "DIURNO", "888", "MATERIAL DEL CLIENTE", "UN", 1.0, 700.0)])

    costed, total = PricingEngine(alm, lista_id=np).cost_apu("NP-3002", "DIURNO")
    mat = [c for c in costed if c.insumo_codigo == "888"][0]
    assert mat.precio_unitario == 0.0 and mat.fuente_precio == "ACTA NP"
    assert mat.calidad_cruce == "exacto"               # NO sin_precio_lista

    motivos = alertas_costeo(_ensamblado(costed, total))
    assert any("888" in m and "en $0" in m for m in motivos)
    assert not any("888" in m and "sin precio en la lista" in m for m in motivos)


# --- Hallazgos 3+4 (Important): lista_id normalizado UNA vez; sin lectura de
# "Principal" contradictoria entre el motor y la capa de datos ---------------

def test_lista_id_string_uno_se_trata_como_principal(alm):
    """lista_id="1" (string, como llegaría de query string/JSON sin tipar) debe
    comportarse EXACTAMENTE como Principal: la capa de datos ya coerciona con
    int(lista_id), el motor debe coincidir."""
    eng_str = PricingEngine(alm, lista_id="1")
    eng_none = PricingEngine(alm)
    assert eng_str.lista_id == config.LISTA_PRINCIPAL_ID
    a, _ = eng_str.cost_apu("NP-3002", "DIURNO")
    b, _ = eng_none.cost_apu("NP-3002", "DIURNO")
    assert [(c.precio_unitario, c.fuente_precio, c.calidad_cruce) for c in a] == \
           [(c.precio_unitario, c.fuente_precio, c.calidad_cruce) for c in b]


def test_lista_id_cero_no_es_principal(alm):
    """lista_id=0 NO debe tratarse como "ausente"/Principal (el patrón `not
    self.lista_id` lo haría, y eso costearía un NP con precios contractuales en
    silencio). 0 no es una lista real, así que ningún insumo tiene fila de precio
    ahí: todo cae al camino "sin precio en lista", nunca al histórico."""
    eng = PricingEngine(alm, lista_id=0)
    assert eng.lista_id == 0
    costed, total = eng.cost_apu("NP-3002", "DIURNO")
    assert total == 0                                  # nada de histórico coló
    for c in costed:
        assert c.precio_unitario == 0.0
        assert c.fuente_precio == "sin precio en lista"
        assert c.calidad_cruce == "sin_precio_lista"


def test_lista_id_es_de_solo_lectura(alm):
    """Mutar `lista_id` post-construcción ya no es posible: es una property de
    solo lectura (hallazgo 3). Antes, mutarla con los cachés calientes daba un
    total plausible y equivocado (precios de una lista + política de respaldo de
    otra); ahora ni siquiera se puede intentar."""
    eng = PricingEngine(alm)
    with pytest.raises(AttributeError):
        eng.lista_id = 999
