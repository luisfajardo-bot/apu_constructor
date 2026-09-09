/**
 * La pantalla de una corrida que TODAVÍA se está armando.
 *
 * El armado dejó de correr dentro de la petición (1900 líneas son horas y las
 * instancias de Render viven 30 minutos): ahora lo toma un hilo del servidor desde una
 * cola en la base, y esta pantalla lo mira por el poll de `GET /corridas/{id}`. Lo que
 * se prueba acá es eso: que el progreso se VEA, que una corrida que se rindió diga por
 * qué y se pueda reintentar, y que el poll no quede latiendo sobre un estado dormido.
 *
 * Va aparte de `Corrida.test.tsx` porque estos casos usan temporizadores falsos y
 * mezclarlos con `findBy*` (que también son timers) hace que los otros 20 tests del
 * archivo dependan de en qué orden corren.
 */
import { render, screen, fireEvent, act } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

vi.mock("react-router-dom", () => ({ useParams: () => ({ id: "1" }) }));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn() },
}));
let rol: "consulta" | "editor" | "admin" = "editor";
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ perfil: { rol } }) }));
// TablaItems -> BuscadorApu -> @/api/autoria: se mockea solo para no cargar el módulo real.
vi.mock("@/api/autoria", () => ({
  listarApus: vi.fn(async () => ({ items: [], total: 0, limit: 15, offset: 0 })),
}));
vi.mock("@/api/corridas", () => ({
  getCorrida: vi.fn(),
  descargarCuadro: vi.fn(),
  congelarCorrida: vi.fn(),
  activarCorrida: vi.fn(),
  revisarCorridaStream: vi.fn(),
  aplicarSugerencias: vi.fn(),
  reanudarArmado: vi.fn(async () => ({})),
}));

import Corrida from "./Corrida";
import { getCorrida, reanudarArmado } from "@/api/corridas";

const fila = (seq: number, descripcion: string) => ({
  seq, item: String(seq), descripcion, unidad: "M3", cantidad: 1,
  apu_codigo: "A", apu_nombre: "APU A", status: "auto", confianza: 1,
  precio_contractual: 0, costo_unitario: 0, margen_unitario: 0, margen_pct: 0,
  contractual_total: 0, costo_total: 0, margen_total: 0, costo_manual: false,
  revision: null,
});

const BASE = {
  id: 1, nombre: "lic", archivo: "obra.xlsx", modo: "activa", duracion_ms: null,
  carpeta_id: 1, lista_precios_id: null, lista_nombre: "Principal",
  ia_disponible: true, estado: "armando", armado: null as unknown,
  items: [fila(0, "Excavación")],
  totales: { contractual: 0, costo: 0, margen: 0, margen_pct: 0, n_items: 1, n_revision: 0 },
};

const armando = (p: Partial<{ hechos: number; total: number; posicion_en_cola: number }>) => ({
  ...BASE,
  estado: "armando",
  armado: { hechos: 0, total: 1939, posicion_en_cola: 0, intentos: 1, ultimo_error: null, ...p },
});

const MOTIVO =
  "El armado se interrumpió 3 veces seguidas. Puede ser un reinicio del servidor o un "
  + "problema con el archivo. Reintentá; si vuelve a pasar, avisá. "
  + "Último error: RuntimeError: connection reset by peer";

const detenida = (ultimo_error: string | null = MOTIVO) => ({
  ...BASE,
  estado: "armado_detenido",
  armado: { hechos: 290, total: 1939, posicion_en_cola: 0, intentos: 4, ultimo_error },
});

/** Monta la pantalla y deja resuelto el primer `getCorrida`. */
async function montar() {
  render(<Corrida />);
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
}

beforeEach(() => {
  rol = "editor";
  vi.useFakeTimers();
  vi.mocked(getCorrida).mockReset();
  vi.mocked(reanudarArmado).mockClear();
});
afterEach(() => { vi.useRealTimers(); });

// ─── Progreso ────────────────────────────────────────────────────────────────

test("armándose, dice cuántas líneas lleva de cuántas", async () => {
  vi.mocked(getCorrida).mockResolvedValue(armando({ hechos: 290 }) as never);
  await montar();

  expect(screen.getByText("Armando: 290 de 1939")).toBeTruthy();
});

test("esperando turno, dice el puesto en la cola y NO un progreso en cero", async () => {
  // Un "Armando: 0 de 1939" que no se mueve durante media hora parece una corrida
  // colgada. Estar en la cola es un estado distinto y se dice distinto.
  vi.mocked(getCorrida).mockResolvedValue(armando({ posicion_en_cola: 2 }) as never);
  await montar();

  expect(screen.getByText("En espera: puesto 2 en la cola")).toBeTruthy();
  expect(screen.queryByText(/Armando: 0 de/)).toBeNull();
});

test("terminada de armar, no queda ningún cartel de progreso", async () => {
  vi.mocked(getCorrida).mockResolvedValue(
    { ...BASE, estado: "en_revision", armado: null } as never);
  await montar();

  expect(screen.queryByText(/Armando:/)).toBeNull();
  expect(screen.queryByText(/En espera/)).toBeNull();
});

// ─── Poll ────────────────────────────────────────────────────────────────────

test("armándose, se relee sola cada 5 s", async () => {
  vi.mocked(getCorrida).mockResolvedValue(armando({ hechos: 1 }) as never);
  await montar();
  expect(vi.mocked(getCorrida)).toHaveBeenCalledTimes(1);

  // A los 2 s todavía no: el armado dura horas, el poll no tiene por qué ser nervioso.
  await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
  expect(vi.mocked(getCorrida)).toHaveBeenCalledTimes(1);

  await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
  expect(vi.mocked(getCorrida)).toHaveBeenCalledTimes(2);
});

test("una corrida detenida NO se pollea: ese estado solo lo mueve el botón", async () => {
  vi.mocked(getCorrida).mockResolvedValue(detenida() as never);
  await montar();
  expect(vi.mocked(getCorrida)).toHaveBeenCalledTimes(1);

  await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
  expect(vi.mocked(getCorrida)).toHaveBeenCalledTimes(1);
});

test("al terminar de armarse, el poll se apaga", async () => {
  vi.mocked(getCorrida)
    .mockResolvedValueOnce(armando({ hechos: 1938 }) as never)
    .mockResolvedValue({ ...BASE, estado: "en_revision", armado: null } as never);
  await montar();

  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(vi.mocked(getCorrida)).toHaveBeenCalledTimes(2);

  // Ya no está 'armando': no se encadena otro ciclo.
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
  expect(vi.mocked(getCorrida)).toHaveBeenCalledTimes(2);
});

// ─── Armado detenido ─────────────────────────────────────────────────────────

test("detenida: el motivo en español manda y lo técnico va aparte", async () => {
  vi.mocked(getCorrida).mockResolvedValue(detenida() as never);
  await montar();

  const humano = screen.getByText(/Reintentá; si vuelve a pasar/);
  // La cola técnica NO puede ser el mensaje: va en su propio nodo, secundario.
  expect(humano.textContent).not.toMatch(/RuntimeError/);
  const tecnico = screen.getByText(/RuntimeError: connection reset by peer/);
  expect(tecnico).not.toBe(humano);
  // Y se dice dónde se quedó, que es lo que explica una corrida a medias.
  expect(screen.getByText(/290 de 1939/)).toBeTruthy();
});

test("detenida sin cola técnica: se muestra el motivo entero igual", async () => {
  vi.mocked(getCorrida).mockResolvedValue(
    detenida("La corrida no tiene guardadas las líneas a armar.") as never);
  await montar();

  expect(screen.getByText("La corrida no tiene guardadas las líneas a armar.")).toBeTruthy();
});

test("detenida: Reintentar armado la reencola y vuelve a leer la corrida", async () => {
  vi.mocked(getCorrida).mockResolvedValue(detenida() as never);
  await montar();

  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: /reintentar armado/i }));
    await vi.advanceTimersByTimeAsync(0);
  });

  expect(vi.mocked(reanudarArmado)).toHaveBeenCalledWith(1);
  // Refrescar es parte del reintento: si no, la pantalla se queda en "detenida" y el
  // poll —que solo arranca con la corrida 'armando'— nunca vuelve a la vida.
  expect(vi.mocked(getCorrida)).toHaveBeenCalledTimes(2);
});

test("detenida: aunque reanudar falle, la pantalla se relee", async () => {
  // El caso real: otra persona ya la reanudó y el backend contesta 409. Lo que hay
  // que hacer es releer, no dejar la pantalla mintiendo.
  vi.mocked(getCorrida).mockResolvedValue(detenida() as never);
  vi.mocked(reanudarArmado).mockRejectedValueOnce(
    new Error("La corrida ya está en la cola de armado."));
  await montar();

  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: /reintentar armado/i }));
    await vi.advanceTimersByTimeAsync(0);
  });

  expect(vi.mocked(getCorrida)).toHaveBeenCalledTimes(2);
});

test("sin rol de editor no se ofrece reintentar el armado", async () => {
  rol = "consulta";
  vi.mocked(getCorrida).mockResolvedValue(detenida() as never);
  await montar();

  // El motivo sí se ve: entender por qué no avanza no necesita permisos.
  expect(screen.getByText(/Reintentá; si vuelve a pasar/)).toBeTruthy();
  expect(screen.queryByRole("button", { name: /reintentar armado/i })).toBeNull();
});
