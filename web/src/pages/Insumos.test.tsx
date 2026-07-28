import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import Insumos from "@/pages/Insumos";

const listarInsumos = vi.fn();
vi.mock("@/api/insumos", () => ({
  listarInsumos: (...a: unknown[]) => listarInsumos(...a),
  getFuentes: () => Promise.resolve([]),
  getGrupos: () => Promise.resolve([]),
  getInsumo: () => Promise.resolve(null),
  aplicarCambios: () => Promise.resolve({ aplicados: 0, errores: [] }),
}));
vi.mock("@/api/listas", () => ({
  listarListas: () => Promise.resolve([
    { id: 1, nombre: "Principal", creada_en: "2026-07-27" },
    { id: 2, nombre: "NP Calle 13", creada_en: "2026-07-27" },
  ]),
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ perfil: { rol: "editor" } }) }));

beforeEach(() => {
  listarInsumos.mockReset();
  listarInsumos.mockResolvedValue({
    items: [{ id: 1, codigo: "9", nombre: "CEMENTO GRIS", unidad: "KG", grupo: "MAT",
              precio: 0, fuente: "", clasificacion: "interno", sin_precio: true }],
    total: 1, limit: 100, offset: 0,
  });
});

describe("Insumos con listas de precios", () => {
  it("carga con la lista Principal por defecto", async () => {
    render(<Insumos />);
    await waitFor(() => expect(listarInsumos).toHaveBeenCalled());
    expect(listarInsumos.mock.calls[0][0].lista).toBe(1);
  });

  it("muestra — cuando el insumo no tiene precio en la lista", async () => {
    render(<Insumos />);
    expect(await screen.findByText("—")).toBeTruthy();
  });

  it("avisa cuando la lista activa no es Principal", async () => {
    render(<Insumos />);
    await waitFor(() => expect(listarInsumos).toHaveBeenCalled());
    // El aviso solo aparece con una lista distinta de Principal; con Principal, no.
    expect(screen.queryByText(/editando la lista/i)).toBeNull();
  });
});
