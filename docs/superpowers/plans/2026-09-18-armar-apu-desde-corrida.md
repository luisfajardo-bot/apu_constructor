# Armar APU desde una fila de la corrida — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un botón **Armar APU** siempre visible en el panel de una fila de corrida, con tres puntos de partida (duplicar el APU asignado, partir de otro que busques, o desde cero con los datos de la actividad), que al crear deja el APU asignado a esa fila.

**Architecture:** Un componente nuevo y chico (`DialogoArmarApu.tsx`) es dueño de elegir el punto de partida y entregarle a `DialogoAgregarApu` el par `(modo, inicial)` correcto. **`DialogoAgregarApu.tsx` no se toca**: sus modos `crear` y `duplicar` con `inicial` ya hacen exactamente lo que hace falta. El backend solo suma dos campos al detalle de la fila.

**Tech Stack:** React + TypeScript + Vite + Tailwind · FastAPI + SQLite/Postgres · vitest + pytest.

**Spec:** `docs/superpowers/specs/2026-09-18-armar-apu-desde-corrida-design.md`

**Rama:** `feat/armar-apu-desde-corrida` (ya creada, con el spec commiteado). No se pushea sin OK explícito: master auto-despliega.

---

## Estructura de archivos

| Archivo | Responsabilidad | Acción |
|---|---|---|
| `apu_tool/servicio/corridas.py` | `detalle_item` suma `codigo_sugerido` y `unidad` | Modificar |
| `web/src/lib/tipos.ts` | `DetalleItem` suma los dos campos | Modificar |
| `web/src/components/corrida/DialogoArmarApu.tsx` | elegir el punto de partida y entregar `(modo, inicial)` | **Crear** |
| `web/src/components/corrida/TablaItems.tsx` | el botón "Armar APU" reemplaza al de duplicar | Modificar |
| `CLAUDE.md` | el flujo nuevo, en la sección Datos | Modificar |

---

## Task 1: el detalle de la fila manda el código del presupuesto y la unidad

**Files:**
- Modify: `apu_tool/servicio/corridas.py` (el `return` de `detalle_item`, ~línea 833)
- Modify: `web/src/lib/tipos.ts` (`interface DetalleItem`, ~línea 280)
- Test: `tests/test_servicio_corridas.py`

- [ ] **Step 1: Escribir los tests que fallan**

Al final de `tests/test_servicio_corridas.py` (reusá el helper `_almacen_seed` que ya está
en ese archivo):

```python
def test_detalle_item_trae_el_codigo_del_presupuesto_y_la_unidad(tmp_path):
    """Los necesita "Armar APU" para precargar el alta desde la fila: el código que
    pedía el presupuesto es justo el que debería llevar el APU nuevo."""
    alm = _almacen_seed(tmp_path)
    items = [LicitacionItem(item="1", descripcion="Concreto clase D", unidad="M3",
                            cantidad=10.0, precio_contractual=400000.0, shift="DIURNO",
                            codigo_sugerido="9001")]
    cid = corridas.construir_corrida(alm, "lic.xlsx", items, "DIURNO", use_ai=False)
    det = corridas.detalle_item(alm, cid, 0)
    assert det["codigo_sugerido"] == "9001"
    assert det["unidad"] == "M3"


def test_detalle_item_sin_codigo_del_presupuesto_devuelve_vacio(tmp_path):
    """Una corrida plana (sin ruta IDU) no trae código: tiene que ser "" y no reventar."""
    alm = _almacen_seed(tmp_path)
    items = [LicitacionItem(item="1", descripcion="Concreto clase D", unidad="M3",
                            cantidad=10.0, precio_contractual=400000.0, shift="DIURNO")]
    cid = corridas.construir_corrida(alm, "lic.xlsx", items, "DIURNO", use_ai=False)
    det = corridas.detalle_item(alm, cid, 0)
    assert det["codigo_sugerido"] == ""
    assert det["unidad"] == "M3"
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `python -m pytest tests/test_servicio_corridas.py -q -k detalle_item_trae`
Expected: FAIL con `KeyError: 'codigo_sugerido'`

- [ ] **Step 3: Implementar el backend**

En `apu_tool/servicio/corridas.py`, en el `return` de `detalle_item`, justo después de
la línea `"apu_turno": row.shift,` y su comentario:

```python
        # El código que pedía el presupuesto (ruta IDU) y la unidad del ítem: los usa
        # "Armar APU" para precargar el alta desde la fila. Si ese APU existiera en la
        # biblioteca el armado ya lo habría asignado, así que cuando la fila no lo tiene,
        # este es el código que el APU nuevo debería llevar. "" en una corrida plana.
        #
        # La unidad es la del ÍTEM, no `row.unidad`: esa es la del APU asignado (la pone
        # `_build` en assemble.py), y un APU nuevo se arma para la ACTIVIDAD. Si la fila
        # trae un APU en M2 y la licitación pide M3, el que manda es M3.
        "codigo_sugerido": row.item.codigo_sugerido,
        "unidad": row.item.unidad,
```

- [ ] **Step 4: Correr los tests**

Run: `python -m pytest tests/test_servicio_corridas.py -q`
Expected: PASS.

- [ ] **Step 5: Agregar los campos al tipo del frontend**

En `web/src/lib/tipos.ts`, dentro de `interface DetalleItem`, después de `apu_nombre`:

```ts
  /** Código IDU que pedía el presupuesto (ruta IDU); "" en una corrida plana. */
  codigo_sugerido: string;
  /** Unidad del ítem de licitación. */
  unidad: string;
```

- [ ] **Step 6: Verificar que el frontend compila**

Run: `cd web && npm run build`
Expected: OK. (Es `tsc -b`: si algún mock de test no trae los campos nuevos, sale acá.)

Si algún test de vitest rompe porque su `DetalleItem` de mentira no tiene los campos,
agregáselos al mock — no aflojes el tipo.

- [ ] **Step 7: Commit**

```bash
git add apu_tool/servicio/corridas.py web/src/lib/tipos.ts tests/test_servicio_corridas.py
git commit -m "feat(corridas): el detalle de la fila trae el codigo del presupuesto y la unidad

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `DialogoArmarApu`, el que elige el punto de partida

**Files:**
- Create: `web/src/components/corrida/DialogoArmarApu.tsx`
- Test: `web/src/components/corrida/DialogoArmarApu.test.tsx`

Antes de escribir, mirá `web/src/components/corrida/DialogoAgregarLineas.tsx` para el
armazón de `Dialog` y el estilo de la casa.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `web/src/components/corrida/DialogoArmarApu.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import DialogoArmarApu from "./DialogoArmarApu";
import type { DetalleItem } from "@/lib/tipos";

// El alta de verdad tiene 822 líneas y ya tiene sus propios tests. Acá se la mockea
// para afirmar sobre el CONTRATO que este componente le entrega: `modo` e `inicial`.
vi.mock("@/components/autoria/DialogoAgregarApu", () => ({
  DialogoAgregarApu: (p: Record<string, unknown>) => (
    <div
      data-testid="alta"
      data-modo={String(p.modo)}
      data-codigo={String((p.inicial as { codigo?: string } | null)?.codigo ?? "")}
      data-nombre={String((p.inicial as { nombre?: string } | null)?.nombre ?? "")}
      data-unidad={String((p.inicial as { unidad?: string } | null)?.unidad ?? "")}
      data-comps={String((p.inicial as { composicion?: unknown[] } | null)?.composicion?.length ?? -1)}
    />
  ),
}));

const getApuDetalle = vi.fn(async (codigo: string, turno: string) => ({
  codigo, turno, nombre: `APU ${codigo}`, unidad: "M3", grupo: "ESTRUCTURAS",
  costo_unitario: 1000, composicion: [{ insumo_codigo: "100", insumo_nombre: "Cemento",
    unidad: "KG", rendimiento: 1, precio_unitario: 500, fuente_precio: "COSTO INTERNO",
    costo: 500, calidad_cruce: "exacto" }],
}));
vi.mock("@/api/autoria", () => ({
  getApuDetalle: (c: string, t: string) => getApuDetalle(c, t),
  listarApus: vi.fn(async () => ({ items: [], total: 0, limit: 15, offset: 0 })),
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

function detalle(over: Partial<DetalleItem> = {}): DetalleItem {
  return {
    seq: 3, descripcion: "PANTALLA ACUSTICA MODULAR", apu_codigo: "", apu_turno: "DIURNO",
    apu_nombre: "", codigo_sugerido: "", unidad: "M2", status: "new", explicacion: "",
    candidatos: [], composicion: [], costo_unitario: 0, costo_manual: false, ...over,
  };
}

beforeEach(() => vi.clearAllMocks());

describe("DialogoArmarApu", () => {
  it("sin APU asignado no ofrece duplicar el asignado", () => {
    render(<DialogoArmarApu abierto detalle={detalle()} onCerrar={vi.fn()}
                            onCreado={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /Duplicar el APU asignado/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Desde cero/ })).toBeTruthy();
  });

  it("con APU asignado ofrece duplicarlo y lo nombra", () => {
    render(<DialogoArmarApu abierto onCerrar={vi.fn()} onCreado={vi.fn()}
      detalle={detalle({ apu_codigo: "A1", apu_nombre: "CONCRETO CLASE D" })} />);
    expect(screen.getByRole("button", { name: /Duplicar el APU asignado/ })).toBeTruthy();
    expect(screen.getByText(/A1/)).toBeTruthy();
  });

  it("desde cero precarga nombre, unidad y el código del presupuesto", async () => {
    render(<DialogoArmarApu abierto onCerrar={vi.fn()} onCreado={vi.fn()}
      detalle={detalle({ codigo_sugerido: "9001" })} />);
    fireEvent.click(screen.getByRole("button", { name: /Desde cero/ }));

    const alta = await screen.findByTestId("alta");
    expect(alta.getAttribute("data-modo")).toBe("crear");
    expect(alta.getAttribute("data-codigo")).toBe("9001");
    expect(alta.getAttribute("data-nombre")).toBe("PANTALLA ACUSTICA MODULAR");
    expect(alta.getAttribute("data-unidad")).toBe("M2");
    // Composición vacía: el alta abre con una fila en blanco.
    expect(alta.getAttribute("data-comps")).toBe("0");
    // Desde cero NO lee la biblioteca.
    expect(getApuDetalle).not.toHaveBeenCalled();
  });

  it("duplicar el asignado lee ese APU de la biblioteca", async () => {
    render(<DialogoArmarApu abierto onCerrar={vi.fn()} onCreado={vi.fn()}
      detalle={detalle({ apu_codigo: "A1", apu_nombre: "CONCRETO", apu_turno: "NOCTURNO" })} />);
    fireEvent.click(screen.getByRole("button", { name: /Duplicar el APU asignado/ }));

    await waitFor(() => expect(getApuDetalle).toHaveBeenCalledWith("A1", "NOCTURNO"));
    const alta = await screen.findByTestId("alta");
    expect(alta.getAttribute("data-modo")).toBe("duplicar");
    expect(alta.getAttribute("data-codigo")).toBe("A1");
    // La composición del APU real, no la de la fila.
    expect(alta.getAttribute("data-comps")).toBe("1");
  });

  it("si leer el APU de origen falla, lo dice y se queda en la elección", async () => {
    getApuDetalle.mockRejectedValueOnce(new Error("no existe"));
    const { toast } = await import("sonner");
    render(<DialogoArmarApu abierto onCerrar={vi.fn()} onCreado={vi.fn()}
      detalle={detalle({ apu_codigo: "A1", apu_nombre: "CONCRETO" })} />);
    fireEvent.click(screen.getByRole("button", { name: /Duplicar el APU asignado/ }));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(screen.queryByTestId("alta")).toBeNull();
    expect(screen.getByRole("button", { name: /Desde cero/ })).toBeTruthy();
  });
});
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `cd web && npx vitest run src/components/corrida/DialogoArmarApu.test.tsx`
Expected: FAIL — el módulo no existe.

- [ ] **Step 3: Implementar el componente**

Crear `web/src/components/corrida/DialogoArmarApu.tsx`:

```tsx
import { useState } from "react";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { DialogoAgregarApu } from "@/components/autoria/DialogoAgregarApu";
import BuscadorApu from "@/components/corrida/BuscadorApu";
import { getApuDetalle } from "@/api/autoria";
import type { ApuDetalle, DetalleItem } from "@/lib/tipos";

interface Props {
  abierto: boolean;
  /** La fila desde la que se arma. */
  detalle: DetalleItem;
  onCerrar: () => void;
  /** El APU quedó creado. El llamador lo asigna a la fila. */
  onCreado: (codigo: string, turno: string) => void;
}

/** Elige el punto de partida para armar un APU parado en una fila de corrida y le
 *  entrega a `DialogoAgregarApu` el `(modo, inicial)` que corresponda.
 *
 *  Existe para NO tocar `DialogoAgregarApu`: tiene 822 líneas y lo usan otras dos
 *  pantallas. Sus modos `crear` y `duplicar` con `inicial` ya hacen lo que hace falta;
 *  lo que faltaba era el camino de entrada. */
export default function DialogoArmarApu({ abierto, detalle, onCerrar, onCreado }: Props) {
  // null = todavía estás eligiendo. Con valor, se muestra el alta ya cargada.
  const [partida, setPartida] = useState<
    { modo: "crear" | "duplicar"; inicial: ApuDetalle } | null
  >(null);
  const [cargando, setCargando] = useState(false);

  /** Lee el APU real de la biblioteca: la composición de la fila es la costeada y no
   *  trae las marcas de sub-APU, así que duplicar desde ahí perdería información. */
  async function partirDe(codigo: string, turno: string) {
    if (cargando) return;
    setCargando(true);
    try {
      setPartida({ modo: "duplicar", inicial: await getApuDetalle(codigo, turno) });
    } catch {
      toast.error("No se pudo leer ese APU de la biblioteca.");
    } finally {
      setCargando(false);
    }
  }

  function desdeCero() {
    setPartida({
      modo: "crear",
      inicial: {
        // El código que pedía el presupuesto. Si ese APU existiera, el armado ya lo
        // habría asignado: que la fila no lo tenga es justamente por qué hay que crearlo.
        codigo: detalle.codigo_sugerido,
        turno: detalle.apu_turno,
        nombre: detalle.descripcion,
        unidad: detalle.unidad,
        grupo: "",                 // lo elegís en el alta
        costo_unitario: 0,
        composicion: [],           // el alta abre con una fila en blanco
      },
    });
  }

  if (partida) {
    return (
      <DialogoAgregarApu
        open
        onOpenChange={(v) => { if (!v) onCerrar(); }}
        onCreado={onCreado}
        modo={partida.modo}
        inicial={partida.inicial}
      />
    );
  }

  return (
    <Dialog open={abierto} onOpenChange={(v) => { if (!v) onCerrar(); }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Armar APU para esta línea</DialogTitle>
        </DialogHeader>
        <p className="text-xs text-muted-foreground -mt-2 break-words">
          {detalle.descripcion}
        </p>

        <div className="flex flex-col gap-2 pt-1">
          {detalle.apu_codigo && (
            <Button variant="outline" className="justify-start h-auto py-2"
              disabled={cargando}
              onClick={() => partirDe(detalle.apu_codigo, detalle.apu_turno)}>
              <span className="flex flex-col items-start gap-0.5 text-left">
                <span className="text-xs font-semibold">Duplicar el APU asignado</span>
                <span className="text-[11px] text-muted-foreground">
                  {detalle.apu_codigo} — {detalle.apu_nombre}
                </span>
              </span>
            </Button>
          )}

          <Button variant="outline" className="justify-start h-auto py-2"
            disabled={cargando} onClick={desdeCero}>
            <span className="flex flex-col items-start gap-0.5 text-left">
              <span className="text-xs font-semibold">Desde cero</span>
              <span className="text-[11px] text-muted-foreground">
                Con el nombre, la unidad y el código de la actividad ya puestos.
              </span>
            </span>
          </Button>

          <div className="rounded border border-border p-2">
            <p className="text-[11px] font-semibold mb-1">Partir de otro APU</p>
            <BuscadorApu disabled={cargando}
              placeholder="Buscar el APU del que querés partir…"
              onElegir={(apu) => partirDe(apu.codigo, apu.turno)} />
          </div>
        </div>

        <div className="flex justify-end pt-2">
          <Button size="sm" variant="outline" onClick={onCerrar}>Cancelar</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 4: Correr los tests**

Run: `cd web && npx vitest run src/components/corrida/DialogoArmarApu.test.tsx`
Expected: PASS, 5 tests.

- [ ] **Step 5: Verificar que compila**

Run: `cd web && npm run build`
Expected: OK.

- [ ] **Step 6: Commit**

```bash
git add web/src/components/corrida/DialogoArmarApu.tsx web/src/components/corrida/DialogoArmarApu.test.tsx
git commit -m "feat(web): dialogo para elegir desde donde armar un APU

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: el botón "Armar APU" reemplaza al de duplicar

**Files:**
- Modify: `web/src/components/corrida/TablaItems.tsx`
- Test: `web/src/components/corrida/TablaItems.test.tsx`

**Contexto de lo que se borra:** hoy `TablaItems` hace el fetch del APU de origen y por eso
carga con `cargandoDuplicar`, `ultimoPedidoDuplicarRef` y `abrirDuplicar` — una máquina
para resolver la carrera de pedir duplicar en la fila A y después en la B antes de que A
responda. **Ese fetch se muda a `DialogoArmarApu`**, que se monta para UNA fila, así que la
carrera desaparece por construcción y esa máquina se va con ella. Es borrado, no descuido:
decilo en el commit.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de `web/src/components/corrida/TablaItems.test.tsx`. El archivo ya trae
el fixture `ITEM` (seq 0, `apu_codigo: "111"`), ya mockea `@/api/corridas::getItem` (que
devuelve el detalle con `apu_codigo: "111"`) y `@/api/autoria::getApuDetalle`. **Ojo:** el
mock de `getItem` hay que ampliarlo con los dos campos nuevos de la Tarea 1 —
`codigo_sugerido: ""` y `unidad: "M3"`— o el tipo no cierra.

```tsx
test("el botón Armar APU aparece en una fila CON APU, y ya no el de duplicar", async () => {
  const { default: TablaItems } = await import("./TablaItems");
  render(<TablaItems corridaId={1} items={[ITEM]} onConfirmado={() => {}}
                     puedeEditar />);

  fireEvent.click(screen.getByLabelText("Expandir fila"));
  await screen.findByText(/APU: 111/);          // el detalle ya cargó

  expect(screen.getByRole("button", { name: /Armar APU/ })).toBeTruthy();
  // El botón viejo era condicional y con otro texto: ya no existe.
  expect(screen.queryByRole("button", { name: /Duplicar este APU y usarlo aquí/ }))
    .toBeNull();
});

test("el botón Armar APU aparece también en una fila SIN APU", async () => {
  // Es el caso que antes NO tenía botón: sin APU no había nada que duplicar.
  const { getItem } = await import("@/api/corridas");
  vi.mocked(getItem).mockResolvedValueOnce({
    seq: 0, descripcion: "Concreto", apu_codigo: "", apu_turno: "DIURNO",
    apu_nombre: "(sin base — armar manual)", codigo_sugerido: "9001", unidad: "M3",
    status: "new", explicacion: "", candidatos: [], composicion: [],
    costo_unitario: 0, costo_manual: false,
  });
  const { default: TablaItems } = await import("./TablaItems");
  render(<TablaItems corridaId={1} onConfirmado={() => {}} puedeEditar
                     items={[{ ...ITEM, apu_codigo: null, status: "new" }]} />);

  fireEvent.click(screen.getByLabelText("Expandir fila"));

  expect(await screen.findByRole("button", { name: /Armar APU/ })).toBeTruthy();
});

test("sin rol editor el botón Armar APU no aparece", async () => {
  const { default: TablaItems } = await import("./TablaItems");
  // `puedeEditar` es false por defecto en el componente.
  render(<TablaItems corridaId={1} items={[ITEM]} onConfirmado={() => {}} />);

  fireEvent.click(screen.getByLabelText("Expandir fila"));
  await screen.findByText(/APU: 111/);

  expect(screen.queryByRole("button", { name: /Armar APU/ })).toBeNull();
});

test("con la corrida congelada el botón Armar APU no aparece", async () => {
  const { default: TablaItems } = await import("./TablaItems");
  render(<TablaItems corridaId={1} items={[ITEM]} onConfirmado={() => {}}
                     puedeEditar readOnly />);

  fireEvent.click(screen.getByLabelText("Expandir fila"));
  await screen.findByText(/APU: 111/);

  expect(screen.queryByRole("button", { name: /Armar APU/ })).toBeNull();
});
```

**Si alguna aserción no encaja con el andamiaje real** (por ejemplo, el `items` del
componente exige otro shape, o `vi.mocked` necesita otro import), arreglá el andamiaje
—no la aserción—: los cuatro casos son el contrato.

- [ ] **Step 2: Correr y verificar que fallan**

Run: `cd web && npx vitest run src/components/corrida/TablaItems.test.tsx`
Expected: FAIL — no existe ningún botón "Armar APU".

- [ ] **Step 3: Borrar la máquina de duplicar**

En `web/src/components/corrida/TablaItems.tsx`, eliminar:

- el estado `const [duplicar, setDuplicar] = useState<{ seq: number; origen: ApuDetalle } | null>(null);` y su comentario;
- `const [cargandoDuplicar, setCargandoDuplicar] = useState<number | null>(null);`;
- `const ultimoPedidoDuplicarRef = useRef<number | null>(null);` y el comentario largo que los explica;
- la función `abrirDuplicar` completa;
- el bloque `{duplicar && (<DialogoAgregarApu … modo="duplicar" … />)}` del final;
- el import de `DialogoAgregarApu` y el de `ApuDetalle` si quedan sin uso.

**No borres `duplicado(seq, codigo, turno)`**: es el que asigna el APU recién creado a la
fila, y lo sigue usando el camino nuevo.

- [ ] **Step 4: Poner el estado y el render nuevos**

En `TablaItems.tsx`, junto a los demás `useState`:

```tsx
  // Armar un APU parado en una fila. Guarda el detalle completo porque el diálogo
  // precarga el alta con la descripción, la unidad y el código del presupuesto.
  const [armar, setArmar] = useState<{ seq: number; detalle: DetalleItem } | null>(null);
```

y al final, donde estaba el bloque de duplicar:

```tsx
      {armar && (
        <DialogoArmarApu
          key={`armar-${armar.seq}`}
          abierto
          detalle={armar.detalle}
          onCerrar={() => setArmar(null)}
          onCreado={(codigo, turno) => { setArmar(null); duplicado(armar.seq, codigo, turno); }}
        />
      )}
```

con los imports:

```tsx
import DialogoArmarApu from "@/components/corrida/DialogoArmarApu";
import type { DetalleItem } from "@/lib/tipos";
```

(`DetalleItem` puede que ya esté importado en ese archivo: fijate antes de duplicar el import.)

- [ ] **Step 5: Cambiar los props de la fila desplegada**

En el componente de la fila desplegada (`FilaDetalle`, donde hoy están `puedeDuplicar`,
`duplicarCargando` y `onDuplicar`), reemplazar esos tres por dos:

```tsx
  puedeArmar: boolean;
  onArmar: (seq: number, detalle: DetalleItem) => void;
```

En el sitio donde se renderiza esa fila, reemplazar:

```tsx
                          puedeDuplicar={puedeEditar && !readOnly}
                          duplicarCargando={cargandoDuplicar === it.seq}
                          onDuplicar={abrirDuplicar}
```

por:

```tsx
                          puedeArmar={puedeEditar && !readOnly}
                          onArmar={(seq, det) => setArmar({ seq, detalle: det })}
```

- [ ] **Step 6: Reemplazar el botón**

Dentro de la fila desplegada, reemplazar el bloque actual —el que empieza con
`{puedeDuplicar && detalle.apu_codigo && (`— por:

```tsx
          {/* Siempre, tenga APU o no: la fila SIN APU es justo la que más lo necesita,
              y antes era la única que no tenía botón. El diálogo decide desde dónde
              partir (duplicar el asignado, partir de otro, o desde cero). */}
          {puedeArmar && (
            <div className="mt-2">
              <Button
                size="xs"
                variant="outline"
                disabled={confirmando !== null}
                onClick={() => onArmar(seq, detalle)}
              >
                Armar APU
              </Button>
            </div>
          )}
```

- [ ] **Step 7: Correr los tests de la tabla**

Run: `cd web && npx vitest run src/components/corrida/TablaItems.test.tsx`
Expected: PASS. Si algún test viejo buscaba "Duplicar este APU y usarlo aquí",
actualizalo al botón nuevo — ese texto ya no existe.

- [ ] **Step 8: Correr todo el frontend y el build**

Run: `cd web && npx vitest run`
Run: `cd web && npm run build`
Expected: los dos OK.

- [ ] **Step 9: Commit**

```bash
git add web/src/components/corrida/TablaItems.tsx web/src/components/corrida/TablaItems.test.tsx
git commit -m "feat(web): Armar APU reemplaza a duplicar y sale tambien sin APU

El fetch del APU de origen se muda al dialogo nuevo, que se monta para UNA fila,
asi que la carrera entre filas desaparece por construccion y con ella el ref y el
estado que la resolvian.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: documentar y verificar todo junto

**Files:**
- Modify: `CLAUDE.md` (sección **Datos**)

- [ ] **Step 1: Documentar**

Agregar a la sección **Datos** de `CLAUDE.md`, después del ítem "Volver a buscar APU":

```markdown
- **Armar APU desde una fila.** El botón **Armar APU** del panel de una fila sale
  siempre (rol editor, corrida no congelada) y ofrece tres puntos de partida: duplicar el
  APU asignado, partir de otro que busques, o desde cero con el nombre, la unidad y el
  `codigo_sugerido` de la actividad ya puestos. Antes solo existía "Duplicar este APU y
  usarlo aquí", que exigía que la fila YA tuviera APU — o sea que faltaba justo en la
  fila que más lo necesita. Lo nuevo es `components/corrida/DialogoArmarApu.tsx`, que
  solo elige el punto de partida: el alta sigue siendo `DialogoAgregarApu` (822 líneas,
  tres consumidores), cuyos modos `crear` y `duplicar` con `inicial` ya hacían lo que
  hacía falta y solo les faltaba llamador. Al crear, el APU queda asignado a la fila y la
  fila `confirmed`, igual que duplicar.
```

**Antes de pegar:** verificá contra el código que todo lo que dice es cierto. Si algo no
coincide, **reportá la discrepancia en vez de documentar una mentira**.

- [ ] **Step 2: Suite entera de Python**

Run: `python -m pytest tests/ -q`
Expected: verde.

**Nota:** hay un flake preexistente conocido — `RuntimeError: Directory '...web/dist/assets'
does not exist` en algún test de API, según el orden. Si aparece, corré ese archivo solo
para confirmar que pasa aislado y reportalo como preexistente.

- [ ] **Step 3: Suite entera del frontend**

Run: `cd web && npx vitest run`
Expected: verde.

- [ ] **Step 4: Build**

Run: `cd web && npm run build`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: armar APU desde una fila de la corrida

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 6: Smoke en el navegador — NO se salta**

Es un cambio de UI: el navegador va antes del push (la lección de la rama del
`DialogoTexto`, que llegó a producción con 145 tests verdes y un modal que se cerraba
solo). Levantar con `python scripts/servidor_local.py` desde la terminal propia.
**Ojo: el puerto 8000 lo tiene tomado Docker Desktop** — usar otro
(`python -m uvicorn apu_tool.servicio.app:app --port 8010`, con `SUPABASE_URL` y
`APU_ADMIN_EMAILS`; el frontend usa `/api` relativo, así que el puerto da igual).

1. Abrir una corrida, desplegar una fila **sin APU** → el botón **Armar APU** está.
2. **Desde cero** → el alta abre con el nombre y la unidad de la actividad; si la corrida
   vino de un presupuesto IDU, también con el código.
3. Crear → la fila queda con ese APU, costeada, badge `confirmado`.
4. Desplegar una fila **con APU** → el botón está igual, y **Duplicar el APU asignado**
   abre el alta con la composición del APU real.
5. **Partir de otro** → buscar uno cualquiera y comprobar que el alta abre con ESE.
6. Congelar la corrida → el botón desaparece.

---

## Fuera de alcance (a propósito)

- No se toca `DialogoAgregarApu.tsx` ni sus otros dos consumidores (`pages/Apus.tsx`, `pages/Composicion.tsx`).
- No se toca "Componer" ni la mesa de composición.
- El botón no se agrega a la columna Acciones: vive solo en el panel desplegado.
- No se crea la columna que compara el código del presupuesto con el asignado. Es otro spec.
