"""Respuestas falsas del SDK para el chat de composición. No se llama a la API real:
se sustituye `_pedir_chat_al_sdk`, la única puerta, como en los tests de `componer`."""
import json
from types import SimpleNamespace

from apu_tool.dominio.ai_assist import ApuAdvisor

USO = SimpleNamespace(input_tokens=10, output_tokens=5)


def resp_herramienta(*llamadas, prefijo="t"):
    """Una respuesta que pide herramientas: llamadas = (nombre, texto), ..."""
    bloques = [SimpleNamespace(type="tool_use", id=f"{prefijo}{i}", name=n,
                               input={"texto": t})
               for i, (n, t) in enumerate(llamadas)]
    return SimpleNamespace(stop_reason="tool_use", content=bloques, usage=USO)


def resp_final(texto="Listo.", cambios=(), stop_reason="end_turn", crudo=None):
    cuerpo = crudo if crudo is not None else json.dumps(
        {"texto": texto, "cambios": list(cambios)})
    return SimpleNamespace(stop_reason=stop_reason,
                           content=[SimpleNamespace(type="text", text=cuerpo)],
                           usage=USO)


def resp_texto(texto):
    """Respuesta final del chat de CONSULTA: texto plano, sin JSON."""
    return SimpleNamespace(stop_reason="end_turn",
                           content=[SimpleNamespace(type="text", text=texto)],
                           usage=USO)


def resp_llamada(nombre, entrada, id_="c0"):
    """Una respuesta que pide UNA herramienta con una entrada arbitraria."""
    return SimpleNamespace(
        stop_reason="tool_use", usage=USO,
        content=[SimpleNamespace(type="tool_use", id=id_, name=nombre, input=entrada)])


def componente(codigo="6092", rendimiento=1.0, funcion="herramienta"):
    return {"codigo": codigo, "tipo": "insumo", "funcion": funcion,
            "rendimiento": rendimiento, "origen": "supuesto_tecnico",
            "referencias": [], "hipotesis": [], "calculo": None,
            "justificacion": "j", "nivel_evidencia": "bajo"}


class AdvisorGuion(ApuAdvisor):
    """Devuelve las respuestas del guion en orden y anota cada llamada."""

    def __init__(self, respuestas):
        self.enabled = True
        self._client = object()
        self.model = "falso"
        self.respuestas = list(respuestas)
        self.llamadas = []

    def _pedir_chat_al_sdk(self, mensajes, con_herramientas):
        self.llamadas.append({"mensajes": list(mensajes),
                              "con_herramientas": con_herramientas})
        return self.respuestas.pop(0)

    def _pedir_consulta_al_sdk(self, mensajes, con_herramientas):
        self.llamadas.append({"mensajes": list(mensajes),
                              "con_herramientas": con_herramientas})
        return self.respuestas.pop(0)
