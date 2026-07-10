# apu_tool/dominio/alertas.py
"""
Alertas de costeo: motivos por los que un ítem necesita revisión de costo.

Regla de negocio: nada puede costar $0 (un $0 SIEMPRE es alerta). Además se
señalan cruces dudosos y sub-APUs sin composición. Vive del lado con dinero;
NUNCA entra al payload de la IA (Invariante #1).
"""
from __future__ import annotations

from apu_tool.nucleo.models import AssembledApu

_MOTIVO_CRUCE = {
    "ambiguo": "cruce ambiguo",
    "huerfano": "sin insumo en catálogo",
    "apu_vacio": "sub-APU sin composición",
    "ciclo": "ciclo de sub-APUs",
}


def alertas_costeo(a: AssembledApu) -> list[str]:
    """Motivos de revisión de costo del ítem. Lista vacía = sin alerta."""
    motivos: list[str] = []
    for c in a.componentes:
        etiqueta = f"{c.insumo_codigo} {c.insumo_nombre}".strip()
        if c.costo <= 0 or c.precio_unitario <= 0:          # regla dura: $0 siempre
            motivos.append(f"{etiqueta}: en $0")
        elif c.calidad_cruce in _MOTIVO_CRUCE:
            motivos.append(f"{etiqueta}: {_MOTIVO_CRUCE[c.calidad_cruce]}")
    if not motivos and a.costo_unitario <= 0:               # ítem sin composición / sin costo
        motivos.append("APU en $0 (sin composición o sin costo)")
    return motivos
