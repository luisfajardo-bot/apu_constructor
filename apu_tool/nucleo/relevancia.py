"""
Orden por relevancia de una búsqueda por texto (capa núcleo, sin dependencias).

Buscar "transporte" devolvía todo lo que contuviera el string ordenado por código: el
APU llamado "TRANSPORTE" salía después de veinte que lo mencionan de paso. Acá vive el
criterio: el NIVEL (dónde aparece lo buscado) manda, y `similarity` (parecido del
nombre completo) desempata dentro del nivel.

También vive acá `similarity` (antes en `dominio/matching.py`): es una utilidad pura de
texto, la misma razón por la que `normalizar` vive en `nucleo/texto.py`. `matching.py`
la reexporta, así que sus importadores no cambian.
"""
from __future__ import annotations

from difflib import SequenceMatcher
from functools import lru_cache

from apu_tool.nucleo.texto import normalizar

MAX_RANKEO = 2000
"""Arriba de esto no se calcula el parecido: `similarity` es caro y una consulta de 1-2
letras trae miles de candidatos donde el parecido es ruido igual. Los niveles se aplican
siempre (son comparaciones de strings, gratis).

ponytail: techo de CPU, no de correctitud — arriba de acá manda el nivel y el código.
El upgrade es un índice de texto (FTS5 en SQLite / pg_trgm en Postgres)."""

_STOPWORDS = {
    "de", "la", "el", "los", "las", "del", "y", "o", "en", "para", "por", "con",
    "incluye", "incluido", "no", "un", "una", "a", "e", "su", "al", "segun",
    "tipo", "obra", "ml", "m2", "m3", "und", "un",
}


@lru_cache(maxsize=20000)
def normalize(text: str) -> str:
    return normalizar(text)


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


def palabras(q: str | None) -> list[str]:
    """Las palabras de la consulta, normalizadas. Vacío si no hay consulta."""
    return [p for p in normalize(q or "").split() if p]


def nivel(nombre: str, codigo: str, q_norm: str, palabras_q: list[str]) -> int | None:
    """Dónde aparece lo buscado. Menor = más relevante. None = no coincide.

    Los niveles 0-2 miran la consulta como FRASE; del 3 en adelante manda el AND por
    palabras (todas tienen que aparecer, en cualquier orden). El truco de rodear con
    espacios (`f" {n} "`) da el borde de palabra gratis, sin regex.
    """
    n = normalize(nombre)
    c = normalize(codigo)
    if n == q_norm or c == q_norm:
        return 0
    if n.startswith(q_norm) or c.startswith(q_norm):
        return 1
    if f" {q_norm} " in f" {n} ":
        return 2
    if any(p not in n and p not in c for p in palabras_q):
        return None
    if all(f" {p} " in f" {n} " for p in palabras_q):
        return 3
    return 4


def ordenar(filas: list, q: str | None, *, nombre_de, codigo_de) -> list:
    """Descarta las filas que no coinciden con `q` y ordena las que quedan por
    (nivel, parecido desc, código). Con `q` vacía devuelve las filas tal cual.

    `nombre_de`/`codigo_de` sacan los dos textos de cada fila, así esto sirve igual
    para un Apu y para un Insumo sin conocer ninguno de los dos.
    """
    ps = palabras(q)
    if not ps:
        return list(filas)
    q_norm = " ".join(ps)
    con_score = len(filas) <= MAX_RANKEO
    clasificadas = []
    for fila in filas:
        nombre, codigo = nombre_de(fila), codigo_de(fila)
        niv = nivel(nombre, codigo, q_norm, ps)
        if niv is None:
            continue
        score = similarity(q_norm, nombre) if con_score else 0.0
        clasificadas.append((niv, -score, normalize(codigo), fila))
    # key=x[:3] y no la tupla entera: si empatan los tres criterios, comparar las filas
    # entre sí sería un TypeError (Apu/Insumo no son ordenables).
    clasificadas.sort(key=lambda x: x[:3])
    return [x[3] for x in clasificadas]
