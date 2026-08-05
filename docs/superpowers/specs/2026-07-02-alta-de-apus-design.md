# Diseño — Alta de APUs (biblioteca): crear/editar/borrar en web + importar Excel

> Fecha: 2026-07-02
> Estado: propuesto (pendiente de revisión del usuario)
> Antecede: `2026-06-24-frontend-web-p1-design.md`, que difirió explícitamente la
> **edición de composición de APUs** al "Proyecto 2". Este spec es ese Proyecto 2.
> Rama de trabajo: `feat/alta-de-apus` (todo local; sin pushes a GitHub).

## Objetivo

Hoy la biblioteca de APUs (`data/apus.db`) solo se puebla con `seed` (carga masiva
desde el Excel del IDU, con **reset**). No hay forma de dar de alta APUs nuevos ni de
editar los existentes salvo tocando la base a mano. Este proyecto agrega esa capacidad
por **dos caminos**:

1. **Gestión desde la web:** una pantalla **"APUs"** para **crear, editar y borrar**
   APUs (cabecera + composición de insumos con rendimiento).
2. **Importar desde Excel** en modo **agregar** (append, sin reset), con el **mismo
   formato de la hoja `APUS` del IDU**, reutilizando el lector que ya usa el `seed`.

La UI sigue la estética ya establecida: **práctica, densa, orientada a tabla, sin cards**.

## Decisiones de alcance

| Decisión | Elección |
|----------|----------|
| Código del APU | Lo **escribe el usuario** (viene del IDU). Obligatorio. Sin autogenerar. |
| Identidad | Un APU es `(codigo, shift)`. Editar **no** cambia esa identidad. |
| Composición | Se **seleccionan insumos del catálogo** (precios.db); si falta uno, se **crea al vuelo**. |
| Alcance de edición | **Crear + editar + borrar** APUs desde la web. |
| Import Excel | Formato hoja `APUS` del IDU; **reutiliza el parser del seed**; modo **append**. |
| Import: insumos | El importador también lee las hojas de insumos (como el seed) y ofrece agregarlos. |
| Import: conflictos | En preview se marca cada APU **NUEVO / YA EXISTE**; al confirmar se elige **omitir** o **reemplazar** los existentes. |
| Parseo de Excel | En el **servidor** (reusa `openpyxl`), como el resto del proyecto. |
| Precio histórico | Los componentes creados a mano dejan `precio_unitario_hist` vacío; el costo usa el precio **vigente** del insumo (comportamiento actual). |
| Despliegue | Local, sin login. |

**Fuera de alcance:** cambiar `codigo`/`shift` de un APU existente (= borrar + crear);
versionado/historial de cambios de APUs; resolución interactiva de códigos de insumo
ambiguos en el import (se listan como advertencia, no se aplican a ciegas); auth;
Postgres/nube.

## Arquitectura y estructura de archivos

El dominio (matching, pricing, assemble, ai_assist) **no se toca**. La gestión de APUs
es edición pura de la biblioteca y **no roza la IA** (invariante #1 intacto). Toda
persistencia nueva vive en `apu_tool/datos/`.

```
apu_tool/datos/parser_historico.py   [nuevo] parser de hojas APUS/insumos (extraído de seed.py)
apu_tool/datos/seed.py               refactor: usa parser_historico (mismo comportamiento)
apu_tool/datos/apus_db.py            + upsert_apu, replace_components, delete_apu, exists_apu,
                                       list_apus (filtrable+paginada con nº de insumos)
apu_tool/datos/precios_db.py         + crear_insumo (alta de un insumo individual)
apu_tool/datos/repositorio.py        + esos métodos en los Protocol correspondientes
apu_tool/servicio/apus.py            [nuevo] lógica de servicio de APUs (crear/editar/borrar/import)
apu_tool/servicio/insumos.py         + crear (alta individual, para el "al vuelo")
apu_tool/servicio/rutas.py           + endpoints /api/apus* y POST /api/insumos
apu_tool/servicio/esquemas.py        + DTOs de APUs e insumo nuevo

web/src/api/apus.ts                  [nuevo] cliente fetch tipado a /api/apus
web/src/pages/Apus.tsx               [nuevo] pantalla de la biblioteca de APUs
web/src/components/apus/*            [nuevo] tabla, formulario, editor de composición, diálogo import
web/src/App.tsx                      + ruta /apus
web/src/components/Layout.tsx        + ítem de navegación "APUs"
web/src/lib/tipos.ts                 + tipos de APU
```

## Capa de datos

### `ApusDB` (`apu_tool/datos/apus_db.py`)
Métodos nuevos (el esquema `db/apus.sql` no cambia):

- `exists_apu(codigo, shift) -> bool` — para detectar duplicados.
- `upsert_apu(apu: Apu) -> None` — crea/actualiza **una** cabecera (`INSERT OR REPLACE`
  de una fila; reutiliza la mecánica de `insert_apus`).
- `replace_components(codigo, shift, comps: list[ApuComponent]) -> None` — **borra** las
  filas de composición de ese `(codigo, shift)` y **reinserta** la lista con `seq` 0..n.
  Es la operación de edición de composición (crear = insertar sobre vacío).
- `delete_apu(codigo, shift) -> bool` — borra primero `apu_componentes` (FK sin cascade)
  y luego la cabecera; `False` si no existía.
- `list_apus(q=None, grupo=None, limit=100, offset=0) -> tuple[list[dict], int]` —
  lista filtrable+paginada; cada fila trae `codigo, shift, nombre, unidad, grupo` y
  `n_insumos` (COUNT de componentes). Devuelve la página y el total.

### `PreciosDB` (`apu_tool/datos/precios_db.py`)
- `crear_insumo(codigo, nombre, unidad, grupo, precio, fuente) -> int` — alta de **un**
  insumo con su precio vigente (reutiliza la mecánica de `insert_insumos`/`set_precio`);
  devuelve el `id`. Error si ya existe la identidad `(codigo, nombre_norm)`.

Los métodos nuevos se agregan también a los `Protocol` de `repositorio.py`.

## Parser compartido + importación (append)

### Refactor del parser
Se extrae de `seed.py` a `apu_tool/datos/parser_historico.py` la lógica de lectura del
workbook: `_read_apus`, `_read_insumos`, las configuraciones `INSUMO_SHEETS`/`APUS_COLS`
y los helpers (`_num`, `_code`, `_text`, `_looks_like_code`). `seed()` pasa a **usar**
ese módulo; su comportamiento no cambia (los tests de seed existentes deben seguir verdes).

### Servicio de importación — `apu_tool/servicio/apus.py`
Dos pasos, igual que la importación de insumos que ya existe:

- `import_preview(alm, contenido_xlsx, nombre) -> dict` — parsea el workbook (sin escribir):
  - APUs de la hoja `APUS` → por cada `(codigo, shift)`: `estado ∈ {nuevo, existe}`
    (vía `exists_apu`), `nombre`, `unidad`, `n_componentes`.
  - Insumos de las hojas de insumos presentes → `insumos_en_excel` marcados nuevo/existe.
  - `insumos_faltantes`: códigos referenciados por componentes que **no** están ni en el
    catálogo ni en el Excel (advertencia).
  - Devuelve `{apus:[...], insumos_en_excel:[...], insumos_faltantes:[...], resumen:{...}}`.
    **No escribe nada.**
- `import_confirmar(alm, contenido_xlsx, nombre, politica, agregar_insumos) -> dict` —
  reparsea y aplica en **modo agregar**, con aplicación **best-effort** (no transaccional:
  cada APU/insumo se escribe de forma independiente, coherente con la capa de datos
  actual, que usa una conexión por operación; si el proceso se interrumpe a mitad, lo ya
  escrito queda y la importación puede **re-ejecutarse** sin duplicar, porque los ya
  existentes se omiten o reemplazan según la política):
  - `agregar_insumos=True` → da de alta los insumos nuevos del Excel (los existentes se omiten).
  - Por cada APU: si `nuevo` → insertar; si `existe` → según `politica`: `"omitir"`
    (default) o `"reemplazar"` (`upsert_apu` + `replace_components`).
  - Aplica `correcciones.aplicar(comps)` a la composición, **igual que el seed**.
  - Devuelve `{agregados, reemplazados, omitidos, insumos_agregados}`.

### Gestión (crear/editar/borrar) — `apu_tool/servicio/apus.py`
- `listar(alm, q, grupo, limit, offset) -> {items, total}` (vía `list_apus`).
- `detalle(alm, codigo, shift) -> dict|None` → cabecera + `componentes` (cada uno con
  `insumo_codigo, insumo_nombre, unidad, rendimiento` y si el código **resuelve** en el
  catálogo, `insumo_id`/`precio_vigente` como ayuda visual). 404 si no existe.
- `crear(alm, datos) -> dict` → valida; error si `(codigo, shift)` ya existe;
  `upsert_apu` + `replace_components`.
- `editar(alm, codigo, shift, datos) -> dict` → 404 si no existe; conserva `codigo/shift`;
  `upsert_apu` (nombre/unidad/grupo) + `replace_components`.
- `borrar(alm, codigo, shift) -> bool` → `delete_apu`.

## API — `apu_tool/servicio/rutas.py`

| Método + ruta | Hace |
|---|---|
| `GET /api/apus?q=&grupo=&limit=&offset=` | lista filtrable+paginada `{items, total}` |
| `GET /api/apus/grupos` | grupos distintos (para el filtro) |
| `GET /api/apus/{codigo}/{shift}` | detalle (cabecera + componentes); 404 si no existe |
| `POST /api/apus` | crear; `409` si `(codigo, shift)` ya existe |
| `PUT /api/apus/{codigo}/{shift}` | editar (cabecera + reemplaza composición); 404 si no existe |
| `DELETE /api/apus/{codigo}/{shift}` | borrar; 404 si no existe |
| `POST /api/apus/importar/preview` | multipart archivo → preview (no aplica) |
| `POST /api/apus/importar/confirmar` | body `{politica, agregar_insumos}` + archivo → aplica |
| `POST /api/insumos` | crear un insumo (alta al vuelo) → `InsumoOut`; `409` si ya existe |

### DTOs — `apu_tool/servicio/esquemas.py`
`ComponenteIn {insumo_codigo:str, insumo_nombre:str, unidad:str, rendimiento:float}`,
`ApuIn {codigo:str, shift:str, nombre:str, unidad:str, grupo:str, componentes:[ComponenteIn]}`,
`ApuEditIn` (igual sin `codigo/shift`), `InsumoNuevoIn {codigo, nombre, unidad, grupo, precio, fuente}`,
`ImportConfirmIn {politica:"omitir"|"reemplazar", agregar_insumos:bool}`. Las respuestas de
listar/preview/detalle se devuelven como `dict` (consistente con el resto del backend).

## Frontend — pantalla "APUs"

Una sola página **`Apus.tsx`**, table-first, sin cards, con el estilo actual:

- **Lista:** barra de filtros (búsqueda `q`, dropdown de grupo) + paginación (limit/offset).
  Tabla: código · turno · nombre · unidad · grupo · **nº insumos** · acciones (editar/borrar).
  Botones de cabecera: **"Nuevo APU"** e **"Importar"**.
- **Formulario crear/editar** (drawer o vista; mismo componente):
  - Cabecera: `codigo` (deshabilitado al editar), `turno` (select DIURNO/NOCTURNO),
    `nombre`, `unidad`, `grupo`.
  - **Editor de composición:** tabla editable de filas. Cada fila: **buscador de insumo**
    (combobox contra `GET /api/insumos?q=`; al elegir, autocompleta `insumo_codigo`,
    `insumo_nombre`, `unidad`), campo **rendimiento**, botón quitar. Botón "agregar fila".
  - Si el insumo no aparece: botón **"Crear insumo"** → diálogo (`codigo, nombre, unidad,
    grupo, precio, fuente`) → `POST /api/insumos` → queda seleccionado en la fila.
  - Guardar → `POST /api/apus` (crear) o `PUT /api/apus/{codigo}/{shift}` (editar) → toast.
- **Borrar:** diálogo de confirmación → `DELETE` → toast + refresco.
- **Importar (diálogo):** subir `.xlsx` → `POST /api/apus/importar/preview` → tabla de
  APUs (NUEVO/YA EXISTE), lista de insumos del Excel y de faltantes; selector de política
  (omitir/reemplazar) y checkbox "agregar insumos nuevos" → **Confirmar** →
  `POST /api/apus/importar/confirmar` → toast con `{agregados, reemplazados, omitidos, insumos_agregados}`.
- **Reutiliza** los componentes UI existentes (`table`, `button`, `dialog`, `input`,
  `select`, `sonner`) y el cliente `api/insumos.ts` para el buscador.

## Errores, privacidad y pruebas

**Privacidad (Invariante #1):** la gestión de APUs no abre ningún camino hacia la IA;
la IA sigue viendo solo `DePriced*` dentro del dominio. El test que verifica que
`apu_tool/servicio/` no contiene `"ai_assist"` cubre también los archivos nuevos.

**Errores/validación:**
- `codigo` y `nombre` obligatorios; `shift ∈ {DIURNO, NOCTURNO}`; `rendimiento` numérico `≥ 0`.
- Crear con `(codigo, shift)` existente → `409` con mensaje claro (no pisa por accidente).
- Componente cuyo `insumo_codigo` no resuelve en el catálogo → **permitido** (enlace
  blando) pero **marcado como advertencia** en detalle/preview.
- Import: Excel sin hoja `APUS` legible → `400`. Confirmar es una aplicación **best-effort
  en modo agregar**: cada APU/insumo se escribe de forma independiente (coherente con la
  capa de datos actual, una conexión por operación); si el proceso se interrumpe a mitad,
  lo ya escrito queda y la importación puede **re-ejecutarse** sin duplicar (los ya
  existentes se omiten o reemplazan según la política). No es una transacción atómica global.
- Editar no permite cambiar `codigo/shift`.

**Pruebas (pytest + TestClient):**
- `ApusDB`: `upsert_apu`, `replace_components` (reemplaza, no duplica seq), `delete_apu`
  (borra componentes + cabecera), `list_apus` (filtros+paginación+`n_insumos`), `exists_apu`.
- `PreciosDB.crear_insumo` (alta + duplicado).
- `parser_historico`: paridad con el comportamiento del seed (mismos APUs/insumos que antes).
- Import: `import_preview` (nuevo/existe/faltantes) e `import_confirmar` (omitir vs
  reemplazar; con/sin `agregar_insumos`; best-effort, re-ejecutable sin duplicar).
- Endpoints nuevos vía TestClient (crear/editar/borrar/preview/confirmar/crear-insumo).
- Frontend: Vitest ligero para el editor de composición (agregar/quitar filas, validación)
  y el render del preview de import. Smoke manual para lo visual.
- `python -m pytest tests/ -q` debe seguir verde (incluye seed y backend previo).

**Build/serve:** al terminar la web, `npm run build` regenera `web/dist` y hay que
**reiniciar el servidor** para servir la versión nueva (se coordina con el usuario; el
servidor corre como proceso independiente PID 3188 y se pidió no tocarlo sin aviso).

## Criterios de aceptación

1. Desde la web, **crear** un APU nuevo (código del IDU, turno, nombre, unidad, grupo +
   varios insumos con rendimiento) y verlo luego en la lista y disponible para corridas.
2. **Editar** un APU existente (p.ej. cambiar el rendimiento del rajón en el 3454 desde la
   UI) y **borrar** un APU, con confirmación.
3. Al agregar un insumo que no existe, **crearlo al vuelo** desde el formulario y usarlo.
4. **Importar** un Excel con formato hoja `APUS`: el preview marca NUEVO/YA EXISTE y lista
   insumos faltantes; confirmar **agrega** sin borrar los 1.098 existentes; política
   omitir/reemplazar respetada; resumen correcto.
5. `pytest` pasa completo, incluido el seed (parser refactorizado sin cambio de conducta).
6. La IA nunca recibe dinero (invariante intacto); la gestión de APUs no toca la IA.
