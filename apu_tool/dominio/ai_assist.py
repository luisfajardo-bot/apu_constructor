"""
Capa de IA acotada para decidir la ESTRUCTURA de los APUs.

Qué hace la IA:
  - Para ítems dudosos o nuevos, elige cuál APU del histórico es el más adecuado
    como base (por afinidad técnica de la actividad y de sus insumos), con un nivel
    de confianza y una justificación corta.

Qué NO hace la IA:
  - No ve precios, costos ni totales (ver privacy.py). Recibe únicamente
    actividades, insumos, unidades y rendimientos.
  - No calcula dinero. El costo lo arma el motor determinístico (pricing.py) a
    partir del APU que la IA eligió.

Si no hay credenciales (ANTHROPIC_API_KEY) o falla la llamada, se usa un fallback
determinístico basado en el matcher. El programa nunca depende de la IA para correr.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from apu_tool import config
from apu_tool.dominio import privacy
from apu_tool.dominio.compose import CandidateInsumo, candidate_insumo_to_dict
from apu_tool.nucleo.models import DePricedApu, LicitacionItem, MatchCandidate

_SYSTEM_PROMPT = """\
Eres un ingeniero de costos de obra civil. Te dan una ACTIVIDAD de una licitación y
una lista de APUs candidatos del histórico de la empresa (cada uno con su unidad y su
composición de insumos con rendimientos). Tu tarea es elegir cuál APU candidato es la
mejor base para armar el APU de la actividad, por afinidad técnica.

Reglas:
- Decides SOLO con base en la actividad, las unidades, los insumos y los rendimientos.
- NUNCA recibirás precios ni costos, y no debes inventarlos ni pedirlos.
- Si ningún candidato es razonable, devuelve apu_codigo = null.
- Prefiere coincidencia de unidad y de tipo de trabajo (excavación, concreto, etc.).

Responde EXCLUSIVAMENTE con un JSON válido con este esquema:
{"apu_codigo": <string|null>, "confianza": <number 0..1>, "justificacion": <string corto>}
"""

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "apu_codigo": {"type": ["string", "null"]},
        "confianza": {"type": "number"},
        "justificacion": {"type": "string"},
    },
    "required": ["apu_codigo", "confianza", "justificacion"],
    "additionalProperties": False,
}


@dataclass
class AIDecision:
    apu_codigo: Optional[str]
    confianza: float
    justificacion: str
    fuente: str  # "ia" o "deterministico"


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
    """Fachada sobre la IA con fallback determinístico."""

    def __init__(self, enabled: Optional[bool] = None, model: str = config.AI_MODEL):
        self.model = model
        self.enabled = config.ai_available() if enabled is None else enabled
        self._client = None
        if self.enabled:
            try:
                import anthropic
                self._client = anthropic.Anthropic()
            except Exception:
                self.enabled = False  # sin SDK -> fallback

    # ------------------------------------------------------------------ API
    def choose_apu(
        self,
        item: LicitacionItem,
        candidatos: list[MatchCandidate],
        depriced_apus: dict[str, DePricedApu],
    ) -> AIDecision:
        """Elige el mejor APU base. `depriced_apus` mapea codigo -> composición SIN dinero."""
        if not candidatos:
            return AIDecision(None, 0.0, "Sin candidatos.", "deterministico")

        if self.enabled and self._client is not None:
            try:
                return self._choose_with_ai(item, candidatos, depriced_apus)
            except Exception as exc:  # cualquier fallo -> fallback, nunca rompe
                dec = self._choose_deterministic(candidatos)
                dec.justificacion += f" (IA no disponible: {type(exc).__name__})"
                return dec
        return self._choose_deterministic(candidatos)

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
                max_tokens=1500,
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

    # --------------------------------------------------------------- interno
    def _choose_deterministic(self, candidatos: list[MatchCandidate]) -> AIDecision:
        best = candidatos[0]
        return AIDecision(
            apu_codigo=best.apu_codigo, confianza=best.score,
            justificacion=f"Mejor similaridad de nombre ({best.score:.0%}).",
            fuente="deterministico",
        )

    def _choose_with_ai(
        self,
        item: LicitacionItem,
        candidatos: list[MatchCandidate],
        depriced_apus: dict[str, DePricedApu],
    ) -> AIDecision:
        payload = {
            "actividad": privacy.licitacion_item_to_dict(item),
            "candidatos": [
                privacy.depriced_apu_to_dict(depriced_apus[c.apu_codigo])
                for c in candidatos
                if c.apu_codigo in depriced_apus
            ],
        }
        # Verificación dura: si esto contuviera dinero, lanza PrivacyViolation.
        user_content = privacy.safe_json(payload)

        resp = self._client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            thinking={"type": "adaptive"},
            output_config={
                "effort": "medium",
                "format": {"type": "json_schema", "schema": _RESPONSE_SCHEMA},
            },
            messages=[{"role": "user", "content": user_content}],
        )
        text = next((b.text for b in resp.content if b.type == "text"), "{}")
        data = json.loads(text)
        cod = data.get("apu_codigo")
        return AIDecision(
            apu_codigo=str(cod) if cod else None,
            confianza=float(data.get("confianza", 0.0)),
            justificacion=str(data.get("justificacion", "")).strip(),
            fuente="ia",
        )
