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


def escribir_si_cambia(destino: Path, contenido: str) -> bool:
    """Escribe `contenido` en `destino` solo si difiere del actual.

    Devuelve si escribió (para que el llamador sepa si hubo cambios reales).
    """
    if destino.exists() and destino.read_text(encoding="utf-8") == contenido:
        return False
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(contenido, encoding="utf-8")
    return True


def aviso_espejo(origen: Path, raiz: Path) -> str:
    relativo = origen.relative_to(raiz).as_posix()
    return f"> Espejo automático — no editar aquí. Fuente: `{relativo}`\n\n"


def espejar_archivo(origen: Path, destino: Path, raiz: Path) -> bool:
    """Copia `origen` a `destino` con un aviso de cabecera antepuesto."""
    contenido = aviso_espejo(origen, raiz) + origen.read_text(encoding="utf-8")
    return escribir_si_cambia(destino, contenido)


def sincronizar_espejos(archivos: list[Path], destino_dir: Path, raiz: Path) -> None:
    """Deja `destino_dir` con exactamente el espejo de `archivos` (borra huérfanos)."""
    destino_dir.mkdir(parents=True, exist_ok=True)
    nombres = {a.name for a in archivos}
    for existente in destino_dir.glob("*.md"):
        if existente.name not in nombres:
            existente.unlink()
    for archivo in archivos:
        espejar_archivo(archivo, destino_dir / archivo.name, raiz)


def clasificar_docs_sueltos(docs: Path) -> dict[str, list[Path]]:
    """Clasifica los .md directamente en `docs/` (sin recursar) en categorías fijas."""
    categorias: dict[str, list[Path]] = {
        "arquitectura": [],
        "auditorias": [],
        "runbooks": [],
        "otros": [],
    }
    for archivo in sorted(docs.glob("*.md")):
        nombre = archivo.name
        if nombre == "ARQUITECTURA.md":
            categorias["arquitectura"].append(archivo)
        elif nombre.startswith("auditoria-"):
            categorias["auditorias"].append(archivo)
        elif nombre.startswith("runbook-"):
            categorias["runbooks"].append(archivo)
        else:
            categorias["otros"].append(archivo)
    return categorias
