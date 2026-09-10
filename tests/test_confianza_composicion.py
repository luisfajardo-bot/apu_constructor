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
        assert m.senal and m.detalle           # todo motivo se puede leer


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


def test_un_rendimiento_atipico_impide_el_nivel_alta():
    """"Alta" significa "aprobalo de un vistazo". Un consumo que la biblioteca
    contradice no lo es, por buenas que sean las demás señales."""
    rara = Propuesta(componentes=(comp(rendimiento=5.0),      # 8x fuera de rango
                                  comp(codigo="6092", funcion="herramienta",
                                       rendimiento=1.0)))
    corregida, v = validar(rara, ctx())
    conf = calcular_confianza(corregida, v, ctx())
    assert conf.nivel == "media"
    assert conf.puntos >= 4          # habría dado "alta" sin el tope
    assert any(m.senal == "tope_por_rendimiento_atipico" for m in conf.motivos)


def test_una_cantidad_sospechosa_no_topea_el_nivel():
    """Un APU en GLB o KM lleva la cantidad de la obra adentro: la advertencia es
    esperable y no puede castigar a toda esa familia de actividades.

    El componente sospechoso es "322", que NO está en `ctx().observados`: así
    dispara CANTIDAD_SOSPECHOSA (supera el techo) pero no RENDIMIENTO_ATIPICO (no
    hay rango observado contra el cual compararlo) — que es justo lo que este test
    necesita aislar. Usar "4279" hubiera disparado los dos a la vez y el test no
    habría probado nada.
    """
    from apu_tool import config
    grande = Propuesta(componentes=(
        comp(codigo="322", funcion="material",
             rendimiento=config.COMPOSICION_LIMITE_RENDIMIENTO + 1),
        comp(codigo="6092", funcion="herramienta", rendimiento=1.0)))
    corregida, v = validar(grande, ctx())
    assert any(h.codigo == "CANTIDAD_SOSPECHOSA" for h in v.advertencias)
    assert not any(h.codigo == "RENDIMIENTO_ATIPICO" for h in v.advertencias)
    conf = calcular_confianza(corregida, v, ctx())
    assert not any(m.senal == "tope_por_rendimiento_atipico" for m in conf.motivos)


def test_el_nivel_no_depende_del_tamano_de_la_propuesta():
    """La misma calidad relativa tiene que dar el mismo nivel con 2 componentes que
    con 12. Sin techo en los castigos por ocurrencia, n=12 daba `baja` donde n=2 y
    n=6 daban `media` (medido: al agregar el techo n=12 pasa de baja(0) a media(+2),
    igualando a n=2 y n=6).

    Códigos todos DISTINTOS por componente (S{i}/G{i}, nunca repetidos): repetir
    código+tipo+turno dispara COMPONENTE_DUPLICADO, que es error y manda todo a
    `insuficiente` — no es lo que este test quiere medir.
    """
    def propuesta_y_ctx(n: int) -> tuple[Propuesta, ContextoValidacion]:
        comps = []
        codigos: set[str] = set()
        unidades: dict[str, str] = {}
        observados: dict[str, RendimientoObservado] = {}
        for i in range(n):
            funcion = "mano_de_obra" if i % 2 == 0 else "herramienta"
            if i % 3 == 0:                        # un tercio, sin evidencia
                codigo = f"S{i}"
                comps.append(comp(codigo=codigo, funcion=funcion, rendimiento=1.0,
                                  origen="sin_evidencia", referencias=()))
            else:                                  # el resto, bien respaldado
                codigo = f"G{i}"
                comps.append(comp(codigo=codigo, funcion=funcion, rendimiento=1.0,
                                  origen="copiado_de_antecedente",
                                  referencias=(Referencia("A1", "DIURNO"),)))
                observados[codigo] = RendimientoObservado(codigo, "HR", 5,
                                                           0.9, 1.0, 1.1)
            codigos.add(codigo)
            unidades[codigo] = "HR"
        c = ctx(codigos_permitidos=frozenset(codigos), unidades_catalogo=unidades,
                observados=observados)
        return Propuesta(componentes=tuple(comps)), c

    niveles = {}
    for n in (2, 6, 12):
        p, c = propuesta_y_ctx(n)
        niveles[n] = _nivel(p, c)
    assert len(set(niveles.values())) == 1, niveles


def test_el_nivel_baja_es_alcanzable():
    floja = Propuesta(componentes=(
        comp(origen="sin_evidencia", referencias=(), rendimiento=5.0),
        comp(codigo="6092", funcion="herramienta", rendimiento=1.0,
             origen="sin_evidencia", referencias=())))
    assert _nivel(floja, ctx()) == "baja"
