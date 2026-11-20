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
from typing import Optional, Sequence

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


def elegir(nombres: Sequence[str], objetivo: str
           ) -> tuple[Optional[int], CalidadCruce, float]:
    """Cuál de `nombres` (las filas de UN código, en orden de id) es `objetivo`.

    Devuelve (índice o None, calidad, score). Es la única regla de elección por nombre
    del repo: la usan el costeo (`resolver`), el alta de APUs, el validador de
    composición, la ficha de la mesa y el chat. Recibe nombres y no `Insumo` porque el
    validador de composición no tiene `Insumo` (lleva `precio`) y no debe tenerlo."""
    if not nombres:
        return None, CalidadCruce.HUERFANO, 0.0
    obj = normalizar(objetivo)
    # 1) Coincidencia exacta de nombre normalizado (única por UNIQUE(codigo, nombre_norm)).
    for i, n in enumerate(nombres):
        if normalizar(n) == obj:
            return i, CalidadCruce.EXACTO, 1.0
    # 2) Mejor coincidencia difusa, con margen sobre el segundo. `sorted` es estable:
    #    a igual score gana el de id menor, como antes.
    puntuados = sorted(((similarity(objetivo, n), i) for i, n in enumerate(nombres)),
                       key=lambda t: t[0], reverse=True)
    mejor_score, mejor = puntuados[0]
    segundo_score = puntuados[1][0] if len(puntuados) > 1 else 0.0
    if mejor_score >= config.CRUCE_UMBRAL and (mejor_score - segundo_score) >= config.CRUCE_MARGEN:
        return mejor, CalidadCruce.APROXIMADO, mejor_score
    return None, CalidadCruce.AMBIGUO, mejor_score


def resolver(candidatos: list[Insumo], nombre_apu: str) -> ResultadoCruce:
    i, calidad, score = elegir([c.nombre for c in candidatos], nombre_apu)
    return ResultadoCruce(candidatos[i] if i is not None else None, calidad, score)


def elegir_fila(candidatos: list[Insumo], nombre: str) -> Optional[Insumo]:
    """La fila que se ESCRIBE para (código, nombre). Un solo candidato es ese, sin
    mirar el nombre (el alta de siempre); con dos o más decide `elegir`, y None
    quiere decir que el nombre no alcanza: hay que preguntarle al ingeniero."""
    if len(candidatos) <= 1:
        return candidatos[0] if candidatos else None
    i, _calidad, _score = elegir([c.nombre for c in candidatos], nombre)
    return candidatos[i] if i is not None else None


def opciones(candidatos: list[Insumo]) -> list[dict]:
    """Las filas de un código compartido, para que el ingeniero escoja. Campo por
    campo: `Insumo` lleva `precio` y esto viaja por la API de composición."""
    return [{"nombre": c.nombre, "unidad": c.unidad, "oculto": c.oculto}
            for c in candidatos]


def ficha(candidatos: list[Insumo], nombre: str) -> dict:
    """Nombre, unidad y grupo de la fila que corresponde a `nombre` (vacíos si no
    resuelve) y, si el código es compartido, las `opciones`. Sin dinero."""
    f = elegir_fila(candidatos, nombre)
    out = ({"nombre": f.nombre, "unidad": f.unidad, "grupo": f.grupo} if f
           else {"nombre": "", "unidad": "", "grupo": ""})
    if len(candidatos) > 1:
        out["opciones"] = opciones(candidatos)
    return out


def compartidos(catalogo: dict[str, list[Insumo]]) -> dict[str, tuple[tuple[str, str], ...]]:
    """(nombre, unidad) de cada código con dos o más filas, a partir de lo que devuelve
    `get_candidatos_bulk`. Es lo que necesita el validador de composición, sin dinero."""
    return {cod: tuple((c.nombre, c.unidad) for c in cands)
            for cod, cands in catalogo.items() if len(cands) > 1}
