# Filtros por columna + ordenamiento en la tabla de la corrida — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ordenar (asc/desc) y filtrar por columna (estilo Excel) la tabla de ítems de una corrida, con los totales recalculando sobre lo filtrado.

**Architecture:** 100% frontend. Un módulo puro `corridaTabla.ts` (funciones sin DOM + un hook) concentra la lógica de filtrado/orden; `TablaItems.tsx` recibe un `control` opcional y, cuando está presente, pinta encabezados ordenables + una fila de filtros; `Corrida.tsx` llama al hook, recalcula los totales sobre las filas filtradas y pasa el control. El modo vivo (streaming) no usa control y se comporta igual que hoy.

**Tech Stack:** React + TypeScript + Vite + Vitest + Testing Library.

## Global Constraints

- **Solo-frontend.** Modificar únicamente bajo `web/src/`. No tocar `apu_tool/`, `report.py`, ni ningún endpoint/backend. Su suite (pytest) no se corre ni cambia.
- **Sin datos nuevos:** todo sale de `CorridaDetalle.items` (`ItemCuadro[]`), ya presente.
- **Invariante #1 intacta:** nada toca la IA.
- **Sin regresiones:** el modo vivo (armado por streaming) y el toggle "Solo revisión" se conservan; cuando `TablaItems` no recibe `control`, se comporta exactamente como hoy.
- Español en dominio/UI; estética densa; reutilizar `cop`/`pct` de `@/lib/moneda` y los componentes `@/components/ui/table` + `@/components/ui/button`. Desplegables con `<select>` nativo (sin dependencias nuevas).
- Texto "contiene": insensible a mayúsculas y tildes. Rango mín–máx inclusivo. `%` en puntos (`12` = 12% ⇒ `margen_pct >= 0.12`). Filtros combinados con **Y**.
- Verificación (desde `web/`): `npx tsc --noEmit`, `npx vitest run`, `npm run build`.

---

### Task 1: Módulo puro `corridaTabla.ts` (lógica + hook) + tests unitarios

**Files:**
- Create: `web/src/lib/corridaTabla.ts`
- Test: `web/src/lib/corridaTabla.test.ts`

**Interfaces:**
- Consumes: `ItemCuadro` de `@/lib/tipos`.
- Produces (exportado):
  - Tipos `ClaveColumna`, `DireccionOrden`, `EstadoOrden`, `FiltroRango`, `FiltrosColumna`, `ControlCorridaTabla`.
  - `FILTROS_VACIOS: FiltrosColumna`.
  - `normalizar(s: string): string`
  - `filtrar(items: ItemCuadro[], f: FiltrosColumna, soloRevision: boolean): ItemCuadro[]`
  - `ordenar(items: ItemCuadro[], orden: EstadoOrden): ItemCuadro[]`
  - `opcionesDe(items: ItemCuadro[], clave: "unidad" | "status"): string[]`
  - `siguienteOrden(prev: EstadoOrden, clave: ClaveColumna): EstadoOrden`
  - `hayFiltrosActivos(f: FiltrosColumna, orden: EstadoOrden, soloRevision: boolean): boolean`
  - `useCorridaTabla(items: ItemCuadro[]): ControlCorridaTabla`

- [ ] **Step 1: Write the failing test**

Crear `web/src/lib/corridaTabla.test.ts`:

```ts
import { describe, expect, test } from "vitest";
import {
  filtrar, ordenar, opcionesDe, siguienteOrden, hayFiltrosActivos,
  normalizar, FILTROS_VACIOS,
} from "./corridaTabla";
import type { ItemCuadro } from "./tipos";

function item(p: Partial<ItemCuadro>): ItemCuadro {
  return {
    seq: 0, item: "1", descripcion: "X", unidad: "M3", cantidad: 1,
    apu_codigo: "A", apu_nombre: "APU A", status: "auto", confianza: 1,
    precio_contractual: 0, costo_unitario: 0, margen_unitario: 0, margen_pct: 0,
    contractual_total: 0, costo_total: 0, margen_total: 0, ...p,
  };
}

test("normalizar quita tildes y baja a minúsculas", () => {
  expect(normalizar("Excavación")).toBe("excavacion");
});

test("filtrar: texto 'contiene' insensible a tildes/mayúsculas", () => {
  const items = [item({ descripcion: "Excavación manual" }), item({ descripcion: "Concreto" })];
  const f = { ...FILTROS_VACIOS, descripcion: "excavacion" };
  expect(filtrar(items, f, false).map((i) => i.descripcion)).toEqual(["Excavación manual"]);
});

test("filtrar: desplegable de unidad es coincidencia exacta", () => {
  const items = [item({ unidad: "M3" }), item({ unidad: "M2" })];
  expect(filtrar(items, { ...FILTROS_VACIOS, unidad: "M2" }, false)).toHaveLength(1);
});

test("filtrar: rango numérico inclusivo, extremos vacíos = sin límite", () => {
  const items = [item({ contractual_total: 100 }), item({ contractual_total: 200 }), item({ contractual_total: 300 })];
  const f = { ...FILTROS_VACIOS, contractual_total: { min: "200", max: "300" } };
  expect(filtrar(items, f, false).map((i) => i.contractual_total)).toEqual([200, 300]);
  const soloMax = { ...FILTROS_VACIOS, contractual_total: { min: "", max: "150" } };
  expect(filtrar(items, soloMax, false).map((i) => i.contractual_total)).toEqual([100]);
});

test("filtrar: % se interpreta en puntos (12 => 0.12)", () => {
  const items = [item({ margen_pct: 0.05 }), item({ margen_pct: 0.12 }), item({ margen_pct: 0.20 })];
  const f = { ...FILTROS_VACIOS, margen_pct: { min: "12", max: "" } };
  expect(filtrar(items, f, false).map((i) => i.margen_pct)).toEqual([0.12, 0.20]);
});

test("filtrar: soloRevision deja solo review/new", () => {
  const items = [item({ status: "auto" }), item({ status: "review" }), item({ status: "new" })];
  expect(filtrar(items, FILTROS_VACIOS, true).map((i) => i.status)).toEqual(["review", "new"]);
});

test("filtrar: combina filtros con Y", () => {
  const items = [
    item({ unidad: "M3", margen_total: -5 }),
    item({ unidad: "M3", margen_total: 10 }),
    item({ unidad: "M2", margen_total: -5 }),
  ];
  const f = { ...FILTROS_VACIOS, unidad: "M3", margen_total: { min: "", max: "0" } };
  expect(filtrar(items, f, false)).toHaveLength(1);
});

test("ordenar: numérico asc y desc", () => {
  const items = [item({ costo_total: 300 }), item({ costo_total: 100 }), item({ costo_total: 200 })];
  expect(ordenar(items, { clave: "costo_total", dir: "asc" }).map((i) => i.costo_total)).toEqual([100, 200, 300]);
  expect(ordenar(items, { clave: "costo_total", dir: "desc" }).map((i) => i.costo_total)).toEqual([300, 200, 100]);
});

test("ordenar: texto con orden natural (1.2 antes de 1.10)", () => {
  const items = [item({ item: "1.10" }), item({ item: "1.2" }), item({ item: "1.1" })];
  expect(ordenar(items, { clave: "item", dir: "asc" }).map((i) => i.item)).toEqual(["1.1", "1.2", "1.10"]);
});

test("ordenar: null conserva el orden original", () => {
  const items = [item({ costo_total: 3 }), item({ costo_total: 1 })];
  expect(ordenar(items, null).map((i) => i.costo_total)).toEqual([3, 1]);
});

test("opcionesDe: distintos y ordenados", () => {
  const items = [item({ unidad: "M3" }), item({ unidad: "M2" }), item({ unidad: "M3" })];
  expect(opcionesDe(items, "unidad")).toEqual(["M2", "M3"]);
});

test("siguienteOrden: ciclo asc -> desc -> null -> asc", () => {
  expect(siguienteOrden(null, "costo_total")).toEqual({ clave: "costo_total", dir: "asc" });
  expect(siguienteOrden({ clave: "costo_total", dir: "asc" }, "costo_total")).toEqual({ clave: "costo_total", dir: "desc" });
  expect(siguienteOrden({ clave: "costo_total", dir: "desc" }, "costo_total")).toBeNull();
  expect(siguienteOrden({ clave: "costo_total", dir: "asc" }, "margen_total")).toEqual({ clave: "margen_total", dir: "asc" });
});

test("hayFiltrosActivos: falso en vacío, verdadero con algún filtro", () => {
  expect(hayFiltrosActivos(FILTROS_VACIOS, null, false)).toBe(false);
  expect(hayFiltrosActivos({ ...FILTROS_VACIOS, item: "1" }, null, false)).toBe(true);
  expect(hayFiltrosActivos(FILTROS_VACIOS, { clave: "item", dir: "asc" }, false)).toBe(true);
  expect(hayFiltrosActivos(FILTROS_VACIOS, null, true)).toBe(true);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (desde `web/`): `npx vitest run src/lib/corridaTabla.test.ts`
Expected: FAIL — no existe `./corridaTabla` (módulo sin resolver).

- [ ] **Step 3: Write minimal implementation**

Crear `web/src/lib/corridaTabla.ts`:

```ts
import { useMemo, useState } from "react";
import type { ItemCuadro } from "@/lib/tipos";

export type ClaveColumna =
  | "descripcion" | "unidad" | "cantidad" | "item" | "apu" | "status"
  | "contractual_total" | "costo_total" | "margen_total" | "margen_pct";

export type DireccionOrden = "asc" | "desc";
export type EstadoOrden = { clave: ClaveColumna; dir: DireccionOrden } | null;

export type FiltroRango = { min: string; max: string };

export interface FiltrosColumna {
  descripcion: string;
  unidad: string;
  cantidad: FiltroRango;
  item: string;
  apu: string;
  status: string;
  contractual_total: FiltroRango;
  costo_total: FiltroRango;
  margen_total: FiltroRango;
  margen_pct: FiltroRango;
}

export const FILTROS_VACIOS: FiltrosColumna = {
  descripcion: "", unidad: "", cantidad: { min: "", max: "" }, item: "",
  apu: "", status: "", contractual_total: { min: "", max: "" },
  costo_total: { min: "", max: "" }, margen_total: { min: "", max: "" },
  margen_pct: { min: "", max: "" },
};

const REVISABLE = new Set(["review", "new", "REVIEW", "NEW"]);
const CLAVES_TEXTO: ClaveColumna[] = ["descripcion", "unidad", "item", "apu", "status"];

export function normalizar(s: string): string {
  return (s ?? "").normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase().trim();
}

function contiene(valor: string, q: string): boolean {
  if (!q.trim()) return true;
  return normalizar(valor).includes(normalizar(q));
}

function enRango(valor: number, r: FiltroRango, escala = 1): boolean {
  const min = r.min.trim() === "" ? null : Number(r.min) * escala;
  const max = r.max.trim() === "" ? null : Number(r.max) * escala;
  if (min !== null && !Number.isNaN(min) && valor < min) return false;
  if (max !== null && !Number.isNaN(max) && valor > max) return false;
  return true;
}

export function filtrar(items: ItemCuadro[], f: FiltrosColumna, soloRevision: boolean): ItemCuadro[] {
  return items.filter((it) => {
    if (soloRevision && !REVISABLE.has(it.status)) return false;
    if (!contiene(it.descripcion, f.descripcion)) return false;
    if (f.unidad && it.unidad !== f.unidad) return false;
    if (!enRango(it.cantidad, f.cantidad)) return false;
    if (!contiene(it.item, f.item)) return false;
    if (!contiene(`${it.apu_codigo} ${it.apu_nombre}`, f.apu)) return false;
    if (f.status && it.status !== f.status) return false;
    if (!enRango(it.contractual_total, f.contractual_total)) return false;
    if (!enRango(it.costo_total, f.costo_total)) return false;
    if (!enRango(it.margen_total, f.margen_total)) return false;
    if (!enRango(it.margen_pct, f.margen_pct, 0.01)) return false;
    return true;
  });
}

function valorTexto(it: ItemCuadro, clave: ClaveColumna): string {
  switch (clave) {
    case "descripcion": return it.descripcion;
    case "unidad": return it.unidad;
    case "item": return it.item;
    case "apu": return it.apu_codigo;
    case "status": return it.status;
    default: return "";
  }
}

function valorNumero(it: ItemCuadro, clave: ClaveColumna): number {
  switch (clave) {
    case "cantidad": return it.cantidad;
    case "contractual_total": return it.contractual_total;
    case "costo_total": return it.costo_total;
    case "margen_total": return it.margen_total;
    case "margen_pct": return it.margen_pct;
    default: return 0;
  }
}

export function ordenar(items: ItemCuadro[], orden: EstadoOrden): ItemCuadro[] {
  if (!orden) return items;
  const { clave, dir } = orden;
  const factor = dir === "asc" ? 1 : -1;
  const esTexto = CLAVES_TEXTO.includes(clave);
  return [...items].sort((a, b) => {
    const cmp = esTexto
      ? valorTexto(a, clave).localeCompare(valorTexto(b, clave), "es", { numeric: true })
      : valorNumero(a, clave) - valorNumero(b, clave);
    return cmp * factor;
  });
}

export function opcionesDe(items: ItemCuadro[], clave: "unidad" | "status"): string[] {
  const set = new Set<string>();
  for (const it of items) {
    const v = clave === "unidad" ? it.unidad : it.status;
    if (v) set.add(v);
  }
  return [...set].sort((a, b) => a.localeCompare(b, "es", { numeric: true }));
}

export function siguienteOrden(prev: EstadoOrden, clave: ClaveColumna): EstadoOrden {
  if (!prev || prev.clave !== clave) return { clave, dir: "asc" };
  if (prev.dir === "asc") return { clave, dir: "desc" };
  return null;
}

export function hayFiltrosActivos(f: FiltrosColumna, orden: EstadoOrden, soloRevision: boolean): boolean {
  if (orden || soloRevision) return true;
  return JSON.stringify(f) !== JSON.stringify(FILTROS_VACIOS);
}

export interface ControlCorridaTabla {
  filtradas: ItemCuadro[];
  totalItems: number;
  orden: EstadoOrden;
  alternarOrden: (clave: ClaveColumna) => void;
  filtros: FiltrosColumna;
  setFiltro: (clave: ClaveColumna, valor: string | FiltroRango) => void;
  soloRevision: boolean;
  setSoloRevision: (v: boolean) => void;
  limpiar: () => void;
  hayFiltros: boolean;
  opcionesUnidad: string[];
  opcionesStatus: string[];
}

export function useCorridaTabla(items: ItemCuadro[]): ControlCorridaTabla {
  const [orden, setOrden] = useState<EstadoOrden>(null);
  const [filtros, setFiltros] = useState<FiltrosColumna>(FILTROS_VACIOS);
  const [soloRevision, setSoloRevision] = useState(false);

  const filtradas = useMemo(
    () => ordenar(filtrar(items, filtros, soloRevision), orden),
    [items, filtros, soloRevision, orden],
  );
  const opcionesUnidad = useMemo(() => opcionesDe(items, "unidad"), [items]);
  const opcionesStatus = useMemo(() => opcionesDe(items, "status"), [items]);
  const hayFiltros = hayFiltrosActivos(filtros, orden, soloRevision);

  return {
    filtradas,
    totalItems: items.length,
    orden,
    alternarOrden: (clave) => setOrden((prev) => siguienteOrden(prev, clave)),
    filtros,
    setFiltro: (clave, valor) => setFiltros((prev) => ({ ...prev, [clave]: valor })),
    soloRevision,
    setSoloRevision,
    limpiar: () => { setFiltros(FILTROS_VACIOS); setOrden(null); setSoloRevision(false); },
    hayFiltros,
    opcionesUnidad,
    opcionesStatus,
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run (desde `web/`): `npx vitest run src/lib/corridaTabla.test.ts`
Expected: PASS (13 tests). Luego `npx tsc --noEmit` limpio.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/corridaTabla.ts web/src/lib/corridaTabla.test.ts
git commit -m "feat(web): lógica pura de filtro/orden de la corrida (corridaTabla) + hook"
```

---

### Task 2: Cabecera con filtros/orden + integrar en `TablaItems`

**Files:**
- Create: `web/src/components/corrida/CabeceraFiltros.tsx`
- Modify: `web/src/components/corrida/TablaItems.tsx` (props, toolbar y elección de cabecera; el `<TableBody>` no cambia)
- Test: `web/src/components/corrida/TablaItems.test.tsx` (agregar casos)

**Interfaces:**
- Consumes: `ControlCorridaTabla`, `FiltroRango`, `ClaveColumna` de `@/lib/corridaTabla`; `useCorridaTabla` (en el test).
- Produces: `TablaItems` acepta prop opcional `control?: ControlCorridaTabla`. Sin `control` = comportamiento actual.

- [ ] **Step 1: Write the failing test**

Agregar al final de `web/src/components/corrida/TablaItems.test.tsx` (reusa el `ITEM` y los mocks ya definidos arriba en ese archivo):

```tsx
import { useCorridaTabla } from "@/lib/corridaTabla";

function TablaConControl({ items }: { items: typeof ITEM[] }) {
  const control = useCorridaTabla(items);
  return (
    <TablaItems corridaId={1} items={control.filtradas} control={control} onConfirmado={() => {}} />
  );
}

test("filtra por Descripción (contiene) ocultando las filas que no coinciden", async () => {
  await import("./TablaItems");
  const items = [
    { ...ITEM, seq: 0, descripcion: "Excavación manual" },
    { ...ITEM, seq: 1, descripcion: "Concreto clase D" },
  ];
  render(<TablaConControl items={items} />);
  expect(screen.getByText("Excavación manual")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Filtrar Descripción"), { target: { value: "concreto" } });
  expect(screen.queryByText("Excavación manual")).toBeNull();
  expect(screen.getByText("Concreto clase D")).toBeTruthy();
});

test("filtra por el desplegable de Und", async () => {
  await import("./TablaItems");
  const items = [
    { ...ITEM, seq: 0, descripcion: "A", unidad: "M3" },
    { ...ITEM, seq: 1, descripcion: "B", unidad: "M2" },
  ];
  render(<TablaConControl items={items} />);
  fireEvent.change(screen.getByLabelText("Filtrar Und"), { target: { value: "M2" } });
  expect(screen.queryByText("A")).toBeNull();
  expect(screen.getByText("B")).toBeTruthy();
});

test("ordena por Costo al hacer clic en el encabezado", async () => {
  await import("./TablaItems");
  const items = [
    { ...ITEM, seq: 0, descripcion: "Alfa", costo_total: 300 },
    { ...ITEM, seq: 1, descripcion: "Beta", costo_total: 100 },
  ];
  render(<TablaConControl items={items} />);
  fireEvent.click(screen.getByLabelText("Ordenar por Costo"));
  const alfa = screen.getByText("Alfa");
  const beta = screen.getByText("Beta");
  // asc: Beta (100) antes que Alfa (300)
  expect(beta.compareDocumentPosition(alfa) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

test("'Limpiar filtros' restablece la vista", async () => {
  await import("./TablaItems");
  const items = [
    { ...ITEM, seq: 0, descripcion: "Excavación manual" },
    { ...ITEM, seq: 1, descripcion: "Concreto clase D" },
  ];
  render(<TablaConControl items={items} />);
  fireEvent.change(screen.getByLabelText("Filtrar Descripción"), { target: { value: "concreto" } });
  expect(screen.queryByText("Excavación manual")).toBeNull();
  fireEvent.click(screen.getByText("Limpiar filtros"));
  expect(screen.getByText("Excavación manual")).toBeTruthy();
});

test("sin control (modo vivo) no aparece la fila de filtros", async () => {
  const { default: TablaItems } = await import("./TablaItems");
  render(<TablaItems corridaId={1} items={[ITEM]} onConfirmado={() => {}} />);
  expect(screen.queryByLabelText("Filtrar Descripción")).toBeNull();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (desde `web/`): `npx vitest run src/components/corrida/TablaItems.test.tsx`
Expected: FAIL — `TablaItems` no acepta `control` y no existe `getByLabelText("Filtrar Descripción")`.

- [ ] **Step 3: Create `CabeceraFiltros.tsx`**

Crear `web/src/components/corrida/CabeceraFiltros.tsx`:

```tsx
import { TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { ClaveColumna, ControlCorridaTabla, FiltroRango } from "@/lib/corridaTabla";

const inputCls =
  "h-6 w-full rounded border border-border bg-transparent px-1 text-[11px] outline-none focus-visible:border-ring";
const miniCls =
  "h-5 w-full rounded border border-border bg-transparent px-1 text-[10px] outline-none focus-visible:border-ring";

type Tipo = "texto" | "select" | "num";
interface Col { clave: ClaveColumna; label: string; tipo: Tipo; ancho: string; derecha?: boolean }

const COLS: Col[] = [
  { clave: "descripcion", label: "Descripción", tipo: "texto", ancho: "" },
  { clave: "unidad", label: "Und", tipo: "select", ancho: "w-12" },
  { clave: "cantidad", label: "Cantidad", tipo: "num", ancho: "w-20", derecha: true },
  { clave: "item", label: "Ítem", tipo: "texto", ancho: "w-24" },
  { clave: "apu", label: "APU", tipo: "texto", ancho: "w-28" },
  { clave: "status", label: "Estado", tipo: "select", ancho: "w-20" },
  { clave: "contractual_total", label: "Contractual", tipo: "num", ancho: "w-28", derecha: true },
  { clave: "costo_total", label: "Costo", tipo: "num", ancho: "w-28", derecha: true },
  { clave: "margen_total", label: "Margen", tipo: "num", ancho: "w-28", derecha: true },
  { clave: "margen_pct", label: "%", tipo: "num", ancho: "w-16", derecha: true },
];

function Rango({ clave, label, control }: { clave: ClaveColumna; label: string; control: ControlCorridaTabla }) {
  const r = control.filtros[clave] as FiltroRango;
  return (
    <div className="flex flex-col gap-0.5">
      <input
        className={miniCls} type="number" value={r.min} placeholder="mín"
        aria-label={`${label} mínimo`}
        onChange={(e) => control.setFiltro(clave, { ...r, min: e.target.value })}
      />
      <input
        className={miniCls} type="number" value={r.max} placeholder="máx"
        aria-label={`${label} máximo`}
        onChange={(e) => control.setFiltro(clave, { ...r, max: e.target.value })}
      />
    </div>
  );
}

export default function CabeceraFiltros({ control }: { control: ControlCorridaTabla }) {
  const flecha = (clave: ClaveColumna) =>
    control.orden?.clave === clave ? (control.orden.dir === "asc" ? "↑" : "↓") : "";

  return (
    <TableHeader>
      <TableRow>
        <TableHead className="w-6 px-1" />
        {COLS.map((c) => (
          <TableHead key={c.clave} className={`text-xs ${c.ancho} ${c.derecha ? "text-right" : ""}`}>
            <button
              type="button"
              aria-label={`Ordenar por ${c.label}`}
              onClick={() => control.alternarOrden(c.clave)}
              className="inline-flex items-center gap-1 hover:text-foreground select-none"
            >
              {c.label}
              <span className="text-[9px] w-2 text-muted-foreground">{flecha(c.clave)}</span>
            </button>
          </TableHead>
        ))}
      </TableRow>
      <TableRow className="hover:bg-transparent">
        <TableHead className="w-6 px-1" />
        {COLS.map((c) => (
          <TableHead key={c.clave} className={`${c.ancho} py-1 align-top`}>
            {c.tipo === "texto" && (
              <input
                className={inputCls} value={control.filtros[c.clave] as string}
                aria-label={`Filtrar ${c.label}`} placeholder="contiene…"
                onChange={(e) => control.setFiltro(c.clave, e.target.value)}
              />
            )}
            {c.tipo === "select" && (
              <select
                className={inputCls} value={control.filtros[c.clave] as string}
                aria-label={`Filtrar ${c.label}`}
                onChange={(e) => control.setFiltro(c.clave, e.target.value)}
              >
                <option value="">(todas)</option>
                {(c.clave === "unidad" ? control.opcionesUnidad : control.opcionesStatus).map((o) => (
                  <option key={o} value={o}>{o}</option>
                ))}
              </select>
            )}
            {c.tipo === "num" && <Rango clave={c.clave} label={c.label} control={control} />}
          </TableHead>
        ))}
      </TableRow>
    </TableHeader>
  );
}
```

- [ ] **Step 4: Wire `TablaItems.tsx`**

En `web/src/components/corrida/TablaItems.tsx`:

(a) Añadir imports (junto a los existentes):

```tsx
import CabeceraFiltros from "@/components/corrida/CabeceraFiltros";
import type { ControlCorridaTabla } from "@/lib/corridaTabla";
```

(b) Reemplazar la interfaz de props (líneas 17-22) por:

```tsx
interface TablaItemsProps {
  corridaId: number;
  items: ItemCuadro[];
  onConfirmado: (corridaActualizada: CorridaDetalle) => void;
  readOnly?: boolean;
  control?: ControlCorridaTabla;
}
```

(c) Reemplazar la firma de la función y el estado `soloRevision` + los cálculos `nPorRevisar`/`visible` (líneas 28-43) por:

```tsx
export default function TablaItems({
  corridaId,
  items,
  onConfirmado,
  readOnly = false,
  control,
}: TablaItemsProps) {
  // Con `control`, el padre ya entrega las filas filtradas/ordenadas y controla
  // "Solo revisión". Sin `control` (modo vivo), se mantiene el filtro local de hoy.
  const [soloRevisionLocal, setSoloRevisionLocal] = useState(false);
  const soloRevision = control ? control.soloRevision : soloRevisionLocal;
  const setSoloRevision = control ? control.setSoloRevision : setSoloRevisionLocal;
  const [expandido, setExpandido] = useState<Record<number, EstadoExpansion | undefined>>({});
  const [confirmando, setConfirmando] = useState<string | null>(null);
  const [errorConfirm, setErrorConfirm] = useState<Record<number, string>>({});

  const nPorRevisar = items.filter((it) => REVISABLE.has(it.status)).length;
  const visible = control
    ? items
    : soloRevision
      ? items.filter((it) => REVISABLE.has(it.status))
      : items;
```

(d) Reemplazar la barra de filtros (líneas 87-103, el bloque `{/* Filter bar */}`) por:

```tsx
      {/* Filter bar */}
      <div className="flex items-center gap-3 px-1">
        <label className="flex items-center gap-1.5 cursor-pointer select-none text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={soloRevision}
            onChange={(e) => setSoloRevision(e.target.checked)}
            className="cursor-pointer"
          />
          Solo revisión
        </label>
        {nPorRevisar > 0 && (
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-800">
            {nPorRevisar} por revisar
          </span>
        )}
        {control?.hayFiltros && (
          <button
            type="button"
            onClick={control.limpiar}
            className="text-[11px] text-muted-foreground underline underline-offset-2 hover:text-foreground"
          >
            Limpiar filtros
          </button>
        )}
      </div>
```

(e) Reemplazar el `<TableHeader>…</TableHeader>` estático (líneas 107-121) por la cabecera condicional:

```tsx
        {control ? (
          <CabeceraFiltros control={control} />
        ) : (
          <TableHeader>
            <TableRow>
              <TableHead className="w-6 px-1" />
              <TableHead className="text-xs">Descripción</TableHead>
              <TableHead className="text-xs w-12">Und</TableHead>
              <TableHead className="text-xs w-20 text-right">Cantidad</TableHead>
              <TableHead className="text-xs w-24">Ítem</TableHead>
              <TableHead className="text-xs w-28">APU</TableHead>
              <TableHead className="text-xs w-20">Estado</TableHead>
              <TableHead className="text-xs w-28 text-right">Contractual</TableHead>
              <TableHead className="text-xs w-28 text-right">Costo</TableHead>
              <TableHead className="text-xs w-28 text-right">Margen</TableHead>
              <TableHead className="text-xs w-16 text-right">%</TableHead>
            </TableRow>
          </TableHeader>
        )}
```

El `<TableBody>` y `DetalleExpandido` NO cambian. `TOTAL_COLS` sigue siendo 11.

- [ ] **Step 5: Run tests to verify they pass**

Run (desde `web/`): `npx vitest run src/components/corrida/TablaItems.test.tsx`
Expected: PASS (los 5 casos nuevos + los existentes de reasignación/solo-lectura/columna-Ítem). Luego `npx tsc --noEmit` limpio.

- [ ] **Step 6: Commit**

```bash
git add web/src/components/corrida/CabeceraFiltros.tsx web/src/components/corrida/TablaItems.tsx web/src/components/corrida/TablaItems.test.tsx
git commit -m "feat(web): cabecera ordenable + fila de filtros por columna en TablaItems (control opcional)"
```

---

### Task 3: Cablear `Corrida.tsx` (totales sobre lo filtrado) + test de integración

**Files:**
- Modify: `web/src/pages/Corrida.tsx`
- Test: `web/src/pages/Corrida.test.tsx` (nuevo)

**Interfaces:**
- Consumes: `useCorridaTabla` de `@/lib/corridaTabla`; `TablaItems` con prop `control`.
- Produces: nada nuevo hacia otros módulos.

- [ ] **Step 1: Write the failing test**

Crear `web/src/pages/Corrida.test.tsx`:

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { expect, test, vi } from "vitest";

vi.mock("react-router-dom", () => ({ useParams: () => ({ id: "1" }) }));
vi.mock("@/lib/armado", () => ({
  useArmadoVivo: () => ({ corridaId: null, estado: "idle", filas: [], total: 0 }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function fila(p: Record<string, unknown>) {
  return {
    seq: 0, item: "1", descripcion: "X", unidad: "M3", cantidad: 1,
    apu_codigo: "A", apu_nombre: "APU A", status: "auto", confianza: 1,
    precio_contractual: 0, costo_unitario: 0, margen_unitario: 0, margen_pct: 0,
    contractual_total: 0, costo_total: 0, margen_total: 0, ...p,
  };
}

const CORRIDA = {
  id: 1, archivo: "obra.xlsx", estado: "en_revision", modo: "activa", duracion_ms: 1000,
  items: [
    fila({ seq: 0, descripcion: "Excavación", unidad: "M3", contractual_total: 1000 }),
    fila({ seq: 1, descripcion: "Concreto", unidad: "M2", contractual_total: 500 }),
  ],
  totales: { contractual: 1500, costo: 0, margen: 1500, margen_pct: 1, n_items: 2, n_revision: 0 },
};

vi.mock("@/api/corridas", () => ({
  getCorrida: vi.fn(async () => CORRIDA),
  descargarCuadro: vi.fn(),
  congelarCorrida: vi.fn(),
  activarCorrida: vi.fn(),
}));

test("al filtrar por Und, los totales y el contador recalculan sobre lo filtrado", async () => {
  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);

  // Carga async de la corrida (aparecen las dos filas)
  await screen.findByText("Excavación");
  expect(screen.getByText("Concreto")).toBeTruthy();

  // Filtra a M2 -> queda 1 de 2 ítems
  fireEvent.change(screen.getByLabelText("Filtrar Und"), { target: { value: "M2" } });
  expect(screen.queryByText("Excavación")).toBeNull();
  expect(screen.getByText(/1 de 2 ítems/)).toBeTruthy();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (desde `web/`): `npx vitest run src/pages/Corrida.test.tsx`
Expected: FAIL — no existe el filtro `Filtrar Und` ni el texto `1 de 2 ítems` (Corrida aún no cablea el control).

- [ ] **Step 3: Wire `Corrida.tsx`**

En `web/src/pages/Corrida.tsx`:

(a) Añadir import:

```tsx
import { useCorridaTabla } from "@/lib/corridaTabla";
```

(b) Llamar el hook junto a los demás hooks, ANTES de cualquier `return` temprano (tras la línea `const [error, setError] = useState<string | null>(null);`, ~línea 36):

```tsx
  const control = useCorridaTabla(corrida?.items ?? []);
```

(c) Tras `if (!data) return null;` (línea 111), reemplazar `const { totales } = data;` por el cálculo según modo:

```tsx
  const enVivo = live;
  const filas = enVivo ? data.items : control.filtradas;
  const totales = enVivo ? data.totales : totalesDe(filas);
  const margenNegativo = totales.margen < 0;
```

(d) En la sub-línea de contadores (bloque `{/* Counters sub-line */}`, ~líneas 166-182), añadir el indicador "N de M ítems" cuando hay filtros. Reemplazar el bloque del contador no-vivo por:

```tsx
        {live ? (
          <span className="text-blue-700 font-medium">
            Armando {vivo.filas.length}/{vivo.total}…
          </span>
        ) : control.hayFiltros ? (
          <span>{filas.length} de {control.totalItems} ítems</span>
        ) : (
          <span>
            {totales.n_items} APUs · armada en {fmtDuracion(data.duracion_ms)}
          </span>
        )}
```

(e) Pasar filas y control a `TablaItems` (el bloque final `<TablaItems … />`):

```tsx
      <TablaItems
        corridaId={corridaId}
        items={filas}
        onConfirmado={(c) => setCorrida(c)}
        readOnly={data.modo === "congelada"}
        control={enVivo ? undefined : control}
      />
```

- [ ] **Step 4: Run test + full verification**

Run (desde `web/`): `npx vitest run src/pages/Corrida.test.tsx` → PASS.
Luego la suite completa y los gates:
- `npx vitest run` (todo verde),
- `npx tsc --noEmit` (limpio),
- `npm run build` (OK).

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/Corrida.tsx web/src/pages/Corrida.test.tsx
git commit -m "feat(web): filtros/orden en la corrida — totales recalculan sobre lo filtrado + contador N de M"
```

---

## Verificación final

- [ ] Desde `web/`: `npx vitest run`, `npx tsc --noEmit`, `npm run build` — verde/OK.
- [ ] En una corrida cargada: cada encabezado ordena asc/desc/—; la fila de filtros filtra por columna (texto "contiene" sin tildes, desplegable Und/Estado, rango mín–máx en numéricos), combinando con Y; "Limpiar filtros" resetea.
- [ ] La barra de totales y `n_revision` recalculan sobre lo filtrado; se muestra "N de M ítems".
- [ ] Modo vivo (armado) y "Solo revisión" siguen igual; sin `control` no aparece la fila de filtros.
- [ ] Backend intacto (no se tocó `apu_tool/`); Invariante #1 intacta.
