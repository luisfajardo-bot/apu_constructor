# apu_tool/dominio/alertas.py
"""
Alertas de costeo: motivos por los que un ítem necesita revisión de costo.

Regla de negocio: nada puede costar $0 (un $0 SIEMPRE es alerta). Además se
señalan cruces dudosos y sub-APUs sin composición. Vive del lado con dinero;
NUNCA entra al payload de la IA (Invariante #1).
"""
from __future__ import annotations

from apu_tool.nucleo.models import (
    AssembledApu, MatchStatus, CALIDAD_SIN_PRECIO_CATALOGO, CALIDAD_SIN_PRECIO_LISTA,
)

_MOTIVO_CRUCE = {
    "ambiguo": "cruce ambiguo",
    "huerfano": "sin insumo en catálogo",
    "apu_vacio": "sub-APU sin composición",
    "ciclo": "ciclo de sub-APUs",
    CALIDAD_SIN_PRECIO_CATALOGO: "sin precio en el catálogo",
}


def alertas_costeo(a: AssembledApu, sin_distancia: tuple[str, ...] = ()) -> list[str]:
    """Motivos de revisión de costo del ítem. Lista vacía = sin alerta.

    `sin_distancia`: códigos de componentes de acarreo que el proyecto NO pudo
    reescalar por falta de clasificación (los reporta `PricingEngine.sin_distancia`).
    Se avisa en vez de costear con la distancia equivocada en silencio."""
    motivos: list[str] = []
    pendientes = set(sin_distancia)
    reportados: set[str] = set()
    for c in a.componentes:
        etiqueta = f"{c.insumo_codigo} {c.insumo_nombre}".strip()
        # Va ANTES de la regla del $0 para dar el motivo accionable en vez del genérico.
        # Solo puede aparecer costeando contra una lista distinta de Principal, así que
        # el camino histórico (Principal) queda idéntico.
        if c.calidad_cruce == CALIDAD_SIN_PRECIO_LISTA:
            motivos.append(f"{etiqueta}: sin precio en la lista")
        elif c.costo <= 0 or c.precio_unitario <= 0:        # regla dura: $0 siempre
            motivos.append(f"{etiqueta}: en $0")
        elif c.insumo_codigo in pendientes:
            motivos.append(f"{etiqueta}: distancia del proyecto no aplicada")
            reportados.add(c.insumo_codigo)
        elif c.calidad_cruce in _MOTIVO_CRUCE:
            motivos.append(f"{etiqueta}: {_MOTIVO_CRUCE[c.calidad_cruce]}")
    # Un pendiente que vive DENTRO de un sub-APU (el caso del botadero) no aparece
    # entre los componentes del ítem, así que el bucle no lo ve. Sin esto, el ítem se
    # costearía con la distancia de la biblioteca y nadie se enteraría.
    for cod in sin_distancia:
        if cod not in reportados:
            motivos.append(f"{cod}: distancia del proyecto no aplicada (en un sub-APU)")
            reportados.add(cod)
    if not motivos and a.costo_unitario <= 0:               # ítem sin composición / sin costo
        motivos.append("APU en $0 (sin composición o sin costo)")
    return motivos


def filas_alertadas(apus: list[AssembledApu]) -> list[tuple[AssembledApu, list[str]]]:
    """Ítems a incluir en la hoja ALERTAS: en revisión/manual, o con alerta de costeo."""
    filas = [(a, alertas_costeo(a)) for a in apus]
    return [(a, ac) for a, ac in filas
            if a.status in (MatchStatus.REVIEW, MatchStatus.NEW) or ac]


def motivo_alerta(a: AssembledApu, ac: list[str]) -> str:
    """Combina la explicación del match con el motivo de costeo (si hay)."""
    motivo = a.explicacion
    if ac:
        motivo = (motivo + " | " if motivo else "") + "Costeo: " + "; ".join(ac)
    return motivo
