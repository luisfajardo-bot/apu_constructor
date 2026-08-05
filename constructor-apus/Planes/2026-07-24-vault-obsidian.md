> Espejo automático — no editar aquí. Fuente: `docs/superpowers/plans/2026-07-24-vault-obsidian.md`

# Vault de Obsidian auto-mantenida — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Poblar la vault de Obsidian ya creada en `constructor-apus/` con una reorganización enlazada de lo que ya existe en `docs/` y la raíz del repo, y dejar su actualización automatizada para siempre vía un hook de git.

**Architecture:** Un script puro (`scripts/actualizar_vault.py`, solo stdlib) espeja archivos individuales (README, CLAUDE, ARQUITECTURA, auditorías, runbook) y carpetas completas (Specs, Planes) hacia `constructor-apus/`, anteponiendo un aviso de "no editar aquí" a cada copia, y genera un `Índice.md` con tablas/enlaces wikilink. Un hook `pre-commit` versionado (`.githooks/pre-commit`) corre el script antes de cada commit y agrega los archivos regenerados al mismo commit.

**Tech Stack:** Python 3 (stdlib: `pathlib`, `re`) para el script y sus tests (`pytest`); `sh` (Git Bash) para el hook.

## Global Constraints

- **Ubicación de la vault:** `constructor-apus/` (ya existe, creada con Obsidian). No se usa `docs/` como vault ni se mueve nada de ahí.
- **Es un espejo, no la fuente de verdad:** cada nota copiada lleva un aviso de cabecera de una línea; la fuente real sigue siendo `docs/` y la raíz del repo.
- **Sin dependencias nuevas:** solo librería estándar de Python.
- **Determinístico e idempotente:** correr el script dos veces sin cambios en las fuentes produce el mismo resultado byte a byte (necesario para que el hook no genere ruido en cada commit).
- **No emparejar specs con planes automáticamente:** se listan por separado, ordenados por fecha (ver spec: varios slugs no coinciden exactamente).
- **No se incluye** memoria del proyecto ni bitácora de commits (decidido explícitamente en el brainstorming).
- **`core.autocrlf` está en `true` en este repo:** el hook (`.githooks/pre-commit`) necesita forzar `eol=lf` vía `.gitattributes`, si no el shebang `#!/bin/sh` puede llegar con `\r` al working tree y romperse.
- **Español** en nombres de funciones, comentarios y mensajes, siguiendo la convención del proyecto (`CLAUDE.md`).
- **Commits:** terminar el mensaje con `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.

## Preparación

Trabajar en una rama nueva desde `master`: `git checkout -b feat/vault-obsidian`.

---

### Task 1: Helpers de título y fecha desde nombre de archivo

**Files:**
- Create: `scripts/actualizar_vault.py`
- Test: `tests/test_actualizar_vault.py` (Create)

**Interfaces:**
- Produces: `titulo_desde_markdown(ruta: Path) -> str`, `fecha_desde_nombre(ruta: Path) -> str | None`

- [ ] **Step 1: Escribir los tests que fallan**

Create `tests/test_actualizar_vault.py`:

```python
from pathlib import Path

from scripts.actualizar_vault import (
    fecha_desde_nombre,
    titulo_desde_markdown,
)


def test_titulo_desde_markdown_usa_primer_encabezado(tmp_path):
    archivo = tmp_path / "algo.md"
    archivo.write_text("> nota\n\n# Mi Título\n\ncontenido\n", encoding="utf-8")
    assert titulo_desde_markdown(archivo) == "Mi Título"


def test_titulo_desde_markdown_fallback_sin_encabezado(tmp_path):
    archivo = tmp_path / "sin-encabezado.md"
    archivo.write_text("solo texto, sin encabezado\n", encoding="utf-8")
    assert titulo_desde_markdown(archivo) == "Sin encabezado"


def test_fecha_desde_nombre_con_prefijo():
    assert fecha_desde_nombre(Path("2026-07-24-algo-design.md")) == "2026-07-24"


def test_fecha_desde_nombre_sin_prefijo():
    assert fecha_desde_nombre(Path("README.md")) is None
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/test_actualizar_vault.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'scripts'` (o similar, el archivo aún no existe).

- [ ] **Step 3: Crear `scripts/__init__.py` vacío y el script con los dos helpers**

Create `scripts/__init__.py` (vacío, para que `scripts` sea un paquete importable desde los tests).

Create `scripts/actualizar_vault.py`:

```python
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
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/test_actualizar_vault.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/__init__.py scripts/actualizar_vault.py tests/test_actualizar_vault.py
git commit -m "$(cat <<'EOF'
feat(vault): helpers de título y fecha desde nombre de archivo

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Escritura idempotente y espejo de un archivo individual

**Files:**
- Modify: `scripts/actualizar_vault.py` (agregar al final)
- Modify: `tests/test_actualizar_vault.py` (agregar tests + actualizar el import)

**Interfaces:**
- Consumes: nada nuevo de Task 1
- Produces: `escribir_si_cambia(destino: Path, contenido: str) -> bool`, `aviso_espejo(origen: Path, raiz: Path) -> str`, `espejar_archivo(origen: Path, destino: Path, raiz: Path) -> bool`

- [ ] **Step 1: Escribir los tests que fallan**

En `tests/test_actualizar_vault.py`, actualizar el import del encabezado:

```python
from scripts.actualizar_vault import (
    aviso_espejo,
    escribir_si_cambia,
    espejar_archivo,
    fecha_desde_nombre,
    titulo_desde_markdown,
)
```

Agregar al final del archivo:

```python
def test_escribir_si_cambia_crea_archivo_nuevo(tmp_path):
    destino = tmp_path / "sub" / "nota.md"
    escribio = escribir_si_cambia(destino, "hola\n")
    assert escribio is True
    assert destino.read_text(encoding="utf-8") == "hola\n"


def test_escribir_si_cambia_no_reescribe_si_es_igual(tmp_path):
    destino = tmp_path / "nota.md"
    destino.write_text("hola\n", encoding="utf-8")
    mtime_antes = destino.stat().st_mtime_ns

    escribio = escribir_si_cambia(destino, "hola\n")

    assert escribio is False
    assert destino.stat().st_mtime_ns == mtime_antes


def test_aviso_espejo_incluye_ruta_relativa_y_texto_fijo(tmp_path):
    origen = tmp_path / "docs" / "ARQUITECTURA.md"
    origen.parent.mkdir()
    origen.write_text("# Arq\n", encoding="utf-8")

    aviso = aviso_espejo(origen, tmp_path)

    assert "docs/ARQUITECTURA.md" in aviso
    assert "no editar aquí" in aviso


def test_espejar_archivo_antepone_aviso_y_copia_contenido(tmp_path):
    raiz = tmp_path
    origen = raiz / "docs" / "ARQUITECTURA.md"
    origen.parent.mkdir()
    origen.write_text("# Arquitectura\n\ncontenido\n", encoding="utf-8")
    destino = raiz / "vault" / "Arquitectura" / "ARQUITECTURA.md"

    escribio = espejar_archivo(origen, destino, raiz)

    texto = destino.read_text(encoding="utf-8")
    assert escribio is True
    assert texto.startswith("> Espejo automático")
    assert "# Arquitectura" in texto
    assert "contenido" in texto


def test_espejar_archivo_es_idempotente(tmp_path):
    raiz = tmp_path
    origen = raiz / "docs" / "ARQUITECTURA.md"
    origen.parent.mkdir()
    origen.write_text("# Arquitectura\n", encoding="utf-8")
    destino = raiz / "vault" / "Arquitectura" / "ARQUITECTURA.md"

    espejar_archivo(origen, destino, raiz)
    escribio_segunda_vez = espejar_archivo(origen, destino, raiz)

    assert escribio_segunda_vez is False
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/test_actualizar_vault.py -q`
Expected: FAIL con `ImportError: cannot import name 'escribir_si_cambia'`.

- [ ] **Step 3: Implementar**

Agregar al final de `scripts/actualizar_vault.py`:

```python
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
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/test_actualizar_vault.py -q`
Expected: PASS (9 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/actualizar_vault.py tests/test_actualizar_vault.py
git commit -m "$(cat <<'EOF'
feat(vault): escritura idempotente y espejo de archivo individual

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Sincronizar carpetas espejo con limpieza de huérfanos

**Files:**
- Modify: `scripts/actualizar_vault.py` (agregar al final)
- Modify: `tests/test_actualizar_vault.py` (agregar tests + actualizar el import)

**Interfaces:**
- Consumes: `espejar_archivo` (Task 2)
- Produces: `sincronizar_espejos(archivos: list[Path], destino_dir: Path, raiz: Path) -> None`

- [ ] **Step 1: Escribir el test que falla**

Actualizar el import en `tests/test_actualizar_vault.py` agregando `sincronizar_espejos`:

```python
from scripts.actualizar_vault import (
    aviso_espejo,
    escribir_si_cambia,
    espejar_archivo,
    fecha_desde_nombre,
    sincronizar_espejos,
    titulo_desde_markdown,
)
```

Agregar al final del archivo:

```python
def test_sincronizar_espejos_copia_y_limpia_huerfanos(tmp_path):
    raiz = tmp_path
    origen_dir = raiz / "docs" / "superpowers" / "plans"
    origen_dir.mkdir(parents=True)
    (origen_dir / "2026-01-01-a.md").write_text("# A\n", encoding="utf-8")
    (origen_dir / "2026-01-02-b.md").write_text("# B\n", encoding="utf-8")
    destino_dir = raiz / "vault" / "Planes"

    sincronizar_espejos(sorted(origen_dir.glob("*.md")), destino_dir, raiz)

    assert {p.name for p in destino_dir.glob("*.md")} == {
        "2026-01-01-a.md",
        "2026-01-02-b.md",
    }

    (origen_dir / "2026-01-02-b.md").unlink()
    sincronizar_espejos(sorted(origen_dir.glob("*.md")), destino_dir, raiz)

    assert {p.name for p in destino_dir.glob("*.md")} == {"2026-01-01-a.md"}


def test_sincronizar_espejos_con_lista_vacia_deja_carpeta_vacia(tmp_path):
    raiz = tmp_path
    destino_dir = raiz / "vault" / "Auditorías"

    sincronizar_espejos([], destino_dir, raiz)

    assert destino_dir.exists()
    assert list(destino_dir.glob("*.md")) == []
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_actualizar_vault.py -q`
Expected: FAIL con `ImportError: cannot import name 'sincronizar_espejos'`.

- [ ] **Step 3: Implementar**

Agregar al final de `scripts/actualizar_vault.py`:

```python
def sincronizar_espejos(archivos: list[Path], destino_dir: Path, raiz: Path) -> None:
    """Deja `destino_dir` con exactamente el espejo de `archivos` (borra huérfanos)."""
    destino_dir.mkdir(parents=True, exist_ok=True)
    nombres = {a.name for a in archivos}
    for existente in destino_dir.glob("*.md"):
        if existente.name not in nombres:
            existente.unlink()
    for archivo in archivos:
        espejar_archivo(archivo, destino_dir / archivo.name, raiz)
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/test_actualizar_vault.py -q`
Expected: PASS (11 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/actualizar_vault.py tests/test_actualizar_vault.py
git commit -m "$(cat <<'EOF'
feat(vault): sincronizar carpetas espejo con limpieza de huérfanos

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Clasificar los .md sueltos de docs/ en categorías fijas

**Files:**
- Modify: `scripts/actualizar_vault.py` (agregar al final)
- Modify: `tests/test_actualizar_vault.py` (agregar tests + actualizar el import)

**Interfaces:**
- Consumes: nada nuevo
- Produces: `clasificar_docs_sueltos(docs: Path) -> dict[str, list[Path]]` (claves: `"arquitectura"`, `"auditorias"`, `"runbooks"`, `"otros"`)

- [ ] **Step 1: Escribir el test que falla**

Actualizar el import agregando `clasificar_docs_sueltos`:

```python
from scripts.actualizar_vault import (
    aviso_espejo,
    clasificar_docs_sueltos,
    escribir_si_cambia,
    espejar_archivo,
    fecha_desde_nombre,
    sincronizar_espejos,
    titulo_desde_markdown,
)
```

Agregar al final del archivo:

```python
def test_clasificar_docs_sueltos(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "ARQUITECTURA.md").write_text("# Arq\n", encoding="utf-8")
    (docs / "auditoria-codigo-2026-07-01.md").write_text("# Auditoría\n", encoding="utf-8")
    (docs / "runbook-correo.md").write_text("# Runbook\n", encoding="utf-8")
    (docs / "algo-suelto.md").write_text("# Suelto\n", encoding="utf-8")

    categorias = clasificar_docs_sueltos(docs)

    assert [a.name for a in categorias["arquitectura"]] == ["ARQUITECTURA.md"]
    assert [a.name for a in categorias["auditorias"]] == ["auditoria-codigo-2026-07-01.md"]
    assert [a.name for a in categorias["runbooks"]] == ["runbook-correo.md"]
    assert [a.name for a in categorias["otros"]] == ["algo-suelto.md"]


def test_clasificar_docs_sueltos_no_recursa_en_subcarpetas(tmp_path):
    docs = tmp_path / "docs"
    (docs / "superpowers" / "specs").mkdir(parents=True)
    (docs / "superpowers" / "specs" / "2026-01-01-x-design.md").write_text(
        "# X\n", encoding="utf-8"
    )

    categorias = clasificar_docs_sueltos(docs)

    assert categorias == {"arquitectura": [], "auditorias": [], "runbooks": [], "otros": []}
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_actualizar_vault.py -q`
Expected: FAIL con `ImportError: cannot import name 'clasificar_docs_sueltos'`.

- [ ] **Step 3: Implementar**

Agregar al final de `scripts/actualizar_vault.py`:

```python
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
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/test_actualizar_vault.py -q`
Expected: PASS (13 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/actualizar_vault.py tests/test_actualizar_vault.py
git commit -m "$(cat <<'EOF'
feat(vault): clasificar docs sueltos de docs/ en categorías fijas

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Generar el Índice.md de la vault

**Files:**
- Modify: `scripts/actualizar_vault.py` (agregar al final)
- Modify: `tests/test_actualizar_vault.py` (agregar tests + actualizar el import)

**Interfaces:**
- Consumes: `fecha_desde_nombre`, `titulo_desde_markdown` (Task 1), `clasificar_docs_sueltos` (Task 4)
- Produces: `entradas_de_carpeta(carpeta: Path) -> list[tuple[str, str, str]]`, `tabla_markdown(entradas, carpeta_vault: str) -> str`, `enlace_bullet(carpeta_vault: str, archivo: Path) -> str`, `bloque_bullets(carpeta_vault: str, archivos: list[Path]) -> str`, `generar_indice(docs: Path) -> str`

- [ ] **Step 1: Escribir los tests que fallan**

Actualizar el import agregando las cinco funciones nuevas:

```python
from scripts.actualizar_vault import (
    aviso_espejo,
    bloque_bullets,
    clasificar_docs_sueltos,
    enlace_bullet,
    entradas_de_carpeta,
    escribir_si_cambia,
    espejar_archivo,
    fecha_desde_nombre,
    generar_indice,
    sincronizar_espejos,
    tabla_markdown,
    titulo_desde_markdown,
)
```

Agregar al final del archivo:

```python
def test_entradas_de_carpeta_ordena_por_fecha_descendente(tmp_path):
    carpeta = tmp_path / "specs"
    carpeta.mkdir()
    (carpeta / "2026-01-01-vieja-design.md").write_text("# Vieja\n", encoding="utf-8")
    (carpeta / "2026-06-01-nueva-design.md").write_text("# Nueva\n", encoding="utf-8")

    entradas = entradas_de_carpeta(carpeta)

    assert entradas[0] == ("2026-06-01", "Nueva", "2026-06-01-nueva-design.md")
    assert entradas[1] == ("2026-01-01", "Vieja", "2026-01-01-vieja-design.md")


def test_tabla_markdown_con_entradas():
    entradas = [("2026-06-01", "Nueva", "2026-06-01-nueva-design.md")]

    tabla = tabla_markdown(entradas, "Specs")

    assert "| 2026-06-01 |" in tabla
    assert "[[Specs/2026-06-01-nueva-design|Nueva]]" in tabla


def test_tabla_markdown_vacia():
    assert tabla_markdown([], "Specs") == "_(vacío)_\n"


def test_bloque_bullets_vacio():
    assert bloque_bullets("Auditorías", []) == "_(vacío)_\n"


def test_enlace_bullet_usa_titulo_y_stem(tmp_path):
    archivo = tmp_path / "runbook-correo.md"
    archivo.write_text("# Correo por Resend\n", encoding="utf-8")

    assert enlace_bullet("Runbooks", archivo) == "- [[Runbooks/runbook-correo|Correo por Resend]]\n"


def test_generar_indice_incluye_secciones_y_conteos(tmp_path):
    raiz = tmp_path
    docs = raiz / "docs"
    (docs / "superpowers" / "specs").mkdir(parents=True)
    (docs / "superpowers" / "plans").mkdir(parents=True)
    (docs / "ARQUITECTURA.md").write_text("# Arquitectura\n", encoding="utf-8")
    (raiz / "README.md").write_text("# Readme\n", encoding="utf-8")
    (raiz / "CLAUDE.md").write_text("# Claude\n", encoding="utf-8")
    (docs / "superpowers" / "specs" / "2026-01-01-x-design.md").write_text(
        "# X\n", encoding="utf-8"
    )
    (docs / "superpowers" / "plans" / "2026-01-01-x.md").write_text(
        "# X plan\n", encoding="utf-8"
    )

    indice = generar_indice(docs)

    assert "1 planes, 1 specs" in indice
    assert "[[Arquitectura/ARQUITECTURA|Arquitectura]]" in indice
    assert "[[Proyecto/README|Readme]]" in indice
    assert "[[Proyecto/CLAUDE|Claude]]" in indice
    assert "[[Specs/2026-01-01-x-design|X]]" in indice
    assert "[[Planes/2026-01-01-x|X plan]]" in indice
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/test_actualizar_vault.py -q`
Expected: FAIL con `ImportError: cannot import name 'entradas_de_carpeta'`.

- [ ] **Step 3: Implementar**

Agregar al final de `scripts/actualizar_vault.py`:

```python
def entradas_de_carpeta(carpeta: Path) -> list[tuple[str, str, str]]:
    """(fecha, título, nombre_de_archivo) de cada .md de `carpeta`, fecha descendente."""
    entradas = []
    for archivo in carpeta.glob("*.md"):
        fecha = fecha_desde_nombre(archivo) or "s/f"
        titulo = titulo_desde_markdown(archivo)
        entradas.append((fecha, titulo, archivo.name))
    entradas.sort(key=lambda e: e[0], reverse=True)
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
    specs = entradas_de_carpeta(docs / "superpowers" / "specs")
    planes = entradas_de_carpeta(docs / "superpowers" / "plans")

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
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/test_actualizar_vault.py -q`
Expected: PASS (19 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/actualizar_vault.py tests/test_actualizar_vault.py
git commit -m "$(cat <<'EOF'
feat(vault): generar Índice.md con secciones, tablas y wikilinks

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Orquestar `main()` — puebla `constructor-apus/` y es idempotente

**Files:**
- Modify: `scripts/actualizar_vault.py` (agregar al final)
- Modify: `tests/test_actualizar_vault.py` (agregar test + actualizar el import)

**Interfaces:**
- Consumes: todas las funciones de Tasks 1-5
- Produces: `main(raiz: Path = RAIZ) -> None`

- [ ] **Step 1: Escribir el test que falla**

Actualizar el import agregando `main`:

```python
from scripts.actualizar_vault import (
    aviso_espejo,
    bloque_bullets,
    clasificar_docs_sueltos,
    enlace_bullet,
    entradas_de_carpeta,
    escribir_si_cambia,
    espejar_archivo,
    fecha_desde_nombre,
    generar_indice,
    main,
    sincronizar_espejos,
    tabla_markdown,
    titulo_desde_markdown,
)
```

Agregar al final del archivo:

```python
def _armar_repo_fixture(raiz):
    docs = raiz / "docs"
    (docs / "superpowers" / "specs").mkdir(parents=True)
    (docs / "superpowers" / "plans").mkdir(parents=True)
    (docs / "ARQUITECTURA.md").write_text("# Arquitectura\n", encoding="utf-8")
    (docs / "auditoria-codigo-2026-07-01.md").write_text("# Auditoría\n", encoding="utf-8")
    (docs / "runbook-correo.md").write_text("# Runbook\n", encoding="utf-8")
    (raiz / "README.md").write_text("# Readme\n", encoding="utf-8")
    (raiz / "CLAUDE.md").write_text("# Claude\n", encoding="utf-8")
    (docs / "superpowers" / "specs" / "2026-01-01-x-design.md").write_text(
        "# X\n", encoding="utf-8"
    )
    (docs / "superpowers" / "plans" / "2026-01-01-x.md").write_text(
        "# X plan\n", encoding="utf-8"
    )
    vault = raiz / "constructor-apus"
    vault.mkdir()
    (vault / "Bienvenido.md").write_text("bienvenida\n", encoding="utf-8")
    return vault


def test_main_puebla_la_vault_y_borra_bienvenido(tmp_path):
    vault = _armar_repo_fixture(tmp_path)

    main(tmp_path)

    assert not (vault / "Bienvenido.md").exists()
    assert (vault / "Arquitectura" / "ARQUITECTURA.md").exists()
    assert (vault / "Auditorías" / "auditoria-codigo-2026-07-01.md").exists()
    assert (vault / "Runbooks" / "runbook-correo.md").exists()
    assert (vault / "Proyecto" / "README.md").exists()
    assert (vault / "Proyecto" / "CLAUDE.md").exists()
    assert (vault / "Specs" / "2026-01-01-x-design.md").exists()
    assert (vault / "Planes" / "2026-01-01-x.md").exists()
    assert (vault / "Índice.md").exists()


def test_main_es_idempotente(tmp_path):
    vault = _armar_repo_fixture(tmp_path)

    main(tmp_path)
    contenidos_antes = {p: p.read_text(encoding="utf-8") for p in vault.rglob("*.md")}

    main(tmp_path)
    contenidos_despues = {p: p.read_text(encoding="utf-8") for p in vault.rglob("*.md")}

    assert contenidos_antes == contenidos_despues
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/test_actualizar_vault.py -q`
Expected: FAIL con `ImportError: cannot import name 'main'`.

- [ ] **Step 3: Implementar**

Agregar al final de `scripts/actualizar_vault.py`:

```python
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
    sincronizar_espejos(
        sorted((docs / "superpowers" / "specs").glob("*.md")), vault / "Specs", raiz
    )
    sincronizar_espejos(
        sorted((docs / "superpowers" / "plans").glob("*.md")), vault / "Planes", raiz
    )

    escribir_si_cambia(vault / "Índice.md", generar_indice(docs))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/test_actualizar_vault.py -q`
Expected: PASS (21 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/actualizar_vault.py tests/test_actualizar_vault.py
git commit -m "$(cat <<'EOF'
feat(vault): orquestar main() — puebla constructor-apus/ de forma idempotente

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Hook `pre-commit`, `.gitattributes`, `.gitignore` y doc de setup

**Files:**
- Create: `.githooks/pre-commit`
- Create: `.gitattributes`
- Modify: `.gitignore`
- Modify: `README.md` (sección "Instalación")

**Interfaces:**
- Consumes: `scripts/actualizar_vault.py` (Task 1-6, ya corre standalone con `python scripts/actualizar_vault.py`)

- [ ] **Step 1: Crear `.gitattributes` para forzar LF en los hooks**

`core.autocrlf` está en `true` en este repo (verificado con `git config --get core.autocrlf`), lo que convierte los finales de línea a CRLF en el working tree. Un shebang `#!/bin/sh\r` con `\r` final puede romper la ejecución del hook. Se fuerza LF explícitamente para `.githooks/`.

Create `.gitattributes`:

```
.githooks/* text eol=lf
```

- [ ] **Step 2: Crear el hook `pre-commit`**

Create `.githooks/pre-commit`:

```sh
#!/bin/sh
# Regenera la vault de Obsidian (constructor-apus/) antes de cada commit.
# Instalado vía: git config core.hooksPath .githooks
python scripts/actualizar_vault.py || exit 1
git add constructor-apus
```

Marcarlo ejecutable:

```bash
chmod +x .githooks/pre-commit
```

- [ ] **Step 3: Ignorar el estado de UI local de Obsidian**

En `.gitignore`, agregar al final:

```
# Vault de Obsidian: estado de UI local (cambia en cada sesión), no se versiona.
# El resto de constructor-apus/.obsidian/ (plugins, apariencia, grafo) sí se versiona.
constructor-apus/.obsidian/workspace.json
constructor-apus/.obsidian/workspace-mobile.json
```

- [ ] **Step 4: Documentar el setup en el README**

En `README.md`, agregar una subsección nueva al final de la sección `## Instalación` (antes del separador `---` que sigue), después del bloque que explica `ANTHROPIC_API_KEY`:

```markdown

### Vault de Obsidian (opcional)

El repo mantiene una vault de Obsidian en `constructor-apus/` con specs, planes,
arquitectura y auditorías reorganizados y enlazados (espejo autogenerado; no editar
las notas ahí, la fuente real sigue siendo `docs/` y la raíz del repo). Se actualiza
sola en cada commit vía un hook de git versionado en `.githooks/`. Para activarlo en
un clon nuevo (una sola vez):

```bash
git config core.hooksPath .githooks
```

Sin este paso los commits funcionan igual — solo que la vault no se regenera sola.
Abrí `constructor-apus/` como vault en Obsidian para navegarla.
```

- [ ] **Step 5: Verificar el script standalone antes de activar el hook**

Run: `python scripts/actualizar_vault.py`
Expected: corre sin error (a esta altura ya puebla `constructor-apus/` de verdad — se revisa el resultado en el Task 8).

- [ ] **Step 6: Commit**

```bash
git add .gitattributes .githooks/pre-commit .gitignore README.md
git commit -m "$(cat <<'EOF'
chore(vault): hook pre-commit + gitattributes + gitignore + doc de setup

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 7: Activar el hook en este clon local**

Run: `git config core.hooksPath .githooks`

(Este comando es config local del repo, no un archivo — no se commitea. Queda documentado en el README para futuros clones.)

---

### Task 8: Poblar `constructor-apus/` con el espejo real del proyecto

**Files:**
- (generados por el script) `constructor-apus/Índice.md`, `constructor-apus/Arquitectura/`, `constructor-apus/Proyecto/`, `constructor-apus/Auditorías/`, `constructor-apus/Runbooks/`, `constructor-apus/Otros/`, `constructor-apus/Specs/`, `constructor-apus/Planes/`

**Interfaces:**
- Consumes: `main()` (Task 6) vía el hook `pre-commit` (Task 7)

- [ ] **Step 1: Confirmar que `Bienvenido.md` ya no existe y que el Índice se generó**

Run: `python scripts/actualizar_vault.py` (el mismo script ya corrió en el Task 7 Step 5; correrlo de nuevo debe ser un no-op)

Expected: sin salida ni error. Verificar a mano:
- `constructor-apus/Bienvenido.md` no existe.
- `constructor-apus/Índice.md` existe y tiene secciones "Arquitectura y referencia", "Auditorías", "Runbooks", "Otros", "Specs (diseños)", "Planes (implementación)".
- `constructor-apus/Specs/` tiene el mismo número de archivos que `docs/superpowers/specs/`, y `constructor-apus/Planes/` el mismo que `docs/superpowers/plans/` (correr `ls docs/superpowers/specs | wc -l` / `ls constructor-apus/Specs | wc -l` y comparar; ambas carpetas siguen creciendo con el proyecto, así que el número exacto no es fijo).

- [ ] **Step 2: Correr la suite completa de tests**

Run: `python -m pytest tests/ -q`
Expected: verde (incluye los `test_actualizar_vault.py` de Tasks 1-6 más la suite existente del proyecto, sin regresiones).

- [ ] **Step 3: Revisar qué va a entrar al commit**

Run: `git add constructor-apus && git status --short`

Expected: `constructor-apus/` aparece staged completo, **sin** `constructor-apus/.obsidian/workspace.json` (excluido por `.gitignore` del Task 7).

- [ ] **Step 4: Commit (dispara el hook ya activo)**

```bash
git commit -m "$(cat <<'EOF'
chore(vault): poblar constructor-apus/ con el espejo real del proyecto

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

El hook `pre-commit` (activo desde el Task 7 Step 7) corre `python scripts/actualizar_vault.py` de nuevo antes de finalizar el commit — al ser idempotente, no debería agregar cambios nuevos al commit ya armado en el Step 3.

- [ ] **Step 5: Verificar que el hook efectivamente corrió y el commit quedó completo**

Run: `git log -1 --stat`
Expected: el commit incluye todos los archivos de `constructor-apus/` (menos `workspace.json`).

---

## Verificación final (tras todas las tareas)

- [ ] `python -m pytest tests/ -q` → verde.
- [ ] Abrir `constructor-apus/` como vault en Obsidian y confirmar: `Índice.md` es la nota que se puede abrir manualmente, los wikilinks de las tablas de Specs/Planes navegan a la nota correcta, el grafo muestra las notas conectadas.
- [ ] Manual: modificar cualquier archivo bajo `docs/superpowers/specs/` o `docs/superpowers/plans/` (o crear uno nuevo), hacer un commit cualquiera, y confirmar que `constructor-apus/Índice.md` y el espejo correspondiente se actualizaron solos y quedaron incluidos en ese mismo commit.

## Self-Review (cobertura del spec)

- Ubicación `constructor-apus/`, no `docs/` → Tasks 6-8 escriben ahí; el spec original de `docs/` como vault quedó descartado en el brainstorming.
- Espejo con aviso de cabecera, no fuente de verdad → `aviso_espejo`/`espejar_archivo` (Task 2), verificado en tests.
- Estructura completa (Arquitectura/Proyecto/Auditorías/Runbooks/Specs/Planes/Otros) → `main()` (Task 6) + `clasificar_docs_sueltos` (Task 4).
- Índice con tablas fecha↓ + wikilinks, sin emparejar spec↔plan → `generar_indice`/`tabla_markdown` (Task 5).
- Catch-all "Otros" sin recursar → `clasificar_docs_sueltos` (Task 4), test dedicado de no-recursión.
- Determinístico e idempotente → tests de idempotencia en Tasks 2, 3 y 6.
- Disparador automático para siempre (hook pre-commit versionado) → Task 7, verificado end-to-end en Task 8.
- `core.autocrlf=true` no rompe el shebang del hook → `.gitattributes` con `eol=lf` (Task 7).
- `.obsidian/workspace.json` no se versiona, el resto de `.obsidian/` sí → `.gitignore` (Task 7 Step 3), no se toca nada más de `.obsidian/`.
- Setup de un solo paso por clon documentado → README (Task 7 Step 4).
- Sin dependencias nuevas → solo `pathlib`/`re` de stdlib en todo el script.
