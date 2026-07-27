"""Mapa de arquitectura de apu_tool/: escanea los módulos reales y genera un
diagrama de dependencias entre paquetes + el detalle de archivos por paquete.

Analiza el código con `ast` (no regex): responsabilidad = primera línea del
docstring del módulo; dependencias = imports `from apu_tool.X.Y import ...`
absolutos (el proyecto no usa imports relativos, verificado). Puro,
determinístico, sin dependencias nuevas — pensado para correr en cada commit
junto al resto de la vault (ver actualizar_vault.py).
"""
from __future__ import annotations

import ast
from pathlib import Path

PAQUETES = ("nucleo", "datos", "dominio", "servicio", "interfaz")


def responsabilidad_de_modulo(ruta: Path) -> str:
    """Primera línea del docstring del módulo; fallback al nombre de archivo legible."""
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    docstring = ast.get_docstring(arbol)
    if docstring:
        primera_linea = docstring.strip().splitlines()[0].strip()
        if primera_linea:
            return primera_linea
    return ruta.stem.replace("_", " ").capitalize()


def imports_internos(ruta: Path) -> list[str]:
    """Módulos `apu_tool.*` importados de forma absoluta por este archivo."""
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    encontrados = []
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.ImportFrom) and nodo.level == 0 and nodo.module:
            if nodo.module == "apu_tool" or nodo.module.startswith("apu_tool."):
                encontrados.append(nodo.module)
    return encontrados


def paquete_de_modulo(modulo_dotted: str) -> str:
    """Paquete de primer nivel bajo apu_tool/, o "raíz" si no está en ninguno."""
    partes = modulo_dotted.split(".")
    if len(partes) >= 2 and partes[1] in PAQUETES:
        return partes[1]
    return "raíz"
