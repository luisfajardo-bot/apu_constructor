import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import Apus from "./Apus";

const detalle = {
  codigo: "3454", turno: "DIURNO", nombre: "MEZCLA MD12", unidad: "M3", grupo: "PAV",
  costo_unitario: 480000,
  composicion: [{
    insumo_codigo: "999", insumo_nombre: "MEZCLA MD12", unidad: "M3",
    rendimiento: 1, precio_unitario: 480000, fuente_precio: "PRECIO IDU",
    costo: 480000, calidad_cruce: "exacto",
  }],
};

vi.mock("@/api/autoria", () => ({
  listarApus: vi.fn(async () => ({
    items: [{ codigo: "3454", turno: "DIURNO", nombre: "MEZCLA MD12", unidad: "M3",
              grupo: "PAV", n_componentes: 1, costo_unitario: 480000 }],
    total: 1, limit: 100, offset: 0,
  })),
  getApuDetalle: vi.fn(async () => detalle),
  crearApu: vi.fn(async () => ({})),
  editarApu: vi.fn(async () => ({})),
  borrarApu: vi.fn(async () => {}),
  getGruposApu: vi.fn(async () => ["PAVIMENTOS", "REDES DE ACUEDUCTO"]),
}));
vi.mock("@/api/insumos", () => ({
  listarInsumos: vi.fn(async () => ({ items: [], total: 0, limit: 15, offset: 0 })),
}));
vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ perfil: { rol: "admin" } }),
}));

test("la fila expandida ofrece Duplicar y abre el diálogo precargado", async () => {
  render(<Apus />);
  fireEvent.click(await screen.findByText("MEZCLA MD12"));      // expande la fila
  fireEvent.click(await screen.findByRole("button", { name: /^Duplicar$/ }));
  await waitFor(() =>
    expect(screen.getByText(/Duplicar APU 3454 \(DIURNO\)/)).toBeTruthy());
  expect(screen.getByDisplayValue("3454-2")).toBeTruthy();
});
