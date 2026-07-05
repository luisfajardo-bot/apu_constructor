# Columna "Ítem" (código de licitación) en la corrida — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mostrar en la tabla de la corrida el código con el que cada actividad entró en la licitación (`ItemCuadro.item`), como columna nueva junto al APU asignado.

**Architecture:** Solo-frontend, un archivo. El dato `it.item` ya viaja en cada fila (`ItemCuadro`); se agrega una columna "Ítem" antes de "APU" en `TablaItems.tsx` y se ajusta `TOTAL_COLS`.

**Tech Stack:** React + TypeScript + Vite + Vitest.

## Global Constraints

- **Solo-frontend:** modificar únicamente `web/src/components/corrida/TablaItems.tsx` (+ su test). No tocar `apu_tool/`, `report.py`, ni ningún backend.
- **Sin datos nuevos:** `ItemCuadro.item` (código de licitación) ya existe en la respuesta de `vista_corrida`.
- Estética densa, `font-mono` para el código; reutilizar estilos existentes.
- Español; Invariante #1 (no toca la IA).
- Verificación (desde `web/`): `npx tsc --noEmit`, `npx vitest run`, `npm run build`.

---

### Task 1: Columna "Ítem" en `TablaItems.tsx` + test

**Files:**
- Modify: `web/src/components/corrida/TablaItems.tsx`
- Test: `web/src/components/corrida/TablaItems.test.tsx`

**Interfaces:**
- Consumes: `ItemCuadro.item` (string, código de licitación) — ya presente en el tipo y en los datos.
- Produces: una columna "Ítem" en la tabla; sin cambios de interfaz para otros módulos.

- [ ] **Step 1: Write the failing test**

En `web/src/components/corrida/TablaItems.test.tsx`, agregar (reusa el `ITEM` fixture y los mocks ya existentes en el archivo):

```tsx
test("muestra el código de licitación (Ítem) junto al APU", async () => {
  const { default: TablaItems } = await import("./TablaItems");
  render(
    <TablaItems corridaId={1} items={[{ ...ITEM, item: "OBRA-77" }]} onConfirmado={() => {}} />,
  );
  // el código con el que entró (Ítem) y el APU asignado (del fixture: "111"), ambos visibles
  expect(screen.getByText("OBRA-77")).toBeTruthy();
  expect(screen.getByText("111")).toBeTruthy();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (desde `web/`): `npx vitest run src/components/corrida/TablaItems.test.tsx`
Expected: FAIL — `getByText("OBRA-77")` no encuentra el texto (la columna aún no existe).

- [ ] **Step 3: Add the "Ítem" header**

En `TablaItems.tsx`, en el `<TableHeader>`, insertar la columna "Ítem" entre "Cantidad" y "APU":

```tsx
            <TableHead className="text-xs w-20 text-right">Cantidad</TableHead>
            <TableHead className="text-xs w-24">Ítem</TableHead>
            <TableHead className="text-xs w-28">APU</TableHead>
```

- [ ] **Step 4: Add the "Ítem" cell in the body row**

En el `<TableBody>`, insertar la celda del código de licitación entre la celda de "Cantidad" y la de `apu_codigo`:

```tsx
                  <TableCell className="text-xs text-right font-mono">
                    {it.cantidad.toLocaleString("es-CO")}
                  </TableCell>
                  <TableCell className="text-xs font-mono">{it.item}</TableCell>
                  <TableCell className="text-xs font-mono text-muted-foreground">
                    {it.apu_codigo}
                  </TableCell>
```

- [ ] **Step 5: Update `TOTAL_COLS` (10 → 11)**

En `TablaItems.tsx`, actualizar la constante y su comentario:

```tsx
  // Total columns = 1 (chevron) + 10 data cols = 11
  const TOTAL_COLS = 11;
```

- [ ] **Step 6: Run test to verify it passes**

Run (desde `web/`): `npx vitest run src/components/corrida/TablaItems.test.tsx`
Expected: PASS (el nuevo test + los existentes de `TablaItems`).

- [ ] **Step 7: Full verification**

Run (desde `web/`): `npx vitest run` (todo verde), `npx tsc --noEmit` (limpio), `npm run build` (OK).

- [ ] **Step 8: Commit**

```bash
git add web/src/components/corrida/TablaItems.tsx web/src/components/corrida/TablaItems.test.tsx
git commit -m "feat(web): columna Ítem (código de licitación) en la tabla de la corrida"
```

---

## Verificación final

- [ ] Desde `web/`: `npx tsc --noEmit`, `npx vitest run`, `npm run build` — verde/OK.
- [ ] La tabla de la corrida muestra "Ítem" (código de licitación) inmediatamente antes de "APU"; la fila expandida sigue ocupando el ancho completo (`TOTAL_COLS=11`).
- [ ] Backend intacto (no se tocó `apu_tool/`); Invariante #1 intacta.
