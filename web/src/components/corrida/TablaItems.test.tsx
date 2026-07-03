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
