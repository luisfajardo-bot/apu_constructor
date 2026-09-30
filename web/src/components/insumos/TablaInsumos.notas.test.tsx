import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TablaInsumos } from "./TablaInsumos";

const listarNotas = vi.fn(async () => []);
vi.mock("@/api/notas", () => ({
  listarNotas: (...a: unknown[]) => listarNotas(...(a as [])),
  crearNota: vi.fn(), editarNota: vi.fn(), borrarNota: vi.fn(),
}));
vi.mock("@/api/insumos", () => ({ getInsumo: vi.fn(), aplicarCambios: vi.fn() }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ perfil: { rol: "editor" } }) }));

const base = { unidad: "ML", grupo: "D", precio: 1, fuente: "COSTO INTERNO",
               clasificacion: "interno", sin_precio: false };

describe("TablaInsumos: columna de notas", () => {
  it("pinta el ícono de la fila con notas y abre su panel", async () => {
    render(<TablaInsumos listaId={1} onReload={() => {}} puedeEditar insumos={[
      { id: 1, codigo: "4520", nombre: "DUCTO", ...base, tiene_notas: true, ultima_nota: "cotización" },
      { id: 2, codigo: "4521", nombre: "CODO", ...base, tiene_notas: false, ultima_nota: "" },
    ]} />);
    const iconos = screen.getAllByRole("button", { name: "Notas" });
    expect(iconos.map((b) => b.getAttribute("data-tiene"))).toEqual(["si", "no"]);
    fireEvent.click(iconos[0]);
    expect(await screen.findByText("Notas · 4520 · DUCTO")).toBeTruthy();
    expect(listarNotas).toHaveBeenCalledWith(
      { entidad: "insumo", codigo: "4520", nombre: "DUCTO", turno: "" });
  });
});
