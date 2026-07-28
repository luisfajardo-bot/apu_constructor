import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
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

  // Discriminan la condición correcta (`ins.sin_precio && …`) del error que el
  // revisor saboteó (`!ins.precio && …`): con el sabotaje, ambos casos de abajo
  // muestran lo contrario de lo esperado. El caso del beforeEach (precio: 0 Y
  // sin_precio: true a la vez) no alcanza a distinguirlos.
  it("precio 0 puesto a propósito (sin_precio: false) se muestra como $0, no como —", async () => {
    listarInsumos.mockResolvedValue({
      items: [{ id: 2, codigo: "10", nombre: "RELLENO GRATIS", unidad: "M3", grupo: "MAT",
                precio: 0, fuente: "PRECIO IDU", clasificacion: "publico", sin_precio: false }],
      total: 1, limit: 100, offset: 0,
    });
    render(<Insumos />);
    expect(await screen.findByText("$0")).toBeTruthy();
    expect(screen.queryByText("—")).toBeNull();
  });

  it("sin tarifa en la lista (sin_precio: true) se muestra como — aunque traiga un precio numérico", async () => {
    listarInsumos.mockResolvedValue({
      items: [{ id: 3, codigo: "11", nombre: "ARENA FINA", unidad: "M3", grupo: "MAT",
                precio: 100, fuente: "", clasificacion: "interno", sin_precio: true }],
      total: 1, limit: 100, offset: 0,
    });
    render(<Insumos />);
    expect(await screen.findByText("—")).toBeTruthy();
    expect(screen.queryByText("$100")).toBeNull();
  });

  it("avisa cuando la lista activa no es Principal", async () => {
    render(<Insumos />);
    await waitFor(() => expect(listarInsumos).toHaveBeenCalled());
    // El aviso solo aparece con una lista distinta de Principal; con Principal, no.
    expect(screen.queryByText(/editando la lista/i)).toBeNull();
  });

  it("el aviso sí aparece al cambiar a una lista distinta de Principal", async () => {
    Element.prototype.scrollIntoView = vi.fn();
    Element.prototype.hasPointerCapture = vi.fn().mockReturnValue(false);
    Element.prototype.setPointerCapture = vi.fn();
    Element.prototype.releasePointerCapture = vi.fn();

    render(<Insumos />);
    await waitFor(() => expect(listarInsumos).toHaveBeenCalled());
    expect(screen.queryByText(/editando la lista/i)).toBeNull();

    const combo = screen.getAllByRole("combobox")[0]; // selector de lista
    fireEvent.click(combo);
    fireEvent.click(await screen.findByText("NP Calle 13"));

    const aviso = await screen.findByText(/editando la lista/i);
    expect(aviso.textContent).toContain("NP Calle 13");
  });
});
