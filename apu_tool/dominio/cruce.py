"""
Resolución del cruce insumo-de-APU -> insumo-de-catálogo, por código + nombre.

Un código puede no ser único en el catálogo (el IDU repite códigos para insumos
distintos). Este resolver recibe los candidatos de un código y el nombre que el APU
cita, y decide cuál es —o avisa que no se puede resolver con confianza—.

Sin dinero: solo compara nombres. Lo usan el motor de costos y el chequeo de integridad.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from apu_tool import config
from apu_tool.dominio.matching import similarity
from apu_tool.nucleo.models import Insumo
from apu_tool.nucleo.texto import normalizar


class CalidadCruce(str, Enum):
    EXACTO = "exacto"          # código coincide y nombre normalizado idéntico
    APROXIMADO = "aproximado"  # código coincide y un nombre destaca por similitud
    AMBIGUO = "ambiguo"        # código coincide pero el nombre no resuelve a uno solo
    HUERFANO = "huerfano"      # ningún insumo tiene ese código


@dataclass(frozen=True)
class ResultadoCruce:
    insumo: Optional[Insumo]   # None si AMBIGUO o HUERFANO
    calidad: CalidadCruce
    score: float               # similitud del mejor candidato (0..1)


def resolver(candidatos: list[Insumo], nombre_apu: str) -> ResultadoCruce:
    if not candidatos:
        return ResultadoCruce(None, CalidadCruce.HUERFANO, 0.0)

    objetivo = normalizar(nombre_apu)
    # 1) Coincidencia exacta de nombre normalizado (única por UNIQUE(codigo, nombre_norm)).
    for c in candidatos:
        if normalizar(c.nombre) == objetivo:
            return ResultadoCruce(c, CalidadCruce.EXACTO, 1.0)

    # 2) Mejor coincidencia difusa, con margen sobre el segundo.
    puntuados = sorted(
        ((similarity(nombre_apu, c.nombre), c) for c in candidatos),
        key=lambda t: t[0], reverse=True,
    )
    mejor_score, mejor = puntuados[0]
    segundo_score = puntuados[1][0] if len(puntuados) > 1 else 0.0
    if mejor_score >= config.CRUCE_UMBRAL and (mejor_score - segundo_score) >= config.CRUCE_MARGEN:
        return ResultadoCruce(mejor, CalidadCruce.APROXIMADO, mejor_score)
    return ResultadoCruce(None, CalidadCruce.AMBIGUO, mejor_score)
