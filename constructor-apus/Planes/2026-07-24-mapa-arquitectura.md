> Espejo automático — no editar aquí. Fuente: `docs/superpowers/plans/2026-07-24-mapa-arquitectura.md`

# Corrección de docs de arquitectura + mapa auto-generado de módulos — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corregir `CLAUDE.md`/`docs/ARQUITECTURA.md` para que reflejen la estructura real de paquetes de `apu_tool/`, y agregar a la vault un mapa de módulos auto-generado (diagrama Mermaid + tablas por paquete) que nunca puede desactualizarse porque se recalcula desde los imports reales en cada commit.

**Architecture:** Un módulo nuevo, `scripts/mapa_arquitectura.py` (solo `ast`/`pathlib`), analiza `apu_tool/` con `ast.parse`: responsabilidad = primera línea del docstring de cada módulo; dependencias = `from apu_tool.X.Y import ...` absolutos. Agrupa por paquete (`nucleo`, `datos`, `dominio`, `servicio`, `interfaz`, `raíz`), arma un diagrama Mermaid de dependencias entre paquetes y una tabla de archivos por paquete. `scripts/actualizar_vault.py::main()` lo llama como un paso más, y `generar_indice()` agrega el link.

**Tech Stack:** Python 3 (stdlib: `ast`, `pathlib`); `pytest` para los tests.

## Global Constraints

- **Alcance:** solo backend Python (`apu_tool/`). No se mapea `web/src` (TypeScript) — decidido explícitamente en brainstorming.
- **Solo imports absolutos:** `ast.ImportFrom` con `node.level == 0` y `node.module` empezando con `"apu_tool"`. El proyecto no usa imports relativos (verificado con `grep`); no hace falta resolverlos.
- **Agrupación:** el paquete de `apu_tool.X.Y...` es `X` si `X ∈ {nucleo, datos, dominio, servicio, interfaz}`; si no, es `"raíz"` (p. ej. `apu_tool.config`). `datos/pg/*` se agrupa bajo `"datos"` (subcarpeta de implementación, no una capa aparte).
- **Determinístico e idempotente:** correr `generar_mapa_arquitectura` dos veces sin cambios en `apu_tool/` da el mismo string byte a byte (`rglob` ordenado, aristas como `set` → `sorted`, tablas ordenadas por archivo).
- **Sin dependencias nuevas:** solo librería estándar.
- **Español** en nombres de funciones, comentarios y mensajes.
- **Commits:** terminar el mensaje con `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.
- **La nota generada no lleva el aviso de "espejo"** (`aviso_espejo`) — no es la copia de un único archivo fuente. Lleva su propio aviso de una línea (ver Task 5).

## Preparación

Trabajar en una rama nueva desde `master`: `git checkout -b feat/mapa-arquitectura`.

---

### Task 1: Corregir `CLAUDE.md` y `docs/ARQUITECTURA.md`

**Files:**
- Modify: `CLAUDE.md` (sección `## Arquitectura (flujo)`, líneas ~47-69)
- Modify: `docs/ARQUITECTURA.md` (tabla "Las cuatro capas" ~29-34, árbol "Estructura de carpetas" ~52-86, sección "Hoja de ruta" ~88-102)

Esta tarea es edición de prosa (sin código ni tests automatizados) — el spec
(`docs/superpowers/specs/2026-07-24-mapa-arquitectura-design.md`, Partes 1 y 2)
tiene el contenido exacto a usar en cada reemplazo.

- [ ] **Step 1: Reemplazar la sección `## Arquitectura (flujo)` de `CLAUDE.md`**

Reemplazar todo el bloque desde `## Arquitectura (flujo)` (línea 47) hasta el
final de la tabla de módulos vieja (línea 69, `| \`gui.py\`/\`cli.py\` | interfaces |`)
por el contenido de la Parte 1 del spec (el diagrama de flujo actualizado, la
nota de `config.py`, y las cinco tablas por paquete: `nucleo/`, `datos/`,
`dominio/`, `servicio/`, `interfaz/`).

- [ ] **Step 2: Reemplazar la tabla "Las cuatro capas" de `docs/ARQUITECTURA.md`**

En la tabla de la sección `## Las cuatro capas` (~línea 29-34), actualizar la
columna "Estado" según la Parte 2a del spec: nivel 01 → `existe hoy (SQLite +
Postgres)`; nivel 03 → `existe hoy (FastAPI, 44 endpoints)`; nivel 04 →
`existe hoy (CLI, GUI y web)`. Nivel 02 no cambia.

- [ ] **Step 3: Reemplazar el árbol "Estructura de carpetas (objetivo)"**

Reemplazar el bloque de código completo bajo `## Estructura de carpetas
(objetivo)` (~línea 52-86) por el árbol de la Parte 2b del spec.

- [ ] **Step 4: Reemplazar la sección "Hoja de ruta"**

Reemplazar la sección `## Hoja de ruta` completa (~línea 88-102) por el
contenido de la Parte 2c del spec (pasos 1-5 marcados ✅, paso 6 con su
estado real).

- [ ] **Step 5: Verificar releyendo ambos archivos completos**

Releer `CLAUDE.md` y `docs/ARQUITECTURA.md` de punta a punta y confirmar:
- No quedan referencias a módulos planos viejos (`db.py`, `ingest.py` sueltos
  sin paquete) fuera de contexto histórico.
- No quedan menciones de "futuro" para Postgres, FastAPI o la app web.
- Los nombres de paquete (`nucleo`, `datos`, `dominio`, `servicio`, `interfaz`)
  aparecen consistentemente entre ambos documentos.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md docs/ARQUITECTURA.md
git commit -m "$(cat <<'EOF'
docs(arquitectura): corregir CLAUDE.md y ARQUITECTURA.md a la estructura real

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Helpers de análisis por archivo (responsabilidad, imports, paquete)

**Files:**
- Create: `scripts/mapa_arquitectura.py`
- Test: `tests/test_mapa_arquitectura.py` (Create)

**Interfaces:**
- Produces: `responsabilidad_de_modulo(ruta: Path) -> str`,
  `imports_internos(ruta: Path) -> list[str]`,
  `paquete_de_modulo(modulo_dotted: str) -> str`

- [ ] **Step 1: Escribir los tests que fallan**

Create `tests/test_mapa_arquitectura.py`:

```python
from pathlib import Path

from scripts.mapa_arquitectura import (
    imports_internos,
    paquete_de_modulo,
    responsabilidad_de_modulo,
)


def test_responsabilidad_de_modulo_usa_primera_linea_del_docstring(tmp_path):
    archivo = tmp_path / "x.py"
    archivo.write_text(
        '"""Primera línea.\n\nMás texto que no importa.\n"""\ndef f(): pass\n',
        encoding="utf-8",
    )
    assert responsabilidad_de_modulo(archivo) == "Primera línea."


def test_responsabilidad_de_modulo_fallback_sin_docstring(tmp_path):
    archivo = tmp_path / "mi_modulo.py"
    archivo.write_text("def f(): pass\n", encoding="utf-8")
    assert responsabilidad_de_modulo(archivo) == "Mi modulo"


def test_imports_internos_detecta_apu_tool_absoluto(tmp_path):
    archivo = tmp_path / "x.py"
    archivo.write_text(
        "import re\n"
        "from pathlib import Path\n"
        "from apu_tool.dominio.pricing import PricingEngine\n"
        "from apu_tool.nucleo.models import Insumo\n",
        encoding="utf-8",
    )
    assert imports_internos(archivo) == [
        "apu_tool.dominio.pricing",
        "apu_tool.nucleo.models",
    ]


def test_imports_internos_ignora_relativos(tmp_path):
    archivo = tmp_path / "x.py"
    archivo.write_text(
        "from . import hermano\nfrom ..nucleo import models\n", encoding="utf-8"
    )
    assert imports_internos(archivo) == []


def test_paquete_de_modulo():
    assert paquete_de_modulo("apu_tool.dominio.pricing") == "dominio"
    assert paquete_de_modulo("apu_tool.datos.pg.precios_pg") == "datos"
    assert paquete_de_modulo("apu_tool.config") == "raíz"
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/test_mapa_arquitectura.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'scripts.mapa_arquitectura'`.

- [ ] **Step 3: Implementar**

Create `scripts/mapa_arquitectura.py`:

```python
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
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/test_mapa_arquitectura.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/mapa_arquitectura.py tests/test_mapa_arquitectura.py
git commit -m "$(cat <<'EOF'
feat(mapa-arquitectura): helpers de análisis por archivo (responsabilidad, imports, paquete)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Escanear `apu_tool/` y armar registros por módulo

**Files:**
- Modify: `scripts/mapa_arquitectura.py` (agregar al final)
- Modify: `tests/test_mapa_arquitectura.py` (agregar tests + actualizar el import)

**Interfaces:**
- Consumes: `responsabilidad_de_modulo`, `imports_internos`, `paquete_de_modulo` (Task 2)
- Produces: `escanear_apu_tool(apu_tool_dir: Path) -> list[dict]` — cada registro:
  `{"modulo": str, "archivo": str, "paquete": str, "responsabilidad": str, "imports": list[str]}`

- [ ] **Step 1: Escribir los tests que fallan**

Actualizar el import en `tests/test_mapa_arquitectura.py`:

```python
from scripts.mapa_arquitectura import (
    escanear_apu_tool,
    imports_internos,
    paquete_de_modulo,
    responsabilidad_de_modulo,
)
```

Agregar al final del archivo:

```python
def test_escanear_apu_tool(tmp_path):
    raiz = tmp_path / "apu_tool"
    (raiz / "nucleo").mkdir(parents=True)
    (raiz / "dominio").mkdir(parents=True)
    (raiz / "nucleo" / "__init__.py").write_text("", encoding="utf-8")
    (raiz / "dominio" / "__init__.py").write_text("", encoding="utf-8")
    (raiz / "nucleo" / "models.py").write_text('"""Tipos puros."""\n', encoding="utf-8")
    (raiz / "dominio" / "pricing.py").write_text(
        '"""Motor de costos."""\nfrom apu_tool.nucleo.models import Insumo\n',
        encoding="utf-8",
    )
    (raiz / "config.py").write_text('"""Config transversal."""\n', encoding="utf-8")

    registros = escanear_apu_tool(raiz)

    por_modulo = {r["modulo"]: r for r in registros}
    assert set(por_modulo) == {
        "apu_tool.nucleo.models",
        "apu_tool.dominio.pricing",
        "apu_tool.config",
    }
    assert por_modulo["apu_tool.dominio.pricing"]["paquete"] == "dominio"
    assert por_modulo["apu_tool.dominio.pricing"]["archivo"] == "pricing.py"
    assert por_modulo["apu_tool.dominio.pricing"]["imports"] == ["apu_tool.nucleo.models"]
    assert por_modulo["apu_tool.dominio.pricing"]["responsabilidad"] == "Motor de costos."
    assert por_modulo["apu_tool.config"]["paquete"] == "raíz"
    assert por_modulo["apu_tool.config"]["archivo"] == "config.py"


def test_escanear_apu_tool_agrupa_pg_bajo_datos(tmp_path):
    raiz = tmp_path / "apu_tool"
    (raiz / "datos" / "pg").mkdir(parents=True)
    (raiz / "datos" / "__init__.py").write_text("", encoding="utf-8")
    (raiz / "datos" / "pg" / "__init__.py").write_text("", encoding="utf-8")
    (raiz / "datos" / "pg" / "precios_pg.py").write_text(
        '"""Backend Postgres de precios."""\n', encoding="utf-8"
    )

    (registro,) = escanear_apu_tool(raiz)

    assert registro["modulo"] == "apu_tool.datos.pg.precios_pg"
    assert registro["paquete"] == "datos"
    assert registro["archivo"] == "pg/precios_pg.py"


def test_escanear_apu_tool_excluye_init(tmp_path):
    raiz = tmp_path / "apu_tool"
    (raiz / "nucleo").mkdir(parents=True)
    (raiz / "nucleo" / "__init__.py").write_text("", encoding="utf-8")

    assert escanear_apu_tool(raiz) == []
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/test_mapa_arquitectura.py -q`
Expected: FAIL con `ImportError: cannot import name 'escanear_apu_tool'`.

- [ ] **Step 3: Implementar**

Agregar al final de `scripts/mapa_arquitectura.py`:

```python
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
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/test_mapa_arquitectura.py -q`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/mapa_arquitectura.py tests/test_mapa_arquitectura.py
git commit -m "$(cat <<'EOF'
feat(mapa-arquitectura): escanear apu_tool/ y armar registros por módulo

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Dependencias entre paquetes + diagrama Mermaid

**Files:**
- Modify: `scripts/mapa_arquitectura.py` (agregar al final)
- Modify: `tests/test_mapa_arquitectura.py` (agregar tests + actualizar el import)

**Interfaces:**
- Consumes: `paquete_de_modulo` (Task 2); registros con forma `{"paquete": str, "imports": list[str]}` (Task 3, aunque los tests de esta tarea usan dicts parciales)
- Produces: `dependencias_entre_paquetes(registros: list[dict]) -> list[tuple[str, str]]`,
  `diagrama_mermaid(aristas: list[tuple[str, str]]) -> str`

- [ ] **Step 1: Escribir los tests que fallan**

Actualizar el import:

```python
from scripts.mapa_arquitectura import (
    dependencias_entre_paquetes,
    diagrama_mermaid,
    escanear_apu_tool,
    imports_internos,
    paquete_de_modulo,
    responsabilidad_de_modulo,
)
```

Agregar al final del archivo:

```python
def test_dependencias_entre_paquetes_deduplica_y_excluye_autoreferencias():
    registros = [
        {"paquete": "dominio", "imports": ["apu_tool.nucleo.models"]},
        {"paquete": "dominio", "imports": ["apu_tool.nucleo.models", "apu_tool.dominio.otro"]},
        {"paquete": "servicio", "imports": ["apu_tool.dominio.pricing"]},
    ]

    aristas = dependencias_entre_paquetes(registros)

    assert aristas == [("dominio", "nucleo"), ("servicio", "dominio")]


def test_diagrama_mermaid_formato():
    diagrama = diagrama_mermaid([("dominio", "nucleo"), ("servicio", "dominio")])

    assert diagrama == (
        "```mermaid\n"
        "flowchart TD\n"
        "    dominio --> nucleo\n"
        "    servicio --> dominio\n"
        "```\n"
    )


def test_diagrama_mermaid_vacio():
    assert diagrama_mermaid([]) == "```mermaid\nflowchart TD\n```\n"
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/test_mapa_arquitectura.py -q`
Expected: FAIL con `ImportError: cannot import name 'dependencias_entre_paquetes'`.

- [ ] **Step 3: Implementar**

Agregar al final de `scripts/mapa_arquitectura.py`:

```python
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
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/test_mapa_arquitectura.py -q`
Expected: PASS (11 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/mapa_arquitectura.py tests/test_mapa_arquitectura.py
git commit -m "$(cat <<'EOF'
feat(mapa-arquitectura): dependencias entre paquetes + diagrama Mermaid

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Secciones por paquete + nota completa del mapa

**Files:**
- Modify: `scripts/mapa_arquitectura.py` (agregar al final)
- Modify: `tests/test_mapa_arquitectura.py` (agregar tests + actualizar el import)

**Interfaces:**
- Consumes: `escanear_apu_tool`, `dependencias_entre_paquetes`, `diagrama_mermaid` (Tasks 3-4)
- Produces: `seccion_paquete(nombre_paquete: str, registros: list[dict]) -> str`,
  `generar_mapa_arquitectura(apu_tool_dir: Path) -> str`

- [ ] **Step 1: Escribir los tests que fallan**

Actualizar el import:

```python
from scripts.mapa_arquitectura import (
    dependencias_entre_paquetes,
    diagrama_mermaid,
    escanear_apu_tool,
    generar_mapa_arquitectura,
    imports_internos,
    paquete_de_modulo,
    responsabilidad_de_modulo,
    seccion_paquete,
)
```

Agregar al final del archivo:

```python
def test_seccion_paquete_tabla_ordenada_por_archivo():
    registros = [
        {"paquete": "dominio", "archivo": "pricing.py", "responsabilidad": "Motor de costos"},
        {"paquete": "dominio", "archivo": "alertas.py", "responsabilidad": "Alertas de costeo"},
        {"paquete": "nucleo", "archivo": "models.py", "responsabilidad": "Tipos puros"},
    ]

    tabla = seccion_paquete("dominio", registros)

    assert tabla == (
        "| Archivo | Responsabilidad |\n"
        "| --- | --- |\n"
        "| `alertas.py` | Alertas de costeo |\n"
        "| `pricing.py` | Motor de costos |\n"
    )


def test_seccion_paquete_vacia():
    assert seccion_paquete("interfaz", []) == "_(vacío)_\n"


def test_generar_mapa_arquitectura_integracion(tmp_path):
    raiz = tmp_path / "apu_tool"
    (raiz / "nucleo").mkdir(parents=True)
    (raiz / "dominio").mkdir(parents=True)
    (raiz / "nucleo" / "models.py").write_text('"""Tipos puros."""\n', encoding="utf-8")
    (raiz / "dominio" / "pricing.py").write_text(
        '"""Motor de costos."""\nfrom apu_tool.nucleo.models import Insumo\n',
        encoding="utf-8",
    )

    mapa = generar_mapa_arquitectura(raiz)

    assert "# Mapa de módulos — apu_tool/" in mapa
    assert "No editar" in mapa
    assert "dominio --> nucleo" in mapa
    assert "`models.py`" in mapa
    assert "`pricing.py`" in mapa
    assert "Motor de costos" in mapa


def test_generar_mapa_arquitectura_es_idempotente(tmp_path):
    raiz = tmp_path / "apu_tool"
    (raiz / "nucleo").mkdir(parents=True)
    (raiz / "nucleo" / "models.py").write_text('"""Tipos puros."""\n', encoding="utf-8")

    assert generar_mapa_arquitectura(raiz) == generar_mapa_arquitectura(raiz)
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/test_mapa_arquitectura.py -q`
Expected: FAIL con `ImportError: cannot import name 'seccion_paquete'`.

- [ ] **Step 3: Implementar**

Agregar al final de `scripts/mapa_arquitectura.py`:

```python
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
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/test_mapa_arquitectura.py -q`
Expected: PASS (15 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/mapa_arquitectura.py tests/test_mapa_arquitectura.py
git commit -m "$(cat <<'EOF'
feat(mapa-arquitectura): generar la nota completa del mapa de módulos

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Integrar el mapa en `actualizar_vault.py` (main + Índice.md)

**Files:**
- Modify: `scripts/actualizar_vault.py`
- Modify: `tests/test_actualizar_vault.py`

**Interfaces:**
- Consumes: `generar_mapa_arquitectura` (Task 5, de `scripts.mapa_arquitectura`)

- [ ] **Step 1: Escribir los tests que fallan**

En `tests/test_actualizar_vault.py`, agregar el import al encabezado (junto a
los existentes de `scripts.actualizar_vault`):

```python
from scripts.mapa_arquitectura import generar_mapa_arquitectura
```

Modificar `_armar_repo_fixture` para agregar un `apu_tool/` mínimo real (con al
menos un archivo, para que `generar_mapa_arquitectura` tenga algo que
escanear) — agregar estas líneas justo antes de `vault = raiz /
"constructor-apus"`:

```python
    (raiz / "apu_tool" / "nucleo").mkdir(parents=True)
    (raiz / "apu_tool" / "nucleo" / "models.py").write_text(
        '"""Tipos puros del dominio."""\n', encoding="utf-8"
    )
```

Modificar `test_main_puebla_la_vault_y_borra_bienvenido` agregando esta
aserción (junto a las demás `assert (vault / ... ).exists()`):

```python
    assert (vault / "Arquitectura" / "Mapa de módulos.md").exists()
```

Modificar `test_generar_indice_incluye_secciones_y_conteos` agregando esta
aserción al final del bloque de asserts existente:

```python
    assert "[[Arquitectura/Mapa de módulos|Mapa de módulos — apu_tool/]]" in indice
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/test_actualizar_vault.py -q`
Expected: FAIL — el bullet del mapa no está en `Índice.md` todavía, y
`constructor-apus/Arquitectura/Mapa de módulos.md` no se crea.

- [ ] **Step 3: Aplicar el import y wirear `generar_indice`**

En `scripts/actualizar_vault.py`, agregar el import bajo los existentes (~línea 12):

```python
from scripts.mapa_arquitectura import generar_mapa_arquitectura
```

En `generar_indice`, agregar una línea al final del bloque `referencia` (justo
después de `referencia += enlace_bullet("Proyecto", raiz / "CLAUDE.md")`):

```python
    referencia += "- [[Arquitectura/Mapa de módulos|Mapa de módulos — apu_tool/]]\n"
```

- [ ] **Step 4: Wirear `main()`**

En `main()`, agregar esta llamada justo antes de la línea `escribir_si_cambia(vault / "Índice.md", generar_indice(docs))`:

```python
    escribir_si_cambia(
        vault / "Arquitectura" / "Mapa de módulos.md",
        generar_mapa_arquitectura(raiz / "apu_tool"),
    )
```

- [ ] **Step 5: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/test_actualizar_vault.py -q`
Expected: PASS (todos los tests existentes + los modificados).

- [ ] **Step 6: Correr la suite completa**

Run: `python -m pytest tests/ -q`
Expected: verde, sin regresiones (incluye `test_mapa_arquitectura.py` de las
Tasks 2-5).

- [ ] **Step 7: Commit**

```bash
git add scripts/actualizar_vault.py tests/test_actualizar_vault.py
git commit -m "$(cat <<'EOF'
feat(vault): integrar el mapa de arquitectura en main() e Índice.md

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Generar el mapa real en la vault

**Files:**
- (generado por el script) `constructor-apus/Arquitectura/Mapa de módulos.md`, `constructor-apus/Índice.md` (actualizado)

**Interfaces:**
- Consumes: `main()` (Task 6) vía el hook `pre-commit` ya activo

- [ ] **Step 1: Correr el script standalone**

Run: `python scripts/actualizar_vault.py`
Expected: sin error. Verificar a mano:
- `constructor-apus/Arquitectura/Mapa de módulos.md` existe y tiene un bloque
  ` ```mermaid ` con al menos las aristas `dominio --> nucleo`, `datos -->
  nucleo`, `servicio --> dominio`, `servicio --> datos`, `interfaz -->
  dominio` (el grafo real de `apu_tool/` hoy).
- Las seis secciones (`nucleo/`, `datos/`, `dominio/`, `servicio/`,
  `interfaz/`, `raíz`) tienen tablas no vacías salvo quizás `raíz` (solo
  `config.py`).
- `constructor-apus/Índice.md` tiene el nuevo bullet del mapa en "Arquitectura
  y referencia".

- [ ] **Step 2: Correr la suite completa**

Run: `python -m pytest tests/ -q`
Expected: verde.

- [ ] **Step 3: Revisar qué va a entrar al commit**

Run: `git add constructor-apus && git status --short`
Expected: solo cambios dentro de `constructor-apus/` (el nuevo `Mapa de
módulos.md`, el `Índice.md` actualizado, y el churn habitual de
`.obsidian/graph.json` si Obsidian estuvo abierto).

- [ ] **Step 4: Commit (dispara el hook ya activo)**

```bash
git commit -m "$(cat <<'EOF'
chore(vault): generar el mapa de arquitectura real en la vault

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 5: Verificar el resultado final**

Run: `git show --stat HEAD`
Expected: el commit incluye `constructor-apus/Arquitectura/Mapa de
módulos.md` (nuevo) y `constructor-apus/Índice.md` (modificado).

---

## Verificación final (tras todas las tareas)

- [ ] `python -m pytest tests/ -q` → verde.
- [ ] Releer `CLAUDE.md` y `docs/ARQUITECTURA.md`: la estructura de paquetes
  coincide con la real (`nucleo`, `datos` +`pg/`, `dominio`, `servicio`,
  `interfaz`), y ningún paso del roadmap dice "futuro" para algo ya construido.
- [ ] Abrir `constructor-apus/Arquitectura/Mapa de módulos.md` en Obsidian y
  confirmar que el diagrama Mermaid renderiza (no queda como bloque de código
  crudo).
- [ ] Manual (opcional): agregar un archivo nuevo a `apu_tool/dominio/` con un
  import a `apu_tool/nucleo/`, commitear, y confirmar que el mapa se actualiza
  solo (nueva fila en la tabla de `dominio/`, sin tocar el resto).

## Self-Review (cobertura del spec)

- Corrección de `CLAUDE.md`/`ARQUITECTURA.md` → Task 1, contenido exacto
  tomado del spec (Partes 1 y 2).
- Mapa auto-generado, alcance solo backend → Tasks 2-5 (`scripts/mapa_arquitectura.py`),
  no toca `web/src`.
- Imports absolutos únicamente, relativos ignorados → Task 2, test dedicado
  (`test_imports_internos_ignora_relativos`).
- Agrupación por paquete con `datos/pg` bajo `datos` → Task 2 (`paquete_de_modulo`)
  + Task 3, test dedicado (`test_escanear_apu_tool_agrupa_pg_bajo_datos`).
- Diagrama Mermaid + tablas por paquete → Task 4 (diagrama) + Task 5 (tablas
  y nota completa).
- Determinístico e idempotente → `test_generar_mapa_arquitectura_es_idempotente`
  (Task 5); `rglob` ordenado y aristas `sorted(set(...))` en la implementación.
- Integración con la vault (main + Índice) → Task 6.
- No depende de nada nuevo (solo `ast`/`pathlib`) → verificado en cada Task,
  ningún import fuera de stdlib en `scripts/mapa_arquitectura.py`.
