"""La puerta al SDK del chat: una vuelta del bucle, sin llamar a la API real."""
import json
from types import SimpleNamespace

import pytest

from apu_tool.dominio import ai_assist
from apu_tool.dominio.ai_assist import (
    HERRAMIENTAS_CHAT, MSG_CREDENCIAL, MSG_SIN_SALDO, ApuAdvisor, IANoDisponible,
)


def advisor_con_cliente(create):
    a = ApuAdvisor(enabled=False)
    a.enabled = True
    a.model = "modelo-x"
    a._client = SimpleNamespace(messages=SimpleNamespace(create=create))
    return a


def test_pide_herramientas_salida_estructurada_y_esfuerzo_bajo():
    visto = {}
    a = advisor_con_cliente(lambda **kw: visto.update(kw) or "resp")
    assert a.turno_chat([{"role": "user", "content": "hola"}],
                        con_herramientas=True) == "resp"
    assert visto["model"] == "modelo-x"
    assert visto["tools"] == HERRAMIENTAS_CHAT
    assert visto["tool_choice"] == {"type": "auto"}
    assert visto["thinking"] == {"type": "adaptive"}
    assert visto["output_config"]["effort"] == "low"
    assert visto["output_config"]["format"]["type"] == "json_schema"
    # Caché automática: cada vuelta del bucle reenvía todo lo anterior, y con esto esa
    # parte se cobra a 0,1x (smoke real 2026-11-19: 94 % de los tokens eran entrada).
    assert visto["cache_control"] == {"type": "ephemeral"}


def test_en_el_tope_apaga_las_herramientas_sin_forzar_ninguna():
    """`tool_choice` forzado (any/tool) da 400 en los modelos nuevos: el tope se
    cierra con `none`, que todos aceptan, y las herramientas siguen declaradas
    porque el historial ya tiene bloques tool_use."""
    visto = {}
    a = advisor_con_cliente(lambda **kw: visto.update(kw))
    a.turno_chat([], con_herramientas=False)
    assert visto["tool_choice"] == {"type": "none"}
    assert visto["tools"] == HERRAMIENTAS_CHAT


def test_los_esquemas_no_usan_lo_que_la_salida_estructurada_rechaza():
    texto = json.dumps([ai_assist._ESQUEMA_CHAT, HERRAMIENTAS_CHAT])
    assert "minimum" not in texto and "maximum" not in texto


def test_el_esquema_del_componente_es_el_mismo_de_componer():
    """Mismo contrato, mismo acotado: sin `apu` en tipo ni `sub_apu` en funcion."""
    item = ai_assist._ESQUEMA_CHAT["properties"]["cambios"]["items"]
    comp = item["properties"]["componente"]
    assert comp["type"] == ["object", "null"]
    assert comp["properties"]["tipo"]["enum"] == ["insumo"]
    assert "sub_apu" not in comp["properties"]["funcion"]["enum"]


def test_sin_credencial_levanta_ia_no_disponible():
    a = ApuAdvisor(enabled=False)
    with pytest.raises(IANoDisponible, match="ANTHROPIC_API_KEY"):
        a.turno_chat([], con_herramientas=True)


class _ErrorApi(Exception):
    def __init__(self, status_code, message="x"):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def test_traduce_credencial_invalida():
    def create(**_kw):
        raise _ErrorApi(401)
    with pytest.raises(IANoDisponible) as e:
        advisor_con_cliente(create).turno_chat([], con_herramientas=True)
    assert str(e.value) == MSG_CREDENCIAL


def test_traduce_sin_saldo():
    def create(**_kw):
        raise _ErrorApi(400, "Your credit balance is too low")
    with pytest.raises(IANoDisponible) as e:
        advisor_con_cliente(create).turno_chat([], con_herramientas=True)
    assert str(e.value) == MSG_SIN_SALDO


def test_otros_errores_suben_tal_cual():
    def create(**_kw):
        raise _ErrorApi(529)
    with pytest.raises(_ErrorApi):
        advisor_con_cliente(create).turno_chat([], con_herramientas=True)


def test_revienta_antes_de_la_red_si_hay_una_clave_monetaria():
    llamado = []
    a = advisor_con_cliente(lambda **kw: llamado.append(kw))
    with pytest.raises(ai_assist.privacy.PrivacyViolation):
        a.turno_chat([{"role": "user", "content": [{"precio": 1}]}],
                     con_herramientas=True)
    assert llamado == []
