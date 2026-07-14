# Costo editable en el armador de APUs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir ajustar el costo de un componente en el diálogo de APUs y que el rendimiento se recalcule solo (y viceversa), mostrando el costo total del APU en vivo.

**Architecture:** Cambio 100% frontend. El costo nunca se persiste: es siempre `rendimiento × precio`. Editar el costo solo despeja y guarda el rendimiento (Opción A del diseño). El precio es un ancla de solo lectura (precio vigente del insumo, o costo del sub-APU). El payload de guardado y el backend no cambian. Lógica pura aislada en un módulo nuevo, testeada sin UI; la UI la consume.

**Tech Stack:** React 19 + TypeScript, Vitest + React Testing Library, Tailwind. Todo dentro de `web/`.

## Global Constraints

- Trabajar en la rama `feat/costo-editable-apu` (ya creada).
- **Sin cambios de backend** ni de contratos de API. El payload de guardado sigue enviando solo `rendimiento` por componente.
- **Nada toca la IA** (invariante #1): esto es dinero de cara al usuario, como el cuadro y la vista `DetalleApu`.
- Nombres de dominio, comentarios y textos de UI **en español**.
- No romper tests existentes. La suite corre desde `web/`.
- Costos en pesos enteros, consistente con `cop()` de `@/lib/moneda` (`$` + `toLocaleString("es-CO")`).
- El precio del insumo NO se edita aquí (sigue en la página de Insumos).
- Comandos de test (desde la raíz del repo, con Bash):
  - Un archivo: `cd web && npx vitest run <ruta-relativa-a-web>`
  - Typecheck: `cd web && npx tsc -b`
  - Suite completa: `cd web && npm run test`

---

### Task 1: Helpers puros del enlace costo ↔ rendimiento

**Files:**
- Create: `web/src/lib/costoApu.ts`
- Test: `web/src/lib/costoApu.test.ts`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `interface FilaCosto { insumo_codigo: string; rendimiento: string; precio: number }`
  - `costoDeFila(rendimiento: string, precio: number): number`
  - `rendimientoDesdeCosto(costo: string, precio: number): number | null`
  - `costoTotalApu(filas: FilaCosto[]): number`

- [ ] **Step 1: Escribir el test que falla**

Create `web/src/lib/costoApu.test.ts`:

```ts
import { costoDeFila, rendimientoDesdeCosto, costoTotalApu } from "./costoApu";

test("costoDeFila: rendimiento × precio; 0 si el rendimiento no es número", () => {
  expect(costoDeFila("2.5", 2000)).toBe(5000);
  expect(costoDeFila("0", 2000)).toBe(0);
  expect(costoDeFila("", 2000)).toBe(0);
  expect(costoDeFila("abc", 2000)).toBe(0);
});

test("rendimientoDesdeCosto: despeja costo/precio; null cuando no se puede", () => {
  expect(rendimientoDesdeCosto("5000", 2000)).toBe(2.5);
  expect(rendimientoDesdeCosto("5000", 0)).toBeNull();   // precio 0 → no se despeja
  expect(rendimientoDesdeCosto("5000", -3)).toBeNull();
  expect(rendimientoDesdeCosto("", 2000)).toBeNull();
  expect(rendimientoDesdeCosto("abc", 2000)).toBeNull();
});

test("ida y vuelta: despejar y volver a costear da el mismo peso", () => {
  const precio = 3;
  const r = rendimientoDesdeCosto("100", precio);
  expect(r).not.toBeNull();
  expect(Math.round(costoDeFila(String(r), precio))).toBe(100);
});

test("costoTotalApu: suma solo las filas con insumo elegido", () => {
  const filas = [
    { insumo_codigo: "A1", rendimiento: "2", precio: 1000 },    // 2000
    { insumo_codigo: "A2", rendimiento: "1.5", precio: 2000 },  // 3000
    { insumo_codigo: "", rendimiento: "10", precio: 5000 },     // ignorada
  ];
  expect(costoTotalApu(filas)).toBe(5000);
});
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `cd web && npx vitest run src/lib/costoApu.test.ts`
Expected: FAIL — no existe el módulo `./costoApu`.

- [ ] **Step 3: Implementación mínima**

Create `web/src/lib/costoApu.ts`:

```ts
// Lógica pura del enlace costo ↔ rendimiento en la composición de un APU.
// Aislada para testear sin montar la UI (como validacionApu.ts).
// El costo NO se persiste: siempre es rendimiento × precio. Editar el costo solo
// despeja el rendimiento (Opción A del diseño): el APU guarda estructura, no dinero.

export interface FilaCosto {
  insumo_codigo: string;
  rendimiento: string;
  precio: number;
}

/** Costo de una fila = rendimiento × precio. 0 si el rendimiento no es número. */
export function costoDeFila(rendimiento: string, precio: number): number {
  const r = Number(rendimiento);
  if (!Number.isFinite(r) || rendimiento.trim() === "") return 0;
  return r * precio;
}

/**
 * Despeja el rendimiento desde un costo objetivo: rendimiento = costo / precio.
 * Devuelve null cuando no se puede despejar (precio <= 0, o costo vacío / no numérico).
 */
export function rendimientoDesdeCosto(costo: string, precio: number): number | null {
  if (precio <= 0) return null;
  const c = Number(costo);
  if (!Number.isFinite(c) || costo.trim() === "") return null;
  return c / precio;
}

/** Costo unitario del APU = suma de costos de las filas con insumo elegido. */
export function costoTotalApu(filas: FilaCosto[]): number {
  return filas
    .filter((f) => f.insumo_codigo.trim() !== "")
    .reduce((acc, f) => acc + costoDeFila(f.rendimiento, f.precio), 0);
}
```

- [ ] **Step 4: Correr el test para verificar que pasa**

Run: `cd web && npx vitest run src/lib/costoApu.test.ts`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/costoApu.ts web/src/lib/costoApu.test.ts
git commit -m "feat(apus): helpers puros del enlace costo<->rendimiento"
```

---

### Task 2: Plumbear el precio en la fila + columna Precio (solo lectura)

**Files:**
- Modify: `web/src/components/autoria/DialogoAgregarApu.tsx`
- Modify: `web/src/components/autoria/DialogoAgregarApu.test.tsx` (actualizar literales de `FilaComp`)

**Interfaces:**
- Consumes: `cop` de `@/lib/moneda`. `LineaComposicion.precio_unitario`, `Insumo.precio`, `ApuResumen.costo_unitario` (ya existen en `@/lib/tipos`).
- Produces: `FilaComp` gana el campo `precio: number`. Una nueva columna **Precio** (solo lectura) en la tabla de composición.

- [ ] **Step 1: Escribir el test que falla**

Add to `web/src/components/autoria/DialogoAgregarApu.test.tsx` (después de los tests existentes). Añade al principio del archivo un objeto `inicial` reutilizable justo debajo de los `vi.mock`:

```tsx
const inicialDemo = {
  codigo: "100", turno: "DIURNO", nombre: "APU DEMO", unidad: "M3", grupo: "G",
  costo_unitario: 4000,
  composicion: [{
    insumo_codigo: "C1", insumo_nombre: "CEMENTO", unidad: "KG",
    rendimiento: 2, precio_unitario: 2000, fuente_precio: "PRECIO IDU",
    costo: 4000, calidad_cruce: "exacto",
  }],
};

test("modo editar muestra el precio del componente (solo lectura)", async () => {
  const { DialogoAgregarApu } = await import("./DialogoAgregarApu");
  render(
    <DialogoAgregarApu
      open onOpenChange={() => {}} onCreado={() => {}}
      modo="editar" inicial={inicialDemo as never}
    />,
  );
  expect(screen.getByText("$2.000")).toBeTruthy();   // precio del insumo
});
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `cd web && npx vitest run src/components/autoria/DialogoAgregarApu.test.tsx`
Expected: FAIL — no aparece "$2.000" (no hay columna de precio todavía).

- [ ] **Step 3: Implementación — agregar `precio` a `FilaComp` y poblarlo**

En `web/src/components/autoria/DialogoAgregarApu.tsx`:

3a. Import de `cop` (junto a los imports existentes de `@/`):

```tsx
import { cop } from "@/lib/moneda";
```

3b. Interface `FilaComp` — agregar el campo `precio` (queda así):

```tsx
interface FilaComp {
  // id local para keys estables
  uid: number;
  tipo: "insumo" | "apu";
  ref_shift: string;
  insumo_codigo: string;
  insumo_nombre: string;
  unidad: string;
  rendimiento: string;
  precio: number;
}
```

3c. `nuevaFila` — agregar `precio: 0` al objeto devuelto:

```tsx
function nuevaFila(tipo: "insumo" | "apu" = "insumo"): FilaComp {
  return {
    uid: uidSeq++,
    tipo,
    ref_shift: "",
    insumo_codigo: "",
    insumo_nombre: "",
    unidad: "",
    rendimiento: "",
    precio: 0,
  };
}
```

3d. En el efecto de carga (`modo === "editar"`), el `.map` de `inicial.composicion` — agregar `precio: c.precio_unitario` al objeto devuelto (junto a `rendimiento: String(c.rendimiento)`):

```tsx
              return {
                uid: uidSeq++,
                tipo,
                ref_shift,
                insumo_codigo: c.insumo_codigo,
                insumo_nombre: c.insumo_nombre,
                unidad: c.unidad,
                rendimiento: String(c.rendimiento),
                precio: c.precio_unitario,
              };
```

3e. En `BuscadorInsumo`, el `onElegir` (la llamada a `setFila` dentro de la fila de insumo) — agregar `precio: ins.precio`:

```tsx
                            onElegir={(ins) =>
                              setFila(f.uid, {
                                insumo_codigo: ins.codigo,
                                insumo_nombre: ins.nombre,
                                unidad: ins.unidad,
                                precio: ins.precio,
                              })
                            }
```

3f. En `SubApuFila`, el `onElegir` (la llamada a `setFila` dentro de la fila sub-APU) — agregar `precio: apu.costo_unitario`:

```tsx
                            onElegir={(apu) =>
                              setFila(f.uid, {
                                insumo_codigo: apu.codigo,
                                insumo_nombre: apu.nombre,
                                unidad: apu.unidad,
                                ref_shift: apu.turno,
                                precio: apu.costo_unitario,
                              })
                            }
```

- [ ] **Step 4: Implementación — columna Precio en la tabla**

4a. En el `<thead>`, insertar una celda **Precio** entre la de "Rendimiento" y la celda vacía (`w-8`):

```tsx
                  <th className="px-2 py-1 text-right font-medium text-muted-foreground border-b w-28">
                    Rendimiento
                  </th>
                  <th className="px-2 py-1 text-right font-medium text-muted-foreground border-b w-24">
                    Precio
                  </th>
                  <th className="px-2 py-1 border-b w-8" />
```

4b. En el `<tbody>`, dentro de cada fila, insertar la celda de Precio justo **después** de la celda del input de rendimiento (la que tiene `type="number"`) y **antes** de la celda del botón "Quitar fila":

```tsx
                      <td className="px-2 py-1 border-b text-right font-mono tabular-nums text-muted-foreground">
                        {f.precio > 0 ? cop(f.precio) : "—"}
                      </td>
```

- [ ] **Step 5: Actualizar los literales de `FilaComp` en el test existente**

En `web/src/components/autoria/DialogoAgregarApu.test.tsx`, el test `"componenteDeFila incluye tipo/ref_shift…"` construye dos objetos `FilaComp` sin `precio`. Agregar `precio: 0` a ambos para que compilen:

```tsx
  const apu = componenteDeFila({
    uid: 1, tipo: "apu", ref_shift: "DIURNO",
    insumo_codigo: "9001", insumo_nombre: "SUB APU DEMO", unidad: "M3",
    rendimiento: "3", precio: 0,
  });
```

```tsx
  const ins = componenteDeFila({
    uid: 2, tipo: "insumo", ref_shift: "",
    insumo_codigo: "100", insumo_nombre: "CEMENTO", unidad: "KG",
    rendimiento: "2", precio: 0,
  });
```

- [ ] **Step 6: Correr tests y typecheck**

Run: `cd web && npx vitest run src/components/autoria/DialogoAgregarApu.test.tsx`
Expected: PASS (los 3 tests previos + el nuevo "muestra el precio").

Run: `cd web && npx tsc -b`
Expected: sin errores de tipos (confirma que los literales de `FilaComp` quedaron completos).

- [ ] **Step 7: Commit**

```bash
git add web/src/components/autoria/DialogoAgregarApu.tsx web/src/components/autoria/DialogoAgregarApu.test.tsx
git commit -m "feat(apus): columna Precio (solo lectura) en el diálogo de composición"
```

---

### Task 3: Columna Costo editable con enlace bidireccional

**Files:**
- Modify: `web/src/components/autoria/DialogoAgregarApu.tsx`
- Modify: `web/src/components/autoria/DialogoAgregarApu.test.tsx`

**Interfaces:**
- Consumes: `costoDeFila`, `rendimientoDesdeCosto` de `@/lib/costoApu`; `rendimientoValido` de `@/lib/validacionApu` (ya importado); `FilaComp.precio` (Task 2).
- Produces: nueva columna **Costo** (input) enlazada con el rendimiento. El input de rendimiento gana `aria-label="Rendimiento"` y el de costo `aria-label="Costo"`.

- [ ] **Step 1: Escribir los tests que fallan**

Add to `web/src/components/autoria/DialogoAgregarApu.test.tsx`:

```tsx
test("editar el costo despeja el rendimiento (precio 2000, costo 6000 → rend 3)", async () => {
  const { DialogoAgregarApu } = await import("./DialogoAgregarApu");
  render(
    <DialogoAgregarApu open onOpenChange={() => {}} onCreado={() => {}}
      modo="editar" inicial={inicialDemo as never} />,
  );
  const costo = screen.getByLabelText("Costo") as HTMLInputElement;
  expect(costo.value).toBe("4000");                       // 2 × 2000
  fireEvent.change(costo, { target: { value: "6000" } });
  const rend = screen.getByLabelText("Rendimiento") as HTMLInputElement;
  expect(rend.value).toBe("3");                           // 6000 / 2000
});

test("editar el rendimiento actualiza el costo mostrado (rend 5 → costo 10000)", async () => {
  const { DialogoAgregarApu } = await import("./DialogoAgregarApu");
  render(
    <DialogoAgregarApu open onOpenChange={() => {}} onCreado={() => {}}
      modo="editar" inicial={inicialDemo as never} />,
  );
  const rend = screen.getByLabelText("Rendimiento") as HTMLInputElement;
  fireEvent.change(rend, { target: { value: "5" } });
  const costo = screen.getByLabelText("Costo") as HTMLInputElement;
  expect(costo.value).toBe("10000");                      // 5 × 2000
});

test("precio 0: no hay input de costo; el rendimiento sigue editable", async () => {
  const inicialSinPrecio = {
    ...inicialDemo,
    composicion: [{ ...inicialDemo.composicion[0], precio_unitario: 0, costo: 0 }],
  };
  const { DialogoAgregarApu } = await import("./DialogoAgregarApu");
  render(
    <DialogoAgregarApu open onOpenChange={() => {}} onCreado={() => {}}
      modo="editar" inicial={inicialSinPrecio as never} />,
  );
  expect(screen.queryByLabelText("Costo")).toBeNull();    // sin input de costo
  expect(screen.getByLabelText("Rendimiento")).toBeTruthy();
});
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `cd web && npx vitest run src/components/autoria/DialogoAgregarApu.test.tsx`
Expected: FAIL — `getByLabelText("Costo")` / `("Rendimiento")` no encuentran nada (aún sin aria-labels ni columna Costo).

- [ ] **Step 3: Implementación — imports y aria-label del rendimiento**

3a. Ampliar el import de `@/lib/costoApu` (agregar el import nuevo junto a los demás de `@/`):

```tsx
import { costoDeFila, rendimientoDesdeCosto } from "@/lib/costoApu";
```

3b. Al input de rendimiento (el `<input type="number">` existente), agregar `aria-label="Rendimiento"`:

```tsx
                        <input
                          className={`${inputCls} text-right ${rendMal ? "border-destructive" : ""}`}
                          type="number"
                          min="0"
                          step="any"
                          aria-label="Rendimiento"
                          value={f.rendimiento}
                          onChange={(e) =>
                            setFila(f.uid, { rendimiento: e.target.value })
                          }
                          aria-invalid={rendMal}
                        />
```

- [ ] **Step 4: Implementación — columna Costo (header + celda con input)**

4a. En el `<thead>`, insertar la celda **Costo** entre "Precio" y la celda vacía (`w-8`):

```tsx
                  <th className="px-2 py-1 text-right font-medium text-muted-foreground border-b w-24">
                    Precio
                  </th>
                  <th className="px-2 py-1 text-right font-medium text-muted-foreground border-b w-24">
                    Costo
                  </th>
                  <th className="px-2 py-1 border-b w-8" />
```

4b. En cada fila, insertar la celda de Costo **después** de la celda de Precio (la de Task 2) y **antes** del botón "Quitar fila":

```tsx
                      <td className="px-2 py-1 border-b">
                        {f.precio > 0 ? (
                          <input
                            className={`${inputCls} text-right`}
                            type="number"
                            min="0"
                            step="any"
                            aria-label="Costo"
                            value={
                              rendimientoValido(f.rendimiento)
                                ? String(Math.round(costoDeFila(f.rendimiento, f.precio)))
                                : ""
                            }
                            onChange={(e) => {
                              const v = e.target.value;
                              if (v.trim() === "") {
                                setFila(f.uid, { rendimiento: "" });
                                return;
                              }
                              const r = rendimientoDesdeCosto(v, f.precio);
                              if (r !== null) setFila(f.uid, { rendimiento: String(r) });
                            }}
                          />
                        ) : (
                          <span
                            className="block text-right text-muted-foreground"
                            title="Sin precio; ajusta el rendimiento"
                          >
                            —
                          </span>
                        )}
                      </td>
```

- [ ] **Step 5: Correr los tests para verificar que pasan**

Run: `cd web && npx vitest run src/components/autoria/DialogoAgregarApu.test.tsx`
Expected: PASS (todos, incluidos los 3 nuevos).

Run: `cd web && npx tsc -b`
Expected: sin errores de tipos.

- [ ] **Step 6: Commit**

```bash
git add web/src/components/autoria/DialogoAgregarApu.tsx web/src/components/autoria/DialogoAgregarApu.test.tsx
git commit -m "feat(apus): costo editable con enlace bidireccional costo<->rendimiento"
```

---

### Task 4: Costo unitario total del APU en vivo

**Files:**
- Modify: `web/src/components/autoria/DialogoAgregarApu.tsx`
- Modify: `web/src/components/autoria/DialogoAgregarApu.test.tsx`

**Interfaces:**
- Consumes: `costoTotalApu` de `@/lib/costoApu`; `FilaComp[]` (superset de `FilaCosto`); `cop` (ya importado en Task 2).
- Produces: pie del diálogo con el costo unitario total, recalculado en vivo.

- [ ] **Step 1: Escribir el test que falla**

Add to `web/src/components/autoria/DialogoAgregarApu.test.tsx`:

```tsx
test("el total del APU refleja el costo de las filas y se actualiza al editar", async () => {
  const { DialogoAgregarApu } = await import("./DialogoAgregarApu");
  render(
    <DialogoAgregarApu open onOpenChange={() => {}} onCreado={() => {}}
      modo="editar" inicial={inicialDemo as never} />,
  );
  expect(screen.getByText("Costo unitario del APU:")).toBeTruthy();
  expect(screen.getByText("$4.000")).toBeTruthy();        // total inicial: 2 × 2000
  const rend = screen.getByLabelText("Rendimiento") as HTMLInputElement;
  fireEvent.change(rend, { target: { value: "5" } });
  expect(screen.getByText("$10.000")).toBeTruthy();       // 5 × 2000
});
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `cd web && npx vitest run src/components/autoria/DialogoAgregarApu.test.tsx`
Expected: FAIL — no existe el texto "Costo unitario del APU:".

- [ ] **Step 3: Implementación — import y pie con el total**

3a. Ampliar el import de `@/lib/costoApu` (quedaría con los tres helpers):

```tsx
import { costoDeFila, rendimientoDesdeCosto, costoTotalApu } from "@/lib/costoApu";
```

3b. Insertar el bloque del total **entre** el cierre del bloque de "Composición" (el `</div>` que cierra el `<div>` con la tabla) y el `<DialogFooter>`:

```tsx
        <div className="flex justify-end items-baseline gap-2 text-xs">
          <span className="text-muted-foreground">Costo unitario del APU:</span>
          <span className="font-mono tabular-nums font-semibold">
            {cop(costoTotalApu(filas))}
          </span>
        </div>
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `cd web && npx vitest run src/components/autoria/DialogoAgregarApu.test.tsx`
Expected: PASS (todos).

Run: `cd web && npx tsc -b`
Expected: sin errores de tipos.

- [ ] **Step 5: Verificación final de toda la suite**

Run: `cd web && npm run test`
Expected: toda la suite del front en verde.

- [ ] **Step 6: Commit**

```bash
git add web/src/components/autoria/DialogoAgregarApu.tsx web/src/components/autoria/DialogoAgregarApu.test.tsx
git commit -m "feat(apus): costo unitario total del APU en vivo en el diálogo"
```

---

## Notas de verificación manual (post-implementación)

Levantar el front (`cd web && npm run dev`) y, autenticado como editor, en la página de APUs:
1. Editar un APU con insumos con precio: cambiar el **rendimiento** de una fila → el **costo** y el **total** se actualizan.
2. Escribir un **costo** objetivo en una fila → el **rendimiento** se recalcula; guardar y reabrir → el costo mostrado coincide (salvo redondeo al peso).
3. Un componente con precio 0 (material del cliente / huérfano) muestra "—" en costo y deja editar el rendimiento.
4. Crear un APU nuevo, elegir insumos y fijar costos → guarda bien; el cuadro/costeo re-deriva el mismo costo con el precio vigente.
