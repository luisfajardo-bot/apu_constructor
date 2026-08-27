"""Regla de transporte por proyecto: pura, sin base de datos."""
from apu_tool import config
from apu_tool.nucleo.models import ClaseTransporte, ParametrosProyecto


def test_parametros_vacios():
    assert ParametrosProyecto().vacio is True
    assert ParametrosProyecto(km_botadero=30).vacio is False
    assert ParametrosProyecto(peaje_aplica=False).vacio is False


def test_km_por_categoria():
    p = ParametrosProyecto(km_botadero=34, km_mezclas=28, km_granulares=32)
    assert p.km("botadero") == 34
    assert p.km("mezclas") == 28
    assert p.km("granulares") == 32
    assert p.km("inexistente") is None


def test_vocabulario_de_config():
    assert config.TRANSPORTE_CATEGORIAS == ("botadero", "mezclas", "granulares")
    assert config.PEAJE == ("INT3", "PEAJE")
    assert config.DERECHOS_BOTADERO == ("7231", "DERECHOS DE BOTADERO")
    assert config.KM_BASE_DEFECTO == 25.0


def test_clase_transporte_es_inmutable():
    c = ClaseTransporte(apu_codigo="4200", shift="DIURNO", insumo_codigo="6878",
                        insumo_nombre="TRANSPORTE DE BASES ASFALTICAS",
                        categoria="mezclas", volumen=1.05, km_base=25.0)
    assert c.volumen == 1.05


from apu_tool.dominio import transporte
from apu_tool.nucleo.models import ApuComponent


def _comp(cod, nombre, unidad="M3-KM", rend=26.25, tipo="insumo", hist=1000.0):
    return ApuComponent(apu_codigo="4200", shift="DIURNO", insumo_codigo=cod,
                        insumo_nombre=nombre, unidad=unidad, rendimiento=rend,
                        precio_unitario_hist=hist, tipo=tipo)


def _clase(cod, nombre, categoria, volumen):
    return {("4200", "DIURNO", cod): ClaseTransporte(
        apu_codigo="4200", shift="DIURNO", insumo_codigo=cod, insumo_nombre=nombre,
        categoria=categoria, volumen=volumen, km_base=25.0)}


def test_sin_parametros_no_toca_nada():
    comps = [_comp("6878", "TRANSPORTE DE BASES ASFALTICAS")]
    assert transporte.aplicar(comps, "4200", "DIURNO") == comps
    assert transporte.aplicar(comps, "4200", "DIURNO",
                              ParametrosProyecto(), {}, ()) == comps


def test_reescala_mezclas():
    comps = [_comp("6878", "TRANSPORTE DE BASES ASFALTICAS")]
    cls = _clase("6878", "TRANSPORTE DE BASES ASFALTICAS", "mezclas", 1.05)
    out = transporte.aplicar(comps, "4200", "DIURNO",
                             ParametrosProyecto(km_mezclas=28), cls, ())
    assert out[0].rendimiento == 29.4
    assert out[0].insumo_codigo == "6878"          # solo cambia el rendimiento


def test_km_de_otra_categoria_no_afecta():
    comps = [_comp("6878", "TRANSPORTE DE BASES ASFALTICAS")]
    cls = _clase("6878", "TRANSPORTE DE BASES ASFALTICAS", "mezclas", 1.05)
    out = transporte.aplicar(comps, "4200", "DIURNO",
                             ParametrosProyecto(km_granulares=32), cls, ())
    assert out[0].rendimiento == 26.25


def test_componente_sin_clasificar_queda_intacto_y_es_pendiente():
    comps = [_comp("7462", "TRANSPORTE DE PETREOS")]
    p = ParametrosProyecto(km_granulares=32)
    assert transporte.aplicar(comps, "4200", "DIURNO", p, {}, ())[0].rendimiento == 26.25
    assert transporte.pendientes(comps, "4200", "DIURNO", p, {}) == ("7462",)


def test_nombre_distinto_no_se_reescala():
    """El mismo código con OTRO nombre es OTRO insumo (7462 es también NIPLE 16")."""
    comps = [_comp("7462", 'NIPLE 16" ACERO CARBON', unidad="UN", rend=1.0)]
    cls = _clase("7462", "TRANSPORTE DE PETREOS", "granulares", 1.05)
    out = transporte.aplicar(comps, "4200", "DIURNO",
                             ParametrosProyecto(km_granulares=32), cls, ())
    assert out[0].rendimiento == 1.0


def test_derechos_de_botadero_nunca_escalan():
    comps = [_comp("7231", "DERECHOS DE BOTADERO", unidad="M3", rend=1.3)]
    out = transporte.aplicar(comps, "4200", "DIURNO",
                             ParametrosProyecto(km_botadero=34), {}, ())
    assert out[0].rendimiento == 1.3
    assert transporte.pendientes(comps, "4200", "DIURNO",
                                 ParametrosProyecto(km_botadero=34), {}) == ()


def test_peaje_se_quita_si_no_aplica():
    comps = [_comp("INT3", "PEAJE", unidad="GLB", rend=1.0),
             _comp("6878", "TRANSPORTE DE BASES ASFALTICAS")]
    out = transporte.aplicar(comps, "4200", "DIURNO",
                             ParametrosProyecto(peaje_aplica=False), {}, ())
    assert [c.insumo_codigo for c in out] == ["6878"]


def test_peaje_se_conserva_si_aplica():
    comps = [_comp("INT3", "PEAJE", unidad="GLB", rend=1.0)]
    out = transporte.aplicar(comps, "4200", "DIURNO",
                             ParametrosProyecto(peaje_aplica=True, peaje_valor=12400),
                             {}, ())
    assert len(out) == 1 and out[0].rendimiento == 1.0   # el valor lo aplica pricing.py


def test_subapu_no_se_toca_aqui():
    comps = [_comp("3017", "TRANSPORTE Y DISPOSICION FINAL DE ESCOMBROS",
                   unidad="M3", rend=1.3, tipo="apu")]
    out = transporte.aplicar(comps, "4200", "DIURNO",
                             ParametrosProyecto(km_botadero=34), {}, ())
    assert out[0].rendimiento == 1.3 and out[0].tipo == "apu"


def test_es_peaje_y_es_derechos():
    assert transporte.es_peaje(_comp("INT3", "PEAJE", unidad="GLB")) is True
    assert transporte.es_peaje(_comp("INT3", "OTRA COSA", unidad="GLB")) is False
    assert transporte.es_derechos(_comp("7231", "DERECHOS DE BOTADERO")) is True
