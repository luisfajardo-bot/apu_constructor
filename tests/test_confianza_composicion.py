"""La confianza la calcula la plataforma, no el modelo.

Cuatro niveles explicables (alta/media/baja/insuficiente) a partir de señales
observables, con el desglose guardado para que el usuario vea por qué.
"""
from apu_tool.dominio.composicion import (
    ComponentePropuesto, Propuesta, Referencia, Supuesto,
)
from apu_tool.dominio.compose import RendimientoObservado
from apu_tool.dominio.validacion_composicion import (
    NIVELES_CONFIANZA, ContextoValidacion, calcular_confianza, validar,
)


def comp(**kw) -> ComponentePropuesto:
    base = dict(codigo="4279", tipo="insumo", funcion="mano_de_obra",
                rendimiento=0.62, origen="copiado_de_antecedente",
                referencias=(Referencia("A1", "DIURNO"),), hipotesis={},
                calculo=None, justificacion="j", nivel_evidencia="alto",
                ref_shift="")
    base.update(kw)
    return ComponentePropuesto(**base)


def ctx(**kw) -> ContextoValidacion:
    base = dict(
        descripcion="EXCAVACION EN MATERIAL COMUN", unidad_actividad="M3",
        shift="DIURNO",
        codigos_permitidos=frozenset({"4279", "6092", "322"}),
        unidades_catalogo={"4279": "HR", "6092": "GLB", "322": "M3"},
        apus_existentes=frozenset({("A1", "DIURNO")}),
        componentes_de_apu={},
        observados={
            "4279": RendimientoObservado("4279", "HR", 14, 0.55, 0.62, 0.70),
            "6092": RendimientoObservado("6092", "GLB", 20, 1.0, 1.0, 1.0),
        },
        unidades_de_apu={("A1", "DIURNO"): "M3"},
        apu_codigo_propio="", supuestos_confirmados=False)
    base.update(kw)
    return ContextoValidacion(**base)


def _nivel(p: Propuesta, c: ContextoValidacion) -> str:
    corregida, v = validar(p, c)
    return calcular_confianza(corregida, v, c).nivel


SANA = Propuesta(componentes=(comp(),
                              comp(codigo="6092", funcion="herramienta",
                                   rendimiento=1.0)))


def test_el_vocabulario_es_el_del_diseno():
    assert NIVELES_CONFIANZA == ("alta", "media", "baja", "insuficiente")


def test_una_propuesta_bien_respaldada_da_alta():
    assert _nivel(SANA, ctx()) == "alta"


def test_con_un_error_bloqueante_siempre_es_insuficiente():
    """Sin excepción: si no se puede aprobar, no hay confianza que reportar."""
    rota = Propuesta(componentes=(comp(codigo="9999"),))
    assert _nivel(rota, ctx()) == "insuficiente"


def test_sin_evidencia_en_todos_los_componentes_no_puede_dar_alta():
    floja = Propuesta(componentes=(
        comp(origen="sin_evidencia", referencias=()),
        comp(codigo="6092", funcion="herramienta", rendimiento=1.0,
             origen="sin_evidencia", referencias=())))
    assert _nivel(floja, ctx()) != "alta"


def test_la_incertidumbre_del_modelo_no_mueve_el_nivel():
    """Criterio 27: dos propuestas idénticas con incertidumbre 0,0 y 1,0 dan lo mismo."""
    segura = Propuesta(componentes=SANA.componentes, incertidumbre_declarada=0.0)
    insegura = Propuesta(componentes=SANA.componentes, incertidumbre_declarada=1.0)
    assert _nivel(segura, ctx()) == _nivel(insegura, ctx())


def test_los_supuestos_sin_confirmar_restan():
    con = Propuesta(componentes=SANA.componentes,
                    supuestos=(Supuesto("prof", "<1,5 m", "cambia el equipo"),))
    corregida, v = validar(con, ctx())
    conf = calcular_confianza(corregida, v, ctx())
    assert any(m.senal == "supuestos_sin_confirmar" and m.aporte < 0
               for m in conf.motivos)


def test_un_rendimiento_atipico_resta():
    rara = Propuesta(componentes=(comp(rendimiento=5.0),
                                  comp(codigo="6092", funcion="herramienta",
                                       rendimiento=1.0)))
    corregida, v = validar(rara, ctx())
    conf = calcular_confianza(corregida, v, ctx())
    assert any(m.senal == "rendimientos_atipicos" and m.aporte < 0
               for m in conf.motivos)


def test_el_desglose_explica_el_nivel():
    corregida, v = validar(SANA, ctx())
    conf = calcular_confianza(corregida, v, ctx())
    assert conf.motivos                       # nunca vacío
    assert sum(m.aporte for m in conf.motivos) == conf.puntos
    for m in conf.motivos:
        assert m.senal and m.valor            # todo motivo se puede leer


def test_la_senal_de_unidad_ve_la_unidad_del_antecedente():
    c_igual = ctx()
    c_distinta = ctx(unidades_de_apu={("A1", "DIURNO"): "ML"})
    aporte = lambda conf: next(m.aporte for m in conf.motivos
                               if m.senal == "unidad_de_antecedentes")
    assert aporte(calcular_confianza(*validar(SANA, c_igual), c_igual)) > \
        aporte(calcular_confianza(*validar(SANA, c_distinta), c_distinta))


def test_la_confianza_no_lleva_dinero():
    from apu_tool.dominio import privacy
    corregida, v = validar(SANA, ctx())
    privacy.assert_no_money(calcular_confianza(corregida, v, ctx()).to_dict())


def test_el_nivel_siempre_es_del_vocabulario():
    for p in (Propuesta(), SANA, Propuesta(componentes=(comp(codigo="9999"),))):
        corregida, v = validar(p, ctx())
        assert calcular_confianza(corregida, v, ctx()).nivel in NIVELES_CONFIANZA
