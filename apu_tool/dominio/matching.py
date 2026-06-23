"""
Matcher determinístico de actividades contra el catálogo de APUs.

No usa IA ni dinero: compara la descripción de cada ítem de licitación contra los
nombres de los APUs históricos, filtrando por turno. Devuelve candidatos
ordenados por similaridad. La decisión sobre los dudosos la toma luego la IA o el
usuario (ver assemble.py).

Algoritmo: normalización (mayúsculas, sin tildes, sin stopwords) + combinación de
similaridad de secuencia (difflib) y similaridad de tokens (Jaccard). Sin
dependencias externas para que corra en cualquier máquina.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from functools import lru_cache

from apu_tool import config
from apu_tool.nucleo.models import LicitacionItem, MatchCandidate, MatchResult, MatchStatus

_STOPWORDS = {
    "de", "la", "el", "los", "las", "del", "y", "o", "en", "para", "por", "con",
    "incluye", "incluido", "no", "un", "una", "a", "e", "su", "al", "segun",
    "tipo", "obra", "ml", "m2", "m3", "und", "un",
}


def _strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )


@lru_cache(maxsize=20000)
def normalize(text: str) -> str:
    text = _strip_accents((text or "").upper())
    text = re.sub(r"[^A-Z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _tokens(text: str) -> frozenset[str]:
    return frozenset(
        t for t in normalize(text).split() if t and t.lower() not in _STOPWORDS
    )


def similarity(a: str, b: str) -> float:
    """Similaridad 0..1 combinando secuencia y tokens."""
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    seq = SequenceMatcher(None, na, nb).ratio()
    ta, tb = _tokens(a), _tokens(b)
    if ta and tb:
        jaccard = len(ta & tb) / len(ta | tb)
    else:
        jaccard = 0.0
    # Peso mayor a tokens: el orden de palabras varía mucho en obra civil.
    return 0.4 * seq + 0.6 * jaccard


class Matcher:
    """Índice de APUs para búsqueda por similaridad, filtrado por turno."""

    def __init__(self, apu_index: list[tuple[str, str, str]]):
        # (codigo, nombre, shift)
        self._by_shift: dict[str, list[tuple[str, str, frozenset[str]]]] = {}
        for codigo, nombre, shift in apu_index:
            self._by_shift.setdefault(shift, []).append((codigo, nombre, _tokens(nombre)))

    def candidates(self, descripcion: str, shift: str, top_n: int = 5
                   ) -> list[MatchCandidate]:
        pool = self._by_shift.get(shift, [])
        if not pool:
            # fallback: buscar en cualquier turno si no hay del turno pedido
            pool = [x for lst in self._by_shift.values() for x in lst]
        query_tokens = _tokens(descripcion)
        scored: list[MatchCandidate] = []
        for codigo, nombre, _toks in pool:
            score = similarity(descripcion, nombre)
            if score > 0:
                scored.append(MatchCandidate(codigo, nombre, round(score, 4)))
        scored.sort(key=lambda c: c.score, reverse=True)
        return scored[:top_n]

    def match(self, item: LicitacionItem) -> MatchResult:
        cands = self.candidates(item.descripcion, item.shift)
        if not cands:
            return MatchResult(item=item, status=MatchStatus.NEW, candidatos=[],
                               explicacion="Sin candidatos en el histórico.")
        best = cands[0]
        if best.score >= config.MATCH_ACCEPT:
            return MatchResult(
                item=item, status=MatchStatus.AUTO, elegido=best, candidatos=cands,
                confianza=best.score,
                explicacion=f"Coincidencia directa (similaridad {best.score:.0%}).",
            )
        if best.score >= config.MATCH_REVIEW:
            return MatchResult(
                item=item, status=MatchStatus.REVIEW, candidatos=cands,
                confianza=best.score,
                explicacion=f"Candidato dudoso (mejor similaridad {best.score:.0%}). "
                            f"Requiere confirmación.",
            )
        return MatchResult(
            item=item, status=MatchStatus.NEW, candidatos=cands,
            confianza=best.score,
            explicacion=f"Sin coincidencia fuerte (mejor {best.score:.0%}). "
                        f"Armar por analogía o manual.",
        )
