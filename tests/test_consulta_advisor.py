"""La puerta del chat de consulta al SDK. No se llama a la API real."""
from types import SimpleNamespace

import pytest

from apu_tool.dominio import ai_assist
from apu_tool.dominio.ai_assist import ApuAdvisor, IANoDisponible
from apu_tool.dominio.privacy import PrivacyViolation


def _con_cliente_falso():
    capturado = {}
    a = ApuAdvisor(enabled=False)
    a.enabled = True
    a._client = SimpleNamespace(messages=SimpleNamespace(
        create=lambda **kw: capturado.update(kw) or "RESP"))
    return a, capturado


def test_sin_credencial_dice_que_falta_la_llave():
    with pytest.raises(IANoDisponible, match="Consultar al agente necesita ANTHROPIC"):
        ApuAdvisor(enabled=False).turno_consulta([], con_herramientas=True)


def test_dinero_en_los_mensajes_revienta_antes_de_llamar():
    a, capturado = _con_cliente_falso()
    with pytest.raises(PrivacyViolation):
        a.turno_consulta([{"role": "user", "content": [{"costo": 1}]}],
                         con_herramientas=True)
    assert capturado == {}


def test_llama_con_su_prompt_sus_herramientas_y_sin_esquema_json():
    a, capturado = _con_cliente_falso()
    assert a.turno_consulta([{"role": "user", "content": "hola"}],
                            con_herramientas=True) == "RESP"
    assert capturado["system"] == ai_assist._SISTEMA_CONSULTA
    assert capturado["tools"] == ai_assist.HERRAMIENTAS_CONSULTA
    assert capturado["tool_choice"] == {"type": "auto"}
    assert "format" not in capturado["output_config"]


def test_en_el_tope_apaga_las_herramientas_sin_sacarlas():
    a, capturado = _con_cliente_falso()
    a.turno_consulta([{"role": "user", "content": "hola"}], con_herramientas=False)
    assert capturado["tool_choice"] == {"type": "none"}
    assert capturado["tools"] == ai_assist.HERRAMIENTAS_CONSULTA


def test_las_herramientas_son_estrictas_y_son_cuatro():
    nombres = [h["name"] for h in ai_assist.HERRAMIENTAS_CONSULTA]
    assert nombres == ["buscar_insumos", "buscar_apus", "buscar_proyectos", "capitulos"]
    assert all(h["strict"] for h in ai_assist.HERRAMIENTAS_CONSULTA)


def test_el_chat_de_la_mesa_conserva_su_mensaje():
    """Regresión del refactor de `_turno`."""
    with pytest.raises(IANoDisponible, match="Conversar con el agente necesita ANTHROPIC"):
        ApuAdvisor(enabled=False).turno_chat([], con_herramientas=True)
