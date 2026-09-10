"""El orquestador: eventos, estados y el pegado de las piezas.

El advisor se sustituye; no se llama a la API real.
"""
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.dominio.ai_assist import ApuAdvisor, IANoDisponible
from apu_tool.dominio.composicion import (
    Calculo, ComponentePropuesto, Propuesta, Referencia,
)
from apu_tool.dominio.composicion_agente import componer, evaluar, recuperar
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo, LicitacionItem

ITEM = LicitacionItem("1.3", "EXCAVACION MANUAL EN MATERIAL COMUN", "M3", 120.0,
                      180000.0, "DIURNO")


@pytest.fixture()
def alm(tmp_path):
    a = Almacen(tmp_path / "precios.db", tmp_path / "apus.db",
                tmp_path / "corridas.db")
    a.reset()
    a.precios.insert_insumos([
        Insumo("4279", "CUADRILLA OFICIAL MAS AYUDANTES", "HR", "MO", 40000,
               "PRECIO IDU"),
        Insumo("6092", "HERRAMIENTA MENOR", "GLB", "EQ", 2000, "PRECIO IDU"),
    ])
    a.apus.insert_apus([
        Apu("A1", "EXCAVACION MANUAL COMUN", "M3", "DIURNO", "EXCAVACIONES")])
    a.apus.insert_components([
        ApuComponent("A1", "DIURNO", "4279", "CUADRILLA", "HR", 0.62, 40000),
        ApuComponent("A1", "DIURNO", "6092", "HERRAMIENTA MENOR", "GLB", 1.0, 2000),
    ])
    return a


class AdvisorFalso(ApuAdvisor):
    def __init__(self, propuesta: Propuesta):
        self.enabled = True
        self._client = object()
        self.model = "falso"
        self.propuesta = propuesta
        self.llamadas = 0
        self.insumos_vistos = None

    def componer(self, item, insumos, ejemplos, observados):
        self.llamadas += 1
        self.insumos_vistos = insumos
        return self.propuesta


def comp(**kw) -> ComponentePropuesto:
    base = dict(codigo="4279", tipo="insumo", funcion="mano_de_obra",
                rendimiento=0.62, origen="copiado_de_antecedente",
                referencias=(Referencia("A1", "DIURNO"),), hipotesis={},
                calculo=None, justificacion="j", nivel_evidencia="alto",
                ref_shift="")
    base.update(kw)
    return ComponentePropuesto(**base)


SANA = Propuesta(componentes=(comp(),
                              comp(codigo="6092", funcion="herramienta",
                                   rendimiento=1.0)))


def eventos(alm, advisor, item=ITEM) -> list[tuple[str, dict]]:
    return list(componer(alm, item, advisor))


# --- recuperar -------------------------------------------------------------
def test_recuperar_llena_el_grupo_de_los_candidatos(alm):
    ctx = recuperar(alm, ITEM)
    grupos = {i.codigo: i.grupo for i in ctx.insumos}
    assert grupos.get("4279") == "MO"


def test_recuperar_arma_la_lista_blanca_y_las_unidades(alm):
    ctx = recuperar(alm, ITEM)
    assert "4279" in ctx.validacion.codigos_permitidos
    assert ctx.validacion.unidades_catalogo["4279"] == "HR"
    assert ("A1", "DIURNO") in ctx.validacion.apus_existentes
    assert ctx.validacion.unidades_de_apu[("A1", "DIURNO")] == "M3"


def test_recuperar_trae_los_rendimientos_observados(alm):
    assert "4279" in recuperar(alm, ITEM).validacion.observados


# --- evaluar (el camino del PUT) -------------------------------------------
def test_evaluar_no_llama_a_la_ia(alm):
    """Guardar una edición humana no vuelve a pagar una generación."""
    ctx = recuperar(alm, ITEM)
    propuesta, validacion, confianza = evaluar(SANA, ctx.validacion)
    assert validacion.valido is True
    assert confianza.nivel in ("alta", "media", "baja")
    assert len(propuesta.componentes) == 2


def test_evaluar_recalcula_la_aritmetica(alm):
    ctx = recuperar(alm, ITEM)
    mala = Propuesta(componentes=(comp(rendimiento=0.09,
                                       calculo=Calculo("division", 8, 96, 0.09)),))
    propuesta, validacion, _ = evaluar(mala, ctx.validacion)
    assert propuesta.componentes[0].rendimiento == pytest.approx(8 / 96)
    assert any(h.codigo == "CALCULO_CORREGIDO" for h in validacion.advertencias)


# --- componer --------------------------------------------------------------
def test_los_eventos_salen_en_orden(alm):
    evs = eventos(alm, AdvisorFalso(SANA))
    assert [e for e, _ in evs] == ["recuperando", "generando", "validando", "lista"]


def test_el_evento_recuperando_dice_cuanto_encontro(alm):
    _, payload = eventos(alm, AdvisorFalso(SANA))[0]
    assert set(payload) == {"n_insumos", "n_apus"}
    assert payload["n_insumos"] > 0


def test_el_evento_lista_trae_todo_lo_que_hay_que_guardar(alm):
    _, payload = eventos(alm, AdvisorFalso(SANA))[-1]
    assert set(payload) == {"propuesta", "validacion", "confianza",
                            "confianza_motivos", "antecedentes", "modelo",
                            "prompt_version"}
    assert payload["prompt_version"].startswith("composicion/")
    assert payload["modelo"] == "falso"


def test_los_antecedentes_guardan_la_lista_blanca(alm):
    _, payload = eventos(alm, AdvisorFalso(SANA))[-1]
    assert "4279" in payload["antecedentes"]["codigos_permitidos"]
    assert {"codigo": "A1", "turno": "DIURNO"} in \
        payload["antecedentes"]["apus_referencia"]


def test_una_propuesta_vacia_sale_invalida_nunca_lista_en_verde(alm):
    _, payload = eventos(alm, AdvisorFalso(Propuesta()))[-1]
    assert payload["validacion"]["valido"] is False
    assert payload["confianza"] == "insuficiente"


def test_un_codigo_inventado_no_pasa(alm):
    inventada = Propuesta(componentes=(comp(codigo="NO-EXISTE"),))
    _, payload = eventos(alm, AdvisorFalso(inventada))[-1]
    codigos = {e["codigo"] for e in payload["validacion"]["errores"]}
    assert "CODIGO_NO_AUTORIZADO" in codigos


def test_la_ia_solo_ve_los_codigos_autorizados(alm):
    a = AdvisorFalso(SANA)
    evs = eventos(alm, a)
    _, payload = evs[-1]
    assert {i.codigo for i in a.insumos_vistos} <= \
        set(payload["antecedentes"]["codigos_permitidos"])


def test_sin_credencial_el_evento_es_error(alm):
    class Sin(AdvisorFalso):
        def componer(self, *a, **k):
            raise IANoDisponible("falta ANTHROPIC_API_KEY")

    evs = eventos(alm, Sin(SANA))
    assert evs[-1][0] == "error"
    assert "ANTHROPIC_API_KEY" in evs[-1][1]["detail"]


def test_una_actividad_sin_candidatos_da_error_legible(alm):
    vacia = LicitacionItem("9.9", "ZZZZZZ QQQQQQ", "UN", 1.0, 0.0, "DIURNO")
    alm.precios.reset()
    alm.apus.reset()
    evs = eventos(alm, AdvisorFalso(SANA), item=vacia)
    assert evs[-1][0] == "error"


def test_la_privacidad_no_se_traga_nunca(alm):
    """Una PrivacyViolation sube; NO se convierte en un evento `error` genérico."""
    from apu_tool.dominio import privacy

    class Fuga(AdvisorFalso):
        def componer(self, *a, **k):
            raise privacy.PrivacyViolation("se coló un precio")

    with pytest.raises(privacy.PrivacyViolation):
        eventos(alm, Fuga(SANA))


def test_el_payload_del_evento_lista_no_lleva_dinero(alm):
    from apu_tool.dominio import privacy
    _, payload = eventos(alm, AdvisorFalso(SANA))[-1]
    privacy.assert_no_money(payload)
