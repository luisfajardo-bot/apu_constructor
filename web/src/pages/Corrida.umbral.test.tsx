/**
 * `aplicarUmbral` (el vecino de `aplicarRebusquedaMarcada`, calcado de
 * `Corrida.rebuscar.test.tsx`): que aplicar mande el id y los seqs correctos, que
 * pinte lo que devuelve el servidor (no lo que mandó el cliente) y cierre el
 * diálogo, y que un error deje todo abierto para reintentar.
 *
 * Archivo aparte (y no `Corrida.test.tsx`) porque necesita ítems candidatos al
 * umbral (en $0, con `precio_contractual` > 0) que el fixture compartido de ese
 * archivo no tiene — agregarlos ahí correría el riesgo de volver "candidata" una
 * fila que otro test de ese archivo da por sentado que no lo es.
 */
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
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
    apu_codigo: "A", apu_nombre: "APU A", status: "auto", confianza: 1,
    precio_contractual: 0, costo_unitario: 0, margen_unitario: 0, margen_pct: 0,
    contractual_total: 0, costo_total: 0, margen_total: 0, costo_manual: false,
    ...p,
  };
}

// item0 queda BAJO cualquier umbral que cubra a item1 también: eso separa "un solo
// candidato marcado" (test A) de "los dos marcados" (test B) con un solo fixture.
const item0 = () => fila({
  seq: 0, descripcion: "Pantalla acustica",
  precio_contractual: 500000, contractual_total: 500000,
});
const item1 = () => fila({
  seq: 1, descripcion: "Otra actividad",
  precio_contractual: 900000, contractual_total: 900000,
});

let modo = "activa";
let estado = "en_revision";
const CORRIDA = () => ({
  id: 1, archivo: "obra.xlsx", estado, modo, duracion_ms: 1000,
  ia_disponible: true, armado: null,
  items: [item0(), item1()],
  totales: { contractual: 1400000, costo: 0, margen: 1400000, margen_pct: 1,
             n_items: 2, n_revision: 0 },
});

const igualarPorUmbral = vi.fn(async () => CORRIDA());

vi.mock("@/api/corridas", () => ({
  getCorrida: vi.fn(async () => CORRIDA()),
  descargarCuadro: vi.fn(),
  congelarCorrida: vi.fn(),
  activarCorrida: vi.fn(),
  revisarCorridaStream: vi.fn(),
  aplicarSugerencias: vi.fn(),
  reanudarArmado: vi.fn(),
  rebuscarApus: vi.fn(),
  aplicarRebusqueda: vi.fn(),
  igualarPorUmbral: (...a: unknown[]) => igualarPorUmbral(...(a as [])),
}));
vi.mock("@/api/autoria", () => ({
  listarApus: vi.fn(async () => ({ items: [], total: 0, limit: 15, offset: 0 })),
}));

beforeEach(() => {
  rol = "editor"; modo = "activa"; estado = "en_revision"; vi.clearAllMocks();
});

/** Abre el diálogo y escribe el umbral. */
async function abrirYEscribirUmbral(umbral: string) {
  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  await screen.findByText("Pantalla acustica");
  fireEvent.click(screen.getByRole("button", { name: /Igualar bajo umbral/i }));
  fireEvent.change(await screen.findByLabelText("Umbral de total contractual"),
    { target: { value: umbral } });
}

test("aplicar manda el id y los seq marcados, pinta lo que devuelve el servidor "
  + "y cierra el diálogo", async () => {
    // Umbral 700000: solo item0 (500000) entra; item1 (900000) queda afuera.
    await abrirYEscribirUmbral("700000");
    const boton = await screen.findByRole("button", { name: /^Igualar 1 línea$/ });

    // costo_total en un valor que no coincida con NINGUNA otra celda de la fila
    // (contractual, unitario, margen): si coincidiera, `findByText` chocaría con
    // más de un elemento.
    igualarPorUmbral.mockResolvedValueOnce({
      ...CORRIDA(),
      items: [{ ...item0(), costo_unitario: 480000, costo_total: 485000 }, item1()],
      igualadas: [0], salteadas: [],
    });
    fireEvent.click(boton);

    await waitFor(() => expect(igualarPorUmbral).toHaveBeenCalledWith(1, 700000, [0]));
    // Se pintó lo que devolvió el servidor (el costo de la fila, antes en $0). Se
    // busca DENTRO de la fila (no con `findByText` a secas): el total "Costo" del
    // encabezado suma lo mismo cuando la otra fila sigue en $0, y colisiona.
    const fila0 = (await screen.findByText("Pantalla acustica")).closest("tr");
    expect(fila0).toBeTruthy();
    expect(within(fila0 as HTMLElement).getByText("$485.000")).toBeTruthy();
    // Y el diálogo se cerró: Radix no monta el contenido con `open=false`.
    expect(screen.queryByLabelText("Umbral de total contractual")).toBeNull();
    expect(toast.success).toHaveBeenCalledWith("1 línea igualada al contractual");
  });

test("el toast de éxito usa el número que devolvió el servidor, no el que se marcó",
  async () => {
    // Umbral 1000000: los dos entran, los dos quedan marcados (nada destildado).
    await abrirYEscribirUmbral("1000000");
    const boton = await screen.findByRole("button", { name: /^Igualar 2 líneas$/ });

    // El servidor solo aplicó una (la otra cambió entre la previa y el aplicar):
    // si el toast leyera `seqs.length` del cliente, diría "2 líneas".
    igualarPorUmbral.mockResolvedValueOnce({
      ...CORRIDA(), igualadas: [0], salteadas: [1],
    });
    fireEvent.click(boton);

    await waitFor(() => expect(igualarPorUmbral).toHaveBeenCalledWith(1, 1000000, [0, 1]));
    expect(toast.success).toHaveBeenCalledWith("1 línea igualada al contractual");
  });

test("avisa (en singular) cuando el servidor salteó una línea que ya no era candidata",
  async () => {
    await abrirYEscribirUmbral("1000000");
    const boton = await screen.findByRole("button", { name: /^Igualar 2 líneas$/ });

    igualarPorUmbral.mockResolvedValueOnce({
      ...CORRIDA(), igualadas: [0], salteadas: [1],
    });
    fireEvent.click(boton);

    await waitFor(() => expect(toast.warning).toHaveBeenCalledWith(
      expect.stringContaining("1 línea sin tocar: cambió")));
  });

test("avisa (en plural) cuando el servidor salteó varias líneas", async () => {
  // Un tercer ítem candidato solo para este caso: dos salteadas de una vez.
  const item2 = fila({
    seq: 2, descripcion: "Tercera actividad",
    precio_contractual: 300000, contractual_total: 300000,
  });
  const { getCorrida } = await import("@/api/corridas");
  vi.mocked(getCorrida).mockResolvedValueOnce(
    { ...CORRIDA(), items: [item0(), item1(), item2] } as never);

  await abrirYEscribirUmbral("1000000");
  const boton = await screen.findByRole("button", { name: /^Igualar 3 líneas$/ });

  igualarPorUmbral.mockResolvedValueOnce({
    ...CORRIDA(), igualadas: [0], salteadas: [1, 2],
  });
  fireEvent.click(boton);

  await waitFor(() => expect(toast.warning).toHaveBeenCalledWith(
    expect.stringContaining("2 líneas sin tocar: cambiaron")));
});

test("si aplicar falla lo dice y deja el diálogo abierto para reintentar", async () => {
  igualarPorUmbral.mockRejectedValueOnce(new Error("La corrida está congelada."));
  await abrirYEscribirUmbral("700000");
  const boton = await screen.findByRole("button", { name: /^Igualar 1 línea$/ });

  fireEvent.click(boton);

  await waitFor(() => expect(toast.error).toHaveBeenCalledWith("La corrida está congelada."));
  // El diálogo NO se cierra: se puede reintentar sin volver a escribir el umbral.
  expect(screen.getByLabelText("Umbral de total contractual")).toBeTruthy();
  expect(screen.getByRole("button", { name: /^Igualar 1 línea$/ })).toBeTruthy();
});

test("cerrar el diálogo (Escape o clic afuera, vía onOpenChange) y volver a abrirlo "
  + "conserva el umbral tipeado", async () => {
  // El diálogo está SIEMPRE montado (Corrida.tsx no lo envuelve en `{abierto && ...}`):
  // cerrar y reabrir no debe perder el `useState` del campo. Se simula el cierre por
  // Escape/clic-afuera con `onOpenChange`, no con el botón "Cerrar", que es el gesto
  // que el hallazgo original señaló como el que se pasaba por alto.
  await abrirYEscribirUmbral("700000");
  expect((await screen.findByLabelText("Umbral de total contractual") as HTMLInputElement)
    .value).toBe("700000");

  // Radix dispara `onOpenChange(false)` con Escape; en jsdom alcanza con el evento.
  fireEvent.keyDown(document, { key: "Escape", code: "Escape" });
  await waitFor(() =>
    expect(screen.queryByLabelText("Umbral de total contractual")).toBeNull());

  fireEvent.click(screen.getByRole("button", { name: /Igualar bajo umbral/i }));
  expect((await screen.findByLabelText("Umbral de total contractual") as HTMLInputElement)
    .value).toBe("700000");
});
