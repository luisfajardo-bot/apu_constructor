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

from dataclasses import asdict, dataclass
from typing import Any, Optional

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
