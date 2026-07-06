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
