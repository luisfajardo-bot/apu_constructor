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


def escanear_apu_tool(apu_tool_dir: Path) -> list[dict]:
    """Escanea todos los .py de apu_tool/ (excepto __init__.py), recursivo."""
    registros = []
    for ruta in sorted(apu_tool_dir.rglob("*.py")):
        if ruta.name == "__init__.py":
            continue
        relativo = ruta.relative_to(apu_tool_dir)
        modulo = "apu_tool." + ".".join(relativo.with_suffix("").parts)
        paquete = paquete_de_modulo(modulo)
        if paquete == "raíz":
            archivo = relativo.as_posix()
        else:
            partes_dentro = relativo.with_suffix("").parts[1:]
            archivo = "/".join(partes_dentro) + ".py"
        imports = [m for m in imports_internos(ruta) if m != modulo]
        registros.append({
            "modulo": modulo,
            "archivo": archivo,
            "paquete": paquete,
            "responsabilidad": responsabilidad_de_modulo(ruta),
            "imports": imports,
        })
    return registros


def dependencias_entre_paquetes(registros: list[dict]) -> list[tuple[str, str]]:
    """Aristas (paquete_origen, paquete_destino) deduplicadas y ordenadas,
    sin aristas de un paquete hacia sí mismo."""
    aristas = set()
    for registro in registros:
        origen = registro["paquete"]
        for modulo_importado in registro["imports"]:
            destino = paquete_de_modulo(modulo_importado)
            if destino != origen:
                aristas.add((origen, destino))
    return sorted(aristas)


def diagrama_mermaid(aristas: list[tuple[str, str]]) -> str:
    lineas = ["```mermaid", "flowchart TD"]
    for origen, destino in aristas:
        lineas.append(f"    {origen} --> {destino}")
    lineas.append("```")
    return "\n".join(lineas) + "\n"


def seccion_paquete(nombre_paquete: str, registros: list[dict]) -> str:
    del_paquete = [r for r in registros if r["paquete"] == nombre_paquete]
    if not del_paquete:
        return "_(vacío)_\n"
    filas = ["| Archivo | Responsabilidad |", "| --- | --- |"]
    for r in sorted(del_paquete, key=lambda r: r["archivo"]):
        filas.append(f"| `{r['archivo']}` | {r['responsabilidad']} |")
    return "\n".join(filas) + "\n"


def generar_mapa_arquitectura(apu_tool_dir: Path) -> str:
    registros = escanear_apu_tool(apu_tool_dir)
    aristas = dependencias_entre_paquetes(registros)

    partes = [
        "# Mapa de módulos — apu_tool/\n",
        "> Autogenerado por `scripts/mapa_arquitectura.py` en cada commit, desde los "
        "imports reales de `apu_tool/`. No editar — se regenera solo.\n",
        "## Dependencias entre paquetes\n",
        diagrama_mermaid(aristas),
        "## nucleo/ — tipos y utilidades puras\n",
        seccion_paquete("nucleo", registros),
        "## datos/ — persistencia (incluye datos/pg/, backend Postgres)\n",
        seccion_paquete("datos", registros),
        "## dominio/ — motor de negocio\n",
        seccion_paquete("dominio", registros),
        "## servicio/ — API web (FastAPI)\n",
        seccion_paquete("servicio", registros),
        "## interfaz/ — puntos de entrada (CLI, GUI)\n",
        seccion_paquete("interfaz", registros),
        "## raíz — módulos transversales sueltos\n",
        seccion_paquete("raíz", registros),
    ]
    return "\n".join(partes)
