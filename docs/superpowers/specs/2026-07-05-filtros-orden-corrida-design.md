# Diseño — Filtros y ordenamiento en la tabla de la corrida

> Fecha: 2026-07-05
> Estado: aprobado por el usuario (pendiente de plan de implementación)
> Rama de trabajo: `feat/filtros-orden-corrida` (parte del tip de `master`).

## Objetivo

Al revisar una corrida, poder **ordenar** (asc/desc) y **filtrar** la tabla de ítems por
cualquier columna, al estilo de un filtro de Excel: buscar por descripción, unidad,
cantidad, código de ítem, APU, estado, y por los montos (contractual, costo, margen, %).

## Alcance y restricciones

- **100% frontend.** No se toca `apu_tool/` (backend), `report.py`, ni ningún endpoint.
  Los datos ya viajan completos en `CorridaDetalle.items` (`ItemCuadro[]`); el filtrado y
  el ordenamiento son en memoria (el volumen es el de una sola corrida).
- **Invariante #1 intacta:** nada de esto toca la IA (la tabla ya muestra dinero en el front).
- **Sin regresiones:** se preserva el comportamiento actual, en particular el **modo vivo**
  (armado por streaming) y el toggle **"Solo revisión"**.
- Estética densa, `table-first`, reutilizando estilos existentes (`text-xs`, `font-mono`).

## Columnas de la tabla (orden actual, sin cambios)

chevron · **Descripción** · **Und** · **Cantidad** · **Ítem** · **APU** · **Estado** ·
**Contractual** · **Costo** · **Margen** · **%**

Clasificación para filtro/orden:

| Columna | Campo (`ItemCuadro`) | Tipo de filtro | Orden |
|---|---|---|---|
| Descripción | `descripcion` | texto "contiene" | natural (es-CO) |
| Und | `unidad` | desplegable (valores presentes) | natural |
| Cantidad | `cantidad` | rango mín–máx | numérico |
| Ítem | `item` | texto "contiene" | natural (`1.2 < 1.10`) |
| APU | `apu_codigo` + `apu_nombre` | texto "contiene" (busca en ambos) | natural por código |
| Estado | `status` | desplegable (valores presentes) | natural |
| Contractual | `contractual_total` | rango mín–máx | numérico |
| Costo | `costo_total` | rango mín–máx | numérico |
| Margen | `margen_total` | rango mín–máx | numérico |
| % | `margen_pct` | rango mín–máx (en **puntos**: `12` = 12%) | numérico |

- **Texto "contiene":** insensible a mayúsculas **y a tildes** (`normalize("NFD")` + quitar
  diacríticos + `toLowerCase`), para que "excavacion" halle "Excavación".
- **Rango mín–máx:** inclusivo en ambos extremos; cualquiera de los dos puede quedar vacío.
  Para `%`, la entrada del usuario está en puntos porcentuales y se compara contra
  `margen_pct` (p. ej. mín `12` ⇒ `margen_pct >= 0.12`).
- **Desplegable:** valores distintos **presentes** en los ítems actuales; opción "(todas)".
- **Combinación:** todos los filtros activos se combinan con **Y** (AND), junto con
  "Solo revisión".

## Arquitectura

Separar la lógica pura (testeable sin DOM) de la UI.

### `web/src/lib/corridaTabla.ts` (módulo puro, nuevo)

- Tipos:
  - `ClaveColumna` = `"descripcion" | "unidad" | "cantidad" | "item" | "apu" | "status" | "contractual_total" | "costo_total" | "margen_total" | "margen_pct"`.
  - `DireccionOrden = "asc" | "desc"`.
  - `EstadoOrden = { clave: ClaveColumna; dir: DireccionOrden } | null`.
  - `FiltroTexto = string` (contiene); `FiltroRango = { min: string; max: string }` (strings del input, se parsean a número); `FiltroSelect = string` (`""` = todas).
  - `FiltrosColumna` = objeto con una entrada por columna filtrable, del tipo que le corresponde.
- Metadatos de columna: qué columnas son texto / número / desplegable, y su accesor.
- Funciones puras:
  - `filtrar(items: ItemCuadro[], filtros: FiltrosColumna, soloRevision: boolean): ItemCuadro[]`
  - `ordenar(items: ItemCuadro[], orden: EstadoOrden): ItemCuadro[]` (estable; `null` = orden original)
  - `opcionesDe(items: ItemCuadro[], clave: "unidad" | "status"): string[]` (distintos, ordenados)
  - `normalizar(s: string): string` (minúsculas + sin tildes) — helper interno reutilizable.

### `useCorridaTabla(items)` (hook, en el mismo archivo)

Guarda `orden: EstadoOrden`, `filtros: FiltrosColumna`, `soloRevision: boolean`. Devuelve:

```ts
{
  filtradas: ItemCuadro[];            // ordenar(filtrar(items, filtros, soloRevision), orden)
  orden: EstadoOrden;
  alternarOrden: (clave: ClaveColumna) => void;  // asc → desc → sin orden → asc …
  filtros: FiltrosColumna;
  setFiltro: (clave: ClaveColumna, valor: FiltroTexto | FiltroRango | FiltroSelect) => void;
  soloRevision: boolean;
  setSoloRevision: (v: boolean) => void;
  limpiar: () => void;                // resetea filtros + orden + soloRevision
  hayFiltros: boolean;                // algún filtro/orden/soloRevision activo
}
```

### Flujo de datos (`web/src/pages/Corrida.tsx`)

- Llama `useCorridaTabla(data.items)` **solo cuando `!live`**. En modo vivo se conserva el
  camino actual (tabla directa desde el stream, totales `totalesDe(vivo.filas)`).
- Cuando `!live`:
  - `totales = totalesDe(controlador.filtradas)` → la barra de totales
    (Contractual/Costo/Margen/%) **recalcula sobre lo filtrado**.
  - La sub-línea de contadores muestra **"{filtradas.length} de {data.items.length} ítems"**
    cuando `hayFiltros`, y `n_revision` recomputado sobre `filtradas`.
  - Renderiza `<TablaItems items={filtradas} control={controlador} … />`.

### `web/src/components/corrida/TablaItems.tsx`

- Nueva prop **opcional** `control?: ControlCorridaTabla` (el objeto del hook).
  - Si `control` está **presente** (vista cargada): renderiza los encabezados como botones de
    orden (con indicador `↑/↓`), una **fila de filtros** bajo los encabezados (caja "contiene",
    desplegable, o dos inputs mín–máx según la columna), y el botón **"Limpiar filtros"** +
    "Solo revisión" en la barra superior. Renderiza `items` **tal cual** los recibe (ya vienen
    filtrados/ordenados desde el padre).
  - Si `control` está **ausente** (modo vivo): se comporta **exactamente como hoy** — sin fila
    de filtros, sin indicadores de orden; conserva su `soloRevision` interno actual.
- El `soloRevision` interno actual se mueve al hook cuando hay `control`; en modo vivo (sin
  `control`) queda el estado local como está.
- La expansión de filas (por `seq`) y la reasignación de APU no cambian.

## Pruebas (Vitest, desde `web/`)

- **`web/src/lib/corridaTabla.test.ts`** (unitarias del módulo puro):
  - `filtrar`: "contiene" insensible a tildes/mayúsculas; rango mín–máx inclusivo (incluye
    bordes, vacío = sin límite); desplegable exacto; combinación de dos filtros (Y); `%` en
    puntos; `soloRevision`.
  - `ordenar`: numérico asc/desc; texto natural (`"1.10"` después de `"1.2"`); `null` = original.
  - `opcionesDe`: distintos y ordenados para `unidad` y `status`.
- **`web/src/components/corrida/TablaItems.test.tsx`** (añadir casos):
  - Con `control`: escribir en el filtro de Descripción reduce las filas visibles; un rango
    en Contractual filtra; el desplegable de Und filtra; clic en el encabezado "Costo" ordena
    (verifica el orden de las filas); "Limpiar filtros" restablece.
  - Sin `control` (modo vivo simulado): no aparece la fila de filtros (comportamiento actual).
- **Verificación:** desde `web/` → `npx tsc --noEmit`, `npx vitest run`, `npm run build`.
  Backend intacto (su suite no se toca).

## Criterios de aceptación

1. En una corrida cargada, cada encabezado ordena asc/desc/—; la fila de filtros permite
   filtrar por columna (texto "contiene", desplegable Und/Estado, rango mín–máx en los
   numéricos); los filtros se combinan con Y.
2. La barra de totales y `n_revision` **recalculan sobre lo filtrado**, y se indica
   "N de M ítems".
3. "Limpiar filtros" restablece filtros + orden + solo-revisión.
4. El **modo vivo** y el resto de la vista se comportan igual que antes.
5. `tsc` / `vitest` / `build` verdes; backend sin cambios; Invariante #1 intacta.
