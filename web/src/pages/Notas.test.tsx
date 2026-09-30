import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import Notas from "./Notas";

const listarTodasNotas = vi.fn();
const listarNotas = vi.fn(async () => []);
vi.mock("@/api/notas", () => ({
  listarTodasNotas: (...a: unknown[]) => listarTodasNotas(...a),
  listarNotas: (...a: unknown[]) => listarNotas(...(a as [])),
  crearNota: vi.fn(), editarNota: vi.fn(), borrarNota: vi.fn(),
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ perfil: { rol: "admin" } }) }));

const DUENO = { entidad: "apu", codigo: "4859", nombre: "", turno: "NOCTURNO" };

beforeEach(() => {
  listarTodasNotas.mockReset();
  listarTodasNotas.mockResolvedValue({
    items: [{ id: 7, entidad: "apu", etiqueta: "4859 · NOCTURNO · EXCAVACION",
              texto: "rendimiento medido en obra", autor_email: "ana@obra.co",
              creada_en: "2026-09-30T10:00:00+00:00", editada_en: null, es_mia: false,
              puede_editar: false, puede_borrar: true, dueno: DUENO }],
    total: 1, limit: 100, offset: 0,
  });
});

describe("Notas", () => {
  it("lista todas las notas y filtra por tipo y texto", async () => {
    render(<Notas />);
    expect(await screen.findByText("rendimiento medido en obra")).toBeTruthy();
    expect(screen.getByText("4859 · NOCTURNO · EXCAVACION")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Tipo"), { target: { value: "apu" } });
    await waitFor(() => expect(listarTodasNotas).toHaveBeenLastCalledWith(
      expect.objectContaining({ entidad: "apu" })));
    fireEvent.change(screen.getByPlaceholderText("Buscar en las notas…"),
                     { target: { value: "obra" } });
    await waitFor(() => expect(listarTodasNotas).toHaveBeenLastCalledWith(
      expect.objectContaining({ q: "obra" })), { timeout: 2000 });
  });

  it("clic en una fila abre el panel de ese dueño", async () => {
    render(<Notas />);
    fireEvent.click(await screen.findByText("rendimiento medido en obra"));
    expect(await screen.findByText("Notas · 4859 · NOCTURNO · EXCAVACION")).toBeTruthy();
    expect(listarNotas).toHaveBeenCalledWith(DUENO);
  });
});
