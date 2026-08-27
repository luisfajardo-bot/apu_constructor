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
