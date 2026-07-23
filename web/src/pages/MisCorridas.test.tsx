import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test, vi, beforeEach, afterEach } from "vitest";
import { colorSigno } from "./MisCorridas";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ perfil: { rol: "admin", email: "a@b.c", nombre: "A" } }),
}));

vi.mock("@/api/corridas", () => ({
  listarCorridas: vi.fn(async () => [{
    id: 1, nombre: "lic.xlsx", archivo: "lic.xlsx", creada_en: "2026-07-08T10:00:00",
    estado: "en_revision", modo: "activa", n_items: 2, n_revision: 1, duracion_ms: 1000,
    contractual: 4000000, costo: 3675000, margen: 325000, margen_pct: 0.08125,
    carpeta_id: 1,
  }]),
  eliminarCorrida: vi.fn(),
  renombrarCorrida: vi.fn(async () => ({})),
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
  crearCarpeta: vi.fn(),
  renombrarCarpeta: vi.fn(),
  borrarCarpeta: vi.fn(),
  moverCorrida: vi.fn(async () => ({})),
  moverCarpeta: vi.fn(async () => ({})),
}));

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
  const { renombrarCorrida } = await import("@/api/corridas");

  const promptSpy = vi.spyOn(window, "prompt").mockReturnValue("Obra Norte");

  render(
    <MemoryRouter initialEntries={["/corridas?carpeta=1"]}>
      <MisCorridas />
    </MemoryRouter>
  );

  await waitFor(() => expect(screen.getByText("lic.xlsx")).toBeTruthy());
  const row = screen.getByText("lic.xlsx").closest("tr")!;
  const btnRenombrar = within(row).getByRole("button", { name: /renombrar/i });
  fireEvent.click(btnRenombrar);

  await waitFor(() => {
    expect(renombrarCorrida).toHaveBeenCalledWith(1, "Obra Norte");
  });

  promptSpy.mockRestore();
});
