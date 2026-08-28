import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test, vi } from "vitest";
// Los imports van ARRIBA. Estaban adentro de cada test (`await import("./MisCorridas")`)
// y el costo de transformar el módulo se le cobraba al presupuesto de 5 s de cada uno:
// medido en otro archivo con la misma forma, 1682-2232 ms de los 5000. `vi.mock` lo
// hoistea vitest antes de los imports, así que los mocks de abajo siguen aplicándose.
import MisCorridas, { claseSigno } from "./MisCorridas";
import { moverCorrida } from "@/api/carpetas";
import { listarCorridas, renombrarCorrida } from "@/api/corridas";

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

// Este test SÍ se modificó, y es el único de la rama. Assertaba los hex literales
// ("#276749" / "#c53030"), que son exactamente lo que esta task viene a eliminar: un
// test que codifica el token viejo tiene que seguir al token. El contrato lógico que
// verifica es idéntico — >= 0 positivo, < 0 negativo, null sin clase — y el color real
// lo verifica scripts/verificar_contraste.py contra WCAG.
test("claseSigno: positivo, negativo, y sin clase si es null", () => {
  expect(claseSigno(10)).toBe("text-margen-pos");
  expect(claseSigno(0)).toBe("text-margen-pos");
  expect(claseSigno(-5)).toBe("text-margen-neg");
  expect(claseSigno(null)).toBeUndefined();
});

test("MisCorridas muestra contractual, costo, dif y margen % formateados (dentro de carpeta)", async () => {
  render(<MemoryRouter initialEntries={["/corridas?carpeta=1"]}><MisCorridas /></MemoryRouter>);
  await waitFor(() => expect(screen.getByText("$4.000.000")).toBeTruthy());
  expect(screen.getByText("$3.675.000")).toBeTruthy();
  expect(screen.getByText("$325.000")).toBeTruthy();
  expect(screen.getByText("8.1%")).toBeTruthy();
});

test("MisCorridas: root muestra carpeta y oculta corridas; entrando a carpeta las muestra", async () => {

  // Root: carpeta visible, dinero de la corrida no visible
  const { unmount } = render(<MemoryRouter initialEntries={["/corridas"]}><MisCorridas /></MemoryRouter>);
  await waitFor(() => expect(screen.getByText("Calle 13")).toBeTruthy());
  expect(screen.queryByText("$4.000.000")).toBeNull();
  unmount();

  // Con carpeta=1: dinero de la corrida visible
  render(<MemoryRouter initialEntries={["/corridas?carpeta=1"]}><MisCorridas /></MemoryRouter>);
  await waitFor(() => expect(screen.getByText("$4.000.000")).toBeTruthy());
});

test("Mover corrida: al hacer clic en 'Mover' y elegir opción 1, llama moverCorrida(1, destinoId)", async () => {

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

test("la columna Lista distingue una corrida NP de una Principal", async () => {
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

// El enlace a las distancias del proyecto vivía SOLO en la fila de la lista de
// subcarpetas, o sea un nivel arriba: al entrar al proyecto desaparecía, y ahí es
// justo donde el usuario trabaja con sus corridas. Lo reportó él, no un test.
test("dentro de un proyecto (nivel 1) hay acceso a sus distancias", async () => {
  render(<MemoryRouter initialEntries={["/corridas?carpeta=1"]}><MisCorridas /></MemoryRouter>);
  const enlace = await screen.findByRole("link", { name: /distancias/i });
  expect(enlace.getAttribute("href")).toBe("/proyecto/1/distancias");
});

test("dentro de una subcarpeta (nivel 2) NO se ofrecen distancias: son del proyecto", async () => {
  render(<MemoryRouter initialEntries={["/corridas?carpeta=2"]}><MisCorridas /></MemoryRouter>);
  await waitFor(() => expect(screen.getByText("Lote 3")).toBeTruthy());
  expect(screen.queryByRole("link", { name: /distancias/i })).toBeNull();
});
