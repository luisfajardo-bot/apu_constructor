"""Contrato de la composición: vocabularios cerrados y parseo tolerante.

El parseo NUNCA descarta un componente: degrada conservadoramente y deja que el
validador (dominio/validacion_composicion.py) lo diga. Descartar en silencio es el
hueco que esta feature viene a tapar.
"""
import math

from apu_tool.dominio.composicion import (
    FUNCIONES,
    NIVELES_EVIDENCIA,
    ORIGENES,
    Calculo,
    propuesta_desde_json,
)


def _crudo(**extra) -> dict:
    """Un JSON del modelo bien formado, con los campos que se quieran pisar."""
    comp = {"codigo": "4279", "tipo": "insumo", "funcion": "mano_de_obra",
            "rendimiento": 0.5, "origen": "copiado_de_antecedente",
            "referencias": [{"apu_codigo": "3010", "turno": "DIURNO"}],
            "hipotesis": {}, "calculo": None, "justificacion": "porque sí",
            "nivel_evidencia": "alto"}
    comp.update(extra)
    return {"componentes": [comp], "supuestos": [], "incertidumbre_declarada": 0.2,
            "justificacion": "global"}


def test_parsea_una_propuesta_bien_formada():
    p = propuesta_desde_json(_crudo())
    assert len(p.componentes) == 1
    c = p.componentes[0]
    assert (c.codigo, c.tipo, c.funcion) == ("4279", "insumo", "mano_de_obra")
    assert c.rendimiento == 0.5
    assert c.referencias[0].apu_codigo == "3010"
    assert p.incertidumbre_declarada == 0.2


def test_funcion_ilegible_no_descarta_el_componente():
    p = propuesta_desde_json(_crudo(funcion="excavacion_y_cargue"))
    assert len(p.componentes) == 1        # NO se tira
    assert p.componentes[0].funcion == ""  # queda vacía; el validador la marca


def test_origen_ilegible_degrada_a_sin_evidencia():
    """Conservador: no reclamar evidencia que no se entendió."""
    p = propuesta_desde_json(_crudo(origen="me_lo_invente"))
    assert p.componentes[0].origen == "sin_evidencia"


def test_nivel_de_evidencia_ilegible_degrada_a_bajo():
    p = propuesta_desde_json(_crudo(nivel_evidencia="altisimo"))
    assert p.componentes[0].nivel_evidencia == "bajo"


def test_rendimiento_no_numerico_queda_nan_y_no_se_descarta():
    p = propuesta_desde_json(_crudo(rendimiento="mucho"))
    assert len(p.componentes) == 1
    assert math.isnan(p.componentes[0].rendimiento)


def test_tipo_ilegible_degrada_a_insumo():
    p = propuesta_desde_json(_crudo(tipo="cosa"))
    assert p.componentes[0].tipo == "insumo"


def test_componente_sin_codigo_no_se_descarta_queda_vacio():
    p = propuesta_desde_json(_crudo(codigo=""))
    assert len(p.componentes) == 1
    assert p.componentes[0].codigo == ""


def test_json_basura_da_propuesta_vacia_no_revienta():
    for basura in ({}, {"componentes": None}, {"componentes": "no"},
                   {"componentes": [42, "x", None]}):
        p = propuesta_desde_json(basura)
        assert p.componentes == ()


def test_calculo_evalua_la_division():
    assert Calculo("division", 8, 96, 0.09).evaluar() == 8 / 96


def test_calculo_con_denominador_cero_es_imposible():
    assert Calculo("division", 8, 0, 1.0).evaluar() is None


def test_calculo_con_valores_no_finitos_es_imposible():
    assert Calculo("division", float("inf"), 96, 1.0).evaluar() is None
    assert Calculo("multiplicacion", float("nan"), 2, 1.0).evaluar() is None


def test_calculo_multiplicacion_y_directo():
    assert Calculo("multiplicacion", 3, 4, 0).evaluar() == 12
    assert Calculo("directo", 0.7, 0, 0).evaluar() == 0.7


def test_vocabularios_son_los_del_diseno():
    assert FUNCIONES == ("mano_de_obra", "equipo", "herramienta", "material",
                         "transporte", "subcontrato", "sub_apu")
    assert ORIGENES == ("copiado_de_antecedente", "ajustado_de_antecedente",
                        "calculado_desde_produccion", "supuesto_tecnico",
                        "sin_evidencia")
    assert NIVELES_EVIDENCIA == ("alto", "medio", "bajo")
