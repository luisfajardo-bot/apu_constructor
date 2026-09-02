"""
Capa de IA acotada para COMPONER la estructura de un APU, a pedido.

Qué hace la IA acá:
  - Para una actividad sin APU adecuado en la biblioteca, y SOLO cuando el usuario
    lo pide explícitamente (`Assembler.generar_composicion`, endpoint de componer),
    propone una composición: qué insumos y con qué rendimiento. Es una PROPUESTA;
    se confirma por el alta normal de APUs, nadie la costea a espaldas del usuario.

Qué NO hace la IA:
  - No participa del armado de corridas. El armado es determinístico (assemble.py):
    elige entre los APUs del histórico o deja la fila SIN APU, nunca inventa.
  - No ve precios, costos ni totales (ver privacy.py). Recibe únicamente
    actividades, insumos, unidades y rendimientos.
  - No calcula dinero. El costo lo arma el motor determinístico (pricing.py).

La auditoría de una corrida YA armada vive aparte, en `dominio/revision.py`.

Sin credenciales (ANTHROPIC_API_KEY) `compose_apu` devuelve None y el ítem queda
manual: el programa nunca depende de la IA para correr.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from apu_tool import config
from apu_tool.dominio import privacy
from apu_tool.dominio.compose import CandidateInsumo, candidate_insumo_to_dict
from apu_tool.nucleo.models import DePricedApu, LicitacionItem


@dataclass
class ComposedComponent:
    insumo_codigo: str
    rendimiento: float


@dataclass
class ComposeResult:
    componentes: list[ComposedComponent]
    justificacion: str
    confianza: float


_COMPOSE_SYSTEM = """\
Eres un ingeniero de costos de obra civil. Te dan una ACTIVIDAD nueva (sin un APU
histórico adecuado), una lista de INSUMOS disponibles (con código, nombre y unidad)
y algunos APUs de actividades parecidas como ejemplo (con sus insumos y rendimientos).

Tu tarea: armar la composición del APU de la actividad, eligiendo insumos de la lista
disponible y asignando a cada uno un RENDIMIENTO (cantidad de insumo por unidad de la
actividad) con criterio técnico, guiándote por los ejemplos.

Reglas estrictas:
- Usa ÚNICAMENTE códigos de insumo que estén en la lista de insumos disponibles.
- NUNCA recibirás precios ni costos, y no debes inventarlos ni pedirlos.
- Incluye típicamente mano de obra (cuadrilla), equipo/herramienta y materiales según
  corresponda a la actividad. Entre 2 y 12 insumos.
- Los rendimientos deben ser cantidades físicas razonables por unidad de la actividad.

Responde EXCLUSIVAMENTE con un JSON válido con este esquema:
{"componentes": [{"insumo_codigo": <string>, "rendimiento": <number>}],
 "confianza": <number 0..1>, "justificacion": <string corto>}
"""

_COMPOSE_SCHEMA = {
    "type": "object",
    "properties": {
        "componentes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "insumo_codigo": {"type": "string"},
                    "rendimiento": {"type": "number"},
                },
                "required": ["insumo_codigo", "rendimiento"],
                "additionalProperties": False,
            },
        },
        "confianza": {"type": "number"},
        "justificacion": {"type": "string"},
    },
    "required": ["componentes", "confianza", "justificacion"],
    "additionalProperties": False,
}


class ApuAdvisor:
    """Fachada sobre la IA. Sin credenciales, `compose_apu` devuelve None."""

    def __init__(self, enabled: Optional[bool] = None, model: str = config.AI_MODEL):
        self.model = model
        self.enabled = config.ai_available() if enabled is None else enabled
        self._client = None
        if self.enabled:
            try:
                import anthropic
                self._client = anthropic.Anthropic()
            except Exception:
                self.enabled = False  # sin SDK -> compose_apu devuelve None

    def compose_apu(
        self,
        item: LicitacionItem,
        insumos: list[CandidateInsumo],
        ejemplos: list[DePricedApu],
    ) -> Optional[ComposeResult]:
        """Compone un APU desde cero para una actividad nueva.

        Devuelve None si la IA no está disponible (en ese caso el ítem queda manual).
        Los rendimientos los pone la IA; los precios NO los ve.
        """
        if not (self.enabled and self._client is not None) or not insumos:
            return None
        codigos_validos = {i.codigo for i in insumos}
        payload = {
            "actividad": privacy.licitacion_item_to_dict(item),
            "insumos_disponibles": [candidate_insumo_to_dict(i) for i in insumos],
            "ejemplos": [privacy.depriced_apu_to_dict(a) for a in ejemplos],
        }
        try:
            user_content = privacy.safe_json(payload)  # garantía: sin dinero
            resp = self._client.messages.create(
                model=self.model,
                # Techo, no gasto: cubre el pensamiento adaptativo MÁS el JSON.
                # Si queda corto, el JSON sale truncado y se pierde la respuesta.
                max_tokens=16000,
                system=_COMPOSE_SYSTEM,
                thinking={"type": "adaptive"},
                output_config={
                    "effort": "medium",
                    "format": {"type": "json_schema", "schema": _COMPOSE_SCHEMA},
                },
                messages=[{"role": "user", "content": user_content}],
            )
            text = next((b.text for b in resp.content if b.type == "text"), "{}")
            data = json.loads(text)
        except Exception:
            return None

        comps: list[ComposedComponent] = []
        for c in data.get("componentes", []):
            cod = str(c.get("insumo_codigo", "")).strip()
            rend = float(c.get("rendimiento", 0) or 0)
            if cod in codigos_validos and rend > 0:
                comps.append(ComposedComponent(cod, rend))
        if not comps:
            return None
        return ComposeResult(
            componentes=comps,
            justificacion=str(data.get("justificacion", "")).strip(),
            confianza=float(data.get("confianza", 0.0)),
        )
