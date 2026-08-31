"""
Revisión con IA de una corrida YA armada.

La IA no arma: audita. Recibe la corrida completa (sin dinero) y dice, por fila, si
el APU asignado le parece bien, dudoso, cambiable por otro candidato, o si para esa
actividad no hay nada en la biblioteca. **Propone; nunca aplica.** Quien aplica es
el usuario, con `confirmar_items`.

Dos pasos, por costo y por foco:
  1. BARRIDO   — lotes de filas, sin composiciones. Cada lote lleva además el índice
                 de la corrida entera, así la IA ve el presupuesto como un todo y
                 puede detectar incoherencias entre líneas. Devuelve ok | revisar.
  2. PROFUNDIZACIÓN — solo las marcadas `revisar`. Una llamada por fila, ahora con la
                 composición completa (insumos, rendimientos, unidades) del APU
                 asignado y de cada candidato.

Invariante #1: todo lo que sale de acá pasa por `privacy.safe_json`. En particular
NO va el `precio_contractual` del ítem (lo omite `licitacion_item_to_dict`) ni el
`score` del matcher: darle la nota del fuzzy hace que la copie en vez de pensar.

Sin `ANTHROPIC_API_KEY` no hay fallback determinístico, a propósito: un revisor
determinístico sería el matcher auditándose a sí mismo.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Optional

from apu_tool import config
from apu_tool.dominio import privacy
from apu_tool.nucleo.models import CorridaItemRow, DePricedApu

# Filas por llamada del barrido. Bajarlo mejora el foco de la IA y sube el costo;
# subirlo hace lo contrario. Es la palanca si al barrido se le escapan objeciones.
TAM_LOTE = 25

DICTAMENES = ("ok", "dudoso", "cambiar", "sin_apu")


@dataclass(frozen=True)
class Veredicto:
    seq: int
    dictamen: str                    # ok | dudoso | cambiar | sin_apu
    apu_sugerido: Optional[str]
    turno_sugerido: Optional[str]
    confianza: float
    justificacion: str
    nivel: str                       # barrido | profundo

    def to_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------ payloads
def payload_barrido(fila: CorridaItemRow) -> dict[str, Any]:
    """Una fila para el barrido: sin composiciones y SIN el score del matcher."""
    return {
        "seq": fila.seq,
        "actividad": privacy.licitacion_item_to_dict(fila.item),
        "apu_asignado": (None if not fila.apu_codigo else {
            "codigo": fila.apu_codigo,
            "nombre": fila.apu_nombre,
            "unidad": fila.unidad,
            "shift": fila.shift,
        }),
        # Los candidatos de la fila vienen del matcher y traen `score`/`motivo`:
        # se copian clave por clave, nunca en bloque.
        "candidatos": [{"codigo": c.get("apu_codigo"), "nombre": c.get("apu_nombre")}
                       for c in (fila.candidatos or [])],
    }


def indice_corrida(filas: list[CorridaItemRow]) -> list[dict[str, Any]]:
    """El presupuesto entero en una línea por ítem: contexto para ver incoherencias
    entre filas (dos actividades gemelas con APUs distintos)."""
    return [{"seq": f.seq, "descripcion": f.item.descripcion,
             "unidad": f.unidad, "apu": f.apu_codigo or None} for f in filas]


def payload_profundo(fila: CorridaItemRow, asignado: Optional[DePricedApu],
                     candidatos: list[DePricedApu]) -> dict[str, Any]:
    """Una fila con TODA la estructura: composiciones del asignado y de cada candidato.

    Los APUs entran como `DePricedApu` (no como la composición costeada de la corrida,
    que sí lleva precio_unitario/costo): la frontera está en el tipo.
    """
    return {
        "seq": fila.seq,
        "actividad": privacy.licitacion_item_to_dict(fila.item),
        "apu_asignado": (None if asignado is None
                         else privacy.depriced_apu_to_dict(asignado)),
        "candidatos": [privacy.depriced_apu_to_dict(a) for a in candidatos],
    }


# ------------------------------------------------------------------- revisor
class IANoDisponible(RuntimeError):
    """No hay ANTHROPIC_API_KEY (o falta el SDK). La revisión no tiene fallback:
    un revisor determinístico sería el matcher auditándose a sí mismo."""


_SISTEMA_BARRIDO = """\
Eres un ingeniero de costos de obra civil auditando un presupuesto YA armado por un
programa determinístico. Para cada ACTIVIDAD te dan el APU que el programa le asignó
y los candidatos que descartó. Además recibes el ÍNDICE de todo el presupuesto.

Tu tarea: decir por cada fila si el APU asignado es razonable ("ok") o si merece un
análisis a fondo ("revisar").

Marca "revisar" cuando:
- la unidad del APU no cuadra con la de la actividad;
- el tipo de trabajo difiere (manual vs mecánico, suministro vs instalación);
- la actividad no tiene APU asignado;
- dos filas del índice describen la misma actividad pero tienen APUs distintos;
- un candidato descartado encaja claramente mejor que el asignado.

Reglas:
- NUNCA recibirás precios ni costos, y no debes inventarlos ni pedirlos.
- Responde por TODAS las filas del lote, usando su `seq` exacto.
- Ante la duda, marca "revisar": el paso siguiente mira a fondo y corrige.

Responde EXCLUSIVAMENTE con un JSON válido con este esquema:
{"filas": [{"seq": <int>, "resultado": "ok"|"revisar"}]}
"""

_ESQUEMA_BARRIDO = {
    "type": "object",
    "properties": {
        "filas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "seq": {"type": "integer"},
                    "resultado": {"type": "string", "enum": ["ok", "revisar"]},
                },
                "required": ["seq", "resultado"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["filas"],
    "additionalProperties": False,
}


class Revisor:
    """Fachada sobre la IA para la revisión. Sin fallback determinístico.

    `_pedir` es la ÚNICA puerta al SDK: los tests heredan de esta clase y la
    sustituyen, así no hace falta simular el cliente de anthropic.
    """

    def __init__(self, enabled: Optional[bool] = None, model: str = config.AI_MODEL):
        self.model = model
        self.enabled = config.ai_available() if enabled is None else enabled
        self._client = None
        # Filas de las que la IA no dijo nada (lote truncado o JSON inválido). No se
        # dan por buenas: quedan sin veredicto y se reportan.
        self.sin_respuesta: set[int] = set()
        if self.enabled:
            try:
                import anthropic
                self._client = anthropic.Anthropic()
            except Exception:
                self.enabled = False

    @property
    def disponible(self) -> bool:
        return bool(self.enabled)

    # ------------------------------------------------------------ puerta al SDK
    def _pedir(self, system: str, schema: dict, payload: dict, effort: str) -> dict:
        """Una llamada a la IA. Devuelve el JSON ya parseado, o {} si falló."""
        if self._client is None:
            raise IANoDisponible("La revisión con IA necesita ANTHROPIC_API_KEY.")
        contenido = privacy.safe_json(payload)   # garantía dura: sin dinero
        resp = self._client.messages.create(
            model=self.model,
            # Techo, no gasto: cubre el pensamiento adaptativo MÁS el JSON.
            max_tokens=16000,
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": effort,
                           "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": contenido}],
        )
        texto = next((b.text for b in resp.content if b.type == "text"), "{}")
        try:
            return json.loads(texto)
        except Exception:
            return {}    # JSON truncado o inválido: nadie queda en "ok" por accidente

    # ------------------------------------------------------------------ barrido
    def barrer(self, filas: list[CorridaItemRow]) -> set[int]:
        """Devuelve los seq que merecen profundización. Deja en `self.sin_respuesta`
        los que la IA no contestó: esos NO se dan por buenos."""
        if not self.disponible:
            raise IANoDisponible("La revisión con IA necesita ANTHROPIC_API_KEY.")
        self.sin_respuesta = set()
        indice = indice_corrida(filas)
        marcadas: set[int] = set()
        for i in range(0, len(filas), TAM_LOTE):
            lote = filas[i:i + TAM_LOTE]
            payload = {"indice": indice,
                       "filas": [payload_barrido(f) for f in lote]}
            data = self._pedir(_SISTEMA_BARRIDO, _ESQUEMA_BARRIDO, payload, "low")
            vistos = set()
            for r in (data or {}).get("filas", []):
                try:
                    seq = int(r.get("seq"))
                except (TypeError, ValueError):
                    continue
                vistos.add(seq)
                if str(r.get("resultado")) == "revisar":
                    marcadas.add(seq)
            self.sin_respuesta |= {f.seq for f in lote if f.seq not in vistos}
        return marcadas
