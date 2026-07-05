import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { expect, test, vi } from "vitest";

vi.mock("@/api/corridas", () => ({
  getItem: vi.fn(async () => ({
    seq: 0, descripcion: "Concreto", apu_codigo: "111", apu_nombre: "APU VIEJO",
    status: "matched", explicacion: "", candidatos: [], composicion: [], costo_unitario: 0,
  })),
  confirmar: vi.fn(async () => ({
    id: 1, archivo: "x", estado: "en_revision", modo: "activa", items: [], duracion_ms: null,
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

test("muestra el error si la reasignación falla en un ítem matched", async () => {
  const { default: TablaItems } = await import("./TablaItems");
  const mod = await import("@/api/corridas");
  vi.mocked(mod.confirmar).mockRejectedValueOnce(new Error("fallo de red"));
  render(<TablaItems corridaId={1} items={[ITEM]} onConfirmado={() => {}} />);

  fireEvent.click(screen.getByLabelText("Expandir fila"));

  fireEvent.change(await screen.findByPlaceholderText(/Buscar APU/i), {
    target: { value: "333" },
  });
  fireEvent.click(await screen.findByText("APU NUEVO"));

  expect(await screen.findByText("fallo de red")).toBeTruthy();
});

test("oculta el buscador 'Cambiar APU' cuando la corrida está en solo lectura", async () => {
  const { default: TablaItems } = await import("./TablaItems");
  render(
    <TablaItems
      corridaId={1}
      items={[ITEM]}
      onConfirmado={() => {}}
      readOnly={true}
    />,
  );

  // Expandir la fila (lazy-fetch del detalle)
  fireEvent.click(screen.getByLabelText("Expandir fila"));

  // Esperar a que el detalle cargue (aparece el header del APU)
  await screen.findByText(/APU: 111/);

  // El buscador "Cambiar APU" NO debe estar presente en modo solo lectura
  expect(screen.queryByPlaceholderText(/Buscar APU/i)).toBeNull();

  // El aviso de solo lectura sí debe estar presente
  expect(
    screen.getByText(/Corrida congelada \(solo lectura\)/i),
  ).toBeTruthy();
});
