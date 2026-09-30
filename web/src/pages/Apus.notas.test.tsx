import { expect, test, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import Apus from "./Apus";

const listarNotas = vi.fn(async () => []);
vi.mock("@/api/notas", () => ({
  listarNotas: (...a: unknown[]) => listarNotas(...(a as [])),
  crearNota: vi.fn(), editarNota: vi.fn(), borrarNota: vi.fn(),
}));
const getApuDetalle = vi.fn();
vi.mock("@/api/autoria", () => ({
  listarApus: vi.fn(async () => ({
    items: [{ codigo: "4859", turno: "NOCTURNO", nombre: "EXCAVACION", unidad: "M3",
              grupo: "EXC", n_componentes: 1, costo_unitario: 1000,
              tiene_notas: true, ultima_nota: "medido en obra" }],
    total: 1, limit: 100, offset: 0,
  })),
  getApuDetalle: (...a: unknown[]) => getApuDetalle(...a),
  crearApu: vi.fn(), editarApu: vi.fn(), borrarApu: vi.fn(),
  getGruposApu: vi.fn(async () => []),
}));
vi.mock("@/api/insumos", () => ({
  listarInsumos: vi.fn(async () => ({ items: [], total: 0, limit: 15, offset: 0 })),
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ perfil: { rol: "consulta" } }) }));

test("el ícono abre las notas del APU por turno sin expandir la fila", async () => {
  render(<Apus />);
  const icono = await screen.findByRole("button", { name: "Notas" });
  expect(icono.getAttribute("data-tiene")).toBe("si");
  fireEvent.click(icono);
  expect(await screen.findByText("Notas · 4859 · NOCTURNO · EXCAVACION")).toBeTruthy();
  expect(listarNotas).toHaveBeenCalledWith(
    { entidad: "apu", codigo: "4859", nombre: "EXCAVACION", turno: "NOCTURNO" });
  expect(getApuDetalle).not.toHaveBeenCalled();
});
