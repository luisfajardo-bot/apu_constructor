import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import Insumos from "@/pages/Insumos";

// Regresión del hallazgo CRITICAL (revisión del commit a1df261): un precio
// editado y sin guardar en una lista de precios no puede sobrevivir (ni
// terminar guardándose) al cambiar a otra lista. Cubre las dos partes pedidas:
// (a) el valor sucio no sobrevive al cambio de lista, (b) si el usuario
// cancela la confirmación, la lista no cambia y el cambio se conserva.

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

// Mismo insumo (id=1) en las dos listas, con precio REAL distinto en cada una:
// así el escenario reproduce exactamente el reportado por el revisor (el
// precio sucio de la lista 1 podría confundirse con el precio real de la 2).
function datosLista(lista: number | undefined) {
  const precio = lista === 2 ? 999 : 100;
  return {
    items: [{ id: 1, codigo: "9", nombre: "CEMENTO GRIS", unidad: "KG", grupo: "MAT",
              precio, fuente: "PRECIO IDU", clasificacion: "interno", sin_precio: false }],
    total: 1, limit: 100, offset: 0,
  };
}

beforeEach(() => {
  listarInsumos.mockReset();
  listarInsumos.mockImplementation(async (params: { lista?: number }) =>
    datosLista(params.lista)
  );
  // Radix Select necesita estos polyfills para funcionar en jsdom.
  Element.prototype.scrollIntoView = vi.fn();
  Element.prototype.hasPointerCapture = vi.fn().mockReturnValue(false);
  Element.prototype.setPointerCapture = vi.fn();
  Element.prototype.releasePointerCapture = vi.fn();
});

afterEach(() => {
  vi.restoreAllMocks();
});

async function editarPrecioA555() {
  const boton = await screen.findByText("$100");
  fireEvent.click(boton);
  const input = screen.getByRole("spinbutton");
  fireEvent.change(input, { target: { value: "555" } });
  fireEvent.blur(input);
}

async function cambiarALista2() {
  const combo = screen.getAllByRole("combobox")[0]; // el selector de lista es el primero
  fireEvent.click(combo);
  const opcion = await screen.findByText("NP Calle 13");
  fireEvent.click(opcion);
}

describe("Insumos: no se puede guardar un precio de una lista en otra", () => {
  it("un precio editado y no guardado no sobrevive al cambio de lista", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<Insumos />);
    await waitFor(() => expect(listarInsumos).toHaveBeenCalledTimes(1));

    await editarPrecioA555();
    expect(await screen.findByText("$555")).toBeTruthy();
    expect(screen.getByText("1 cambio sin guardar")).toBeTruthy();

    await cambiarALista2();

    // Se pidió confirmación (menciona cuántos cambios se descartan).
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("1 cambio"));

    await waitFor(() =>
      expect(listarInsumos.mock.calls.some((c) => c[0].lista === 2)).toBe(true)
    );
    // El valor sucio de la lista 1 no debe verse ni haberse "guardado" en la 2.
    expect(screen.queryByText("$555")).toBeNull();
    expect(screen.queryByText(/cambio.*sin guardar/)).toBeNull();
    // La lista nueva muestra su propio precio real, no el sucio.
    expect(await screen.findByText("$999")).toBeTruthy();
  });

  it("si el usuario cancela la confirmación, la lista no cambia y el cambio se conserva", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<Insumos />);
    await waitFor(() => expect(listarInsumos).toHaveBeenCalledTimes(1));

    await editarPrecioA555();
    expect(await screen.findByText("$555")).toBeTruthy();

    await cambiarALista2();

    expect(window.confirm).toHaveBeenCalled();
    // Nunca se llegó a pedir la lista 2: el cambio de lista se abortó.
    expect(listarInsumos.mock.calls.some((c) => c[0].lista === 2)).toBe(false);
    expect(screen.queryByText(/editando la lista/i)).toBeNull();
    // El cambio sin guardar sigue ahí, intacto.
    expect(screen.getByText("$555")).toBeTruthy();
    expect(screen.getByText("1 cambio sin guardar")).toBeTruthy();
  });
});
