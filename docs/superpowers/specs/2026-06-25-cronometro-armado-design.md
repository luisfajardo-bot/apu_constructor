# Diseño — Cronómetro del armado (tiempo final persistido)

> Fecha: 2026-06-25
> Estado: aprobado para implementación

## Objetivo

Al terminar de armar una corrida, mostrar **cuánto tardó** junto con cuántos APUs se
armaron — p.ej. **"15 APUs · armada en 3.2 s"** — **persistido** para verlo al reabrir la
corrida y en la lista "Mis corridas" (y poder comparar corridas). El usuario priorizó el
**número final**; el cronómetro en vivo (tickeo) **NO** entra en alcance (el progreso
"Armando i/total" del SSE ya da feedback en vivo suficiente).

## Global Constraints (cero regresiones)

- No se toca la lógica de matching/costeo. La medición solo cronometra el armado existente.
- Migración idempotente: las corridas viejas (sin la columna) siguen funcionando (`duracion_ms` NULL → se muestra "—"). `duracion_ms` nullable en todos los modelos.
- Persistencia solo en `apu_tool/datos/`. Invariante #1: sin `ai_assist` en `servicio/`.
- `python -m pytest tests/ -q` verde tras cada tarea de backend; frontend `npm run build` 0 TS.

## Backend

### Esquema + migración — `apu_tool/datos/corridas_db.py`, `db/corridas.sql`
- `db/corridas.sql`: la tabla `corrida` gana `duracion_ms INTEGER` (para bases nuevas).
- **Migración idempotente** en `CorridasDB.init_schema()`: tras `executescript`, comprobar con
  `PRAGMA table_info(corrida)` si existe `duracion_ms`; si falta, `ALTER TABLE corrida ADD COLUMN
  duracion_ms INTEGER`. Así las bases existentes ganan la columna sin perder datos (valor NULL).
- `CorridaMeta` (en `nucleo/models.py`) gana `duracion_ms: Optional[int] = None`.
- `_row_to_meta` lee `duracion_ms` (tolerante: las filas viejas dan NULL).
- `crear_corrida` inserta con `duracion_ms` NULL (se setea al terminar).
- Nuevo `CorridasDB.set_duracion(corrida_id: int, duracion_ms: int) -> None` (UPDATE) + en el Protocol `RepositorioCorridas`.

### Medición — `apu_tool/servicio/corridas.py`
- En `construir_corrida_stream`: `import time`; `t0 = time.monotonic()` al inicio. Tras
  `guardar_items` (antes del `yield ("done", ...)`): `duracion_ms = round((time.monotonic() - t0) * 1000)`;
  `alm.corridas.set_duracion(corrida_id, duracion_ms)`; el evento `done` pasa a
  `{"id": corrida_id, "resumen": resumen, "duracion_ms": duracion_ms}`.
- (El envoltorio `construir_corrida` que drena el generador sigue devolviendo el id; sin cambio de contrato.)

### Exponer — `apu_tool/servicio/corridas.py`
- `vista_corrida` agrega `"duracion_ms"` al dict de la corrida (de `meta.duracion_ms`).
- `listar_corridas` agrega `"duracion_ms"` por corrida (de `meta.duracion_ms`).

## Frontend

- **Tipos** (`web/src/lib/tipos.ts`): `CorridaDetalle` y `CorridaResumen` ganan `duracion_ms: number | null`.
  Si el evento `done` (`CorridaCreada`) ya se usa para navegar, no necesita el campo (se relee de `vista_corrida`).
- **Helper de formato** (`web/src/lib/moneda.ts` o un `tiempo.ts`): `fmtDuracion(ms: number | null): string`
  → `null` → "—"; `< 60000` → `"3.2 s"` (un decimal); `>= 60000` → `"1 m 05 s"`.
- **Cuadro** (`web/src/pages/Corrida.tsx`): en el encabezado, junto a los totales, una línea/badge
  **"{n_items} APUs · armada en {fmtDuracion(duracion_ms)}"** (n_items de `totales`, duracion de la corrida).
- **Mis corridas** (`web/src/pages/MisCorridas.tsx`): una columna **"Tiempo"** con `fmtDuracion(c.duracion_ms)`.

## No romper / pruebas

**Pruebas (backend, pytest):**
- Migración: sobre una DB creada con un esquema sin `duracion_ms`, `init_schema()` agrega la columna y no rompe (las corridas existentes quedan con NULL). (Se puede simular creando la tabla sin la columna y corriendo init_schema.)
- `construir_corrida_stream` persiste `duracion_ms` (`get_corrida(id).duracion_ms` es un int ≥ 0) y el evento `done` lo incluye.
- `vista_corrida` y `listar_corridas` exponen `duracion_ms`.
- Corridas viejas (sin duración): `vista_corrida`/`listar_corridas` devuelven `duracion_ms` None sin error.
- Suite completa verde.

**Frontend:** `fmtDuracion` (Vitest: null→"—", 3210→"3.2 s", 65000→"1 m 05 s"); build verde; el resumen en el cuadro y la lista se verifican en vivo.

## Criterios de aceptación

1. Al armar una corrida, al terminar el cuadro muestra "{N} APUs · armada en {tiempo}".
2. "Mis corridas" muestra el tiempo de cada corrida; las corridas viejas muestran "—".
3. El tiempo persiste (se ve al reabrir el cuadro y en la lista entre reinicios).
4. `pytest` verde (migración no rompe DBs existentes; matcher/costeo intactos).
