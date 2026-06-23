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


def _sin_tildes(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def normalizar(texto: str) -> str:
    t = _sin_tildes((texto or "").upper())
    t = re.sub(r"[^A-Z0-9 ]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t
