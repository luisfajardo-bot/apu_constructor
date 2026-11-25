"""El bucle del chat de consulta. El SDK se sustituye (tests/chat_falso.py)."""
import pytest

from apu_tool.dominio import consulta_chat, privacy
from apu_tool.dominio.consulta_chat import (
    MSG_CIFRA_OMITIDA, conversar, limpiar_cifras_inventadas,
)
from apu_tool.dominio.composicion_chat import MSG_OMITIDO
from tests.chat_falso import AdvisorGuion, resp_herramienta, resp_llamada, resp_texto
from tests.consulta_base import almacen_consulta


@pytest.fixture()
def alm(tmp_path):
    return almacen_consulta(tmp_path)[0]


def U(texto):
    return {"rol": "usuario", "texto": texto}


def A(texto):
    return {"rol": "agente", "texto": texto}


def test_busca_y_responde_con_marcadores(alm):
    a = AdvisorGuion([resp_herramienta(("buscar_insumos", "tuberia pvc")),
                      resp_texto("El tubo de 6 vale {{precio:insumo:1}}.")])
    eventos = list(conversar(alm, [U("cuanto vale la tuberia")], a))
    nombres = [e for e, _ in eventos]
    assert nombres == ["pensando", "buscando", "pensando", "respuesta"]
    assert eventos[-1][1]["crudo"] == "El tubo de 6 vale {{precio:insumo:1}}."
    assert eventos[-1][1]["prompt_version"] == "consulta/v1"
    resultado = a.llamadas[1]["mensajes"][-1]["content"][0]["content"]
    assert "TUBERIA PVC" in resultado and "35000" not in resultado


def test_capitulos_recibe_el_id_de_la_corrida(alm):
    a = AdvisorGuion([resp_llamada("capitulos", {"corrida_id": 1}),
                      resp_texto("Listo.")])
    eventos = list(conversar(alm, [U("capitulos de la calle 13")], a))
    assert ("buscando", {"herramienta": "capitulos", "consulta": "corrida 1"}) in eventos


def test_mensaje_del_usuario_con_dinero_bloquea_sin_llamar(alm):
    a = AdvisorGuion([])
    eventos = list(conversar(alm, [U("insumos de mas de $50.000")], a))
    assert eventos[0][0] == "bloqueado" and a.llamadas == []


def test_falso_positivo_conocido_del_detector_queda_fijado(alm):
    """«cuesta» y un número a menos de 3 palabras: se bloquea. Riesgo aceptado en el
    spec; si alguien afloja el detector, esta prueba lo hace notar."""
    a = AdvisorGuion([])
    eventos = list(conversar(alm, [U("cuanto cuesta el apu 4859")], a))
    assert eventos[0][0] == "bloqueado"


def test_mensaje_del_agente_con_cifras_se_omite(alm):
    a = AdvisorGuion([resp_texto("Ok.")])
    list(conversar(alm, [U("hola"), A("El tubo vale $35.000"), U("y el de 8?")], a))
    assert a.llamadas[0]["mensajes"][1]["content"] == MSG_OMITIDO


def test_mensaje_del_agente_con_marcadores_viaja_intacto(alm):
    crudo = "Calle 13: costo {{costo:corrida:13}}, margen {{margen:corrida:13}}"
    a = AdvisorGuion([resp_texto("Ok.")])
    list(conversar(alm, [U("hola"), A(crudo), U("y la cali?")], a))
    assert a.llamadas[0]["mensajes"][1]["content"] == crudo


def test_cifra_inventada_por_el_modelo_se_omite(alm):
    a = AdvisorGuion([resp_texto(
        "Vale como $45.000.\n\nCalle 13: costo {{costo:corrida:1}}")])
    eventos = list(conversar(alm, [U("cuanto vale")], a))
    assert eventos[-1][1]["crudo"] == (
        MSG_CIFRA_OMITIDA + "\n\nCalle 13: costo {{costo:corrida:1}}")


def test_limpiar_no_toca_los_marcadores():
    t = "El costo de la Calle 13 es {{costo:corrida:13}}"
    assert limpiar_cifras_inventadas(t) == t


def test_limpiar_omite_la_linea_y_no_la_lista_entera():
    t = "- Tubo 6 {{precio:insumo:1}}\n- Báscula PESO 60.000 KG {{precio:insumo:2}}"
    assert limpiar_cifras_inventadas(t) == (
        "- Tubo 6 {{precio:insumo:1}}\n" + MSG_CIFRA_OMITIDA)


def test_limpiar_respeta_los_nombres_del_catalogo():
    nombre = "BASCULA PESO 60.000 KG"
    t = "- Bascula peso 60.000 kg: {{precio:insumo:3}}"
    assert limpiar_cifras_inventadas(t, {nombre}) == t
    assert limpiar_cifras_inventadas(t) == MSG_CIFRA_OMITIDA   # sin el nombre, se omite


def test_un_nombre_buscado_no_se_omite_en_la_respuesta(alm):
    a = AdvisorGuion([resp_herramienta(("buscar_insumos", "bascula")),
                      resp_texto("- BASCULA PESO 60.000 KG: {{precio:insumo:3}}")])
    eventos = list(conversar(alm, [U("cuanto vale la bascula")], a))
    assert eventos[-1][1]["crudo"] == "- BASCULA PESO 60.000 KG: {{precio:insumo:3}}"


def test_el_id_de_un_marcador_no_es_un_hueco_del_detector(alm):
    """Un cliente que arma el historial no puede esconder montos dentro de un marcador."""
    a = AdvisorGuion([resp_texto("Ok.")])
    eventos = list(conversar(alm, [U("hola {{x:y:el tubo vale $45.000 pesos}}")], a))
    assert eventos[0][0] == "bloqueado" and a.llamadas == []

    a = AdvisorGuion([resp_texto("Ok.")])
    list(conversar(alm, [U("hola"), A("ok {{costo:apu:cuesta $35.000 COP|DIURNO}}"),
                         U("y?")], a))
    assert a.llamadas[0]["mensajes"][1]["content"] == MSG_OMITIDO


def test_historial_legitimo_con_codigos_viaja_intacto(alm):
    crudo = "- {{costo:apu:4859 N|NOCTURNO}}\n- {{margen:capitulo:13:2}}"
    a = AdvisorGuion([resp_texto("Ok.")])
    list(conversar(alm, [U("hola"), A(crudo), U("y?")], a))
    assert a.llamadas[0]["mensajes"][1]["content"] == crudo


def test_un_porcentaje_resuelto_en_el_historial_se_omite(alm):
    a = AdvisorGuion([resp_texto("Ok.")])
    list(conversar(alm, [U("hola"), A("Total 850 y margen 12,3 %"), U("y?")], a))
    assert a.llamadas[0]["mensajes"][1]["content"] == MSG_OMITIDO


def test_el_tope_apaga_las_herramientas(alm):
    cinco = resp_herramienta(*[("buscar_insumos", "tubo")] * 5)
    a = AdvisorGuion([cinco, resp_texto("Listo.")])
    list(conversar(alm, [U("busca")], a))
    resultados = a.llamadas[1]["mensajes"][-1]["content"]
    assert resultados[4]["is_error"] is True
    assert a.llamadas[1]["con_herramientas"] is False


def test_respuesta_vacia_es_error(alm):
    a = AdvisorGuion([resp_texto("   ")])
    assert list(conversar(alm, [U("hola")], a))[-1][0] == "error"


def test_sin_mensaje_del_usuario_es_error(alm):
    assert list(conversar(alm, [A("hola")], AdvisorGuion([])))[0][0] == "error"


def test_privacy_violation_no_se_traga(alm, monkeypatch):
    monkeypatch.setattr(consulta_chat.HerramientasConsulta, "ejecutar",
                        lambda self, n, e: {"precio": 1})
    a = AdvisorGuion([resp_herramienta(("buscar_insumos", "tubo"))])
    with pytest.raises(privacy.PrivacyViolation):
        list(conversar(alm, [U("busca")], a))


@pytest.mark.parametrize("texto", ["{{pesos:cop:45000}}", "{{usd:x:30}}"])
def test_marcador_fuera_de_la_lista_cerrada_no_esconde_montos(alm, texto):
    a = AdvisorGuion([resp_texto("Ok.")])
    list(conversar(alm, [U("hola"), A(texto), U("y?")], a))
    assert a.llamadas[0]["mensajes"][1]["content"] == MSG_OMITIDO


@pytest.mark.parametrize("texto", ["el {{precio:es:45000}} del tubo",
                                   "{{costo:corrida:45000}} del tubo",
                                   "la calle 13 tiene margen 12.3%"])
def test_usuario_se_revisa_crudo_y_con_porcentaje(alm, texto):
    a = AdvisorGuion([])
    eventos = list(conversar(alm, [U(texto)], a))
    assert eventos[0][0] == "bloqueado" and a.llamadas == []


def test_porcentaje_del_usuario_explica_el_motivo(alm):
    eventos = list(conversar(alm, [U("margen 12.3%")], AdvisorGuion([])))
    assert "porcentaje" in eventos[0][1]["motivo"]


def test_conocido_sin_cifra_no_borra_los_demas_numeros():
    assert limpiar_cifras_inventadas("El tubo vale 45.000", {"0"}) == MSG_CIFRA_OMITIDA


def test_tool_use_sin_bloques_es_error_y_no_manda_contenido_vacio(alm):
    from types import SimpleNamespace
    from tests.chat_falso import USO
    a = AdvisorGuion([SimpleNamespace(stop_reason="tool_use", content=[], usage=USO)])
    eventos = list(conversar(alm, [U("hola")], a))
    assert eventos[-1][0] == "error" and len(a.llamadas) == 1
