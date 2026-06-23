"""
Correcciones de código aplicadas al semillar (normalización mínima).

El histórico cita códigos de insumo que en el catálogo significan otra cosa. Aquí se
remapean al código correcto del catálogo. Arranca con el descalce confirmado del 4613:
la composición lo usa como "transporte y disposición final", pero 4613 en precios es
"UNIÓN PVC D=10"; el código correcto del transporte (diurno) es 3017.
"""
from __future__ import annotations

from dataclasses import replace
from apu_tool.nucleo.models import ApuComponent

CORRECCIONES_CODIGO: dict[str, str] = {
    "4613": "3017",   # transporte y disposición final (diurno)
}


def aplicar(comps: list[ApuComponent]) -> list[ApuComponent]:
    """Devuelve la lista con insumo_codigo remapeado según CORRECCIONES_CODIGO."""
    out = []
    for c in comps:
        nuevo = CORRECCIONES_CODIGO.get(c.insumo_codigo)
        out.append(replace(c, insumo_codigo=nuevo) if nuevo else c)
    return out
