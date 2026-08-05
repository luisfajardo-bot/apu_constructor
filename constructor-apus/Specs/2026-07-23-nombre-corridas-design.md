> Espejo automático — no editar aquí. Fuente: `docs/superpowers/specs/2026-07-23-nombre-corridas-design.md`

# Diseño — Nombre/alias para corridas

> Fecha: 2026-07-23
> Estado: propuesto (aprobado en brainstorming; pendiente de revisión del spec escrito)
> Rama de trabajo sugerida: `feat/nombre-corridas`

## Objetivo

Hoy una corrida **no tiene nombre propio**: se identifica y se muestra por el campo
`CorridaMeta.archivo`, que es el nombre del archivo de licitación subido. En "Mis
corridas", en los prompts de borrar/mover y en los toasts se usa ese `archivo`.

Este proyecto le da a la corrida un **nombre/alias editable**:

1. Al **crear** la corrida, el campo "Nombre" se **precarga con el nombre del archivo
   subido, sin la extensión** (ej. `Licitacion Calle 13.xlsx` → `Licitacion Calle 13`),
   y el usuario puede editarlo. **Se permiten espacios.**
2. Una corrida existente se puede **renombrar** desde "Mis corridas".
3. Se **conserva** el nombre de archivo original (`archivo`) como dato de procedencia
   inmutable, aunque en pantalla se muestre el alias.

## Decisiones tomadas (brainstorming)

- **Alcance:** crear + renombrar después (no solo al crear).
- **Default:** nombre del archivo **sin extensión**.
- **Procedencia:** se conserva `archivo` original; el alias es un campo aparte.
- **UX de renombrar:** `window.prompt`, reusando el patrón que ya existe para
  renombrar carpetas (`MisCorridas.tsx:128`). Mínimo código, máxima consistencia.
- **Renombrar en corridas congeladas:** **permitido**. El nombre es una etiqueta y
  **no** forma parte del snapshot inmutable (precios/composición). Es análogo a
  renombrar una carpeta.

## Invariante #1 (recordatorio)

Esta feature **no toca dinero** y **no toca la IA**. Solo agrega una etiqueta de texto
a la corrida. No hay payload nuevo hacia la IA. Sin implicaciones para `privacy.py`.

## Modelo de datos

- `CorridaMeta` (`apu_tool/nucleo/models.py`): se agrega **`nombre: str = ""`** justo
  después de `archivo`. `archivo` queda **inmutable** (procedencia). `nombre` es el
  alias editable.

- **SQLite** (`apu_tool/datos/corridas_db.py`):
  - En `init_schema`, mismo patrón que `modo`/`carpeta_id`: si la columna `nombre` no
    existe en `PRAGMA table_info(corrida)`, `ALTER TABLE corrida ADD COLUMN nombre TEXT`.
  - **Backfill** para corridas existentes:
    `UPDATE corrida SET nombre = archivo WHERE nombre IS NULL OR nombre = ''`.
  - El `schema.sql` (DBs nuevas) incluye `nombre TEXT`.
  - `_insert_corrida` incluye `nombre` en el INSERT.
  - El `row→meta` (~línea 189) lee `nombre` con fallback a `archivo` si viniera nulo.
  - Nuevo método **`set_nombre(self, corrida_id: int, nombre: str) -> None`**.

- **Postgres** (`apu_tool/datos/pg/corridas_pg.py` + su `schema.sql`):
  - En el `schema.sql` (que corre al boot vía `ejecutar_migracion`, idempotente):
    `ALTER TABLE corridas.corrida ADD COLUMN IF NOT EXISTS nombre TEXT;`
    y backfill `UPDATE corridas.corrida SET nombre = archivo WHERE nombre IS NULL;`
    (mismo mecanismo que `modo`/`snapshot_json`).
  - `_insert_corrida` incluye `nombre`.
  - El `row→meta` (~línea 138) lee `nombre` con fallback a `archivo`.
  - Mismo `set_nombre`.

- **Contrato** (`apu_tool/datos/repositorio.py`): se añade a la interfaz de corridas
  `def set_nombre(self, corrida_id: int, nombre: str) -> None: ...` para que ambos
  backends lo cumplan.

## Regla del nombre por defecto (sin extensión)

- Helper puro `_nombre_desde_archivo(filename: str) -> str`: quita la última extensión
  (`.xlsx`/`.csv`) y aplica `.strip()`. Ubicación: junto a la lógica de servicio de
  corridas (reutilizable por backend).
- **Doble red:** el frontend precarga el campo ya sin extensión; el backend, si `nombre`
  llega vacío/ausente, lo deriva del filename con el mismo helper. **Nunca queda en
  blanco.**
- Validación: `trim`; **espacios permitidos**; tope de longitud **120** (se recorta si
  excede). Vacío tras trim → cae al default derivado del archivo.

## Backend — creación

- `apu_tool/servicio/rutas.py` (`POST /corridas` y `POST /corridas/stream`): nuevo
  parámetro `nombre: Optional[str] = Form(None)`. Nombre efectivo =
  `nombre.strip()` si viene no vacío, si no `_nombre_desde_archivo(archivo.filename)`.
- `apu_tool/servicio/corridas.py`: `construir_corrida_stream(...)` y
  `construir_corrida(...)` reciben `nombre: str` y lo pasan a
  `CorridaMeta(nombre=..., archivo=..., ...)`.
- El endpoint de ejemplo (`/sample`, `/sample/stream`) usa `nombre="Ejemplo"`.

## Backend — renombrar (endpoint nuevo)

- **`POST /corridas/{id}/renombrar`** con body JSON `{ "nombre": "..." }`, al estilo de
  los endpoints de acción ya existentes (`/congelar`, `/activar`).
- Validación: `trim`; vacío → **400**; corrida inexistente → **404**; tope 120.
- Llama `alm.corridas.set_nombre(id, nombre)` y devuelve el `CorridaDetalle` actualizado.
- **Control de acceso:** mismo esquema (ownership/RBAC) que `eliminar`/`mover`.
- **Permitido aun si la corrida está congelada** (el nombre no es parte del snapshot).

## Frontend — creación (`web/src/pages/CorridasInicio.tsx`)

- Nuevo input de texto **"Nombre"**. Estado `nombre` + flag `nombreTocado`.
- Al elegir archivo (`onChange` del input file): si `!nombreTocado`, precargar
  `nombre = stripExt(file.name)`. Si el usuario ya editó el campo, **no** se pisa.
- Marcar `nombreTocado = true` cuando el usuario escribe en el campo Nombre.
- Se agrega `nombre` al `FormData` en `handleArmar`.
- Espacios permitidos (input de texto normal, sin sanitización más allá de trim en
  el envío).

## Frontend — renombrar (`web/src/pages/MisCorridas.tsx`)

- Acción **"Renombrar"** por corrida (junto a borrar/mover), con
  `window.prompt("Nuevo nombre", c.nombre)` — mismo patrón que renombrar carpeta
  (línea 128). Si el valor es válido y distinto, llama `renombrarCorrida(id, nombre)`,
  refresca la lista y hace `toast.success`.
- **Display:** la fila pasa de mostrar `{c.archivo}` (línea 340) a `{c.nombre}`, con
  `title={c.archivo}` como tooltip de procedencia.
- Los prompts/toasts de borrar/mover pasan a usar `c.nombre`.

## Frontend — API y tipos

- `web/src/api/corridas.ts`: nueva función
  `renombrarCorrida(id: number, nombre: string): Promise<CorridaDetalle>` →
  `apiPost('/corridas/${id}/renombrar', { nombre })`.
- `web/src/lib/tipos.ts`: agregar `nombre: string` a `CorridaResumen` y a
  `CorridaDetalle`.

## Vistas del servicio

- `vista_corrida` y la vista de lista (`apu_tool/servicio/corridas.py:205` y `:295`)
  incluyen `"nombre": meta.nombre` en el dict devuelto, para que el frontend lo reciba.

## Pruebas (extender, no romper)

- **Contrato** (`tests/test_repositorios_contrato.py`): `set_nombre` persiste en ambos
  backends; `crear_corrida` guarda `nombre`; `row→meta` lo devuelve.
- **Servicio** (`tests/test_servicio_corridas.py`): `construir_corrida` con `nombre`
  explícito y sin él (default sin extensión). Unit test del helper
  `_nombre_desde_archivo` (varios casos: `.xlsx`, `.csv`, sin extensión, con espacios,
  con puntos intermedios).
- **API** (`tests/test_api_corridas.py`): crear con `nombre`; `renombrar` OK devuelve
  detalle; vacío → 400; inexistente → 404; renombrar corrida congelada → 200.
- **Frontend**:
  - `CorridasInicio.test.tsx`: al elegir archivo precarga nombre sin extensión;
    no pisa una edición manual; el submit envía `nombre` en el FormData.
  - `MisCorridas.test.tsx`: la lista muestra `nombre`; la acción renombrar llama a la
    API y refresca.

## Migración / compatibilidad

- Corridas existentes → `nombre = archivo` (con extensión, que es como se ven hoy).
  Nada aparece en blanco; se ven igual hasta que se renombren. `archivo` **nunca** se
  pierde. **Cero regresión.**

## Fuera de alcance (YAGNI)

- Unicidad de nombres entre corridas.
- Filtrar/buscar corridas por nombre.
- Renombrar desde la página de detalle de la corrida (solo desde "Mis corridas").

Se pueden agregar después si se necesitan.
