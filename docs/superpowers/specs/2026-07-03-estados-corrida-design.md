# Diseño — Estados de corrida (activa / congelada)

> Fecha: 2026-07-03
> Estado: propuesto (pendiente de revisión del usuario)
> Reemplaza al borrador de backup `2026-07-02-estados-corrida-design.md`, adaptándolo a la
> realidad actual: producción sobre Render + Supabase (Postgres), doble backend, y las features
> ya en prod de editar/borrar APUs y reasignar el APU de un ítem de corrida.
> Rama de trabajo: `feat/estados-corrida` (parte del tip de `master`).

## Objetivo

Hoy una corrida es un híbrido: la **composición** de cada ítem quedó congelada (foto al armar/
confirmar), pero los **precios** se recalculan siempre en vivo. No hay forma de que una corrida
**siga** los cambios de la biblioteca de APUs, ni de "cerrarla" como una cotización fija.

Este proyecto agrega un **modo** por corrida:

- **Activa** (por defecto): la corrida **sigue la biblioteca**. Al verla, cada ítem re-lee la
  composición actual de su APU asignado y se costea con precios vigentes. Es el borrador de trabajo.
- **Congelada**: la corrida es una **foto inmutable** (composición **y** precios fijos del momento
  en que se congeló). No cambia aunque después se editen APUs o suban precios. Es la cotización emitida.

El modo es **reversible** (Congelar / Activar).

## Decisiones de alcance

| Decisión | Elección |
|----------|----------|
| Qué congela | **Todo**: composición + precios (foto completa e inmutable). |
| Qué sigue la activa | Re-lee la **composición del APU asignado** a cada ítem + **precios vigentes**. |
| Match | **No** se re-hace el matching: se respeta qué APU quedó asignado/confirmado en cada ítem. |
| Estado inicial | Nace **activa**. Corridas existentes (prod) → **activa** (por el DEFAULT). |
| Reversibilidad | **Reversible**: Congelar / Activar cuando se quiera. |
| Generar cuadro | **Auto-congela** (el cuadro es lo que se envía → queda fijo). Reversible. |
| Congelada | **Solo lectura**: reasignar/confirmar ítems queda deshabilitado hasta activar. |
| Relación con el ciclo actual | `modo` es **ortogonal** a `estado` (`armando`/`en_revision`/`finalizada`), que no cambia. |
| Editar composición de una línea | **Fuera de alcance** — ya se cubre con *activa* + editar el APU en la biblioteca (feature en prod). |
| Rol para congelar/activar | `consulta` (consistente con confirmar/eliminar corrida, que hoy son `consulta`). |
| Backends | SQLite **y** Postgres (dual-backend), como el resto del proyecto. |

**Fuera de alcance:** re-matching automático en modo activa; versionar/guardar múltiples fotos por
corrida (solo la última congelación); congelar/activar ítems individuales (el modo es de toda la
corrida); editar la composición de una línea como override local.

## Arquitectura y estructura de archivos

El dominio (matcher, assembler, pricing, report) **no cambia**. La lógica de modo vive en el servicio
de corridas y en la capa de datos de corridas (ambos backends). **No toca la IA**: el snapshot con
dinero es un entregable interno (como el cuadro), nunca se pasa a la IA (Invariante #1).

```
db/corridas.sql                    + corrida.modo, + corrida_item.snapshot_json (CREATE + nada más; migración en init_schema)
db/pg/corridas.sql                 + columnas en CREATE TABLE + ALTER TABLE ... ADD COLUMN IF NOT EXISTS (migra prod)
apu_tool/datos/corridas_db.py      init_schema: ALTER ADD COLUMN si faltan (patrón de duracion_ms); set_modo;
                                     set_snapshot; get_snapshots; modo en _insert_corrida/_row_to_meta
apu_tool/datos/pg/corridas_pg.py   set_modo; set_snapshot; get_snapshots; modo en _insert_corrida/_row_to_meta
apu_tool/datos/repositorio.py      + set_modo, set_snapshot, get_snapshots en RepositorioCorridas
apu_tool/nucleo/models.py          CorridaMeta + campo `modo` (default "activa")
apu_tool/servicio/corridas.py      costeo según modo; congelar/activar; modo en vista/listar;
                                     generar_cuadro auto-congela; confirmar bloqueado si congelada
apu_tool/servicio/rutas.py         + POST /api/corridas/{id}/congelar y /activar; confirmar → 409 si congelada
web/src/api/corridas.ts            + congelarCorrida, activarCorrida
web/src/lib/tipos.ts               + `modo` en CorridaDetalle y CorridaResumen
web/src/pages/Corrida.tsx          badge Activa/Congelada + botones Congelar/Activar; readOnly → TablaItems
web/src/components/corrida/TablaItems.tsx  prop readOnly: deshabilita reasignar/confirmar con aviso
web/src/pages/MisCorridas.tsx      muestra el modo en la lista
```

## Datos / migración (dual-backend)

- `corrida`: `+ modo TEXT NOT NULL DEFAULT 'activa'`.
- `corrida_item`: `+ snapshot_json TEXT` (nullable; foto costeada al congelar).
- **SQLite** (`CorridasDB.init_schema`): además del `CREATE TABLE IF NOT EXISTS`, revisa
  `PRAGMA table_info(...)` y hace `ALTER TABLE corrida ADD COLUMN modo TEXT NOT NULL DEFAULT 'activa'`
  y `ALTER TABLE corrida_item ADD COLUMN snapshot_json TEXT` si faltan — **mismo patrón que ya se usa
  para `duracion_ms`**. Las bases existentes ganan las columnas sin resetear ni perder corridas.
- **Postgres** (`db/pg/corridas.sql`): las columnas van en el `CREATE TABLE` (bases nuevas) **y** se
  agregan `ALTER TABLE corridas.corrida ADD COLUMN IF NOT EXISTS modo TEXT NOT NULL DEFAULT 'activa';`
  y `ALTER TABLE corridas.corrida_item ADD COLUMN IF NOT EXISTS snapshot_json TEXT;`. Como
  `Almacen.init_schema()` corre en cada arranque (también en prod) y `CorridasPg.init_schema` ejecuta
  ese `.sql`, el deploy migra la tabla de producción **idempotentemente y sin pérdida**.
- **Corridas existentes** quedan `modo='activa'` por el DEFAULT. En la práctica su costo mostrado solo
  cambia si el APU asignado fue editado en la biblioteca desde que se armó la corrida.
- `CorridaMeta` (`nucleo/models.py`) += `modo: str = "activa"`; `_insert_corrida`/`_row_to_meta` lo
  escriben/leen en ambos backends. `CorridaItemRow` **no cambia** (el snapshot con dinero se lee aparte
  vía `get_snapshots`, no se mezcla en la fila money-free).

### Métodos nuevos de datos (RepositorioCorridas Protocol + `CorridasDB` + `CorridasPg`)
- `set_modo(corrida_id, modo)` — `UPDATE corrida SET modo`.
- `set_snapshot(corrida_id, seq, payload: dict)` — `UPDATE corrida_item SET snapshot_json` (por ítem;
  se llama en el loop de `congelar`). Serializa `payload` a JSON.
- `get_snapshots(corrida_id) -> dict[int, dict]` — lee `seq` + `snapshot_json`, parsea, devuelve
  `{seq: payload}` solo de los ítems que tienen snapshot.

## Comportamiento de costeo (el corazón)

En `apu_tool/servicio/corridas.py`, el costeo decide según `meta.modo` (`get_corrida` ya lo trae):

- **Activa** — por cada ítem (reemplaza el `_costear_row` actual, que hoy costea desde `row.componentes`):
  - Si tiene `apu_codigo` **y el APU existe** en la biblioteca → **re-lee**
    `alm.apus.get_components(apu_codigo, shift)` y costea con `PricingEngine` (precios vigentes).
  - Si **no** tiene `apu_codigo` (status "nuevo") → usa `row.componentes` (como hoy).
  - Si tiene `apu_codigo` pero el APU **fue borrado** (composición vacía / `get_apu` None) → respaldo a
    `row.componentes`; no revienta.
- **Congelada** — por cada ítem se construye la vista **desde el `snapshot_json`** (composición +
  precios + costos tal cual, sin recalcular). Si un ítem no tiene snapshot (improbable) → se costea como
  activa (degradación segura).

**Estructura de servicio:**
- `vista_corrida(alm, corrida_id)`: obtiene `meta`. Si `congelada` → `get_snapshots(corrida_id)` una vez
  y arma cada fila desde su snapshot; si `activa` → costea cada fila re-leyendo la biblioteca. Los
  totales se suman de las filas resultantes (igual que hoy). Añade `modo` a la respuesta.
- `detalle_item(alm, corrida_id, seq)`: mismo branch por `modo` — en congelada la "composición costeada"
  sale del snapshot.
- `listar_corridas`: añade `modo` a cada fila.

## Congelar / Activar / Generar cuadro

- **`congelar(alm, corrida_id) -> dict | None`**: `get_corrida` (None → 404). Costea la vista **activa**
  en ese instante (composición live + precios vigentes) y por cada ítem guarda su foto costeada con
  `set_snapshot(corrida_id, seq, payload)`, `payload = {"composicion": [{insumo_codigo, insumo_nombre,
  unidad, rendimiento, precio_unitario, fuente_precio, costo, calidad_cruce}], "costo_unitario": float}`.
  Luego `set_modo('congelada')`. Devuelve `vista_corrida` (congelada). **Idempotente** (recongelar = foto nueva).
- **`activar(alm, corrida_id) -> dict | None`**: `get_corrida` (None → 404); `set_modo('activa')`. El
  snapshot queda guardado pero se ignora; la próxima congelación lo sobrescribe. Devuelve `vista_corrida`.
- **`generar_cuadro`** (ya existe): **auto-congela** — llama a `congelar` (guarda snapshots + `modo='congelada'`)
  y escribe el Excel desde esa vista congelada; conserva su `estado='finalizada'` actual (modo ⟂ estado).
  El cuadro queda coherente con lo enviado.
- **`confirmar_item`** (la ruta que usan reasignar/confirmar): si la corrida está **congelada** → rechaza
  (señal para `409`); si activa, funciona como hoy.

## API — `apu_tool/servicio/rutas.py`

| Método + ruta | Rol | Hace |
|---|---|---|
| `POST /api/corridas/{id}/congelar` | `consulta` | congela; `404` si no existe; devuelve la vista (modo=congelada) |
| `POST /api/corridas/{id}/activar` | `consulta` | activa; `404` si no existe; devuelve la vista |
| `POST /api/corridas/{id}/items/{seq}/confirmar` | `consulta` | como hoy, pero **`409`** si la corrida está congelada |

`vista_corrida` y `listar_corridas` añaden `modo` a su respuesta.

## UI

- `web/src/api/corridas.ts`: + `congelarCorrida(id)`, `activarCorrida(id)` (`POST`); `modo` en los tipos.
- `web/src/lib/tipos.ts`: + `modo: string` en `CorridaDetalle` y `CorridaResumen`.
- `web/src/pages/Corrida.tsx`: **badge** "Activa"/"Congelada" junto a los totales + botones
  **Congelar**/**Activar** (según `modo`). Si congelada, pasa `readOnly` a `TablaItems`.
- `web/src/components/corrida/TablaItems.tsx`: prop `readOnly` — con la corrida congelada, deshabilita el
  buscador "Cambiar APU", los "Elegir" de candidatos y "Confirmar APU actual", con aviso
  "Activá la corrida para modificar". El `409` del backend es el respaldo.
- `web/src/pages/MisCorridas.tsx`: muestra el `modo` de cada corrida.

## Errores / casos límite

- APU asignado borrado (activa) → respaldo a `row.componentes`; sin error.
- Confirmar/reasignar en corrida congelada → `409` con mensaje claro (y UI deshabilitada).
- Congelar corrida sin ítems → no-op válido (marca modo, sin snapshots). Activar una activa /
  congelar una congelada → idempotente.
- `snapshot_json` ausente en un ítem de corrida congelada → ese ítem se costea como activa (degradación segura).
- Migración: correr `init_schema` dos veces y sobre una base "vieja" sin columnas no falla, agrega las
  columnas y no pierde corridas.

## Privacidad (Invariante #1)

`snapshot_json` contiene dinero → es un dato interno del equipo (como el cuadro), **nunca** se pasa a la
IA. `componentes_json` sigue money-free. El test que verifica que `apu_tool/servicio/` no referencia
`ai_assist` sigue aplicando. La IA nunca ve el snapshot.

## Pruebas (pytest + TestClient)

- **Datos (SQLite en `tests/test_corridas_db.py`; Postgres gateado por `TEST_DATABASE_URL`):** migración
  idempotente (`init_schema` 2× y sobre una base sin las columnas → agrega, no pierde corridas); `modo`
  default `'activa'`; `set_modo`; `set_snapshot`/`get_snapshots` (roundtrip).
- **Servicio:**
  - Activa re-lee composición: armar corrida → editar el rendimiento de un APU en la biblioteca →
    `vista_corrida` refleja el nuevo costo.
  - Congelar fija todo: congelar → cambiar rendimiento del APU y/o precio del insumo → `vista_corrida`
    **no** cambia; activar → **sí** cambia.
  - `generar_cuadro` deja la corrida en `modo='congelada'` y con snapshots (+ `estado='finalizada'`).
  - `confirmar_item`/reasignar sobre corrida congelada → bloqueado.
- **API:** `POST congelar`/`activar` cambian el modo; `modo` presente en vista/lista; confirmar en
  congelada → `409`.
- **Frontend (Vitest ligero):** render del badge/botones según modo y que `readOnly` deshabilita las
  acciones de reasignación/confirmación; smoke manual.
- `python -m pytest tests/ -q` verde, incluido el test de privacidad; la IA nunca ve dinero.

## Despliegue

`npm run build` regenera `web/dist`; el `ALTER ... ADD COLUMN IF NOT EXISTS` corre en el deploy vía
`init_schema` (migra la tabla de prod sin pérdida; corridas existentes → `activa`). Redeploy en Render;
**sin merge/push a prod sin OK explícito del usuario**.

## Criterios de aceptación

1. Una corrida nueva nace **activa**; editar un rendimiento (o agregar/quitar un insumo) en un APU se
   refleja en la corrida activa al abrirla.
2. **Congelar** deja la corrida inmutable: cambios posteriores en APUs o precios no la alteran.
3. **Activar** la vuelve a hacer seguir la biblioteca.
4. **Generar el cuadro** congela la corrida automáticamente (reversible).
5. Estando **congelada**, no se puede reasignar/confirmar ítems (`409` + UI deshabilitada) hasta activarla.
6. La migración no pierde corridas existentes (SQLite y Postgres); `pytest` pasa completo; la IA nunca
   recibe dinero.
