import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import Insumos from "@/pages/Insumos";

// Feature: crear/renombrar listas de precios desde la pantalla de Insumos.
// La API (crearLista/renombrarLista) ya existía pero ninguna pantalla la
// llamaba: había que hacer el POST a mano. Cubre: alta + auto-selección en la
// lista nueva, ocultamiento de los controles para el rol de consulta, la
// lista Principal sin opción de renombrar, y que un 400 del backend (nombre
// duplicado) se muestre tal cual lo manda el backend (no un texto genérico).

const listarInsumos = vi.fn();
vi.mock("@/api/insumos", () => ({
  listarInsumos: (...a: unknown[]) => listarInsumos(...a),
  getFuentes: () => Promise.resolve([]),
  getGrupos: () => Promise.resolve([]),
  getInsumo: () => Promise.resolve(null),
  aplicarCambios: () => Promise.resolve({ aplicados: 0, errores: [] }),
}));

const listarListas = vi.fn();
const crearLista = vi.fn();
const renombrarLista = vi.fn();
vi.mock("@/api/listas", () => ({
  listarListas: (...a: unknown[]) => listarListas(...a),
  crearLista: (...a: unknown[]) => crearLista(...a),
  renombrarLista: (...a: unknown[]) => renombrarLista(...a),
}));

vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

let rol: "consulta" | "editor" | "admin" = "editor";
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ perfil: { rol } }) }));

beforeEach(async () => {
  rol = "editor";
  listarInsumos.mockReset();
  listarInsumos.mockResolvedValue({ items: [], total: 0, limit: 100, offset: 0 });
  listarListas.mockReset();
  listarListas.mockResolvedValue([
    { id: 1, nombre: "Principal", creada_en: "2026-07-27" },
    { id: 2, nombre: "NP Calle 13", creada_en: "2026-07-27" },
  ]);
  crearLista.mockReset();
  renombrarLista.mockReset();

  const { toast } = await import("sonner");
  (toast.error as ReturnType<typeof vi.fn>).mockReset();
  (toast.success as ReturnType<typeof vi.fn>).mockReset();

  // Radix Select necesita estos polyfills para funcionar en jsdom.
  Element.prototype.scrollIntoView = vi.fn();
  Element.prototype.hasPointerCapture = vi.fn().mockReturnValue(false);
  Element.prototype.setPointerCapture = vi.fn();
  Element.prototype.releasePointerCapture = vi.fn();
});

afterEach(() => {
  vi.restoreAllMocks();
});

async function cambiarANpCalle13() {
  const combo = screen.getAllByRole("combobox")[0]; // selector de lista
  fireEvent.click(combo);
  fireEvent.click(await screen.findByText("NP Calle 13"));
}

describe("Insumos: crear y renombrar listas de precios", () => {
  it("un editor puede crear una lista y queda seleccionado en ella", async () => {
    vi.spyOn(window, "prompt").mockReturnValue("NP Peñón");
    crearLista.mockResolvedValue({ id: 3, nombre: "NP Peñón", creada_en: "2026-07-28" });

    render(<Insumos />);
    await waitFor(() => expect(listarInsumos).toHaveBeenCalledTimes(1));
    expect(listarInsumos.mock.calls[0][0].lista).toBe(1);
    expect(listarListas).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByText("+ Nueva"));

    await waitFor(() => expect(crearLista).toHaveBeenCalledWith("NP Peñón"));
    // Queda seleccionado en la lista recién creada.
    await waitFor(() =>
      expect(listarInsumos.mock.calls.some((c) => c[0].lista === 3)).toBe(true)
    );
    // El desplegable se recarga tras crear.
    await waitFor(() => expect(listarListas.mock.calls.length).toBeGreaterThan(1));
  });

  it("cancelar el prompt no crea ninguna lista", async () => {
    vi.spyOn(window, "prompt").mockReturnValue(null);
    render(<Insumos />);
    await waitFor(() => expect(listarInsumos).toHaveBeenCalled());

    fireEvent.click(screen.getByText("+ Nueva"));

    await waitFor(() => expect(window.prompt).toHaveBeenCalled());
    expect(crearLista).not.toHaveBeenCalled();
  });

  it("un usuario de consulta no ve los controles de listas", async () => {
    rol = "consulta";
    render(<Insumos />);
    await waitFor(() => expect(listarInsumos).toHaveBeenCalled());
    expect(screen.queryByText("+ Nueva")).toBeNull();
    expect(screen.queryByText("Renombrar")).toBeNull();
  });

  it("renombrar no se ofrece con Principal seleccionada, sí con otra lista", async () => {
    render(<Insumos />);
    await waitFor(() => expect(listarInsumos).toHaveBeenCalled());
    expect(screen.queryByText("Renombrar")).toBeNull();

    await cambiarANpCalle13();

    expect(await screen.findByText("Renombrar")).toBeTruthy();
  });

  it("un 400 del backend (nombre duplicado) al crear muestra el mensaje del backend", async () => {
    vi.spyOn(window, "prompt").mockReturnValue("NP Calle 13");
    crearLista.mockRejectedValue(
      new Error("Ya existe una lista de precios llamada «NP Calle 13».")
    );

    render(<Insumos />);
    await waitFor(() => expect(listarInsumos).toHaveBeenCalled());

    fireEvent.click(screen.getByText("+ Nueva"));

    const { toast } = await import("sonner");
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Ya existe una lista de precios llamada «NP Calle 13»."
      )
    );
    // No se quedó seleccionado en ninguna lista nueva: sigue en Principal.
    expect(listarInsumos.mock.calls.every((c) => c[0].lista === 1)).toBe(true);
  });

  it("un 400 del backend al renombrar (nombre duplicado) muestra el mensaje del backend", async () => {
    vi.spyOn(window, "prompt").mockReturnValue("Principal");
    renombrarLista.mockRejectedValue(
      new Error("Ya existe una lista de precios llamada «Principal».")
    );

    render(<Insumos />);
    await waitFor(() => expect(listarInsumos).toHaveBeenCalled());
    await cambiarANpCalle13();

    fireEvent.click(await screen.findByText("Renombrar"));

    await waitFor(() => expect(renombrarLista).toHaveBeenCalledWith(2, "Principal"));
    const { toast } = await import("sonner");
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(
        "Ya existe una lista de precios llamada «Principal»."
      )
    );
  });

  it("renombrar exitoso recarga las listas", async () => {
    vi.spyOn(window, "prompt").mockReturnValue("NP Calle 13 bis");
    renombrarLista.mockResolvedValue({
      id: 2,
      nombre: "NP Calle 13 bis",
      creada_en: "2026-07-27",
    });

    render(<Insumos />);
    await waitFor(() => expect(listarInsumos).toHaveBeenCalled());
    await cambiarANpCalle13();
    expect(listarListas).toHaveBeenCalledTimes(1);

    fireEvent.click(await screen.findByText("Renombrar"));

    await waitFor(() => expect(renombrarLista).toHaveBeenCalledWith(2, "NP Calle 13 bis"));
    await waitFor(() => expect(listarListas.mock.calls.length).toBeGreaterThan(1));
  });

  it("crear una lista con cambios sin guardar respeta el guard de confirmación", async () => {
    vi.spyOn(window, "prompt").mockReturnValue("NP Peñón");
    crearLista.mockResolvedValue({ id: 3, nombre: "NP Peñón", creada_en: "2026-07-28" });
    listarInsumos.mockResolvedValue({
      items: [{ id: 1, codigo: "9", nombre: "CEMENTO GRIS", unidad: "KG", grupo: "MAT",
                precio: 100, fuente: "PRECIO IDU", clasificacion: "interno", sin_precio: false }],
      total: 1, limit: 100, offset: 0,
    });
    vi.spyOn(window, "confirm").mockReturnValue(false);

    render(<Insumos />);
    await waitFor(() => expect(listarInsumos).toHaveBeenCalledTimes(1));

    const boton = await screen.findByText("$100");
    fireEvent.click(boton);
    const input = screen.getByRole("spinbutton");
    fireEvent.change(input, { target: { value: "555" } });
    fireEvent.blur(input);
    expect(await screen.findByText("$555")).toBeTruthy();

    fireEvent.click(screen.getByText("+ Nueva"));

    // La lista se crea igual (no se pierde el trabajo del usuario), pero
    // como canceló la confirmación, NO se cambia de lista activa: el cambio
    // sin guardar sigue intacto.
    await waitFor(() => expect(crearLista).toHaveBeenCalledWith("NP Peñón"));
    expect(window.confirm).toHaveBeenCalled();
    expect(listarInsumos.mock.calls.some((c) => c[0].lista === 3)).toBe(false);
    expect(screen.getByText("$555")).toBeTruthy();
  });
});
