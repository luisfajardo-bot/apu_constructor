"""La frontera de privacidad del chat: el texto libre que escribe una persona.

`assert_no_money` mira NOMBRES de clave, no valores. El chat es el primer payload hacia
la IA hecho de texto libre escrito por personas, así que necesita un detector propio
para los valores. Preferimos fallar a filtrar: un falso positivo cuesta reescribir el
mensaje; un falso negativo le muestra un precio a la IA.
"""
import json

import pytest

from apu_tool.dominio import privacy
from apu_tool.dominio.compose import RendimientoObservado
from apu_tool.dominio.privacy import texto_con_dinero
from apu_tool.nucleo.models import Insumo, LicitacionItem


@pytest.mark.parametrize("texto", [
    "el cemento nos salió en $45.000",
    "$ 12000",
    "nos lo cotizaron a 45000",
    "Cotización: 1.250.000 el m3",
    "vale 3 millones",
    "COP 1200 por unidad",
    "eso cuesta 3000",
    "el precio es 12.500",
    "45 USD",
    "son 200 pesos",
    "valor 80.000",
    # pegados al número o con verbos de plata (revisión del plan, ejecutados)
    "precio:45000",
    "costo=45000",
    "precio/und 45000",
    "el cemento nos salió en 45.000",
    "el m3 sale a 320.000",
    "pagamos 90.000 el jornal",
    "sale en 45 mil",
    "45k por hora",
    "€45",
])
def test_bloquea_un_monto(texto):
    motivo = texto_con_dinero(texto)
    assert motivo is not None
    assert "IA no puede ver precios" in motivo


@pytest.mark.parametrize("texto", [
    "8 horas por jornada",
    "rendimiento de 0,125 HH/m3",
    "1,05 m3 de concreto",
    "rendimiento de 12 m2 por jornada",
    "vale, agrega 2 ayudantes",
    "busca una mano de obra que tenga licencia de soldador",
    "el valor del rendimiento no me cuadra",
    "cuadrilla de 1 oficial y 2 ayudantes",
    "peso específico 2,4 t/m3",
    "pon el rendimiento en 0,5",
    "concreto de 3000 psi",
    "rendimiento 0.125",
    "Propuse: + 7001 OFICIAL SOLDADOR HR 0,1 (aplicado)",
    "",
])
def test_deja_pasar_cantidades_fisicas(texto):
    assert texto_con_dinero(texto) is None


def test_el_motivo_dice_como_escribir_una_cantidad_fisica():
    """«pon el valor en 0,5» se bloquea (falso positivo aceptado): el motivo le dice
    a la persona cómo decirlo sin que salte."""
    assert "rendimiento 0,5" in texto_con_dinero("pon el valor en 0,5")


def test_el_motivo_cita_el_fragmento_para_que_la_persona_lo_encuentre():
    motivo = texto_con_dinero("agrega el oficial, nos cobra 90.000 de tarifa diaria")
    assert "tarifa" in motivo or "cobra" in motivo


ITEM = LicitacionItem("1.3", "EXCAVACION MANUAL", "M3", 120.0, 180000.0, "DIURNO")
CATALOGO = {"4279": {"nombre": "CUADRILLA", "unidad": "HR", "grupo": "MO"}}
COMP = {"codigo": "4279", "tipo": "insumo", "funcion": "mano_de_obra",
        "rendimiento": 0.62, "origen": "copiado_de_antecedente",
        "referencias": [], "hipotesis": {"costo_m3": "45000"}, "calculo": None,
        "justificacion": "nos lo cobran a $45.000", "nivel_evidencia": "alto",
        "ref_shift": ""}


def test_payload_chat_no_lleva_dinero_ni_texto_libre_de_la_mesa():
    p = privacy.payload_chat(ITEM, [COMP], CATALOGO)
    privacy.assert_no_money(p)
    texto = json.dumps(p, ensure_ascii=False)
    assert "180000" not in texto          # precio_contractual
    assert "45000" not in texto           # hipotesis y justificacion: no viajan
    assert p["composicion_actual"] == [{
        "codigo": "4279", "nombre": "CUADRILLA", "unidad": "HR",
        "funcion": "mano_de_obra", "rendimiento": 0.62,
        "origen": "copiado_de_antecedente"}]


def test_un_rendimiento_ilegible_viaja_como_null():
    p = privacy.payload_chat(ITEM, [dict(COMP, rendimiento="abc")], CATALOGO)
    assert p["composicion_actual"][0]["rendimiento"] is None


def test_los_campos_libres_del_cliente_no_cuelan_texto():
    """`funcion` y `origen` solo viajan si son del vocabulario; un `codigo` con
    pinta de monto viaja vacío. Lo explota solo un cliente hostil, pero es gratis."""
    raro = dict(COMP, funcion="cuesta $45.000", origen="cotizado a 45000",
                codigo="$45.000")
    c = privacy.payload_chat(ITEM, [raro], CATALOGO)["composicion_actual"][0]
    assert (c["funcion"], c["origen"], c["codigo"]) == ("", "", "")


def test_insumo_encontrado_copia_campo_por_campo_sin_precio():
    ins = Insumo("4279", "CUADRILLA", "HR", "SUELDOS Y JORNALES", 40000, "COSTO INTERNO")
    obs = RendimientoObservado("4279", "HR", 14, 0.4, 0.62, 1.1)
    d = privacy.insumo_encontrado_to_dict(ins, obs)
    privacy.assert_no_money(d)
    assert "40000" not in json.dumps(d)
    assert d["insumo_codigo"] == "4279" and d["grupo"] == "SUELDOS Y JORNALES"
    assert d["rendimientos_observados"]["mediana"] == 0.62
    assert privacy.insumo_encontrado_to_dict(ins, None)["rendimientos_observados"] is None
