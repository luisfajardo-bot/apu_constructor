# Diseño — Autoría de la base: agregar insumos y APUs (etapa 3, sub-proyecto 1)

> Fecha: 2026-06-30
> Estado: aprobado para implementación
> Contexto: hoy la base solo se **edita** (precios/fuentes) o se **siembra** desde el
> Excel fuente. Se necesita **agregar** insumos y APUs nuevos desde la app —
> individual (formulario) y por Excel (varios) — para, entre otras cosas, completar
> a mano las obras especiales (sub-proyecto 2) sin re-sembrar (que borra corridas).

## Objetivo

Poder **crear** en la base, desde la app:
- **Insumos** nuevos: `código, nombre, unidad, grupo, precio, fuente`.
- **APUs** nuevos con **composición**: `código, turno, nombre, unidad, grupo` + filas
  `insumo + rendimiento`.

Ambos: **individual** (formulario) y **por Excel** (lote), con **preview antes de
aplicar** (qué se creará / qué ya existe / qué es ambiguo). Aditivo: no re-siembra,
no borra nada.

## Global Constraints (cero regresiones)

- No se toca matching / costeo / corridas. Todo es **aditivo**.
- Persistencia aislada en `apu_tool/datos/` (sin SQL crudo fuera). Edición de catálogo
  ve dinero pero **nunca** abre camino a la IA (Invariante #1: sin `ai_assist` en
  `servicio/`).
- Identidades existentes del esquema: insumo = `(código, nombre_norm)`; APU =
  `(código, turno)`; componente liga al insumo por código (**enlace blando, sin FK**).
- No sobrescribir en silencio: crear algo que ya existe se **reporta**, no se pisa.
- UI densa, table-first, sin cards; imports `@/`. `pytest -q` verde; `npm run build` 0 TS.

## Modelo de datos (sin cambios de esquema)

- `insumos(id, codigo, nombre, nombre_norm, unidad, grupo)` + `insumo_precios(insumo_id,
  precio, fuente, clasificacion, fecha, vigente)`. Crear insumo = fila en `insumos` +
  fila `insumo_precios` vigente. `clasificacion` se deriva de `fuente`
  (`config.classify_price_source`).
- `apus(codigo, shift, nombre, unidad, grupo)` PK `(codigo, shift)` +
  `apu_componentes(apu_codigo, shift, seq, insumo_codigo, insumo_nombre, unidad,
  rendimiento, precio_unitario_hist)`. Crear APU = fila en `apus` + sus componentes.

## Backend

### B.1 — Capa de datos (nuevos métodos de creación)

- `PreciosDB.crear_insumo(insumo: Insumo) -> int`: si `(codigo, nombre_norm)` ya existe
  → `ValueError` ("ya existe"); si no, inserta el insumo y su precio vigente
  (reusa `_insertar_precio_vigente`); devuelve el `id` nuevo. (Hoy `insert_insumos`
  hace INSERT OR IGNORE en lote; este método es la creación atómica con detección de
  duplicado y devolución del id.)
- `ApusDB.crear_apu(apu: Apu, componentes: list[ApuComponent]) -> None`: si `(codigo,
  shift)` ya existe → `ValueError`; si no, inserta el APU (sin `INSERT OR REPLACE`, para
  no pisar) y sus componentes con `seq` correlativo (reusa la lógica de
  `insert_components`). Cada componente resuelve `insumo_nombre`/`unidad` desde la base
  si el código existe; si no, guarda lo que venga (enlace blando) y queda como aviso.
- Ambos métodos al Protocol (`RepositorioPrecios`, `RepositorioApus`).
- **Lectura nueva para la página de APUs:** `ApusDB.list_apus(q=None, grupo=None,
  shift=None, limit=100, offset=0) -> tuple[list[Apu], int]` (paginado, como
  `list_insumos`). `get_apu`/`get_components` ya existen para el detalle/composición.

### B.2 — Servicio `apu_tool/servicio/autoria.py` (nuevo)

Separado de `corridas`/`insumos`. Valida + arma preview + aplica. No toca IA.

- **Insumo individual:** `crear_insumo(alm, datos) -> dict`. Valida: `codigo` y `nombre`
  no vacíos, `precio >= 0`. Llama `precios.crear_insumo`. Devuelve el insumo creado o
  error claro si ya existe.
- **APU individual:** `crear_apu(alm, datos) -> dict`. Valida: `codigo`, `nombre`,
  `turno ∈ {DIURNO,NOCTURNO}`; componentes con `rendimiento > 0`. Llama `apus.crear_apu`.
- **Import insumos (crear):** `preview_importar_insumos(alm, contenido, nombre) -> dict`
  con columnas `codigo, nombre, unidad, grupo, precio, fuente`. Clasifica cada fila:
  `crear` (no existe la identidad), `ya_existe` (existe `(codigo, nombre_norm)`),
  `invalida` (faltan campos). `aplicar_importar_insumos(alm, filas) -> dict` crea las
  marcadas `crear`. (Distinto del import de **precios** existente, que actualiza por
  código; este es para **altas**.)
- **Import APUs (crear):** `preview_importar_apus(alm, contenido, nombre) -> dict` y
  `aplicar_importar_apus(...)`. **Reutiliza el parser del seed** `seed._read_apus(wb)`
  (mismo formato de la hoja `APUS`: fila cabecera con COD IDU + actividad + unidad +
  turno; luego filas de componente). Preview lista los APUs a crear (con nº de
  componentes) y marca los `(codigo, turno)` que ya existen como `ya_existe` (no se
  pisan). **No** aplica las `correcciones` del seed (esas son del histórico original;
  los APUs que el usuario sube van tal cual).

### B.3 — API `apu_tool/servicio/rutas.py`

- `POST /api/insumos/crear` → `autoria.crear_insumo` (400 en ValueError).
- `POST /api/insumos/importar-crear/preview` (multipart) → `preview_importar_insumos`.
- `POST /api/insumos/importar-crear` → `aplicar_importar_insumos`.
- `GET /api/apus` → `list_apus` (lista paginada para la página de APUs; filtros q/grupo/turno).
- `GET /api/apus/{codigo}/{shift}` → APU + composición (detalle).
- `POST /api/apus/crear` → `autoria.crear_apu`.
- `POST /api/apus/importar/preview` (multipart) + `POST /api/apus/importar` → APUs por Excel.
- Esquemas Pydantic nuevos en `esquemas.py`: `InsumoNuevoIn`, `ApuNuevoIn`
  (con `componentes: list[ComponenteIn]`).

## Frontend (densa, table-first)

- **Página Insumos** (existente): botón **"Agregar insumo"** → formulario pequeño
  (código, nombre, unidad, grupo, precio, fuente) con preview/confirmación; y en el
  importador, una pestaña/acción **"Importar para crear"** (formato con nombre/unidad/
  grupo) que muestra el preview `crear / ya_existe / inválida` antes de aplicar.
- **Nueva página "APUs"** en el nav: tabla densa de APUs (código, turno, nombre, unidad,
  grupo, nº componentes) con búsqueda; **"Agregar APU"** → formulario con sub-tabla de
  composición (buscar insumo en la base + rendimiento, agregar/quitar filas); **"Importar
  APUs (Excel)"** con preview. Ver composición de un APU (desplegable, opcional, reusa
  el patrón de `TablaItems`).
- `web/src/api/` y `lib/tipos.ts`: tipos y llamadas nuevas (`crearInsumo`,
  `previewImportInsumos`, `crearApu`, `listarApus`, `previewImportApus`, etc.).

## Errores y pruebas

**Errores:** crear duplicado (identidad existente) → mensaje claro, no pisa. Excel sin
columnas requeridas → 400 con qué falta. Rendimiento ≤ 0 o campos vacíos → inválido en
preview. Componente que referencia un insumo inexistente → se crea (enlace blando) con
**aviso** (cruce huérfano al costear, comportamiento ya existente).

**Pruebas (pytest):**
- `crear_insumo`: crea + precio vigente; duplicado `(codigo, nombre_norm)` → ValueError;
  mismo código con otro nombre → permitido (identidad distinta).
- `crear_apu`: crea APU + componentes con `seq` correlativo; `(codigo, turno)` duplicado
  → ValueError; `get_apu`/`get_components` lo devuelven; costeo del APU nuevo da el costo
  esperado (vía `pricing`, sin cambios en el motor).
- `list_apus`: paginación y filtros.
- Servicio: preview de import insumos (crear/ya_existe/invalida) y de import APUs
  (reusa `_read_apus`, marca existentes); aplicar crea lo correcto.
- API (TestClient): cada endpoint, incl. duplicado → 400 y Excel malo → 400.
- Tests existentes verdes (nada de matching/costeo/corridas cambió).

**Frontend (Vitest, ligero):** validación del formulario (campos requeridos, rendimiento
> 0); build verde. Verificación en vivo (controlador): agregar un insumo y un APU, e
importar un Excel de cada uno.

## No romper

- `insert_insumos` / `insert_apus` / `insert_components` (usados por el seed) **no
  cambian**. Los métodos nuevos son aparte. El seed sigue igual.
- Re-seed sigue siendo la única vía que borra/recrea; la autoría **no** resetea nada.

## Criterios de aceptación

1. Agregar un insumo (individual y por Excel) lo deja consultable y disponible para
   costear; duplicados se reportan sin pisar.
2. Agregar un APU con composición (individual y por Excel) lo deja en la biblioteca,
   costeable como cualquier APU histórico.
3. La página de APUs lista/busca y permite agregar/importar; Insumos gana agregar/importar-crear.
4. `pytest` verde; `npm run build` 0 TS; Invariante #1 intacto; nada de corridas/seed cambió.

## Dependencias

Ninguna nueva. Habilita el sub-proyecto 2 (obras especiales: completar a mano el ítem
faltante y que el cuadro lo recostee en vivo).
