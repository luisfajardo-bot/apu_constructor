# Columnas unitarias en la tabla de corrida — diseño

Fecha: 2026-07-09
Estado: aprobado (pendiente revisión de spec)

## Problema

Al abrir una corrida, la tabla de ítems muestra solo montos **totales**
(Contractual, Costo, Margen, %). Un total puede verse grande solo porque la
cantidad es alta; para detectar un precio "raro" hay que abrir el ítem y mirar
el costo unitario. Queremos ver los **unitarios** directamente en la tabla, sin
expandir cada fila, y abrir el ítem solo cuando un unitario se ve mal.

## Alcance

Cambio **100% frontend** (`web/src`). No se toca Python, API ni base de datos.
Los datos ya existen por ítem en el backend:

- `ItemCuadro.precio_contractual` — unitario contractual
- `ItemCuadro.costo_unitario` — unitario costo

(la GUI de escritorio ya los muestra; `contractual_total = precio_contractual ×
cantidad`). Los campos ya están declarados en `web/src/lib/tipos.ts`, así que
ese archivo no cambia.

## Orden final de columnas

```
Descripción · Und · Cantidad · Ítem · APU · Estado ·
Unit. Contractual · Unit. Costo · Total Contractual · Total Costo · Margen · %
```

- Se agregan **Unit. Contractual** y **Unit. Costo**, juntas, justo antes de los
  totales.
- Se renombran las columnas existentes: **Contractual → Total Contractual** y
  **Costo → Total Costo**. (Los `label` cambian; las claves internas
  `contractual_total` / `costo_total` NO cambian.)

## Comportamiento

Las dos columnas nuevas se comportan igual que las demás columnas de precio:

- **Filtro por rango** (mín/máx) en la cabecera.
- **Orden** al hacer clic en el encabezado (asc → desc → sin orden).
- Formato de moneda con `cop(...)`, alineadas a la derecha, `font-mono
  tabular-nums`.

No se agrega columna de margen unitario (fuera de alcance).

## Cambios por archivo

### 1. `web/src/lib/corridaTabla.ts` (motor de tabla)

- `ClaveColumna`: agregar `"precio_contractual"` y `"costo_unitario"`.
- `FiltrosColumna` y `FILTROS_VACIOS`: agregar sus `FiltroRango`.
- `filtrar()`: dos comprobaciones `enRango` nuevas.
- `valorNumero()`: mapear las dos claves nuevas a `it.precio_contractual` /
  `it.costo_unitario`. (Son numéricas, no van en `CLAVES_TEXTO`.)

### 2. `web/src/components/corrida/CabeceraFiltros.tsx` (cabecera con control)

- Insertar en `COLS` las dos columnas nuevas en su posición (antes de
  `contractual_total`), tipo `"num"`, `derecha: true`, `ancho: "w-28"`.
- Renombrar labels: `contractual_total → "Total Contractual"`,
  `costo_total → "Total Costo"`.

### 3. `web/src/components/corrida/TablaItems.tsx`

- **Cabecera estática** (ruta "vivo", sin `control`): mismas inserciones y
  renombres que en `CabeceraFiltros`.
- **Cuerpo**: dos `<TableCell>` nuevas mostrando `cop(it.precio_contractual)` y
  `cop(it.costo_unitario)`, con las mismas clases que las celdas de total.
- `TOTAL_COLS`: **11 → 13** (usado en el `colSpan` de la fila expandida y de la
  fila "No hay ítems").

## Pruebas

- `web/src/lib/corridaTabla.test.ts`: caso de orden y filtro por
  `precio_contractual` / `costo_unitario`.
- `web/src/components/corrida/TablaItems.test.tsx`: verificar presencia de las
  celdas unitarias y `colSpan` actualizado (si el test lo comprueba).
- Ejecutar la suite de tests del front antes de dar por terminado.

## Fuera de alcance

- Columna de margen unitario.
- Cambios de backend / API / DB.
- Exportación a Excel (el cuadro resumen ya tiene su propio formato).
