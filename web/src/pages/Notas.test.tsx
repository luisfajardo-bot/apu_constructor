import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import Notas from "./Notas";

const listarTodasNotas = vi.fn();
const listarNotas = vi.fn(async () => []);
vi.mock("@/api/notas", () => ({
  listarTodasNotas: (...a: unknown[]) => listarTodasNotas(...a),
  listarNotas: (...a: unknown[]) => listarNotas(...(a as [])),
  crearNota: vi.fn(), editarNota: vi.fn(), borrarNota: vi.fn(),
  listarMencionables: vi.fn(async () => []),
}));
const listarUsuarios = vi.fn();
vi.mock("@/api/usuarios", () => ({ listarUsuarios: () => listarUsuarios() }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ perfil: { rol: "admin" } }) }));

const DUENO = { entidad: "apu", codigo: "4859", nombre: "", turno: "NOCTURNO" };

beforeEach(() => {
  listarTodasNotas.mockReset();
  listarUsuarios.mockReset();
  listarUsuarios.mockResolvedValue([
    { user_id: "u-2", email: "zoe@obra.co", rol: "editor", estado: "activo", nombre: "" },
    { user_id: "u-1", email: "ana@obra.co", rol: "admin", estado: "activo", nombre: "Ana Ruiz" },
  ]);
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

  it("filtra por autor y vuelve a la primera página", async () => {
    render(<Notas />);
    await screen.findByText("rendimiento medido en obra");
    await screen.findByRole("option", { name: "Ana Ruiz" });
    fireEvent.change(screen.getByLabelText("Autor"), { target: { value: "u-1" } });
    await waitFor(() => expect(listarTodasNotas).toHaveBeenLastCalledWith(
      expect.objectContaining({ autor: "u-1", offset: 0 })));
  });

  it("descarta la respuesta vieja que llega después de la nueva", async () => {
    const nota = (id: number, texto: string) => ({
      items: [{ id, entidad: "apu", etiqueta: "x", texto, autor_email: "a@b.co",
                creada_en: "2026-09-30T10:00:00+00:00", editada_en: null, es_mia: false,
                puede_editar: false, puede_borrar: true, dueno: DUENO }],
      total: 1, limit: 100, offset: 0,
    });
    let soltarPrimera!: (v: unknown) => void;
    listarTodasNotas.mockReset();
    listarTodasNotas.mockReturnValueOnce(new Promise((r) => { soltarPrimera = r; }));
    listarTodasNotas.mockResolvedValue(nota(2, "nueva"));
    render(<Notas />);
    fireEvent.change(screen.getByLabelText("Tipo"), { target: { value: "apu" } });
    await screen.findByText("nueva");
    await act(async () => { soltarPrimera(nota(1, "vieja")); });
    expect(screen.queryByText("vieja")).toBeNull();
    expect(screen.getByText("nueva")).toBeTruthy();
  });
});
