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

from difflib import SequenceMatcher
from functools import lru_cache

from apu_tool import config
from apu_tool.nucleo.models import LicitacionItem, MatchCandidate, MatchResult, MatchStatus
from apu_tool.nucleo.texto import normalizar as _normalizar

_STOPWORDS = {
    "de", "la", "el", "los", "las", "del", "y", "o", "en", "para", "por", "con",
    "incluye", "incluido", "no", "un", "una", "a", "e", "su", "al", "segun",
    "tipo", "obra", "ml", "m2", "m3", "und", "un",
}


@lru_cache(maxsize=20000)
def normalize(text: str) -> str:
    return _normalizar(text)


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
    """Índice de APUs para búsqueda por similaridad, filtrado por turno.

    Optimización (etapa 2): además del pool por turno, un índice invertido
    token → posiciones. Para cada consulta se puntúan SOLO los APUs que comparten
    ≥1 token (vía rápida); si el mejor de esos queda por debajo del umbral de
    REVISAR, se escanea el pool completo (respaldo) para no perder el "mejor global"
    de los ítems sin match fuerte. El resultado (estado, elegido, candidatos[0]) es
    idéntico al del escaneo completo; solo la cola de candidatos puede variar.
    """

    def __init__(self, apu_index: list[tuple[str, str, str]]):
        # (codigo, nombre, shift)
        self._by_shift: dict[str, list[tuple[str, str, frozenset[str]]]] = {}
        self._postings_by_shift: dict[str, dict[str, list[int]]] = {}
        for codigo, nombre, shift in apu_index:
            pool = self._by_shift.setdefault(shift, [])
            idx = len(pool)
            toks = _tokens(nombre)
            pool.append((codigo, nombre, toks))
            postings = self._postings_by_shift.setdefault(shift, {})
            for t in toks:
                postings.setdefault(t, []).append(idx)
        # Índice combinado (fallback de turno: si no hay APUs del turno pedido).
        self._all_pool = [x for lst in self._by_shift.values() for x in lst]
        self._all_postings: dict[str, list[int]] = {}
        for idx, (_c, _n, toks) in enumerate(self._all_pool):
            for t in toks:
                self._all_postings.setdefault(t, []).append(idx)

    @staticmethod
    def _top(scored: list[tuple[float, int, str, str]], top_n: int) -> list[MatchCandidate]:
        # Orden idéntico al escaneo completo: score desc; empates por orden del pool
        # (idx asc) — replica el sort estable sobre el pool de la versión original.
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [MatchCandidate(c, n, s) for (s, _i, c, n) in scored[:top_n]]
        # (x = (score, idx, codigo, nombre))

    def _full_scan(self, descripcion: str,
                   pool: list[tuple[str, str, frozenset[str]]], top_n: int
                   ) -> list[MatchCandidate]:
        """Escaneo completo del pool (exacto, como la versión original)."""
        scored = []
        for idx, (codigo, nombre, _toks) in enumerate(pool):
            score = round(similarity(descripcion, nombre), 4)
            if score > 0:
                scored.append((score, idx, codigo, nombre))
        return self._top(scored, top_n)

    def candidates(self, descripcion: str, shift: str, top_n: int = 5
                   ) -> list[MatchCandidate]:
        pool = self._by_shift.get(shift)
        postings = self._postings_by_shift.get(shift)
        if not pool:
            # fallback: buscar en cualquier turno si no hay del turno pedido
            pool, postings = self._all_pool, self._all_postings

        qtokens = _tokens(descripcion)
        nq = len(qtokens)
        # Cuántos tokens comparte cada APU candidato (vía índice invertido).
        shared: dict[int, int] = {}
        for t in qtokens:
            for i in postings.get(t, ()):
                shared[i] = shared.get(i, 0) + 1

        # Ramificación y poda: ordenar por jaccard desc y calcular el SequenceMatcher
        # caro solo mientras la cota superior del score (0.4·seq_max + 0.6·jaccard,
        # con seq_max=1) aún pueda superar al mejor actual. score = 0.4·seq+0.6·jac.
        cand = []
        for i, sh in shared.items():
            _c, _n, atoks = pool[i]
            jac = sh / (nq + len(atoks) - sh)   # |∩| / |∪|, idéntico al de similarity()
            cand.append((jac, i))
        cand.sort(key=lambda x: -x[0])

        scored: list[tuple[float, int, str, str]] = []
        best = 0.0
        for jac, i in cand:
            # Cota superior (seq=1). Margen 1e-4 por el redondeo a 4 decimales del score.
            if 0.4 + 0.6 * jac < best - 1e-4:
                break
            codigo, nombre, _toks = pool[i]
            score = round(similarity(descripcion, nombre), 4)
            if score > 0:
                scored.append((score, i, codigo, nombre))
                if score > best:
                    best = score

        # Garantía exacta: si el mejor con tokens en común alcanza REVISAR, ese es el
        # mejor global (un APU sin tokens comunes tiene jaccard 0 -> score ≤ 0.4 < 0.55).
        if best >= config.MATCH_REVIEW:
            return self._top(scored, top_n)
        # Débil/novedoso: el mejor global podría ser un APU sin tokens comunes (alta
        # similitud de caracteres) -> escaneo completo exacto para no perderlo.
        return self._full_scan(descripcion, pool, top_n)

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
