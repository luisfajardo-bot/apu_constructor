import { render, screen, fireEvent } from "@testing-library/react";
import { expect, test, vi } from "vitest";

// `Link` entra al mock porque el encabezado ahora enlaza a las distancias del
// proyecto; sin el stub, el componente revienta con Link undefined.
vi.mock("react-router-dom", () => ({
  useParams: () => ({ id: "1" }),
  Link: ({ to, children, ...resto }: { to: string; children: React.ReactNode }) => (
    <a href={to} {...resto}>{children}</a>
  ),
}));
vi.mock("@/lib/armado", () => ({
  useArmadoVivo: () => ({ corridaId: null, estado: "idle", filas: [], total: 0 }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
// Corrida ahora usa useAuth() para calcular `puedeEditar` (rol -> TablaItems).
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ perfil: { rol: "editor" } }) }));

function fila(p: Record<string, unknown>) {
  return {
    seq: 0, item: "1", descripcion: "X", unidad: "M3", cantidad: 1,
    apu_codigo: "A", apu_nombre: "APU A", status: "auto", confianza: 1,
    precio_contractual: 0, costo_unitario: 0, margen_unitario: 0, margen_pct: 0,
    contractual_total: 0, costo_total: 0, margen_total: 0, ...p,
  };
}

const CORRIDA = {
  id: 1, archivo: "obra.xlsx", estado: "en_revision", modo: "activa", duracion_ms: 1000,
  items: [
    fila({ seq: 0, descripcion: "Excavación", unidad: "M3", contractual_total: 1000 }),
    fila({ seq: 1, descripcion: "Concreto", unidad: "M2", contractual_total: 500 }),
  ],
  totales: { contractual: 1500, costo: 0, margen: 1500, margen_pct: 1, n_items: 2, n_revision: 0 },
};

vi.mock("@/api/corridas", () => ({
  getCorrida: vi.fn(async () => CORRIDA),
  descargarCuadro: vi.fn(),
  congelarCorrida: vi.fn(),
  activarCorrida: vi.fn(),
}));
// TablaItems importa BuscadorApu -> @/api/autoria -> @/api/client -> @/lib/supabase,
// que crea el cliente de Supabase al cargar el módulo (falla sin envs en test). Se
// mockea aquí (igual que en TablaItems.test.tsx) solo para evitar esa carga real.
vi.mock("@/api/autoria", () => ({
  listarApus: vi.fn(async () => ({ items: [], total: 0, limit: 15, offset: 0 })),
}));

test("al filtrar por Und, los totales y el contador recalculan sobre lo filtrado", async () => {
  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);

  // Carga async de la corrida (aparecen las dos filas)
  await screen.findByText("Excavación");
  expect(screen.getByText("Concreto")).toBeTruthy();

  // Filtra a M2 -> queda 1 de 2 ítems
  fireEvent.change(screen.getByLabelText("Filtrar Und"), { target: { value: "M2" } });
  expect(screen.queryByText("Excavación")).toBeNull();
  expect(screen.getByText(/1 de 2 ítems/)).toBeTruthy();
});

test("muestra la lista de precios de la corrida cuando no es Principal", async () => {
  const { default: Corrida } = await import("./Corrida");
  const { getCorrida } = await import("@/api/corridas");
  (getCorrida as unknown as { mockResolvedValueOnce: (v: unknown) => void }).mockResolvedValueOnce({
    ...CORRIDA,
    lista_precios_id: 2,
    lista_nombre: "NP Calle 13",
  });

  render(<Corrida />);

  await screen.findByText("Excavación");
  expect(screen.getByText("NP Calle 13")).toBeTruthy();
});

test("con la corrida armándose (otra pestaña/F5), el botón Agregar líneas no aparece", async () => {
  const { default: Corrida } = await import("./Corrida");
  const { getCorrida } = await import("@/api/corridas");
  (getCorrida as unknown as { mockResolvedValueOnce: (v: unknown) => void }).mockResolvedValueOnce({
    ...CORRIDA,
    estado: "armando",
    modo: "activa",
  });

  render(<Corrida />);

  await screen.findByText("Excavación");
  expect(screen.queryByText("Agregar líneas")).toBeNull();
});

test("con la corrida en_revision, el botón Agregar líneas sí aparece", async () => {
  const { default: Corrida } = await import("./Corrida");
  const { getCorrida } = await import("@/api/corridas");
  (getCorrida as unknown as { mockResolvedValueOnce: (v: unknown) => void }).mockResolvedValueOnce({
    ...CORRIDA,
    estado: "en_revision",
    modo: "activa",
  });

  render(<Corrida />);

  await screen.findByText("Excavación");
  expect(screen.getByText("Agregar líneas")).toBeTruthy();
});


test("desde la corrida se puede ir a las distancias del proyecto", async () => {
  const { getCorrida } = await import("@/api/corridas");
  (getCorrida as unknown as { mockResolvedValueOnce: (v: unknown) => void }).mockResolvedValueOnce({
    ...CORRIDA, carpeta_id: 7,
    transporte: { km_botadero: 34, km_mezclas: 28, km_granulares: 32,
                  peaje_aplica: true, peaje_valor: 12400, ajustes: 0 },
  });
  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  const enlace = await screen.findByRole("link", { name: /botadero 34 km/i });
  expect(enlace.getAttribute("href")).toBe("/proyecto/7/distancias");
});

test("sin distancias cargadas, la corrida igual ofrece ir a definirlas", async () => {
  const { getCorrida } = await import("@/api/corridas");
  (getCorrida as unknown as { mockResolvedValueOnce: (v: unknown) => void }).mockResolvedValueOnce({
    ...CORRIDA, carpeta_id: 7, transporte: null,
  });
  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  // Es justo cuando MAS hace falta el acceso: no hay distancias que mostrar todavia.
  const enlace = await screen.findByRole("link", { name: /definir distancias del proyecto/i });
  expect(enlace.getAttribute("href")).toBe("/proyecto/7/distancias");
});
