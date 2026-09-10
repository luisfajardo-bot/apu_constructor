"""Contrato de la composición: vocabularios cerrados y parseo tolerante.

El parseo NUNCA descarta un componente: degrada conservadoramente y deja que el
validador (dominio/validacion_composicion.py) lo diga. Descartar en silencio es el
hueco que esta feature viene a tapar.
"""
import math

from apu_tool.dominio.composicion import (
    ESTADOS,
    FUNCIONES,
    NIVELES_EVIDENCIA,
    OPERACIONES,
    ORIGENES,
    TIPOS,
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
    assert TIPOS == ("insumo", "apu")
    assert OPERACIONES == ("division", "multiplicacion", "directo")
    assert ESTADOS == ("generando", "propuesta", "editada", "aprobada",
                       "rechazada", "error")


def test_la_incertidumbre_se_acota_y_lo_no_finito_cae_a_cero():
    """El guard de isfinite es load-bearing: min(max(nan,0),1) devuelve nan."""
    for crudo, esperado in ((5, 1.0), (-1, 0.0), (float("inf"), 0.0),
                            (float("nan"), 0.0), ("x", 0.0)):
        p = propuesta_desde_json({"componentes": [],
                                  "incertidumbre_declarada": crudo})
        assert p.incertidumbre_declarada == esperado


def test_un_calculo_con_operacion_ilegible_queda_en_none():
    p = propuesta_desde_json(_crudo(calculo={"operacion": "raiz", "numerador": 1,
                                             "denominador": 2, "resultado": 3}))
    assert p.componentes[0].calculo is None


def test_un_calculo_que_no_es_dict_queda_en_none():
    p = propuesta_desde_json(_crudo(calculo="8/96"))
    assert p.componentes[0].calculo is None


def test_un_calculo_bien_formado_se_parsea():
    p = propuesta_desde_json(_crudo(calculo={"operacion": "division",
                                             "numerador": 8, "denominador": 96,
                                             "resultado": 0.083}))
    assert p.componentes[0].calculo.evaluar() == 8 / 96


def test_directo_no_necesita_denominador():
    assert Calculo("directo", 0.5, float("nan"), 0.5).evaluar() == 0.5


def test_un_resultado_no_finito_es_imposible():
    assert Calculo("division", 1e308, 1e-308, 0).evaluar() is None
    assert Calculo("multiplicacion", 1e200, 1e200, 0).evaluar() is None


def test_un_entero_gigante_no_revienta_el_parseo():
    """Un entero de 400 dígitos es JSON válido; json.loads lo da como int."""
    import json as _json
    crudo = _json.loads('{"componentes": [{"codigo": "4279", "rendimiento": '
                        + "9" * 400 + '}]}')
    p = propuesta_desde_json(crudo)
    assert len(p.componentes) == 1
    assert math.isnan(p.componentes[0].rendimiento)


def test_to_dict_produce_json_valido_aunque_haya_nan():
    """NaN rompe JSON.parse en el navegador y da 500 en Starlette (allow_nan=False)."""
    import json as _json
    p = propuesta_desde_json(_crudo(rendimiento="ilegible"))
    texto = _json.dumps(p.to_dict(), allow_nan=False)   # no debe levantar
    assert '"rendimiento": null' in texto


def test_la_propuesta_hace_round_trip_por_json():
    import json as _json
    original = propuesta_desde_json(_crudo(calculo={"operacion": "division",
                                                    "numerador": 8,
                                                    "denominador": 96,
                                                    "resultado": 0.083}))
    vuelta = propuesta_desde_json(_json.loads(_json.dumps(original.to_dict())))
    assert vuelta == original


def test_las_hipotesis_no_quedan_aliasadas_al_json_del_llamador():
    crudo = _crudo(hipotesis={"horas_jornada": 8})
    p = propuesta_desde_json(crudo)
    crudo["componentes"][0]["hipotesis"]["horas_jornada"] = 999
    assert p.componentes[0].hipotesis["horas_jornada"] == 8


def test_un_codigo_absurdamente_largo_se_acota_en_el_parseo():
    """La salida del modelo es un borde de confianza: se acota acá, no río abajo.
    Un código de 10 KB rompe la tabla de la interfaz y se persiste igual, porque la
    validación trunca los mensajes pero no los datos."""
    p = propuesta_desde_json(_crudo(codigo="X" * 10_000,
                                    justificacion="J" * 10_000))
    assert len(p.componentes[0].codigo) == 40
    assert len(p.componentes[0].justificacion) == 500
