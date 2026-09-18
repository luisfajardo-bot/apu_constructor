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
