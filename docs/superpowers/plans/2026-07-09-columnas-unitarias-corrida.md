# Columnas unitarias en la tabla de corrida — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mostrar el precio unitario contractual y el costo unitario como columnas propias en la tabla de ítems de una corrida, con filtro y orden, para detectar unitarios "raros" sin abrir cada ítem.

**Architecture:** Cambio 100% frontend en `web/src`. Los datos ya vienen por ítem del backend (`ItemCuadro.precio_contractual`, `ItemCuadro.costo_unitario`), así que no se toca Python/API/DB ni `tipos.ts`. Se extiende el motor de tabla (`corridaTabla.ts`) con dos claves de columna nuevas, y ambas cabeceras (la de control con filtros y la estática del modo "vivo") más el cuerpo de `TablaItems.tsx` se actualizan para renderizarlas. Las columnas de total se renombran a "Total Contractual" / "Total Costo".

**Tech Stack:** React + TypeScript, Vitest + Testing Library. Comando de test: `npm test` desde `web/` (o `npx vitest run <archivo>` para un archivo).

**Orden final de columnas:**
`Descripción · Und · Cantidad · Ítem · APU · Estado · Unit. Contractual · Unit. Costo · Total Contractual · Total Costo · Margen · %`

**Nota de trabajo:** Todos los comandos se corren desde el directorio `web/`.

---

### Task 1: Extender el motor de tabla (claves, filtros, orden)

**Files:**
- Modify: `web/src/lib/corridaTabla.ts`
- Test: `web/src/lib/corridaTabla.test.ts`

- [ ] **Step 1: Escribir los tests que fallan**

Agregar estos tests al final de `web/src/lib/corridaTabla.test.ts`:

```typescript
test("filtrar: rango por precio_contractual (unitario)", () => {
  const items = [
    item({ precio_contractual: 100 }),
    item({ precio_contractual: 200 }),
    item({ precio_contractual: 300 }),
  ];
  const f = { ...FILTROS_VACIOS, precio_contractual: { min: "200", max: "" } };
  expect(filtrar(items, f, false).map((i) => i.precio_contractual)).toEqual([200, 300]);
});

test("filtrar: rango por costo_unitario", () => {
  const items = [
    item({ costo_unitario: 50 }),
    item({ costo_unitario: 150 }),
  ];
  const f = { ...FILTROS_VACIOS, costo_unitario: { min: "", max: "100" } };
  expect(filtrar(items, f, false).map((i) => i.costo_unitario)).toEqual([50]);
});

test("ordenar: por precio_contractual asc y desc", () => {
  const items = [
    item({ precio_contractual: 300 }),
    item({ precio_contractual: 100 }),
    item({ precio_contractual: 200 }),
  ];
  expect(ordenar(items, { clave: "precio_contractual", dir: "asc" }).map((i) => i.precio_contractual)).toEqual([100, 200, 300]);
  expect(ordenar(items, { clave: "precio_contractual", dir: "desc" }).map((i) => i.precio_contractual)).toEqual([300, 200, 100]);
});

test("ordenar: por costo_unitario asc", () => {
  const items = [item({ costo_unitario: 30 }), item({ costo_unitario: 10 })];
  expect(ordenar(items, { clave: "costo_unitario", dir: "asc" }).map((i) => i.costo_unitario)).toEqual([10, 30]);
});
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `npx vitest run src/lib/corridaTabla.test.ts`
Expected: FAIL — TypeScript rechaza `precio_contractual`/`costo_unitario` como `ClaveColumna` y como claves de `FILTROS_VACIOS`.

- [ ] **Step 3: Agregar las claves nuevas al tipo `ClaveColumna`**

En `web/src/lib/corridaTabla.ts`, reemplazar la definición del tipo:

```typescript
export type ClaveColumna =
  | "descripcion" | "unidad" | "cantidad" | "item" | "apu" | "status"
  | "precio_contractual" | "costo_unitario"
  | "contractual_total" | "costo_total" | "margen_total" | "margen_pct";
```

- [ ] **Step 4: Agregar los rangos a `FiltrosColumna` y `FILTROS_VACIOS`**

Reemplazar la interfaz `FiltrosColumna`:

```typescript
export interface FiltrosColumna {
  descripcion: string;
  unidad: string;
  cantidad: FiltroRango;
  item: string;
  apu: string;
  status: string;
  precio_contractual: FiltroRango;
  costo_unitario: FiltroRango;
  contractual_total: FiltroRango;
  costo_total: FiltroRango;
  margen_total: FiltroRango;
  margen_pct: FiltroRango;
}
```

Reemplazar `FILTROS_VACIOS`:

```typescript
export const FILTROS_VACIOS: FiltrosColumna = {
  descripcion: "", unidad: "", cantidad: { min: "", max: "" }, item: "",
  apu: "", status: "",
  precio_contractual: { min: "", max: "" }, costo_unitario: { min: "", max: "" },
  contractual_total: { min: "", max: "" },
  costo_total: { min: "", max: "" }, margen_total: { min: "", max: "" },
  margen_pct: { min: "", max: "" },
};
```

- [ ] **Step 5: Agregar las comprobaciones en `filtrar()`**

En la función `filtrar`, justo antes de `if (!enRango(it.contractual_total, f.contractual_total)) return false;`, agregar:

```typescript
    if (!enRango(it.precio_contractual, f.precio_contractual)) return false;
    if (!enRango(it.costo_unitario, f.costo_unitario)) return false;
```

- [ ] **Step 6: Mapear las claves nuevas en `valorNumero()`**

En la función `valorNumero`, agregar estos dos `case` antes de `case "contractual_total":`:

```typescript
    case "precio_contractual": return it.precio_contractual;
    case "costo_unitario": return it.costo_unitario;
```

(No se tocan `CLAVES_TEXTO` — ambas son numéricas.)

- [ ] **Step 7: Correr los tests y verificar que pasan**

Run: `npx vitest run src/lib/corridaTabla.test.ts`
Expected: PASS (todos, incluidos los 4 nuevos).

- [ ] **Step 8: Commit**

```bash
git add web/src/lib/corridaTabla.ts web/src/lib/corridaTabla.test.ts
git commit -m "feat(web): claves de tabla para unitario contractual y costo"
```

---

### Task 2: Cabecera con filtros (ruta con `control`)

**Files:**
- Modify: `web/src/components/corrida/CabeceraFiltros.tsx`

Esta tarea agrega las columnas a la cabecera que se muestra cuando hay `control`
(filtros + orden). No hay test unitario directo de este componente; se valida a
través de `TablaItems.test.tsx` en la Task 3. Por eso aquí no aplica TDD: es una
edición de configuración declarativa (el array `COLS`) que compila y se ejercita
después.

- [ ] **Step 1: Insertar las columnas nuevas y renombrar los totales en `COLS`**

En `web/src/components/corrida/CabeceraFiltros.tsx`, reemplazar estas dos líneas del array `COLS`:

```typescript
  { clave: "contractual_total", label: "Contractual", tipo: "num", ancho: "w-28", derecha: true },
  { clave: "costo_total", label: "Costo", tipo: "num", ancho: "w-28", derecha: true },
```

por estas cuatro (dos nuevas + dos renombradas), en este orden:

```typescript
  { clave: "precio_contractual", label: "Unit. Contractual", tipo: "num", ancho: "w-28", derecha: true },
  { clave: "costo_unitario", label: "Unit. Costo", tipo: "num", ancho: "w-28", derecha: true },
  { clave: "contractual_total", label: "Total Contractual", tipo: "num", ancho: "w-28", derecha: true },
  { clave: "costo_total", label: "Total Costo", tipo: "num", ancho: "w-28", derecha: true },
```

- [ ] **Step 2: Verificar que compila**

Run: `npx tsc -b --noEmit` (o confiar en que la Task 3 lo ejercita).
Expected: sin errores de tipo.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/corrida/CabeceraFiltros.tsx
git commit -m "feat(web): cabecera con columnas unitarias y renombre a Total"
```

---

### Task 3: Cabecera estática, celdas de cuerpo y colSpan en TablaItems

**Files:**
- Modify: `web/src/components/corrida/TablaItems.tsx`
- Test: `web/src/components/corrida/TablaItems.test.tsx`

- [ ] **Step 1: Escribir el test que falla + actualizar el test afectado por el renombre**

En `web/src/components/corrida/TablaItems.test.tsx`:

(a) Reemplazar, en el test "ordena por Costo al hacer clic en el encabezado", la línea:

```typescript
  fireEvent.click(screen.getByLabelText("Ordenar por Costo"));
```

por:

```typescript
  fireEvent.click(screen.getByLabelText("Ordenar por Total Costo"));
```

(b) Agregar este test nuevo al final del archivo:

```typescript
test("muestra el unitario contractual y el costo unitario en la fila", async () => {
  await import("./TablaItems");
  const items = [
    { ...ITEM, seq: 0, precio_contractual: 1234, costo_unitario: 567 },
  ];
  render(<TablaConControl items={items} />);
  // cop(): "$" + toLocaleString("es-CO"), sin espacio ni decimales
  expect(screen.getByText("$1.234")).toBeTruthy();
  expect(screen.getByText("$567")).toBeTruthy();
});
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `npx vitest run src/components/corrida/TablaItems.test.tsx`
Expected: FAIL — el test nuevo no encuentra "$1.234"/"$567" porque las columnas aún no se renderizan.

- [ ] **Step 3: Renombrar y agregar columnas en la cabecera estática**

En `web/src/components/corrida/TablaItems.tsx`, dentro del `<TableHeader>` del bloque `else` (cuando no hay `control`), reemplazar:

```tsx
              <TableHead className="text-xs w-28 text-right">Contractual</TableHead>
              <TableHead className="text-xs w-28 text-right">Costo</TableHead>
```

por:

```tsx
              <TableHead className="text-xs w-28 text-right">Unit. Contractual</TableHead>
              <TableHead className="text-xs w-28 text-right">Unit. Costo</TableHead>
              <TableHead className="text-xs w-28 text-right">Total Contractual</TableHead>
              <TableHead className="text-xs w-28 text-right">Total Costo</TableHead>
```

- [ ] **Step 4: Agregar las celdas unitarias en el cuerpo de la fila**

En el cuerpo (`<TableBody>`), justo antes de la celda que muestra `cop(it.contractual_total)`, agregar:

```tsx
                  <TableCell className="text-xs text-right font-mono tabular-nums">
                    {cop(it.precio_contractual)}
                  </TableCell>
                  <TableCell className="text-xs text-right font-mono tabular-nums">
                    {cop(it.costo_unitario)}
                  </TableCell>
```

- [ ] **Step 5: Actualizar `TOTAL_COLS`**

Reemplazar:

```tsx
  // Total columns = 1 (chevron) + 10 data cols = 11
  const TOTAL_COLS = 11;
```

por:

```tsx
  // Total columns = 1 (chevron) + 12 data cols = 13
  const TOTAL_COLS = 13;
```

- [ ] **Step 6: Correr los tests y verificar que pasan**

Run: `npx vitest run src/components/corrida/TablaItems.test.tsx`
Expected: PASS (incluido el test nuevo y el de orden renombrado).

- [ ] **Step 7: Correr toda la suite del front y el type-check**

Run: `npm test`
Expected: PASS (toda la suite).

Run: `npx tsc -b --noEmit`
Expected: sin errores de tipo.

- [ ] **Step 8: Commit**

```bash
git add web/src/components/corrida/TablaItems.tsx web/src/components/corrida/TablaItems.test.tsx
git commit -m "feat(web): columnas unitario contractual y costo en tabla de corrida"
```

---

## Verificación final (manual, opcional pero recomendado)

- [ ] Levantar el front (`npm run dev` desde `web/`), abrir una corrida y confirmar:
  - Se ven las 12 columnas de datos en el orden esperado.
  - "Total Contractual" y "Total Costo" reemplazan a "Contractual"/"Costo".
  - Filtro por rango y orden funcionan en las dos columnas nuevas.
  - La fila expandida (chevron) sigue ocupando todo el ancho (colSpan correcto).
  - El modo "vivo" (armado en progreso, sin filtros) muestra la cabecera estática con las columnas nuevas.
