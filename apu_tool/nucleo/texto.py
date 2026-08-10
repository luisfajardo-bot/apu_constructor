"""
Normalización de texto compartida (capa núcleo, sin dependencias).

Una sola definición de "normalizar un nombre": sin tildes, MAYÚSCULAS, sin
puntuación, espacios colapsados. La usan el seed (para `nombre_norm`), la capa de
datos, el resolver de cruce y el chequeo de integridad. Antes estaba duplicada en
`matching.normalize` y en `integridad._norm`.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache


def _sin_tildes(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


# Es pura (mismo string -> mismo resultado siempre) y la llaman barridos que repiten
# los mismos nombres una y otra vez: el chequeo de duplicados del alta (una vuelta
# completa al índice de APUs/insumos por cada fila del archivo), el matcher y el
# cruce. Sin caché, importar 1182 APUs recorre el índice completo por fila y quema
# decenas de segundos de CPU — en el único worker de producción (WEB_CONCURRENCY=1)
# eso deja la app muda para todos mientras corre.
# ponytail: la caché está acotada por `maxsize`; sobre un catálogo con muchos más
# nombres distintos que 4096 habría churn de evicciones. Si eso llegara a importar,
# el upgrade es normalizar el índice una sola vez en el llamador en vez de por fila.
@lru_cache(maxsize=4096)
def normalizar(texto: str) -> str:
    t = _sin_tildes((texto or "").upper())
    t = re.sub(r"[^A-Z0-9 ]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t
