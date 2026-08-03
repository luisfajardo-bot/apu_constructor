import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test, vi, beforeEach, afterEach } from "vitest";
import { colorSigno } from "./MisCorridas";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ perfil: { rol: "admin", email: "a@b.c", nombre: "A" } }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

// Hoisted para poder inspeccionar (mock.calls) las llamadas que dispara el modal
// DialogoTexto, igual que armarArchivoMock en CorridasInicio.test.tsx.
const { crearCarpetaMock, renombrarCarpetaMock, renombrarCorridaMock } = vi.hoisted(() => ({
  crearCarpetaMock: vi.fn(),
  renombrarCarpetaMock: vi.fn(),
  renombrarCorridaMock: vi.fn(async () => ({})),
}));

vi.mock("@/api/corridas", () => ({
  listarCorridas: vi.fn(async () => [{
    id: 1, nombre: "lic.xlsx", archivo: "lic.xlsx", creada_en: "2026-07-08T10:00:00",
    estado: "en_revision", modo: "activa", n_items: 2, n_revision: 1, duracion_ms: 1000,
    contractual: 4000000, costo: 3675000, margen: 325000, margen_pct: 0.08125,
    carpeta_id: 1,
  }]),
  eliminarCorrida: vi.fn(),
  renombrarCorrida: renombrarCorridaMock,
  descargarPlantillaLicitacion: vi.fn(),
}));

vi.mock("@/api/carpetas", () => ({
  listarCarpetas: vi.fn(async () => [
    {
      id: 1, nombre: "Calle 13", parent_id: null, n_corridas: 1,
      hijas: [
        { id: 2, nombre: "Lote 3", parent_id: 1, n_corridas: 0, hijas: [] },
      ],
    },
  ]),
  crearCarpeta: crearCarpetaMock,
  renombrarCarpeta: renombrarCarpetaMock,
  borrarCarpeta: vi.fn(),
  moverCorrida: vi.fn(async () => ({})),
  moverCarpeta: vi.fn(async () => ({})),
}));

afterEach(async () => {
  crearCarpetaMock.mockClear();
  renombrarCarpetaMock.mockClear();
  renombrarCorridaMock.mockClear();
  const { toast } = await import("sonner");
  vi.mocked(toast.success).mockClear();
  vi.mocked(toast.error).mockClear();
});

test("colorSigno: verde si >=0, rojo si <0, undefined si null", () => {
  expect(colorSigno(10)).toBe("#276749");
  expect(colorSigno(0)).toBe("#276749");
  expect(colorSigno(-5)).toBe("#c53030");
  expect(colorSigno(null)).toBeUndefined();
});

test("MisCorridas muestra contractual, costo, dif y margen % formateados (dentro de carpeta)", async () => {
  const { default: MisCorridas } = await import("./MisCorridas");
  render(<MemoryRouter initialEntries={["/corridas?carpeta=1"]}><MisCorridas /></MemoryRouter>);
  await waitFor(() => expect(screen.getByText("$4.000.000")).toBeTruthy());
  expect(screen.getByText("$3.675.000")).toBeTruthy();
  expect(screen.getByText("$325.000")).toBeTruthy();
  expect(screen.getByText("8.1%")).toBeTruthy();
});

test("MisCorridas: root muestra carpeta y oculta corridas; entrando a carpeta las muestra", async () => {
  const { default: MisCorridas } = await import("./MisCorridas");

  // Root: carpeta visible, dinero de la corrida no visible
  const { unmount } = render(<MemoryRouter initialEntries={["/corridas"]}><MisCorridas /></MemoryRouter>);
  await waitFor(() => expect(screen.getByText("Calle 13")).toBeTruthy());
  expect(screen.queryByText("$4.000.000")).toBeNull();
  unmount();

  // Con carpeta=1: dinero de la corrida visible
  const { default: MisCorridasB } = await import("./MisCorridas");
  render(<MemoryRouter initialEntries={["/corridas?carpeta=1"]}><MisCorridasB /></MemoryRouter>);
  await waitFor(() => expect(screen.getByText("$4.000.000")).toBeTruthy());
});

test("Mover corrida: al hacer clic en 'Mover' y elegir opción 1, llama moverCorrida(1, destinoId)", async () => {
  const { default: MisCorridas } = await import("./MisCorridas");
  const { moverCorrida } = await import("@/api/carpetas");

  const promptSpy = vi.spyOn(window, "prompt").mockReturnValue("1");

  render(
    <MemoryRouter initialEntries={["/corridas?carpeta=1"]}>
      <MisCorridas />
    </MemoryRouter>
  );

  // Esperar a que cargue la corrida
  await waitFor(() => expect(screen.getByText("lic.xlsx")).toBeTruthy());

  // Buscar la fila de la corrida y el botón Mover dentro de ella
  const row = screen.getByText("lic.xlsx").closest("tr")!;
  const btnMoverCorrida = within(row).getByRole("button", { name: /mover/i });
  fireEvent.click(btnMoverCorrida);

  await waitFor(() => {
    expect(moverCorrida).toHaveBeenCalledWith(1, expect.any(Number));
  });

  promptSpy.mockRestore();
});

test("Renombrar corrida: al hacer clic y confirmar, llama renombrarCorrida(1, nuevo)", async () => {
  const { default: MisCorridas } = await import("./MisCorridas");

  render(
    <MemoryRouter initialEntries={["/corridas?carpeta=1"]}>
      <MisCorridas />
    </MemoryRouter>
  );

  await waitFor(() => expect(screen.getByText("lic.xlsx")).toBeTruthy());
  const row = screen.getByText("lic.xlsx").closest("tr")!;
  fireEvent.click(within(row).getByRole("button", { name: /renombrar/i }));

  const dialogo = await screen.findByRole("dialog");
  fireEvent.change(within(dialogo).getByLabelText("Nombre"), { target: { value: "Obra Norte" } });
  fireEvent.click(within(dialogo).getByRole("button", { name: "Guardar" }));

  await waitFor(() => {
    expect(renombrarCorridaMock).toHaveBeenCalledWith(1, "Obra Norte");
  });
});

test("Renombrar corrida muestra el toast de éxito con el nombre nuevo", async () => {
  const { default: MisCorridas } = await import("./MisCorridas");
  const { toast } = await import("sonner");

  render(
    <MemoryRouter initialEntries={["/corridas?carpeta=1"]}>
      <MisCorridas />
    </MemoryRouter>
  );

  await waitFor(() => expect(screen.getByText("lic.xlsx")).toBeTruthy());
  fireEvent.click(screen.getByTitle("Renombrar corrida"));

  const dialogo = await screen.findByRole("dialog");
  fireEvent.change(within(dialogo).getByLabelText("Nombre"), { target: { value: "Obra Norte" } });
  fireEvent.click(within(dialogo).getByRole("button", { name: "Guardar" }));

  await waitFor(() => {
    expect(vi.mocked(toast.success)).toHaveBeenCalledWith('Corrida renombrada a "Obra Norte"');
  });
});

test("Nueva carpeta: crea la carpeta con el nombre ingresado", async () => {
  const { default: MisCorridas } = await import("./MisCorridas");

  render(<MemoryRouter initialEntries={["/corridas"]}><MisCorridas /></MemoryRouter>);
  await screen.findByText("Calle 13");

  fireEvent.click(screen.getByRole("button", { name: "Nueva carpeta" }));

  const dialogo = await screen.findByRole("dialog");
  fireEvent.change(within(dialogo).getByLabelText("Nombre"), { target: { value: "Obra Sur" } });
  fireEvent.click(within(dialogo).getByRole("button", { name: "Crear" }));

  // Estamos en la raíz (sin ?carpeta=), así que carpetaActual es null.
  await waitFor(() => expect(crearCarpetaMock).toHaveBeenCalledWith("Obra Sur", null));
});

test("Renombrar carpeta: al confirmar con nombre distinto, llama renombrarCarpeta(id, nuevo)", async () => {
  const { default: MisCorridas } = await import("./MisCorridas");

  render(<MemoryRouter initialEntries={["/corridas"]}><MisCorridas /></MemoryRouter>);
  await screen.findByText("Calle 13");

  fireEvent.click(screen.getAllByTitle("Renombrar carpeta")[0]);

  const dialogo = await screen.findByRole("dialog");
  fireEvent.change(within(dialogo).getByLabelText("Nombre"), { target: { value: "Calle 14" } });
  fireEvent.click(within(dialogo).getByRole("button", { name: "Guardar" }));

  await waitFor(() => expect(renombrarCarpetaMock).toHaveBeenCalledWith(1, "Calle 14"));
});

test("renombrar con el mismo nombre no llama a la API", async () => {
  const { default: MisCorridas } = await import("./MisCorridas");
  render(<MemoryRouter><MisCorridas /></MemoryRouter>);
  await screen.findByText("Calle 13");

  fireEvent.click(screen.getAllByTitle("Renombrar carpeta")[0]);
  // El modal viene precargado con el nombre actual: confirmar sin cambiarlo no debe hacer nada.
  fireEvent.click(await screen.findByRole("button", { name: "Guardar" }));

  await waitFor(() => expect(screen.queryByLabelText("Nombre")).toBeNull());
  expect(renombrarCarpetaMock).not.toHaveBeenCalled();
});

test("la columna Lista distingue una corrida NP de una Principal", async () => {
  const { default: MisCorridas } = await import("./MisCorridas");
  const { listarCorridas } = await import("@/api/corridas");
  (listarCorridas as unknown as { mockResolvedValueOnce: (v: unknown) => void }).mockResolvedValueOnce([
    {
      id: 1, nombre: "lic.xlsx", archivo: "lic.xlsx", creada_en: "2026-07-08T10:00:00",
      estado: "en_revision", modo: "activa", n_items: 2, n_revision: 1, duracion_ms: 1000,
      contractual: 4000000, costo: 3675000, margen: 325000, margen_pct: 0.08125,
      carpeta_id: 1, lista_precios_id: null, lista_nombre: "Principal",
    },
    {
      id: 2, nombre: "np.xlsx", archivo: "np.xlsx", creada_en: "2026-07-28T10:00:00",
      estado: "en_revision", modo: "activa", n_items: 1, n_revision: 0, duracion_ms: 500,
      contractual: 1000, costo: 800, margen: 200, margen_pct: 0.2,
      carpeta_id: 1, lista_precios_id: 2, lista_nombre: "NP Calle 13",
    },
  ]);

  render(<MemoryRouter initialEntries={["/corridas?carpeta=1"]}><MisCorridas /></MemoryRouter>);

  await waitFor(() => expect(screen.getByText("np.xlsx")).toBeTruthy());
  expect(screen.getByText("NP Calle 13")).toBeTruthy();
  const filaPrincipal = screen.getByText("lic.xlsx").closest("tr")!;
  expect(within(filaPrincipal).getByText("Principal")).toBeTruthy();
});
