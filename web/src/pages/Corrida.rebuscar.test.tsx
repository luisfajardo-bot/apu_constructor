import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { toast } from "sonner";      // el mock de abajo; sirve para afirmar sobre él

vi.mock("react-router-dom", () => ({
  useParams: () => ({ id: "1" }),
  useNavigate: () => vi.fn(),
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn() },
}));
let rol: "consulta" | "editor" | "admin" = "editor";
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ perfil: { rol } }) }));

function fila(p: Record<string, unknown>) {
  return {
    seq: 0, item: "1", descripcion: "X", unidad: "M3", cantidad: 1,
    apu_codigo: null, apu_nombre: "(sin base — armar manual)", status: "new",
    confianza: 0, precio_contractual: 900000, costo_unitario: 0, margen_unitario: 0,
    margen_pct: 0, contractual_total: 0, costo_total: 0, margen_total: 0, ...p,
  };
}

let modo = "activa";
let estado = "en_revision";
const CORRIDA = () => ({
  id: 1, archivo: "obra.xlsx", estado, modo, duracion_ms: 1000,
  ia_disponible: true, armado: null,
  items: [fila({ seq: 0, descripcion: "Pantalla acustica" })],
  totales: { contractual: 900000, costo: 0, margen: 900000, margen_pct: 1,
             n_items: 1, n_revision: 0 },
});

const PREVIA = {
  corrida_id: 1, escaneadas: 1,
  propuestas: [{
    seq: 0, item: "1", descripcion: "Pantalla acustica", unidad: "M2", cantidad: 10,
    apu_actual: null,
    apu_propuesto: { codigo: "A9", nombre: "PANTALLA ACUSTICA", turno: "DIURNO" },
    score: 0.98, status: "auto", explicacion: "Coincidencia directa (98%).",
    precio_contractual: 900000, costo_unitario: 700000, margen_unitario: 200000,
    margen_pct: 22.2, sin_apu: true,
  }],
};

const APLICADA = () => ({
  ...CORRIDA(),
  items: [fila({ seq: 0, descripcion: "Pantalla acustica", apu_codigo: "A9",
                 apu_nombre: "PANTALLA ACUSTICA", status: "auto",
                 costo_unitario: 700000 })],
  rebusqueda: { aplicadas: [0], salteadas: [] },
});

const rebuscarApus = vi.fn(async () => PREVIA);
const aplicarRebusqueda = vi.fn(async () => APLICADA());

vi.mock("@/api/corridas", () => ({
  getCorrida: vi.fn(async () => CORRIDA()),
  descargarCuadro: vi.fn(),
  congelarCorrida: vi.fn(),
  activarCorrida: vi.fn(),
  revisarCorridaStream: vi.fn(),
  aplicarSugerencias: vi.fn(),
  reanudarArmado: vi.fn(),
  rebuscarApus: (...a: unknown[]) => rebuscarApus(...(a as [])),
  aplicarRebusqueda: (...a: unknown[]) => aplicarRebusqueda(...(a as [])),
}));
vi.mock("@/api/autoria", () => ({
  listarApus: vi.fn(async () => ({ items: [], total: 0, limit: 15, offset: 0 })),
}));

beforeEach(() => {
  rol = "editor"; modo = "activa"; estado = "en_revision"; vi.clearAllMocks();
});

test("el botón pide la previa y abre el diálogo con las propuestas", async () => {
  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  await screen.findByText("Pantalla acustica");

  fireEvent.click(screen.getByRole("button", { name: /Volver a buscar APU/ }));

  await waitFor(() => expect(rebuscarApus).toHaveBeenCalledWith(1));
  expect(await screen.findByText(/A9/)).toBeTruthy();
  // La fila viene sin APU: se marca sola.
  expect((screen.getByLabelText("Marcar línea 1") as HTMLInputElement).checked)
    .toBe(true);
});

test("aplicar manda los seq marcados y pinta la corrida que devuelve el servidor",
  async () => {
    const { default: Corrida } = await import("./Corrida");
    render(<Corrida />);
    await screen.findByText("Pantalla acustica");
    fireEvent.click(screen.getByRole("button", { name: /Volver a buscar APU/ }));
    await screen.findByText(/A9/);

    fireEvent.click(screen.getByRole("button", { name: /Aplicar 1 cambio/ }));

    await waitFor(() => expect(aplicarRebusqueda).toHaveBeenCalledWith(1, [0]));
    // La tabla se actualiza con la respuesta, sin volver a pedir la corrida.
    expect(await screen.findByText("A9")).toBeTruthy();
  });

test("en una corrida congelada el botón no está", async () => {
  modo = "congelada";
  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  await screen.findByText("Pantalla acustica");
  expect(screen.queryByRole("button", { name: /Volver a buscar APU/ })).toBeNull();
});

test("sin rol editor el botón no está", async () => {
  rol = "consulta";
  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  await screen.findByText("Pantalla acustica");
  expect(screen.queryByRole("button", { name: /Volver a buscar APU/ })).toBeNull();
});

test("con el armado a medias el botón no está", async () => {
  // El backend lo rechaza con un 400 mientras el plan no termine: ofrecer un botón
  // que solo sabe fallar es peor que no ofrecerlo. `armado_detenido` cuenta igual
  // que `armando` — es el estado en el que quedó un armado que se rindió.
  estado = "armado_detenido";
  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  await screen.findByText("Pantalla acustica");
  expect(screen.queryByRole("button", { name: /Volver a buscar APU/ })).toBeNull();
});

test("si aplicar falla lo dice y deja el diálogo abierto para reintentar", async () => {
  aplicarRebusqueda.mockRejectedValueOnce(new Error("La corrida está congelada."));
  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  await screen.findByText("Pantalla acustica");
  fireEvent.click(screen.getByRole("button", { name: /Volver a buscar APU/ }));
  await screen.findByText(/A9/);

  fireEvent.click(screen.getByRole("button", { name: /Aplicar 1 cambio/ }));

  await waitFor(() => expect(toast.error).toHaveBeenCalledWith("La corrida está congelada."));
  // La previa NO se cierra: el usuario puede reintentar sin volver a buscar, y el
  // botón tiene que quedar habilitado de nuevo (el `finally` limpia el flag).
  expect(screen.getByRole("button", { name: /Aplicar 1 cambio/ })).toBeTruthy();
});

test("avisa cuando el servidor salteó líneas que cambiaron", async () => {
  aplicarRebusqueda.mockResolvedValueOnce({
    ...APLICADA(), rebusqueda: { aplicadas: [], salteadas: [0] },
  });
  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  await screen.findByText("Pantalla acustica");
  fireEvent.click(screen.getByRole("button", { name: /Volver a buscar APU/ }));
  await screen.findByText(/A9/);

  fireEvent.click(screen.getByRole("button", { name: /Aplicar 1 cambio/ }));

  await waitFor(() => expect(toast.warning).toHaveBeenCalledWith(
    expect.stringContaining("1 línea cambió mientras mirabas la propuesta")));
});
