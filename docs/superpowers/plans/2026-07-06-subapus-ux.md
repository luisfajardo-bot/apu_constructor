# UX de sub-APUs (editor + badge) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Poder crear/editar componentes sub-APU desde el editor de APU y distinguir las líneas de sub-APU (badge) en la corrida y en el detalle de la biblioteca.

**Architecture:** El detalle de APU expone `tipo`/`ref_shift` por línea (backend chico). Un badge reutilizable `SubApuBadge` marca las líneas de sub-APU en las dos tablas de "Composición costeada" que ya existen (corrida y biblioteca). El editor `DialogoAgregarApu` gana filas tipadas (insumo/sub-APU) con `BuscadorApu` y round-tripea `tipo`/`ref_shift`.

**Tech Stack:** Python + pytest (backend); React + TypeScript + Vitest (frontend).

## Global Constraints

- **Apilado sobre `feat/subapus-import`** (Fase 1 + import). Usa `ApuComponent.tipo`/`ref_shift`, el costeo recursivo, `ComponenteIn` (ya acepta `tipo`/`ref_shift`) y `editar_apu` (preserva marcas). No reimplementar nada de eso.
- **Trabajo LOCAL, sin push a prod.** Sin dependencias nuevas. Español. Invariante #1 (nada de dinero a la IA).
- **LISTÓN DE DISEÑO (impecable, atractivo, NO vibecodeado):** reutilizar el lenguaje visual existente — el chip debe seguir el patrón de `EstadoBadge.tsx` (`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-semibold leading-none uppercase tracking-wide` + colores); botones con las variantes de `@/components/ui/button`; tablas densas ya presentes; reusar `BuscadorApu`/`BuscadorInsumo`. Denso, table-first, **sin cards**, coherente con los diálogos actuales. No introducir estilos nuevos ad-hoc.
- Verificación: `python -m pytest tests/ -q`; desde `web/`: `npx tsc --noEmit`, `npx vitest run`, `npm run build`.

---

### Task 1: El detalle de APU expone `tipo`/`ref_shift`

**Files:**
- Modify: `apu_tool/servicio/apus.py:43-47` (dict de `composicion` en `detalle`)
- Modify: `web/src/lib/tipos.ts:50-59` (`LineaComposicion`)
- Test: `tests/test_apus_detalle_subapu.py`

**Interfaces:**
- Consumes: `CostedComponent.tipo`/`ref_shift` (ya presentes).
- Produces: cada línea de `apus_svc.detalle(...)["composicion"]` incluye `tipo` y `ref_shift`; `LineaComposicion` (frontend) gana `tipo: string` y `ref_shift: string`.

- [ ] **Step 1: Write the failing test**

Crear `tests/test_apus_detalle_subapu.py`:

```python
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo
from apu_tool.servicio import apus as apus_svc


def _alm(tmp_path):
    a = Almacen(tmp_path / "p.db", tmp_path / "a.db")
    a.reset()
    return a


def test_detalle_expone_tipo_y_ref_shift(tmp_path):
    alm = _alm(tmp_path)
    alm.precios.insert_insumos([Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU")])
    # sub-APU B
    alm.apus.insert_apus([Apu("B", "SUBAPU", "M3", "DIURNO")])
    alm.apus.insert_components([ApuComponent("B", "DIURNO", "100", "CEMENTO", "KG", 2.0, 0.0)])
    # APU A: un componente insumo + un componente sub-APU (B)
    alm.apus.insert_apus([Apu("A", "COMP", "M2", "DIURNO")])
    alm.apus.insert_components([
        ApuComponent("A", "DIURNO", "100", "CEMENTO", "KG", 1.0, 0.0),
        ApuComponent("A", "DIURNO", "B", "SUBAPU", "M3", 3.0, 0.0, tipo="apu", ref_shift="DIURNO"),
    ])
    d = apus_svc.detalle(alm, "A", "DIURNO")
    porcod = {l["insumo_codigo"]: l for l in d["composicion"]}
    assert porcod["B"]["tipo"] == "apu" and porcod["B"]["ref_shift"] == "DIURNO"
    assert porcod["100"]["tipo"] == "insumo" and porcod["100"]["ref_shift"] == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_apus_detalle_subapu.py -q`
Expected: FAIL — las líneas de `composicion` no tienen `tipo`/`ref_shift`.

- [ ] **Step 3: Añadir `tipo`/`ref_shift` al dict del detalle**

En `apu_tool/servicio/apus.py`, en `detalle`, la comprensión de `composicion` (líneas 43-47) → añadir los dos campos:

```python
        "composicion": [{
            "insumo_codigo": c.insumo_codigo, "insumo_nombre": c.insumo_nombre,
            "unidad": c.unidad, "rendimiento": c.rendimiento,
            "precio_unitario": c.precio_unitario, "fuente_precio": c.fuente_precio,
            "costo": c.costo, "calidad_cruce": c.calidad_cruce,
            "tipo": c.tipo, "ref_shift": c.ref_shift} for c in costed],
```

- [ ] **Step 4: Actualizar el tipo del frontend**

En `web/src/lib/tipos.ts`, `LineaComposicion` (líneas 50-59) → añadir dos campos:

```ts
export interface LineaComposicion {
  insumo_codigo: string;
  insumo_nombre: string;
  unidad: string;
  rendimiento: number;
  precio_unitario: number;
  fuente_precio: string;
  costo: number;
  calidad_cruce: string;
  tipo: string;
  ref_shift: string;
}
```

- [ ] **Step 5: Run test + tsc**

Run: `python -m pytest tests/test_apus_detalle_subapu.py -q` → PASS.
Desde `web/`: `npx tsc --noEmit` → limpio (los consumidores de `LineaComposicion` no rompen; los campos son nuevos).

- [ ] **Step 6: Commit**

```bash
git add apu_tool/servicio/apus.py web/src/lib/tipos.ts tests/test_apus_detalle_subapu.py
git commit -m "feat(apus): el detalle expone tipo/ref_shift por línea de composición"
```

---

### Task 2: Badge `SubApuBadge` + marcar sub-APUs en las tablas de composición

**Files:**
- Create: `web/src/components/SubApuBadge.tsx`
- Modify: `web/src/components/corrida/TablaItems.tsx` (celda "Cruce" en `DetalleExpandido`, líneas 369-371)
- Modify: `web/src/pages/Apus.tsx` (celda "Cruce" en `DetalleApu`, líneas 387-389)
- Test: `web/src/components/SubApuBadge.test.tsx`

**Interfaces:**
- Consumes: `LineaComposicion.calidad_cruce` (`"apu"` para sub-APUs).
- Produces: componente `SubApuBadge` (default export) reutilizable.

- [ ] **Step 1: Write the failing test**

Crear `web/src/components/SubApuBadge.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import SubApuBadge from "./SubApuBadge";

test("renderiza el chip APU", () => {
  render(<SubApuBadge />);
  expect(screen.getByText("APU")).toBeTruthy();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (desde `web/`): `npx vitest run src/components/SubApuBadge.test.tsx`
Expected: FAIL — `SubApuBadge` no existe.

- [ ] **Step 3: Crear `SubApuBadge` (mismo lenguaje visual que `EstadoBadge`)**

Crear `web/src/components/SubApuBadge.tsx`:

```tsx
import { cn } from "@/lib/utils";

/** Chip para marcar una línea/fila que es un sub-APU. Sigue el estilo de EstadoBadge. */
export default function SubApuBadge({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-semibold",
        "leading-none uppercase tracking-wide bg-indigo-100 text-indigo-800 border-indigo-200",
        className,
      )}
    >
      APU
    </span>
  );
}
```

- [ ] **Step 4: Usarlo en la corrida (`TablaItems.tsx`)**

En `web/src/components/corrida/TablaItems.tsx`, importar arriba:

```tsx
import SubApuBadge from "@/components/SubApuBadge";
```

En `DetalleExpandido`, la celda "Cruce" (líneas 369-371) → reemplazar el texto crudo por el badge cuando es sub-APU:

```tsx
                  <TableCell className="text-xs text-muted-foreground">
                    {lin.calidad_cruce === "apu"
                      ? <SubApuBadge />
                      : lin.calidad_cruce}
                  </TableCell>
```

- [ ] **Step 5: Usarlo en la biblioteca (`Apus.tsx`)**

En `web/src/pages/Apus.tsx`, importar arriba:

```tsx
import SubApuBadge from "@/components/SubApuBadge";
```

En `DetalleApu`, la celda "Cruce" (líneas 387-389) → mismo reemplazo:

```tsx
                <TableCell className="text-xs text-muted-foreground">
                  {lin.calidad_cruce === "apu"
                    ? <SubApuBadge />
                    : lin.calidad_cruce}
                </TableCell>
```

- [ ] **Step 6: Run test + tsc**

Run (desde `web/`): `npx vitest run src/components/SubApuBadge.test.tsx` → PASS.
`npx tsc --noEmit` → limpio.

- [ ] **Step 7: Commit**

```bash
git add web/src/components/SubApuBadge.tsx web/src/components/corrida/TablaItems.tsx web/src/pages/Apus.tsx web/src/components/SubApuBadge.test.tsx
git commit -m "feat(web): badge SubApuBadge en la composición de la corrida y la biblioteca"
```

---

### Task 3: Editor de APU — agregar/editar componentes sub-APU

**Files:**
- Modify: `web/src/components/autoria/DialogoAgregarApu.tsx`
- Modify: `web/src/lib/tipos.ts:183-188` (`ComponenteNuevo`)
- Test: `web/src/components/autoria/DialogoAgregarApu.test.tsx`

**Interfaces:**
- Consumes: `LineaComposicion.tipo`/`ref_shift` (Task 1); `SubApuBadge` (Task 2); `BuscadorApu` (`@/components/corrida/BuscadorApu`, default export; `onElegir(apu: ApuResumen)` con `{codigo, turno, nombre, unidad, ...}`).
- Produces: componentes con `tipo`/`ref_shift` hacia `crearApu`/`editarApu`; helpers puros `componenteDeFila` y `tipoRefDeLinea` (exportados para test).

- [ ] **Step 1: Write the failing tests**

Crear `web/src/components/autoria/DialogoAgregarApu.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";

vi.mock("@/api/autoria", () => ({
  crearApu: vi.fn(async () => ({})),
  editarApu: vi.fn(async () => ({})),
  listarApus: vi.fn(async () => ({
    items: [{ codigo: "9001", turno: "DIURNO", nombre: "SUB APU DEMO",
              unidad: "M3", grupo: "G", n_componentes: 2, costo_unitario: 0 }],
    total: 1, limit: 15, offset: 0,
  })),
}));
vi.mock("@/api/insumos", () => ({
  listarInsumos: vi.fn(async () => ({ items: [], total: 0, limit: 15, offset: 0 })),
}));

test("componenteDeFila incluye tipo/ref_shift en una fila sub-APU", async () => {
  const { componenteDeFila } = await import("./DialogoAgregarApu");
  const apu = componenteDeFila({
    uid: 1, tipo: "apu", ref_shift: "DIURNO",
    insumo_codigo: "9001", insumo_nombre: "SUB APU DEMO", unidad: "M3", rendimiento: "3",
  });
  expect(apu).toEqual({
    insumo_codigo: "9001", rendimiento: 3, insumo_nombre: "SUB APU DEMO",
    unidad: "M3", tipo: "apu", ref_shift: "DIURNO",
  });
  const ins = componenteDeFila({
    uid: 2, tipo: "insumo", ref_shift: "",
    insumo_codigo: "100", insumo_nombre: "CEMENTO", unidad: "KG", rendimiento: "2",
  });
  expect(ins).toEqual({
    insumo_codigo: "100", rendimiento: 2, insumo_nombre: "CEMENTO", unidad: "KG",
  });                                   // sin tipo/ref_shift cuando es insumo
});

test("tipoRefDeLinea deduce sub-APU desde calidad_cruce o tipo", async () => {
  const { tipoRefDeLinea } = await import("./DialogoAgregarApu");
  expect(tipoRefDeLinea({ tipo: "apu", ref_shift: "NOCTURNO", calidad_cruce: "apu" }))
    .toEqual({ tipo: "apu", ref_shift: "NOCTURNO" });
  expect(tipoRefDeLinea({ tipo: "", ref_shift: "", calidad_cruce: "apu" }))
    .toEqual({ tipo: "apu", ref_shift: "" });          // respaldo por calidad_cruce
  expect(tipoRefDeLinea({ tipo: "insumo", ref_shift: "", calidad_cruce: "exacto" }))
    .toEqual({ tipo: "insumo", ref_shift: "" });
});

test("'+ Sub-APU' agrega una fila con BuscadorApu y al elegir muestra el chip APU", async () => {
  const { DialogoAgregarApu } = await import("./DialogoAgregarApu");
  render(<DialogoAgregarApu open onOpenChange={() => {}} onCreado={() => {}} />);
  fireEvent.click(screen.getByText("+ Sub-APU"));
  const input = await screen.findByPlaceholderText(/Buscar APU/i);
  fireEvent.change(input, { target: { value: "900" } });
  fireEvent.click(await screen.findByText("SUB APU DEMO"));
  await waitFor(() => expect(screen.getByText("APU")).toBeTruthy());   // chip
  expect(screen.getByText("9001")).toBeTruthy();                        // código elegido
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (desde `web/`): `npx vitest run src/components/autoria/DialogoAgregarApu.test.tsx`
Expected: FAIL — no existen `componenteDeFila`/`tipoRefDeLinea` ni el botón "+ Sub-APU".

- [ ] **Step 3: `ComponenteNuevo` gana `tipo`/`ref_shift`**

En `web/src/lib/tipos.ts` (líneas 183-188):

```ts
export interface ComponenteNuevo {
  insumo_codigo: string;
  rendimiento: number;
  insumo_nombre?: string;
  unidad?: string;
  tipo?: string;
  ref_shift?: string;
}
```

- [ ] **Step 4: `FilaComp` tipada + helpers puros + prefill (`DialogoAgregarApu.tsx`)**

En `web/src/components/autoria/DialogoAgregarApu.tsx`:

(a) Imports nuevos (arriba):

```tsx
import BuscadorApu from "@/components/corrida/BuscadorApu";
import SubApuBadge from "@/components/SubApuBadge";
import type { ComponenteNuevo, Insumo, ApuDetalle, LineaComposicion, ApuResumen } from "@/lib/tipos";
```

(b) `FilaComp` gana `tipo`/`ref_shift`; `nuevaFila` acepta el tipo:

```tsx
interface FilaComp {
  uid: number;
  tipo: "insumo" | "apu";
  ref_shift: string;
  insumo_codigo: string;
  insumo_nombre: string;
  unidad: string;
  rendimiento: string;
}

let uidSeq = 1;
function nuevaFila(tipo: "insumo" | "apu" = "insumo"): FilaComp {
  return { uid: uidSeq++, tipo, ref_shift: "", insumo_codigo: "", insumo_nombre: "",
           unidad: "", rendimiento: "" };
}
```

(c) Helpers puros EXPORTADOS (antes del componente):

```tsx
export function tipoRefDeLinea(
  linea: Pick<LineaComposicion, "tipo" | "ref_shift" | "calidad_cruce">,
): { tipo: "insumo" | "apu"; ref_shift: string } {
  const esApu = linea.tipo === "apu" || linea.calidad_cruce === "apu";
  return { tipo: esApu ? "apu" : "insumo", ref_shift: linea.ref_shift || "" };
}

export function componenteDeFila(f: FilaComp): ComponenteNuevo | null {
  if (f.insumo_codigo.trim() === "" || !rendimientoValido(f.rendimiento)) return null;
  const base: ComponenteNuevo = {
    insumo_codigo: f.insumo_codigo,
    rendimiento: Number(f.rendimiento),
    insumo_nombre: f.insumo_nombre || undefined,
    unidad: f.unidad || undefined,
  };
  return f.tipo === "apu" ? { ...base, tipo: "apu", ref_shift: f.ref_shift } : base;
}
```

(d) `compValidos` usa el helper:

```tsx
  const compValidos: ComponenteNuevo[] = filas
    .map(componenteDeFila)
    .filter((c): c is ComponenteNuevo => c !== null);
```

(e) Prefill al editar (dentro del `useEffect`, el `setFilas(...)` de `inicial.composicion`): cada línea mapea `tipo`/`ref_shift`:

```tsx
      setFilas(
        inicial.composicion.length === 0
          ? [nuevaFila()]
          : inicial.composicion.map((c) => {
              const { tipo, ref_shift } = tipoRefDeLinea(c);
              return {
                uid: uidSeq++, tipo, ref_shift,
                insumo_codigo: c.insumo_codigo, insumo_nombre: c.insumo_nombre,
                unidad: c.unidad, rendimiento: String(c.rendimiento),
              };
            }),
      );
```

- [ ] **Step 5: Dos botones + fila tipada en el JSX (`DialogoAgregarApu.tsx`)**

(a) Reemplazar el botón único "+ Agregar fila" (líneas 233-239) por dos:

```tsx
            <div className="flex gap-2">
              <Button size="xs" variant="outline"
                onClick={() => setFilas((prev) => [...prev, nuevaFila("insumo")])}>
                + Insumo
              </Button>
              <Button size="xs" variant="outline"
                onClick={() => setFilas((prev) => [...prev, nuevaFila("apu")])}>
                + Sub-APU
              </Button>
            </div>
```

(b) En la celda "Insumo" de cada fila (el `<td>` con `BuscadorInsumo`, líneas 263-275), ramificar por tipo:

```tsx
                      <td className="px-2 py-1 border-b">
                        {f.tipo === "apu" ? (
                          <SubApuFila fila={f} onElegir={(apu) =>
                            setFila(f.uid, {
                              insumo_codigo: apu.codigo, insumo_nombre: apu.nombre,
                              unidad: apu.unidad, ref_shift: apu.turno,
                            })
                          } />
                        ) : (
                          <BuscadorInsumo
                            codigo={f.insumo_codigo}
                            nombre={f.insumo_nombre}
                            onElegir={(ins) =>
                              setFila(f.uid, {
                                insumo_codigo: ins.codigo, insumo_nombre: ins.nombre,
                                unidad: ins.unidad,
                              })
                            }
                          />
                        )}
                      </td>
```

(c) Subcomponente `SubApuFila` (al final del archivo, junto a `BuscadorInsumo`): muestra el sub-APU elegido (chip + código + nombre + "cambiar"), o el `BuscadorApu` si aún no se eligió — mismo patrón que el estado "elegido" de `BuscadorInsumo`:

```tsx
// (ApuResumen ya está importado arriba, junto a los otros tipos)
function SubApuFila({ fila, onElegir }: { fila: FilaComp; onElegir: (apu: ApuResumen) => void }) {
  const [reeligiendo, setReeligiendo] = useState(false);
  if (fila.insumo_codigo && !reeligiendo) {
    return (
      <div className="flex items-center gap-1.5">
        <SubApuBadge />
        <span className="font-mono text-[11px] rounded bg-muted px-1.5 py-0.5">
          {fila.insumo_codigo}
        </span>
        <span className="truncate max-w-[14rem]" title={fila.insumo_nombre}>
          {fila.insumo_nombre}
        </span>
        <button type="button"
          className="ml-auto text-[11px] text-muted-foreground hover:text-foreground underline"
          onClick={() => setReeligiendo(true)}>
          cambiar
        </button>
      </div>
    );
  }
  return (
    <BuscadorApu
      placeholder="Buscar APU por código / nombre…"
      onElegir={(apu) => { onElegir(apu); setReeligiendo(false); }}
    />
  );
}
```

- [ ] **Step 6: Run tests + verificación completa**

Run (desde `web/`): `npx vitest run src/components/autoria/DialogoAgregarApu.test.tsx` → PASS (3 tests).
Luego: `npx vitest run` (suite web verde), `npx tsc --noEmit` (limpio), `npm run build` (OK).
Y backend intacto: `python -m pytest tests/ -q`.

- [ ] **Step 7: Commit**

```bash
git add web/src/components/autoria/DialogoAgregarApu.tsx web/src/lib/tipos.ts web/src/components/autoria/DialogoAgregarApu.test.tsx
git commit -m "feat(web): editor de APU con filas sub-APU (+ Sub-APU, chip, round-trip tipo/ref_shift)"
```

---

## Verificación final

- [ ] `python -m pytest tests/ -q`; desde `web/`: `npx tsc --noEmit`, `npx vitest run`, `npm run build` — verde/OK.
- [ ] En el editor puedo agregar una fila **sub-APU** (buscador de APU, chip "APU") y guardarla; el componente sale con `tipo='apu'` + `ref_shift`.
- [ ] Al editar un APU con sub-APUs, esas filas aparecen como sub-APU (chip) y se conservan al guardar.
- [ ] Las líneas de sub-APU muestran el badge "APU" en la corrida y en el detalle de la biblioteca.
- [ ] Sin regresión: crear/editar un APU solo con insumos funciona igual. Invariante #1 intacta. Diseño coherente con el lenguaje visual existente (badge estilo EstadoBadge, variantes de Button, tablas densas).
