# Reasignar el APU de un ítem de corrida — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir reasignar el APU de **cualquier** ítem de una corrida mediante un buscador autocompletar contra la biblioteca, reusando el endpoint `confirmar` existente.

**Architecture:** Solo-frontend. Un componente nuevo `BuscadorApu` (clon del `BuscadorInsumo`) que busca con `listarApus({q})`, y cambios acotados en `TablaItems.tsx` para (a) exponer la reasignación en todos los ítems, (b) integrar el buscador, y (c) permitir pasar el `turno` elegido a `confirmar`. No se toca el backend.

**Tech Stack:** React + TypeScript + Vite + Vitest + Testing Library.

## Global Constraints

- **Solo-frontend:** no se modifica ningún archivo de `apu_tool/` ni de `db/`. El backend ya soporta todo (endpoint `POST /api/corridas/{cid}/items/{seq}/confirmar` con `ConfirmarIn {apu_codigo, shift?}`).
- **No tocar** `web/src/api/corridas.ts`, `web/src/pages/MisCorridas.tsx`, `web/src/pages/Corrida.tsx` (trabajo reciente / no necesario). Reusar `confirmar(id, seq, apu_codigo, shift?)` de `@/api/corridas` y `listarApus({q})` de `@/api/autoria` tal cual existen.
- **Turno:** el buscador devuelve entradas `ApuResumen {codigo, turno, ...}`; al elegir, se llama `confirmar(corridaId, seq, apu.codigo, apu.turno)` (el ítem adopta ese `(codigo, turno)`). Los candidatos del matcher confirman con el turno del ítem (sin pasar `shift`), como hoy.
- **Reasignar disponible en TODOS los ítems** (no solo `review`/`new`).
- **Español** en UI/nombres. Estética densa, table-first, sin cards; reutilizar estilos existentes.
- **Invariante #1:** intacta — nada toca la IA.
- Comandos web desde `web/`. Verificación: `npx tsc --noEmit`, `npx vitest run`, `npm run build`.

---

### Task 1: Componente `BuscadorApu` + test

**Files:**
- Create: `web/src/components/corrida/BuscadorApu.tsx`
- Test: `web/src/components/corrida/BuscadorApu.test.tsx`

**Interfaces:**
- Consumes: `listarApus(params: {q?: string; limit?: number}): Promise<ListaApus>` de `@/api/autoria`; tipo `ApuResumen {codigo, turno, nombre, unidad, grupo, n_componentes}` de `@/lib/tipos`.
- Produces: `export default function BuscadorApu({ onElegir, disabled?, placeholder? })` donde `onElegir: (apu: ApuResumen) => void`.

- [ ] **Step 1: Write the failing test**

Crear `web/src/components/corrida/BuscadorApu.test.tsx`:

```tsx
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { expect, test, vi } from "vitest";

vi.mock("@/api/autoria", () => ({
  listarApus: vi.fn(async () => ({
    items: [
      { codigo: "33333", turno: "DIURNO", nombre: "EXCAVACION MANUAL",
        unidad: "M3", grupo: "MOV", n_componentes: 3 },
    ],
    total: 1, limit: 15, offset: 0,
  })),
}));

test("busca por texto y entrega el APU elegido", async () => {
  const { default: BuscadorApu } = await import("./BuscadorApu");
  const { listarApus } = await import("@/api/autoria");
  const onElegir = vi.fn();
  render(<BuscadorApu onElegir={onElegir} />);

  fireEvent.change(screen.getByPlaceholderText(/Buscar APU/i), {
    target: { value: "333" },
  });

  await waitFor(() =>
    expect(listarApus).toHaveBeenCalledWith({ q: "333", limit: 15 }),
  );
  fireEvent.click(await screen.findByText("EXCAVACION MANUAL"));
  expect(onElegir).toHaveBeenCalledWith(
    expect.objectContaining({ codigo: "33333", turno: "DIURNO" }),
  );
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (desde `web/`): `npx vitest run src/components/corrida/BuscadorApu.test.tsx`
Expected: FAIL (no existe `./BuscadorApu`).

- [ ] **Step 3: Create the component**

Crear `web/src/components/corrida/BuscadorApu.tsx`:

```tsx
import { useEffect, useRef, useState } from "react";
import { listarApus } from "@/api/autoria";
import type { ApuResumen } from "@/lib/tipos";

const inputCls =
  "h-8 w-full rounded border border-border bg-transparent px-2 py-1 text-xs outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40";

interface BuscadorApuProps {
  onElegir: (apu: ApuResumen) => void;
  disabled?: boolean;
  placeholder?: string;
}

export default function BuscadorApu({
  onElegir,
  disabled = false,
  placeholder = "Buscar APU por código / nombre…",
}: BuscadorApuProps) {
  const [q, setQ] = useState("");
  const [resultados, setResultados] = useState<ApuResumen[]>([]);
  const [abierto, setAbierto] = useState(false);
  const [buscando, setBuscando] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  // Cerrar al hacer clic fuera
  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) {
        setAbierto(false);
      }
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  // Debounce de la búsqueda
  useEffect(() => {
    if (q.trim() === "") {
      setResultados([]);
      return;
    }
    let cancelado = false;
    setBuscando(true);
    const t = setTimeout(async () => {
      try {
        const res = await listarApus({ q: q.trim(), limit: 15 });
        if (!cancelado) {
          setResultados(res.items);
          setAbierto(true);
        }
      } catch {
        if (!cancelado) setResultados([]);
      } finally {
        if (!cancelado) setBuscando(false);
      }
    }, 250);
    return () => {
      cancelado = true;
      clearTimeout(t);
    };
  }, [q]);

  function elegir(apu: ApuResumen) {
    onElegir(apu);
    setQ("");
    setResultados([]);
    setAbierto(false);
  }

  return (
    <div ref={boxRef} className="relative">
      <input
        className={inputCls}
        placeholder={placeholder}
        value={q}
        disabled={disabled}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => {
          if (resultados.length > 0) setAbierto(true);
        }}
      />
      {abierto && (
        <div className="absolute z-20 mt-1 w-full max-h-52 overflow-auto rounded border bg-popover shadow-md">
          {buscando && (
            <p className="px-2 py-1.5 text-[11px] text-muted-foreground">buscando…</p>
          )}
          {!buscando && resultados.length === 0 && q.trim() !== "" && (
            <p className="px-2 py-1.5 text-[11px] text-muted-foreground">Sin resultados</p>
          )}
          {resultados.map((apu) => (
            <button
              key={`${apu.codigo}@@${apu.turno}`}
              type="button"
              onClick={() => elegir(apu)}
              className="flex w-full items-baseline gap-2 px-2 py-1 text-left text-xs hover:bg-muted"
            >
              <span className="font-mono text-[11px] text-muted-foreground">{apu.codigo}</span>
              <span className="rounded bg-muted px-1 text-[10px] text-muted-foreground">
                {apu.turno}
              </span>
              <span className="truncate">{apu.nombre}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run (desde `web/`): `npx vitest run src/components/corrida/BuscadorApu.test.tsx`
Expected: PASS.

- [ ] **Step 5: Typecheck**

Run (desde `web/`): `npx tsc --noEmit`
Expected: sin errores.

- [ ] **Step 6: Commit**

```bash
git add web/src/components/corrida/BuscadorApu.tsx web/src/components/corrida/BuscadorApu.test.tsx
git commit -m "feat(web): BuscadorApu — combobox autocompletar de APU contra la biblioteca"
```

---

### Task 2: Integrar reasignación en `TablaItems.tsx` + test

**Files:**
- Modify: `web/src/components/corrida/TablaItems.tsx`
- Test: `web/src/components/corrida/TablaItems.test.tsx`

**Interfaces:**
- Consumes: `BuscadorApu` (Task 1); `confirmar(id, seq, apu_codigo, shift?): Promise<CorridaDetalle>` de `@/api/corridas`; tipos `ItemCuadro`, `DetalleItem` de `@/lib/tipos`.
- Produces: cambios de UI internos a `TablaItems` (no expone nada nuevo a otros módulos).

Contexto del archivo actual (referencia — NO reescribir el archivo entero, aplicar los cambios puntuales):
- `handleConfirmar(seq: number, apuCodigo: string)` llama `await confirmar(corridaId, seq, apuCodigo)`.
- `DetalleExpandido` recibe `onConfirmar: (seq: number, apuCodigo: string) => void` y define `const esRevisable = REVISABLE.has(detalle.status)`.
- La tabla de candidatos está bajo `{esRevisable && detalle.candidatos.length > 0 && (...)}`.
- El botón "Confirmar APU actual" está bajo `{esRevisable && (...)}`.
- El botón "Elegir" de cada candidato llama `onConfirmar(seq, c.apu_codigo)`.

- [ ] **Step 1: Write the failing test**

Crear `web/src/components/corrida/TablaItems.test.tsx`:

```tsx
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { expect, test, vi } from "vitest";

vi.mock("@/api/corridas", () => ({
  getItem: vi.fn(async () => ({
    seq: 0, descripcion: "Concreto", apu_codigo: "111", apu_nombre: "APU VIEJO",
    status: "matched", explicacion: "", candidatos: [], composicion: [], costo_unitario: 0,
  })),
  confirmar: vi.fn(async () => ({
    id: 1, archivo: "x", estado: "en_revision", items: [], duracion_ms: null,
    totales: { contractual: 0, costo: 0, margen: 0, margen_pct: 0, n_items: 0, n_revision: 0 },
  })),
}));
vi.mock("@/api/autoria", () => ({
  listarApus: vi.fn(async () => ({
    items: [{ codigo: "33333", turno: "DIURNO", nombre: "APU NUEVO",
              unidad: "M3", grupo: "G", n_componentes: 2 }],
    total: 1, limit: 15, offset: 0,
  })),
}));

const ITEM = {
  seq: 0, item: "1", descripcion: "Concreto", unidad: "M3", cantidad: 10,
  apu_codigo: "111", apu_nombre: "APU VIEJO", status: "matched", confianza: 1,
  precio_contractual: 0, costo_unitario: 0, margen_unitario: 0, margen_pct: 0,
  contractual_total: 0, costo_total: 0, margen_total: 0,
};

test("reasigna un ítem matched vía el buscador (pasa el turno elegido)", async () => {
  const { default: TablaItems } = await import("./TablaItems");
  const { confirmar } = await import("@/api/corridas");
  render(<TablaItems corridaId={1} items={[ITEM]} onConfirmado={() => {}} />);

  // Expandir la fila (lazy-fetch del detalle)
  fireEvent.click(screen.getByLabelText("Expandir fila"));

  // El buscador "Cambiar APU" aparece aunque el ítem sea matched
  const input = await screen.findByPlaceholderText(/Buscar APU/i);
  fireEvent.change(input, { target: { value: "333" } });
  fireEvent.click(await screen.findByText("APU NUEVO"));

  await waitFor(() =>
    expect(confirmar).toHaveBeenCalledWith(1, 0, "33333", "DIURNO"),
  );
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (desde `web/`): `npx vitest run src/components/corrida/TablaItems.test.tsx`
Expected: FAIL (hoy el bloque de reasignación no se muestra en ítems `matched`; no hay input "Buscar APU").

- [ ] **Step 3: Import `BuscadorApu` in `TablaItems.tsx`**

Añadir el import junto a los demás imports de la parte superior del archivo:

```tsx
import BuscadorApu from "@/components/corrida/BuscadorApu";
```

- [ ] **Step 4: Extend `handleConfirmar` to accept an optional `shift`**

Reemplazar la firma y la llamada a `confirmar` dentro de `handleConfirmar`:

```tsx
  async function handleConfirmar(seq: number, apuCodigo: string, shift?: string) {
    setConfirmando(apuCodigo + "@" + seq);
    setErrorConfirm((prev) => ({ ...prev, [seq]: "" }));
    try {
      const corridaActualizada = await confirmar(corridaId, seq, apuCodigo, shift);
      setExpandido((prev) => ({ ...prev, [seq]: undefined }));
      onConfirmado(corridaActualizada);
    } catch (err) {
      setErrorConfirm((prev) => ({
        ...prev,
        [seq]: err instanceof Error ? err.message : "Error al confirmar",
      }));
    } finally {
      setConfirmando(null);
    }
  }
```

- [ ] **Step 5: Update the `DetalleExpandido` prop type**

En `interface DetalleExpandidoProps`, cambiar la firma de `onConfirmar`:

```tsx
  onConfirmar: (seq: number, apuCodigo: string, shift?: string) => void;
```

- [ ] **Step 6: Show candidates whenever they exist (not only when revisable)**

En `DetalleExpandido`, cambiar la condición de la tabla de candidatos de:

```tsx
      {esRevisable && detalle.candidatos.length > 0 && (
```

a:

```tsx
      {detalle.candidatos.length > 0 && (
```

- [ ] **Step 7: Add the "Cambiar APU" search block for ALL items**

En `DetalleExpandido`, insertar este bloque **inmediatamente después** del cierre de la sección de candidatos (la `</section>` que cierra la tabla de "Candidatos") y **antes** de la sección de "Composición costeada":

```tsx
      {/* Reasignar a cualquier APU de la biblioteca (todos los ítems) */}
      <section>
        <h4 className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground mb-1">
          Cambiar APU
        </h4>
        <BuscadorApu
          disabled={confirmando !== null}
          onElegir={(apu) => onConfirmar(seq, apu.codigo, apu.turno)}
        />
      </section>
```

- [ ] **Step 8: Run test to verify it passes**

Run (desde `web/`): `npx vitest run src/components/corrida/TablaItems.test.tsx`
Expected: PASS.

- [ ] **Step 9: Full frontend verification (no regressions)**

Run (desde `web/`):
- `npx vitest run` → todo verde (incluye el test de Task 1 y los preexistentes).
- `npx tsc --noEmit` → sin errores.
- `npm run build` → OK.

- [ ] **Step 10: Commit**

```bash
git add web/src/components/corrida/TablaItems.tsx web/src/components/corrida/TablaItems.test.tsx
git commit -m "feat(web): reasignar APU de cualquier ítem de corrida con buscador de biblioteca"
```

---

## Verificación final

- [ ] Desde `web/`: `npx tsc --noEmit`, `npx vitest run`, `npm run build` — todo verde/OK.
- [ ] **Backend intacto:** no se modificó nada de `apu_tool/`; opcionalmente `python -m pytest tests/ -q` sigue verde (no debería cambiar).
- [ ] Smoke manual (opcional, coordinar server como en el feature anterior): expandir un ítem `matched`, escribir un código en "Cambiar APU", elegir → el ítem se reasigna y recostea.
- [ ] Invariante #1 intacta (sin cambios que toquen la IA).
