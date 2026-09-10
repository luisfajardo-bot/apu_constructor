"""Invariante #1 en la superficie nueva: la IA nunca ve dinero.

Se prueba por forma (qué claves lleva el payload) y por guardián (que
`assert_no_money` reviente si algo monetario se cuela). Las dos cosas: la forma atrapa
un campo agregado sin pensar, el guardián atrapa uno con nombre monetario.
"""
import pytest

from apu_tool.dominio import privacy
from apu_tool.dominio.compose import CandidateInsumo, RendimientoObservado
from apu_tool.nucleo.models import (
    DePricedApu, DePricedComponent, LicitacionItem,
)

ITEM = LicitacionItem(item="1.3", descripcion="EXCAVACION MANUAL", unidad="M3",
                      cantidad=120.0, precio_contractual=180000.0, shift="DIURNO")
INSUMOS = [CandidateInsumo("4279", "CUADRILLA", "HR", "MO")]
EJEMPLOS = [DePricedApu("A1", "UNO", "M3", "DIURNO", "EXCAVACIONES",
                        (DePricedComponent("4279", "CUADRILLA", "HR", 0.62),))]
OBS = {"4279": RendimientoObservado("4279", "HR", 14, 0.40, 0.62, 1.10)}


def test_el_payload_pasa_el_guardian():
    privacy.assert_no_money(privacy.payload_composicion(ITEM, INSUMOS, EJEMPLOS, OBS))


def test_el_payload_lleva_exactamente_estas_claves():
    """Test de forma: un campo agregado sin pensar rompe acá antes que en producción."""
    p = privacy.payload_composicion(ITEM, INSUMOS, EJEMPLOS, OBS)
    assert set(p) == {"actividad", "insumos_disponibles", "apus_referencia",
                      "rendimientos_observados"}
    assert set(p["actividad"]) == {"item", "descripcion", "unidad", "cantidad",
                                   "shift"}
    assert set(p["insumos_disponibles"][0]) == {"insumo_codigo", "insumo_nombre",
                                                "unidad", "grupo"}
    assert set(p["rendimientos_observados"][0]) == {"insumo_codigo", "unidad", "n",
                                                    "minimo", "mediana", "maximo",
                                                    "descartados_otra_unidad"}


def test_el_precio_contractual_de_la_actividad_no_viaja():
    p = privacy.payload_composicion(ITEM, INSUMOS, EJEMPLOS, OBS)
    assert "precio_contractual" not in p["actividad"]
    assert 180000.0 not in p["actividad"].values()


def test_los_apus_de_referencia_no_llevan_precio_historico():
    p = privacy.payload_composicion(ITEM, INSUMOS, EJEMPLOS, OBS)
    comp = p["apus_referencia"][0]["componentes"][0]
    assert "precio_unitario_hist" not in comp
    assert "precio" not in comp


def test_un_precio_colado_en_el_payload_revienta():
    p = privacy.payload_composicion(ITEM, INSUMOS, EJEMPLOS, OBS)
    p["insumos_disponibles"][0]["precio"] = 40000
    with pytest.raises(privacy.PrivacyViolation):
        privacy.assert_no_money(p)


@pytest.mark.parametrize("clave", ["precio", "costo", "costo_unitario", "valor_total",
                                   "margen", "total", "amount", "fuente_precio",
                                   "costo_manual", "plan_json"])
def test_cada_nombre_monetario_revienta_donde_sea(clave):
    p = privacy.payload_composicion(ITEM, INSUMOS, EJEMPLOS, OBS)
    p["apus_referencia"][0]["componentes"][0][clave] = 1
    with pytest.raises(privacy.PrivacyViolation):
        privacy.assert_no_money(p)


def test_safe_json_es_el_unico_camino_de_salida():
    texto = privacy.safe_json(privacy.payload_composicion(ITEM, INSUMOS, EJEMPLOS, OBS))
    assert "180000" not in texto
    assert "EXCAVACION MANUAL" in texto


def test_el_payload_sin_antecedentes_sigue_siendo_valido():
    p = privacy.payload_composicion(ITEM, INSUMOS, EJEMPLOS, {})
    assert p["rendimientos_observados"] == []
    privacy.assert_no_money(p)


def test_candidate_insumo_lleva_grupo_y_nada_mas():
    from dataclasses import fields
    assert {f.name for f in fields(CandidateInsumo)} == {"codigo", "nombre", "unidad",
                                                         "grupo"}


def test_el_retriever_sigue_devolviendo_candidatos_sin_grupo():
    """`grupo` tiene default vacío: el retriever no consulta el catálogo para
    llenarlo, lo hace el orquestador con la misma lectura que usa para validar."""
    assert CandidateInsumo("1", "X", "UN").grupo == ""
