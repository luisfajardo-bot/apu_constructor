# Diseño — Armado incremental + tabla en vivo (etapa 2, sub-proyecto B)

> Fecha: 2026-06-25
> Estado: aprobado para implementación
> Contexto: tras la optimización del matcher (sub-proyecto A). Hoy la corrida se
> persiste **al final** (fix atómico `crear_corrida_con_items`, que evitaba el
> `FOREIGN KEY constraint failed`). Se quiere **persistir cada APU al armarlo** y
> **ver la tabla llenándose** en `/corridas/:id`.

## Objetivo

1. Guardar cada APU en `corrida_item` **a medida que se arma** (no todo al final).
2. Entrar a `/corridas/:id` y **ver la tabla crecer** APU por APU, en vivo.
3. Hacerlo **sin reabrir** el bug del FK: manejar explícitamente que la corrida se
   borre o resetee durante el armado.

## Decisión de diseño (aprobada)

- **Tabla en vivo:** se emite el id al inicio; el front navega a `/corridas/:id` y
  pinta cada fila desde el stream SSE; el server persiste cada APU al vuelo.
- **Seguridad:** estado `armando`; **borrar = cancelar** (si la corrida desaparece
  a mitad, el armado se cancela limpio, nunca el FK crudo).

## Global Constraints (cero regresiones)

- No se toca la lógica de matching/costeo. El re-costeo (`_costear_row` /
  `vista_corrida`) no cambia.
- Persistencia solo en `apu_tool/datos/`; sin SQL crudo fuera de esa capa.
- Invariante #1: ningún archivo en `apu_tool/servicio/` contiene "ai_assist".
- UI densa, table-first, sin cards; imports `@/`.
- `python -m pytest tests/ -q` verde tras cada tarea de backend; frontend compila
  (`npm run build`, 0 TS).

## Ciclo de estado de la corrida

`armando` (en proceso) → `en_revision` (terminó de armar) → `finalizada` (cuadro
generado). El estado `armando` es nuevo; `vista_corrida`/`listar_corridas` ya lo
exponen vía `estado` sin cambios de esquema (la columna `estado` es TEXT libre).

## Backend

### B.1 — Persistencia incremental — `apu_tool/servicio/corridas.py`

`construir_corrida_stream` pasa de "armar todo en memoria → guardar al final" a:

- Al inicio: `corrida_id = alm.corridas.crear_corrida(CorridaMeta(... estado="armando"))`;
  `t0 = time.monotonic()`; emite **`("started", {"id": corrida_id, "total": total})`**.
- Por ítem: arma con **un solo match** (sub-proyecto A) → persiste esa fila
  (`alm.corridas.guardar_items(corrida_id, [fila])`, que ya inserta por lotes y
  acepta lista de uno) → emite **`("progress", {...})`** enriquecido con la fila ya
  costeada (misma forma que un ítem de `vista_corrida`: `seq`, `descripcion`,
  `apu_codigo`, `apu_nombre`, `unidad`, `status`, `costo_unitario`,
  `contractual_total`, `costo_total`, `margen_*`). El costeo por ítem ya está en el
  `AssembledApu` que devuelve `assemble_item`; se reusa `_vista_item`.
- Si un insert lanza `sqlite3.IntegrityError` (FK: la corrida ya no existe) →
  **cancelar limpio**: dejar de iterar y emitir
  **`("error", {"detail": "Armado cancelado: la corrida fue eliminada."})`** (el
  `_event_stream` ya serializa `error`; aquí se detecta el caso concreto y se da un
  mensaje claro, no el `FOREIGN KEY constraint failed` crudo).
- Al final (sin cancelación): `alm.corridas.set_estado(corrida_id, "en_revision")`;
  `duracion_ms = round((time.monotonic()-t0)*1000)`; `alm.corridas.set_duracion(...)`;
  emite **`("done", {"id", "resumen", "duracion_ms"})`** (resumen de `vista_corrida`).
- `construir_corrida` (envoltorio no-stream) sigue drenando el generador y
  devolviendo el id del `done`; si hubo cancelación, devuelve -1 (o el id de la
  corrida cancelada — a definir en el plan; el wrapper lo usa la API no-stream y los
  tests).

### B.2 — Retirar `crear_corrida_con_items`

El método atómico que se agregó en el fix del FK queda **superado** por el armado
incremental seguro. Se retira de `CorridasDB` y del Protocol `RepositorioCorridas`,
junto con sus tests (`test_crear_corrida_con_items_*`). `crear_corrida` +
`guardar_items` (incremental) son ahora el camino de producción. *(YAGNI: no dejar
dos formas de persistir una corrida.)*

> Nota de seguridad: el armado incremental reintroduce la corrida "a medio armar",
> pero ahora con estado `armando` y cancelación limpia ante borrado/reset — el
> `FOREIGN KEY` ya no escapa al usuario.

### B.3 — API/SSE — `apu_tool/servicio/rutas.py`

- El endpoint `/corridas/stream` y `/sample/stream` no cambian de firma; el
  generador ahora emite `started` antes del primer `progress`. `_event_stream`
  serializa cualquier evento (`started`/`progress`/`done`/`error`) tal cual.
- `eliminar_corrida` (`DELETE /corridas/{cid}`) no cambia: borra la corrida (cascade
  de ítems). Si está `armando`, el armado en curso lo detecta y se cancela.

## Frontend

### B.4 — Store de armado en vivo — `web/src/`

- Tipos (`lib/tipos.ts`): `Progreso` gana los campos de la fila costeada; nuevo tipo
  para el evento `started` (`{id, total}`). `CorridaResumen`/`CorridaDetalle` ya
  tienen `estado`.
- `api/corridas.ts`: `streamCorrida` reconoce el evento `started` (callback
  `onStarted(id, total)`) además de `progress`/`done`/`error`.
- Un store ligero (módulo o React context) `armadoVivo`: `{corridaId, filas[],
  total, estado}`, alimentado por los callbacks del stream. Se llena durante el
  armado iniciado en `CorridasInicio`.

### B.5 — Navegación y vista en vivo

- `CorridasInicio.tsx`: al recibir `started`, **navega a `/corridas/:id`** y deja el
  stream corriendo (el store se sigue llenando). En `done` no re-navega (ya está
  ahí); en `error`/cancelación muestra toast y vuelve a `/corridas`.
- `Corrida.tsx`: si el store de armado vivo coincide con `:id`, renderiza las filas
  del store (en vivo, sin polling) y un encabezado "armando i/total". Si no hay
  store para ese id (p. ej. recarga de página), cae a `getCorrida(id)` (muestra lo
  persistido hasta ese momento). Si `estado==="armando"` y no hay stream activo,
  **poll ligero** cada ~2 s a `getCorrida` hasta que `estado` deje de ser `armando`.
- `MisCorridas.tsx`: las corridas `armando` se muestran con estado "armando" (y, si
  hay datos, "i/total" por `n_items`); **eliminar = cancelar** (mismo botón, con la
  confirmación actual).

### B.6 — Comportamiento al abandonar

Si se cierra la pestaña a mitad, el stream server-side se interrumpe; los APUs ya
insertados quedan guardados (corrida `armando` parcial), visible en "Mis corridas"
y borrable. (No se auto-limpia; el usuario decide.)

## Errores y pruebas

**Errores:**
- Borrado/reset de la corrida durante el armado → cancelación limpia (mensaje claro,
  sin FK crudo). Test que lo simula: crear corrida `armando`, borrarla, intentar el
  siguiente `guardar_items([fila])` → la capa de servicio lo traduce a cancelación.
- En `/corridas/:id` de una corrida cancelada/borrada → `getCorrida` da 404 → aviso
  y volver a la lista (camino ya existente).

**Pruebas (backend, pytest):**
- `construir_corrida_stream` emite `started` primero, un `progress` por ítem **con
  la fila costeada**, y `done` al final; la corrida nace `armando` y termina
  `en_revision` con `duracion_ms`.
- **Incremental:** tras consumir N de M eventos `progress`, hay N ítems persistidos
  (la tabla crece, no aparece toda al final).
- **Cancelación:** si la corrida se borra a mitad, el stream emite `error` de
  cancelación y no propaga `FOREIGN KEY constraint failed` al usuario.
- `vista_corrida` sobre una corrida `armando` parcial funciona (recostea lo que hay).
- Tests existentes adaptados (el orden de persistencia cambió; `crear_corrida_con_items`
  y sus tests se retiran).

**Frontend (Vitest, ligero):** parseo del evento `started`; el store acumula filas
de `progress`; build verde. Verificación en vivo (controlador): armar una lista,
ver la tabla llenándose, y cancelar borrando.

## Criterios de aceptación

1. Al armar, se navega a `/corridas/:id` y la tabla se llena APU por APU en vivo.
2. Cada APU queda persistido al armarse (no todo al final); recargar a mitad muestra
   lo ya armado.
3. Borrar la corrida durante el armado la cancela con aviso claro; **nunca** aparece
   `FOREIGN KEY constraint failed`.
4. Al terminar, la corrida queda `en_revision` con su tiempo; el cuadro y "Mis
   corridas" funcionan igual que hoy.
5. `pytest` verde (matcher/costeo intactos); `npm run build` 0 TS; Invariante #1 OK.

## Dependencias

Ninguna. Depende de que el sub-proyecto A (un solo match) esté integrado.
