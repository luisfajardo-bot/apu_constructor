"""El validador determinístico: qué bloquea, qué advierte y qué recalcula.

Regla del reparto: bloquea lo ESTRUCTURAL (el código no existe, la cantidad no es un
número, el sub-APU cicla) y advierte lo CONTEXTUAL (rendimiento raro, falta
herramienta, el método no cuadra). Convertir criterio de ingeniería discutible en
bloqueo absoluto es lo que el diseño prohíbe.
"""
import pytest

from apu_tool import config
from apu_tool.dominio.composicion import (
    Calculo, ComponentePropuesto, Propuesta, Referencia, Supuesto,
)
from apu_tool.dominio.compose import RendimientoObservado
from apu_tool.dominio.validacion_composicion import ContextoValidacion, validar


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
        descripcion="EXCAVACION MANUAL EN MATERIAL COMUN", unidad_actividad="M3",
        shift="DIURNO",
        codigos_permitidos=frozenset({"4279", "6092", "322"}),
        unidades_catalogo={"4279": "HR", "6092": "GLB", "322": "M3"},
        apus_existentes=frozenset({("A1", "DIURNO"), ("SUB", "DIURNO")}),
        componentes_de_apu={("SUB", "DIURNO"): ()},
        observados={"4279": RendimientoObservado("4279", "HR", 14, 0.40, 0.62, 1.10)},
        apu_codigo_propio="", supuestos_confirmados=False)
    base.update(kw)
    return ContextoValidacion(**base)


def codigos(hallazgos) -> set[str]:
    return {h.codigo for h in hallazgos}


# --- casos limpios ---------------------------------------------------------
def test_una_propuesta_sana_es_valida():
    p = Propuesta(componentes=(comp(), comp(codigo="6092", funcion="herramienta",
                                            rendimiento=1.0)))
    _, v = validar(p, ctx())
    assert v.valido is True
    assert v.errores == ()
    assert v.totales > 0 and v.superadas <= v.totales


# --- bloqueantes -----------------------------------------------------------
def test_propuesta_vacia_es_error():
    _, v = validar(Propuesta(), ctx())
    assert v.valido is False
    assert "PROPUESTA_VACIA" in codigos(v.errores)


def test_codigo_fuera_de_la_lista_blanca_es_error():
    _, v = validar(Propuesta(componentes=(comp(codigo="9999"),)), ctx())
    assert "CODIGO_NO_AUTORIZADO" in codigos(v.errores)
    assert v.valido is False


def test_codigo_autorizado_pero_ausente_del_catalogo_es_error():
    c = ctx(codigos_permitidos=frozenset({"4279", "7777"}))
    _, v = validar(Propuesta(componentes=(comp(codigo="7777"),)), c)
    assert "CODIGO_INEXISTENTE" in codigos(v.errores)


@pytest.mark.parametrize("valor", [0.0, -1.0, float("nan"), float("inf")])
def test_cantidades_no_positivas_o_no_finitas_son_error(valor):
    _, v = validar(Propuesta(componentes=(comp(rendimiento=valor),)), ctx())
    assert "CANTIDAD_INVALIDA" in codigos(v.errores)


def test_cantidad_por_encima_del_techo_advierte_pero_no_bloquea():
    """Antes era error. Un APU en GLB o KM lleva la cantidad de obra adentro y pasa
    el techo legítimamente; bloquearlo no dejaba ningún estado en el que aprobarlo."""
    absurdo = config.COMPOSICION_LIMITE_RENDIMIENTO + 1
    _, v = validar(Propuesta(componentes=(comp(rendimiento=absurdo),)), ctx())
    assert "CANTIDAD_INVALIDA" not in codigos(v.errores)
    assert "CANTIDAD_SOSPECHOSA" in codigos(v.advertencias)


def test_componente_duplicado_es_error():
    _, v = validar(Propuesta(componentes=(comp(), comp())), ctx())
    assert "COMPONENTE_DUPLICADO" in codigos(v.errores)


def test_varios_duplicados_dan_un_solo_hallazgo():
    """Una regla, un hallazgo: si emitiera uno por par, `superadas` restaría de más."""
    p = Propuesta(componentes=(comp(), comp(),
                               comp(codigo="6092", funcion="herramienta",
                                    rendimiento=1.0),
                               comp(codigo="6092", funcion="herramienta",
                                    rendimiento=1.0)))
    _, v = validar(p, ctx())
    dups = [h for h in v.errores if h.codigo == "COMPONENTE_DUPLICADO"]
    assert len(dups) == 1
    assert "4279" in dups[0].mensaje and "6092" in dups[0].mensaje


def test_mismo_codigo_como_insumo_y_como_subapu_no_es_duplicado():
    """La clave es (codigo, tipo, ref_shift): son dos cosas distintas."""
    p = Propuesta(componentes=(
        comp(codigo="SUB", tipo="apu", funcion="sub_apu", ref_shift="DIURNO"),
        comp(codigo="SUB", tipo="insumo")))
    c = ctx(codigos_permitidos=frozenset({"SUB"}), unidades_catalogo={"SUB": "UN"})
    _, v = validar(p, c)
    assert "COMPONENTE_DUPLICADO" not in codigos(v.errores)


def test_subapu_inexistente_es_error():
    p = Propuesta(componentes=(comp(codigo="NOEXISTE", tipo="apu", funcion="sub_apu",
                                    ref_shift="DIURNO"),))
    _, v = validar(p, ctx(codigos_permitidos=frozenset({"NOEXISTE"})))
    assert "SUBAPU_INEXISTENTE" in codigos(v.errores)


def test_subapu_en_otro_turno_del_que_existe_es_error():
    p = Propuesta(componentes=(comp(codigo="SUB", tipo="apu", funcion="sub_apu",
                                    ref_shift="NOCTURNO"),))
    _, v = validar(p, ctx(codigos_permitidos=frozenset({"SUB"})))
    assert "SUBAPU_INEXISTENTE" in codigos(v.errores)


def test_subapu_que_contiene_al_apu_que_se_esta_creando_es_ciclo():
    """Solo detectable al aprobar, cuando el código propio ya se eligió."""
    p = Propuesta(componentes=(comp(codigo="SUB", tipo="apu", funcion="sub_apu",
                                    ref_shift="DIURNO"),))
    c = ctx(codigos_permitidos=frozenset({"SUB"}),
            componentes_de_apu={("SUB", "DIURNO"): (("YO", "apu", "DIURNO"),)},
            apu_codigo_propio="YO")
    _, v = validar(p, c)
    assert "SUBAPU_CICLO" in codigos(v.errores)


def test_calculo_con_denominador_cero_es_error():
    p = Propuesta(componentes=(comp(calculo=Calculo("division", 8, 0, 1.0)),))
    _, v = validar(p, ctx())
    assert "CALCULO_IMPOSIBLE" in codigos(v.errores)


# --- recálculo -------------------------------------------------------------
def test_python_manda_sobre_la_aritmetica_del_modelo():
    """El modelo dice 8/96 = 0,09. Python escribe 0,0833... y lo advierte."""
    p = Propuesta(componentes=(comp(rendimiento=0.09,
                                    calculo=Calculo("division", 8, 96, 0.09)),))
    corregida, v = validar(p, ctx())
    assert corregida.componentes[0].rendimiento == pytest.approx(8 / 96)
    assert "CALCULO_CORREGIDO" in codigos(v.advertencias)
    assert v.valido is True          # se corrige, no se rechaza


def test_un_redondeo_razonable_no_se_marca_como_corregido():
    p = Propuesta(componentes=(comp(rendimiento=0.083333,
                                    calculo=Calculo("division", 8, 96, 0.083333)),))
    _, v = validar(p, ctx())
    assert "CALCULO_CORREGIDO" not in codigos(v.advertencias)


def test_sin_calculo_el_rendimiento_del_modelo_se_respeta():
    corregida, _ = validar(Propuesta(componentes=(comp(rendimiento=0.62),)), ctx())
    assert corregida.componentes[0].rendimiento == 0.62


def test_la_unidad_del_componente_la_pone_el_catalogo_no_el_modelo():
    """No hay regla de unidad porque no hay campo de unidad: el contrato no deja que
    el modelo la declare. Que la actividad sea M3 y la cuadrilla HR es lo normal —
    el rendimiento es HR por M3, no una incoherencia."""
    from dataclasses import fields
    assert "unidad" not in {f.name for f in fields(ComponentePropuesto)}


# --- advertencias ----------------------------------------------------------
def test_rendimiento_fuera_del_rango_observado_advierte():
    _, v = validar(Propuesta(componentes=(comp(rendimiento=5.0),)), ctx())
    assert "RENDIMIENTO_ATIPICO" in codigos(v.advertencias)
    assert v.valido is True          # advierte, no bloquea


def test_con_pocos_antecedentes_no_se_llama_atipico_a_nada():
    pocos = {"4279": RendimientoObservado("4279", "HR", 2, 0.40, 0.50, 0.60)}
    _, v = validar(Propuesta(componentes=(comp(rendimiento=5.0),)),
                   ctx(observados=pocos))
    assert "RENDIMIENTO_ATIPICO" not in codigos(v.advertencias)
    assert "SIN_ANTECEDENTES" in codigos(v.advertencias)


def test_origen_sin_evidencia_advierte():
    _, v = validar(Propuesta(componentes=(comp(origen="sin_evidencia",
                                               referencias=()),)), ctx())
    assert "SIN_EVIDENCIA" in codigos(v.advertencias)


def test_origen_que_exige_antecedente_sin_referencias_advierte():
    _, v = validar(Propuesta(componentes=(comp(origen="copiado_de_antecedente",
                                               referencias=()),)), ctx())
    assert "SIN_EVIDENCIA" in codigos(v.advertencias)


def test_referencia_a_un_apu_que_no_existe_se_limpia_y_advierte():
    p = Propuesta(componentes=(comp(referencias=(Referencia("FANTASMA", "DIURNO"),
                                                 Referencia("A1", "DIURNO"))),))
    corregida, v = validar(p, ctx())
    assert [r.apu_codigo for r in corregida.componentes[0].referencias] == ["A1"]
    assert "REFERENCIA_INEXISTENTE" in codigos(v.advertencias)


def test_funcion_ilegible_advierte():
    _, v = validar(Propuesta(componentes=(comp(funcion=""),)), ctx())
    assert "FUNCION_ILEGIBLE" in codigos(v.advertencias)


def test_sin_mano_de_obra_ni_equipo_advierte():
    p = Propuesta(componentes=(comp(codigo="322", funcion="material",
                                    rendimiento=1.0),))
    _, v = validar(p, ctx())
    assert "FALTA_MANO_DE_OBRA" in codigos(v.advertencias)


def test_mano_de_obra_sin_herramienta_ni_equipo_advierte():
    _, v = validar(Propuesta(componentes=(comp(),)), ctx())
    assert "FALTA_HERRAMIENTA" in codigos(v.advertencias)


def test_actividad_manual_con_equipo_pesado_advierte():
    p = Propuesta(componentes=(comp(), comp(codigo="6092", funcion="equipo",
                                            rendimiento=1.0)))
    _, v = validar(p, ctx(descripcion="EXCAVACION MANUAL EN MATERIAL COMUN"))
    assert "METODO_INCOHERENTE" in codigos(v.advertencias)


def test_actividad_mecanica_sin_equipo_advierte():
    p = Propuesta(componentes=(comp(), comp(codigo="6092", funcion="herramienta",
                                            rendimiento=1.0)))
    _, v = validar(p, ctx(descripcion="EXCAVACION MECANICA CON RETROEXCAVADORA"))
    assert "METODO_INCOHERENTE" in codigos(v.advertencias)


def test_supuesto_sin_confirmar_advierte():
    p = Propuesta(componentes=(comp(),),
                  supuestos=(Supuesto("profundidad_m", "< 1,5 m", "cambia el equipo"),))
    _, v = validar(p, ctx(supuestos_confirmados=False))
    assert "SUPUESTO_SIN_CONFIRMAR" in codigos(v.advertencias)


def test_supuesto_confirmado_no_advierte():
    p = Propuesta(componentes=(comp(),),
                  supuestos=(Supuesto("profundidad_m", "< 1,5 m", "cambia el equipo"),))
    _, v = validar(p, ctx(supuestos_confirmados=True))
    assert "SUPUESTO_SIN_CONFIRMAR" not in codigos(v.advertencias)


# --- forma del resultado ---------------------------------------------------
def test_la_forma_del_resultado_es_estable():
    _, v = validar(Propuesta(componentes=(comp(),)), ctx())
    d = v.to_dict()
    assert set(d) == {"valido", "errores", "advertencias", "metricas"}
    assert set(d["metricas"]) == {"superadas", "totales"}


def test_una_regla_rota_resta_exactamente_uno():
    """Candado de la convención: una regla = un hallazgo. El test viejo comparaba
    `superadas` contra su propia definición y no podía fallar nunca.

    La mutación es el rendimiento y no la `funcion`: vaciar `funcion` rompe DOS reglas
    a la vez (FUNCION_ILEGIBLE y, porque el conjunto de funciones se queda sin
    `mano_de_obra`, FALTA_MANO_DE_OBRA), y un diferencial de dos no mide una regla.
    Un rendimiento fuera del rango observado rompe exactamente una y no mueve
    `totales`, que es lo que este candado necesita."""
    limpia = Propuesta(componentes=(comp(), comp(codigo="6092",
                                                 funcion="herramienta",
                                                 rendimiento=1.0)))
    rota = Propuesta(componentes=(comp(rendimiento=5.0), comp(codigo="6092",
                                                              funcion="herramienta",
                                                              rendimiento=1.0)))
    _, vl = validar(limpia, ctx())
    _, vr = validar(rota, ctx())
    assert vr.totales == vl.totales
    assert vr.superadas == vl.superadas - 1


def test_todas_las_referencias_muertas_dejan_el_componente_sin_evidencia():
    p = Propuesta(componentes=(comp(referencias=(Referencia("FANTASMA", "DIURNO"),)),))
    corregida, v = validar(p, ctx())
    assert corregida.componentes[0].referencias == ()
    assert "REFERENCIA_INEXISTENTE" in codigos(v.advertencias)
    assert "SIN_EVIDENCIA" in codigos(v.advertencias)


def test_un_rendimiento_ilegible_lo_rescata_su_propia_formula():
    """NaN del parseo + una fórmula válida: Python la evalúa y el componente se salva."""
    p = Propuesta(componentes=(comp(rendimiento=float("nan"),
                                    calculo=Calculo("division", 8, 96, 0.083)),))
    corregida, v = validar(p, ctx())
    assert corregida.componentes[0].rendimiento == pytest.approx(8 / 96)
    assert "CANTIDAD_INVALIDA" not in codigos(v.errores)


def test_el_techo_exacto_no_es_sospechoso():
    justo = config.COMPOSICION_LIMITE_RENDIMIENTO
    _, v = validar(Propuesta(componentes=(comp(rendimiento=justo),)), ctx())
    assert "CANTIDAD_SOSPECHOSA" not in codigos(v.advertencias)
    _, v2 = validar(Propuesta(componentes=(comp(rendimiento=justo + 1),)), ctx())
    assert "CANTIDAD_SOSPECHOSA" in codigos(v2.advertencias)
    assert v2.valido is True          # sospechoso, no bloqueante


def test_un_codigo_vacio_no_rompe_los_mensajes():
    _, v = validar(Propuesta(componentes=(comp(codigo=""),)), ctx())
    assert "CODIGO_NO_AUTORIZADO" in codigos(v.errores)
    assert all(h.mensaje for h in v.errores)


def test_funcion_subapu_con_tipo_insumo_es_error():
    p = Propuesta(componentes=(comp(codigo="SUB", funcion="sub_apu", tipo="insumo"),))
    _, v = validar(p, ctx(codigos_permitidos=frozenset({"SUB"}),
                          unidades_catalogo={"SUB": "UN"}))
    assert "TIPO_INCOHERENTE" in codigos(v.errores)


def test_un_subapu_no_arrastra_sin_antecedentes():
    p = Propuesta(componentes=(comp(codigo="SUB", tipo="apu", funcion="sub_apu",
                                    ref_shift="DIURNO"),))
    _, v = validar(p, ctx(codigos_permitidos=frozenset({"SUB"})))
    assert "SIN_ANTECEDENTES" not in codigos(v.advertencias)


def test_calculado_sin_cuenta_advierte():
    _, v = validar(Propuesta(componentes=(
        comp(origen="calculado_desde_produccion", calculo=None),)), ctx())
    assert "SIN_EVIDENCIA" in codigos(v.advertencias)


def test_supuesto_tecnico_sin_supuesto_declarado_advierte():
    _, v = validar(Propuesta(componentes=(comp(origen="supuesto_tecnico"),)), ctx())
    assert "SIN_EVIDENCIA" in codigos(v.advertencias)


def test_supuesto_tecnico_con_supuesto_declarado_no_advierte():
    p = Propuesta(componentes=(comp(origen="supuesto_tecnico"),),
                  supuestos=(Supuesto("prof", "<1,5 m", "cambia el equipo"),))
    _, v = validar(p, ctx())
    assert "SIN_EVIDENCIA" not in codigos(v.advertencias)


def test_el_calculo_corregido_tambien_corrige_su_propio_resultado():
    """La interfaz muestra la fórmula: no puede decir '8/96 = 0,09' arriba de 0,083."""
    p = Propuesta(componentes=(comp(rendimiento=0.09,
                                    calculo=Calculo("division", 8, 96, 0.09)),))
    corregida, _ = validar(p, ctx())
    assert corregida.componentes[0].calculo.resultado == pytest.approx(8 / 96)


def test_cada_hallazgo_apunta_a_su_componente():
    _, v = validar(Propuesta(componentes=(comp(codigo="9999"),)), ctx())
    err = next(h for h in v.errores if h.codigo == "CODIGO_NO_AUTORIZADO")
    assert err.componente == "9999"
    assert err.mensaje


def test_la_validacion_no_lleva_dinero():
    from apu_tool.dominio import privacy
    _, v = validar(Propuesta(componentes=(comp(),)), ctx())
    privacy.assert_no_money(v.to_dict())
