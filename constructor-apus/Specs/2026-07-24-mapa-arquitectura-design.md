> Espejo automático — no editar aquí. Fuente: `docs/superpowers/specs/2026-07-24-mapa-arquitectura-design.md`

# Diseño — Corrección de docs de arquitectura + mapa auto-generado de módulos

> Fecha: 2026-07-24
> Estado: propuesto (aprobado en brainstorming; pendiente de revisión del spec escrito)
> Rama de trabajo sugerida: `feat/mapa-arquitectura`

## Objetivo

Al usar la vault de Obsidian (`constructor-apus/`), lo único "vivo" y confiable es la
lista de specs — la arquitectura documentada (`CLAUDE.md`, `docs/ARQUITECTURA.md`) quedó
desactualizada frente al código real: `CLAUDE.md` describe una estructura plana
(`models.py`, `db.py`, `pricing.py`...) que ya no existe, y `ARQUITECTURA.md` describe
como "futuro" cosas que ya están construidas (backend Postgres, API FastAPI completa,
frontend web ya compilado). Este proyecto (1) corrige ambos documentos a mano para que
reflejen la estructura real de paquetes, y (2) agrega a la vault un **mapa de módulos
auto-generado** desde los imports reales de `apu_tool/`, que nunca puede desactualizarse
porque se recalcula en cada commit — a diferencia de la prosa a mano, que ya demostró
poder desviarse.

## Decisiones tomadas (brainstorming)

- **Corregir los docs a mano + agregar el mapa auto-generado** (ambas cosas, no solo una).
- **Formato del mapa:** diagrama **Mermaid** (Obsidian lo renderiza nativo) de
  dependencias entre paquetes, más una tabla de archivos por paquete con su
  responsabilidad (para ver "los diferentes archivos", no solo el diagrama).
- **Alcance:** solo backend Python (`apu_tool/`). No se mapea `web/src` (TypeScript) —
  parsear imports de TS es una lógica distinta; queda fuera por ahora.
- **Imports absolutos únicamente:** el mapa resuelve `from apu_tool.X.Y import ...`
  absolutos (`ast.ImportFrom` con `level == 0`). Se verificó que el proyecto no usa
  imports relativos ni `import apu_tool.X` plano en ningún archivo de `apu_tool/`
  (`grep` sin resultados) — no hace falta resolver esos casos.

## Parte 1 — Corrección de `CLAUDE.md`

Reemplazar la sección `## Arquitectura (flujo)` completa (la tabla `| Módulo |
Responsabilidad |` y el diagrama de flujo) por el siguiente contenido exacto:

```markdown
## Arquitectura (flujo)

```
Excel histórico ──seed──► SQLite/Postgres (precios, apus, corridas, perfiles, auditoría)
lista licitación ──► matching ──► IA acotada (sin dinero) ──► confirma usuario
                                       └─► motor de precios ──► cuadro resumen (Excel)

Interfaces sobre el mismo pipeline (dominio/pipeline.py):
  interfaz/{cli,gui}.py (local) · servicio/ (FastAPI, 44 endpoints) + web/ (React) para multiusuario
```

`apu_tool/config.py` es transversal, fuera de cualquier paquete: rutas, umbrales de
matching, modelo de IA, clasificación de precios.

### `apu_tool/nucleo/` — tipos y utilidades puras (sin dependencias de otras capas)

| Módulo | Responsabilidad |
|--------|-----------------|
| `models.py`   | tipos del dominio; vistas `DePriced*` SIN dinero |
| `redondeo.py` | redondeo a la unidad (peso) en multiplicaciones monetarias |
| `texto.py`    | normalización de texto compartida |

### `apu_tool/datos/` — persistencia (**toda** la persistencia pasa por aquí)

| Módulo | Responsabilidad |
|--------|-----------------|
| `repositorio.py`  | contratos de almacenamiento (`Protocol`), por dominio |
| `precios_db.py`   | SQLite de `precios.db` (catálogo + precios) |
| `apus_db.py`      | SQLite de `apus.db` (biblioteca de APUs) |
| `carpetas_db.py`  | SQLite de carpetas de corridas |
| `corridas_db.py`  | SQLite de `corridas.db` (estado de corridas en curso) |
| `auditoria_db.py` | SQLite de auditoría (`seguridad.db`) |
| `perfiles_db.py`  | SQLite de perfiles (identidad + rol) |
| `almacen.py`      | fachada que agrupa los repos SQLite/Postgres |
| `seed.py`         | ingesta Excel histórico → bases |
| `correcciones.py` | correcciones de código aplicadas al semillar |
| `migracion_pg.py` | migración SQLite → Postgres (Supabase); corridas NO se migran |
| `pg/`             | backend Postgres (espejo 1:1 de los `*_db.py`, para la nube) |

### `apu_tool/dominio/` — motor de negocio (`pricing.py` es el **único** que ve dinero)

| Módulo | Responsabilidad |
|--------|-----------------|
| `licitacion.py`          | lectura de la lista de entrada + generador de ejemplo |
| `presupuesto.py`         | lectura del presupuesto oficial por capítulos |
| `matching.py`            | matcher determinístico (fuzzy, sin dependencias externas) |
| `cruce.py`               | cruce insumo-de-APU ↔ insumo-de-catálogo por código+nombre |
| `compose.py`             | candidatos de insumos para composición generativa |
| `privacy.py`             | frontera de precios para la IA (invariante #1) |
| `ai_assist.py`           | IA acotada (Anthropic SDK) + fallback determinístico |
| `assemble.py`            | orquestador por ítem |
| `pricing.py`             | motor de costos (**ÚNICO** que ve dinero) |
| `alertas.py`             | alertas de costeo (por qué un ítem necesita revisión) |
| `report.py`              | cuadro resumen en Excel |
| `report_categorizado.py` | cuadro resumen agrupado por capítulos de presupuesto |
| `integridad.py`          | chequeo de integridad del vínculo APU↔insumo |
| `pipeline.py`            | orquestación de alto nivel (la usan CLI, GUI y el servicio web) |

### `apu_tool/servicio/` — API web (FastAPI)

| Módulo | Responsabilidad |
|--------|-----------------|
| `app.py`               | arma la app FastAPI: monta `/api`, sirve `web/dist`, middlewares de seguridad |
| `rutas.py`             | el único `APIRouter`; todos los endpoints HTTP (delega a los módulos de abajo) |
| `dependencias.py`      | inyección de dependencias (el `Almacen` vive en `app.state`) |
| `esquemas.py`          | DTOs del contrato HTTP |
| `auth.py`              | autenticación (Supabase Auth) + autorización por rol |
| `limites.py`           | límite de tamaño de subida + rate limiting |
| `seguridad_headers.py` | middleware de headers de seguridad (HSTS, CSP, etc.) |
| `corridas.py`          | lógica de servicio de corridas (armado en vivo) |
| `insumos.py`           | lógica de servicio para editar insumos |
| `autoria.py`           | alta de insumos/APUs nuevos |
| `subapus.py`           | migración: marca componentes que son sub-APU |
| `apus.py`              | lectura de la biblioteca de APUs |
| `carpetas.py`          | reglas de carpetas de corridas |
| `usuarios.py`          | gestión de usuarios (solo Admin) |
| `auditoria.py`         | servicio de auditoría (registro + lectura paginada) |
| `supabase_admin.py`    | cliente de la Admin API de Supabase Auth |
| `plantillas.py`        | plantillas `.xlsx` para importadores |

### `apu_tool/interfaz/` — puntos de entrada

| Módulo | Responsabilidad |
|--------|-----------------|
| `cli.py` | línea de comandos |
| `gui.py` | interfaz gráfica (Tkinter) |
```

## Parte 2 — Corrección de `docs/ARQUITECTURA.md`

Cambios puntuales sobre el archivo existente (no reescribir todo el documento, solo estas
secciones):

**a) Tabla "Las cuatro capas" (línea ~29-34) — columna Estado:**

| Nivel | Capa | Estado actual (reemplaza) |
|------:|------|------|
| 01 | Plataforma de datos | `base` → **`existe hoy (SQLite + Postgres)`** |
| 02 | Dominio / motor | `existe hoy` → sin cambio |
| 03 | Servicio / API | `futuro` → **`existe hoy (FastAPI, 44 endpoints)`** |
| 04 | Interfaz | `CLI/GUI hoy, web futuro` → **`existe hoy (CLI, GUI y web)`** |

**b) Bloque "Estructura de carpetas (objetivo)" (línea ~52-86) — reemplazar el árbol
completo por:**

```
intento_plan/
├── apu_tool/
│   ├── config.py                  # transversal: rutas, umbrales, modelo IA
│   ├── nucleo/                    ── KERNEL COMPARTIDO
│   │   ├── models.py              #   dataclasses puras (Insumo, Apu, DePriced*)
│   │   ├── redondeo.py            #   redondeo a la unidad en multiplicaciones monetarias
│   │   └── texto.py               #   normalización de texto compartida
│   │
│   ├── datos/                     ── NIVEL 01 · plataforma de datos
│   │   ├── repositorio.py         #   Protocols de almacenamiento
│   │   ├── precios_db.py   apus_db.py   carpetas_db.py   corridas_db.py
│   │   ├── auditoria_db.py   perfiles_db.py
│   │   ├── almacen.py             #   fachada Almacen (agrupa SQLite/Postgres)
│   │   ├── seed.py   correcciones.py
│   │   ├── migracion_pg.py        #   migración SQLite → Postgres
│   │   └── pg/                    #   backend Postgres (espejo 1:1 de los *_db.py)
│   │
│   ├── dominio/                   ── NIVEL 02 · motor (lógica pura)
│   │   ├── licitacion.py   presupuesto.py   matching.py   cruce.py   compose.py
│   │   ├── privacy.py   ai_assist.py   assemble.py
│   │   ├── pricing.py   alertas.py   report.py   report_categorizado.py
│   │   ├── integridad.py          #   chequeo de integridad APU↔insumo
│   │   └── pipeline.py            #   orquestación (usa datos + dominio)
│   │
│   ├── servicio/                  ── NIVEL 03 · API (FastAPI) — 44 endpoints
│   │   ├── app.py   rutas.py   dependencias.py   esquemas.py
│   │   ├── auth.py   limites.py   seguridad_headers.py
│   │   └── corridas.py   insumos.py   autoria.py   subapus.py   apus.py
│   │       carpetas.py   usuarios.py   auditoria.py   supabase_admin.py   plantillas.py
│   │
│   └── interfaz/                  ── NIVEL 04 · interfaces
│       ├── cli.py   gui.py
│
├── db/                            # DDL canónico (SQL): precios, apus, corridas, seguridad
├── data/                          # bases mantenidas: precios.db, apus.db, corridas.db, seguridad.db
├── salidas/                       # cuadros generados
├── ejemplos/                      # licitaciones de ejemplo
├── tests/
├── web/                           # frontend React ya construido (Vite + TS + Supabase)
├── constructor-apus/              # vault de Obsidian auto-mantenida (ver su propio spec)
├── docs/                          # ARQUITECTURA.md + superpowers/{specs,plans}
├── run_cli.py   run_gui.py   run_web.py   requirements.txt
```

**c) Sección "Hoja de ruta" (línea ~88-102) — reemplazar completa por:**

```markdown
## Hoja de ruta

Los pasos 1 a 5 ya están construidos; el proyecto pasó de roadmap a mantenimiento y
features incrementales (ver `docs/superpowers/plans/` y `docs/superpowers/specs/` para
el historial de features desde entonces).

1. ✅ **Datos canónicos y separados** — reorganización completa a la estructura por capas.
2. ✅ **Dominio como librería con API clara.**
3. ✅ **Postgres** — `datos/pg/` implementa los repositorios contra Supabase; `datos/almacen.py`
   elige el backend. Migración con `datos/migracion_pg.py`.
4. ✅ **Capa de servicio / API (FastAPI)** — `servicio/`, 44 endpoints, auth Supabase + RBAC,
   rate limiting, headers de seguridad.
5. ✅ **App web** — `web/` (React + TypeScript + Vite), consume la API, servida por
   `servicio/app.py` desde `web/dist`.
6. **Endurecer multiusuario** — auth/RBAC y auditoría ya en producción; optimización de
   round-trips a Postgres ya hecha (ver `perf-corrida-optimizacion` en el historial de
   specs). Concurrencia y roles finos sobre precios se siguen evaluando caso a caso, sin
   un ítem de trabajo abierto puntual hoy.

*(La normalización de insumos —skill `apu-civil:apu-normalizar`— se usó para limpiar la
data canónica durante los pasos 1–3.)*
```

## Parte 3 — Mapa de módulos auto-generado

### Nuevo módulo: `scripts/mapa_arquitectura.py`

Solo librería estándar (`ast`, `pathlib`). Analiza `apu_tool/` con el módulo `ast` (no
regex): la responsabilidad de cada archivo es la primera línea de su docstring de
módulo (`ast.get_docstring`); sus dependencias internas son los `from apu_tool.X.Y
import ...` absolutos (`ast.ImportFrom` con `node.level == 0`).

**Agrupación por paquete:** el paquete de un módulo `apu_tool.X.Y...` es `X` si `X` está
en `("nucleo", "datos", "dominio", "servicio", "interfaz")`; si no (p. ej.
`apu_tool.config`), el paquete es `"raíz"`. `datos/pg/*` se agrupa bajo `"datos"` (es una
subcarpeta de implementación, no una capa arquitectónica aparte) — así el diagrama tiene
5 nodos (más "raíz"), legible, en vez de un grafo de 50+ archivos.

**Funciones:**

- `responsabilidad_de_modulo(ruta: Path) -> str` — primera línea del docstring;
  fallback al nombre de archivo legible si no hay docstring.
- `imports_internos(ruta: Path) -> list[str]` — lista de módulos `apu_tool.*`
  importados de forma absoluta (`ImportFrom` con `level == 0`), en el orden en que
  aparecen en el archivo.
- `paquete_de_modulo(modulo_dotted: str) -> str` — `"nucleo"`, `"datos"`, `"dominio"`,
  `"servicio"`, `"interfaz"` o `"raíz"`, según la regla de arriba.
- `escanear_apu_tool(apu_tool_dir: Path) -> list[dict]` — recorre `apu_tool_dir.rglob("*.py")`
  (ordenado, excluyendo `__init__.py`); por archivo arma
  `{"modulo": str, "archivo": str, "paquete": str, "responsabilidad": str, "imports": list[str]}`,
  donde `"archivo"` es la ruta relativa **dentro** del paquete (p. ej. `"pricing.py"` o
  `"pg/precios_pg.py"`), y `"imports"` excluye el propio módulo (sin auto-referencias).
- `dependencias_entre_paquetes(registros: list[dict]) -> list[tuple[str, str]]` —
  aristas `(paquete_origen, paquete_destino)` deduplicadas (`set`), ordenadas
  (`sorted`), excluyendo aristas de un paquete hacia sí mismo.
- `diagrama_mermaid(aristas: list[tuple[str, str]]) -> str` — bloque ` ```mermaid /
  flowchart TD / paquete_a --> paquete_b / ``` ` con una línea por arista, en el orden
  ya determinístico que entrega `dependencias_entre_paquetes`.
- `seccion_paquete(nombre_paquete: str, registros: list[dict]) -> str` — tabla markdown
  `| Archivo | Responsabilidad |` de los registros de ese paquete, ordenados por
  `"archivo"`; `"_(vacío)_\n"` si no hay ninguno (mismo patrón que `tabla_markdown` en
  `actualizar_vault.py`).
- `generar_mapa_arquitectura(apu_tool_dir: Path) -> str` — arma la nota completa: título,
  aviso de autogenerado, el diagrama Mermaid, y una sección por cada uno de los 6 grupos
  (`nucleo`, `datos`, `dominio`, `servicio`, `interfaz`, `raíz`) en ese orden fijo.

**Determinismo:** `rglob` se ordena explícitamente (`sorted(...)`); las aristas son un
`set` convertido a `sorted(...)`; las tablas de cada paquete se ordenan por nombre de
archivo. Correr `generar_mapa_arquitectura` dos veces sin cambios en `apu_tool/` produce
el mismo string byte a byte.

### Integración con `scripts/actualizar_vault.py`

- `main()` agrega un paso: `escribir_si_cambia(vault / "Arquitectura" / "Mapa de
  módulos.md", generar_mapa_arquitectura(raiz / "apu_tool"))`.
- `generar_indice()` agrega, al final de la sección "Arquitectura y referencia", el
  bullet `"- [[Arquitectura/Mapa de módulos|Mapa de módulos — apu_tool/]]\n"` (link fijo,
  no hace falta leer el archivo generado para sacar el título — ya se conoce).
- La nota `Mapa de módulos.md` **no** lleva el aviso de "espejo" (`aviso_espejo`) porque
  no es la copia de un único archivo fuente; lleva su propio aviso de una línea:
  `"> Autogenerado por scripts/mapa_arquitectura.py en cada commit, desde los imports "
  "reales de apu_tool/. No editar — se regenera solo.\n\n"`.

## Pruebas

- `tests/test_mapa_arquitectura.py`:
  - `responsabilidad_de_modulo`: con docstring (primera línea) y sin docstring (fallback).
  - `imports_internos`: detecta `from apu_tool.dominio.pricing import X`; ignora imports
    de stdlib/terceros (`import re`, `from pathlib import Path`); ignora imports
    relativos (`from . import x`, `level > 0`) — verificado con un archivo de prueba que
    los tiene, para dejar constancia de que la limitación es intencional, no un olvido.
  - `paquete_de_modulo`: casos `apu_tool.dominio.pricing` → `dominio`,
    `apu_tool.datos.pg.precios_pg` → `datos`, `apu_tool.config` → `raíz`.
  - `escanear_apu_tool`: árbol de prueba (`tmp_path`) con 2-3 paquetes, `__init__.py`
    (debe excluirse), y un módulo transversal tipo `config.py` — verifica los campos de
    cada registro.
  - `dependencias_entre_paquetes`: aristas correctas, deduplicadas, sin auto-referencias
    (dos archivos del mismo paquete importándose entre sí no generan arista).
  - `diagrama_mermaid` y `seccion_paquete`: formato exacto, caso vacío.
  - `generar_mapa_arquitectura`: integración contra un árbol de prueba completo;
    idempotencia (correr dos veces sin cambios da el mismo string).
- `tests/test_actualizar_vault.py`: la fixture de `main()` (`_armar_repo_fixture`) se
  extiende con un `apu_tool/` mínimo (al menos un archivo en `dominio/` y uno en
  `nucleo/`, con un import real entre ellos) para que el nuevo paso de `main()` tenga
  algo real que escanear; se agrega la aserción de que
  `constructor-apus/Arquitectura/Mapa de módulos.md` existe tras correr `main()`.
- Se corre `pytest` completo como parte de verificar la feature.

## Fuera de alcance (YAGNI)

- Mapear `web/src` (TypeScript/React) — parsing de imports ES/TS es una lógica
  distinta; decidido explícitamente que no, por ahora.
- Resolver imports relativos (`from . import`, `from .. import`) — no se usan en el
  proyecto hoy (verificado); si aparecieran, `imports_internos` los ignora en silencio
  (comportamiento documentado, no un bug).
- Un grafo a nivel de archivo individual (50+ nodos) — se decidió agregar por paquete
  para que el diagrama sea legible; el detalle de archivos va en las tablas, no en el
  diagrama.
- Mantener sincronizada a mano la prosa de `CLAUDE.md`/`ARQUITECTURA.md` en el futuro —
  esta corrección es puntual (un mal estado detectado ahora); no se agrega automatización
  para mantener esa prosa al día (esa es justamente la razón de ser del mapa
  auto-generado, que sí se mantiene solo).
