# Totales (contractual / costo / diferencia / margen%) en la lista de corridas — Diseño

**Fecha:** 2026-07-08
**Estado:** aprobado por el usuario (pendiente revisión del spec escrito)

## Objetivo

Mostrar en la **lista de corridas** (`Mis corridas`), sin tener que abrir cada una,
cuatro cifras por corrida: **precio contractual total**, **costo interno total**,
**diferencia en $** (contractual − costo) y **margen %** (diferencia ÷ contractual).

## Invariante central (requisito explícito del usuario)

Los valores de la lista deben ser **idénticos** a los que se ven al abrir la corrida.
No se inventa un cálculo nuevo: se **reutiliza el mismo cálculo** que ya produce
`vista_corrida` (el bloque `totales`). La lista solo trae esos números a la vista.

## Contexto actual

- `apu_tool/servicio/corridas.py::vista_corrida` (línea ~161) ya calcula el bloque
  `totales` = `{contractual, costo, margen, margen_pct, n_items, n_revision}`.
  Respeta el modo: **activa** = costeo en vivo (`_costear_row`, con `PricingEngine`
  + `precargar` en lote); **congelada** = snapshot inmutable (`_assembled_desde_snapshot`).
- `apu_tool/servicio/corridas.py::listar_corridas` (línea ~272) ya carga los ítems de
  cada corrida pero **solo los cuenta** (`n_items`, `n_revision`); no calcula totales.
- Frontend: `web/src/pages/MisCorridas.tsx` renderiza la tabla (columnas: Nombre, Items,
  Por revisar, Tiempo, Estado, Modo, Eliminar). Tipo `CorridaResumen`
  (`web/src/lib/tipos.ts:109`). API `listarCorridas()` (`web/src/api/corridas.ts:24`).
  Formateador de moneda: `web/src/lib/moneda.ts` (`toLocaleString("es-CO")`).

## Diseño

### 1. Backend — un solo cálculo, dos consumidores (DRY)

Extraer de `vista_corrida` dos helpers en `corridas.py`, para que lista y detalle
usen exactamente el mismo camino y **no puedan divergir**:

- `_ensamblar_corrida(alm, meta, rows, pricing) -> list[AssembledApu]`: el bucle
  actual que respeta el modo (congelada → snapshot por ítem, con caída a
  `_costear_row` si falta el snapshot; activa → `_costear_row(alm, r, pricing)`).
- `_totales(ensambles, rows) -> dict`: suma sobre los `AssembledApu`
  (`contractual_total`, `costo_total`) y devuelve
  `{contractual, costo, margen, margen_pct, n_items, n_revision}` — **misma fórmula
  que hoy** (`margen = contractual − costo`; `margen_pct = margen/contractual` o 0 si
  contractual = 0; `n_revision` = ítems con status en `("review","new")`).

`vista_corrida` pasa a usar ambos (ensambles → `items` vía `_vista_item` + `_totales`).
`listar_corridas` usa ambos por corrida: crea un `PricingEngine(alm)`, `precargar` las
claves de los ítems, `_ensamblar_corrida`, y `_totales`; agrega esos 4 campos a la
salida además de los actuales.

### 2. Robustez

El costeo de cada corrida dentro de `listar_corridas` va en `try/except`: si una
corrida falla al costear (dato inconsistente), sus 4 cifras quedan en `None` y la fila
igual aparece; **una corrida mala no rompe la lista**. (Los conteos `n_items`/
`n_revision` no dependen del costeo, así que se conservan siempre.)

### 3. API / tipos

- `listar_corridas` agrega por corrida: `contractual: float`, `costo: float`,
  `margen: float`, `margen_pct: float` (o `None` si el costeo falló).
- `CorridaResumen` (tipos.ts) gana esos 4 campos (`number | null`).
- `listarCorridas()` no cambia (ya devuelve `CorridaResumen[]`).

### 4. Frontend — `MisCorridas.tsx`

Cuatro columnas nuevas, numéricas, alineadas a la derecha, con `tabular-nums`, en el
formato de moneda de `@/lib/moneda`:

```
Nombre        Items  Por rev.  Contractual     Costo       Dif. $     Margen%  Estado  Modo …
```

- **Dif. $** y **Margen %**: color según signo — verde si ≥ 0, rojo si < 0.
- Si los campos vienen `null` (costeo falló), mostrar `—` en las 4 celdas.
- La fila sigue clicable (navega al detalle). Se mantiene el estilo denso actual.

### 5. Pruebas

- **Backend (invariante):** para una corrida **activa** y una **congelada**, los
  totales de `listar_corridas` == el bloque `totales` de `vista_corrida` (mismos
  `contractual`, `costo`, `margen`, `margen_pct`). Este test es el que blinda el
  requisito "deben ser los mismos valores".
- **Backend (robustez):** si el costeo de una corrida lanza, `listar_corridas` no
  propaga y devuelve esa fila con las cifras en `None`.
- **Frontend:** `MisCorridas` renderiza las 4 columnas con el formato correcto y aplica
  el color del margen según el signo; con `null` muestra `—`.

## Rendimiento

Cálculo al vuelo. Con la optimización reciente (motor compartido + precarga en lote),
cada corrida activa cuesta ~2 consultas; las congeladas salen del snapshot. Con el
volumen actual (pocas corridas) es imperceptible. **YAGNI:** no se cachea ni se
persiste el total ahora; si algún día se acumulan cientos de corridas se evaluará
cachear (fuera de alcance de este spec).

## Fuera de alcance

- Persistir/cachear totales por corrida.
- Cambios de formato en el detalle de la corrida (`Corrida.tsx`).
- Ordenar/filtrar la lista por estas nuevas columnas.
