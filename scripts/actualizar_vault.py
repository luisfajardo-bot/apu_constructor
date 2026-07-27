"""Regenera la vault de Obsidian (constructor-apus/) a partir de docs/ y la raíz
del repo.

Espejo de solo lectura: cada nota copiada lleva un aviso de cabecera. La fuente
de verdad sigue siendo docs/ y la raíz del repo. Pensado para correr en cada
commit vía .githooks/pre-commit — es determinístico e idempotente.
"""
from __future__ import annotations

import re
import subprocess
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


def nombres_trackeados(carpeta: Path, raiz: Path) -> set[str]:
    """Nombres de archivo bajo `carpeta` (no recursivo) que están trackeados en git.

    Evita que un archivo suelto sin commitear (un borrador de otra rama, un plan
    a medio terminar) se cuele en la vault: el espejo refleja lo que está en el
    repo, no lo que haya en el working tree en el momento del commit — si no,
    reaparecería en cada commit mientras el archivo siga sin trackear.
    """
    relativo = carpeta.relative_to(raiz).as_posix()
    resultado = subprocess.run(
        ["git", "-c", "core.quotepath=false", "-C", str(raiz), "ls-files", "--", relativo],
        capture_output=True, encoding="utf-8", check=True,
    )
    return {Path(linea).name for linea in resultado.stdout.splitlines() if linea}


def clasificar_docs_sueltos(docs: Path) -> dict[str, list[Path]]:
    """Clasifica los .md trackeados directamente en `docs/` (sin recursar) en categorías fijas."""
    trackeados = nombres_trackeados(docs, docs.parent)
    categorias: dict[str, list[Path]] = {
        "arquitectura": [],
        "auditorias": [],
        "runbooks": [],
        "otros": [],
    }
    for archivo in sorted(docs.glob("*.md")):
        if archivo.name not in trackeados:
            continue
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


def entradas_de_carpeta(carpeta: Path, raiz: Path) -> list[tuple[str, str, str]]:
    """(fecha, título, nombre_de_archivo) de cada .md trackeado de `carpeta`,
    fecha descendente. Un archivo sin commitear no aparece (ver `nombres_trackeados`)."""
    trackeados = nombres_trackeados(carpeta, raiz)
    entradas = []
    for archivo in carpeta.glob("*.md"):
        if archivo.name not in trackeados:
            continue
        fecha = fecha_desde_nombre(archivo) or "s/f"
        titulo = titulo_desde_markdown(archivo)
        entradas.append((fecha, titulo, archivo.name))
    entradas.sort(key=lambda e: (e[0], e[2]), reverse=True)
    return entradas


def tabla_markdown(entradas: list[tuple[str, str, str]], carpeta_vault: str) -> str:
    if not entradas:
        return "_(vacío)_\n"
    filas = ["| Fecha | Título |", "| --- | --- |"]
    for fecha, titulo, nombre in entradas:
        objetivo = f"{carpeta_vault}/{Path(nombre).stem}"
        filas.append(f"| {fecha} | [[{objetivo}|{titulo}]] |")
    return "\n".join(filas) + "\n"


def enlace_bullet(carpeta_vault: str, archivo: Path) -> str:
    titulo = titulo_desde_markdown(archivo)
    return f"- [[{carpeta_vault}/{archivo.stem}|{titulo}]]\n"


def bloque_bullets(carpeta_vault: str, archivos: list[Path]) -> str:
    if not archivos:
        return "_(vacío)_\n"
    return "".join(enlace_bullet(carpeta_vault, a) for a in archivos)


def generar_indice(docs: Path) -> str:
    raiz = docs.parent
    categorias = clasificar_docs_sueltos(docs)
    specs = entradas_de_carpeta(docs / "superpowers" / "specs", raiz)
    planes = entradas_de_carpeta(docs / "superpowers" / "plans", raiz)

    referencia = "".join(
        enlace_bullet("Arquitectura", a) for a in categorias["arquitectura"]
    )
    referencia += enlace_bullet("Proyecto", raiz / "README.md")
    referencia += enlace_bullet("Proyecto", raiz / "CLAUDE.md")

    partes = [
        "# Índice\n",
        f"Vault autogenerada por `scripts/actualizar_vault.py` en cada commit — "
        f"{len(planes)} planes, {len(specs)} specs. Las notas espejo no se editan "
        "aquí; la fuente de verdad sigue siendo `docs/` y la raíz del repo.\n",
        "## Arquitectura y referencia\n",
        referencia,
        "## Auditorías\n",
        bloque_bullets("Auditorías", categorias["auditorias"]),
        "## Runbooks\n",
        bloque_bullets("Runbooks", categorias["runbooks"]),
        "## Otros\n",
        bloque_bullets("Otros", categorias["otros"]),
        "## Specs (diseños)\n",
        tabla_markdown(specs, "Specs"),
        "## Planes (implementación)\n",
        tabla_markdown(planes, "Planes"),
    ]
    return "\n".join(partes)


def main(raiz: Path = RAIZ) -> None:
    docs = raiz / "docs"
    vault = raiz / "constructor-apus"

    bienvenida = vault / "Bienvenido.md"
    if bienvenida.exists():
        bienvenida.unlink()

    categorias = clasificar_docs_sueltos(docs)
    sincronizar_espejos(categorias["arquitectura"], vault / "Arquitectura", raiz)
    sincronizar_espejos([raiz / "README.md", raiz / "CLAUDE.md"], vault / "Proyecto", raiz)
    sincronizar_espejos(categorias["auditorias"], vault / "Auditorías", raiz)
    sincronizar_espejos(categorias["runbooks"], vault / "Runbooks", raiz)
    sincronizar_espejos(categorias["otros"], vault / "Otros", raiz)

    specs_dir = docs / "superpowers" / "specs"
    planes_dir = docs / "superpowers" / "plans"
    specs_trackeados = nombres_trackeados(specs_dir, raiz)
    planes_trackeados = nombres_trackeados(planes_dir, raiz)
    sincronizar_espejos(
        sorted(p for p in specs_dir.glob("*.md") if p.name in specs_trackeados),
        vault / "Specs", raiz,
    )
    sincronizar_espejos(
        sorted(p for p in planes_dir.glob("*.md") if p.name in planes_trackeados),
        vault / "Planes", raiz,
    )

    escribir_si_cambia(vault / "Índice.md", generar_indice(docs))


if __name__ == "__main__":
    main()
