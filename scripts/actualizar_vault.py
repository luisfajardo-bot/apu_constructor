"""Regenera la vault de Obsidian (constructor-apus/) a partir de docs/ y la raíz
del repo.

Espejo de solo lectura: cada nota copiada lleva un aviso de cabecera. La fuente
de verdad sigue siendo docs/ y la raíz del repo. Pensado para correr en cada
commit vía .githooks/pre-commit — es determinístico e idempotente.
"""
from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

_RE_FECHA = re.compile(r"^(\d{4}-\d{2}-\d{2})-")


def titulo_desde_markdown(ruta: Path) -> str:
    """Primer encabezado `# ` del archivo; si no hay, el nombre de archivo legible."""
    texto = ruta.read_text(encoding="utf-8")
    for linea in texto.splitlines():
        linea = linea.strip()
        if linea.startswith("# "):
            return linea[2:].strip()
    return ruta.stem.replace("-", " ").replace("_", " ").strip().capitalize()


def fecha_desde_nombre(ruta: Path) -> str | None:
    """Prefijo YYYY-MM-DD del nombre de archivo, o None si no lo tiene."""
    m = _RE_FECHA.match(ruta.name)
    return m.group(1) if m else None
