import { beforeEach, expect, test, vi } from "vitest";

const apiGet = vi.fn();
const apiPut = vi.fn();
const apiPost = vi.fn();
const consumirSse = vi.fn();

vi.mock("./client", () => ({
  apiGet: (...a: unknown[]) => apiGet(...a),
  apiPut: (...a: unknown[]) => apiPut(...a),
  apiPost: (...a: unknown[]) => apiPost(...a),
}));
vi.mock("./corridas", () => ({
  consumirSse: (...a: unknown[]) => consumirSse(...a),
}));

const VACIA = { vigente: null, historial: [] };

beforeEach(() => {
  apiGet.mockReset().mockResolvedValue(VACIA);
  apiPut.mockReset().mockResolvedValue(VACIA);
  apiPost.mockReset().mockResolvedValue(VACIA);
  consumirSse.mockReset().mockResolvedValue(undefined);
});

test("getComposicion pega al GET de la fila", async () => {
  const { getComposicion } = await import("./composicion");
  await getComposicion(7, 3);
  expect(apiGet).toHaveBeenCalledWith("/corridas/7/composicion/3");
});

test("guardarComposicion manda version_base, componentes y supuestos", async () => {
  const { guardarComposicion } = await import("./composicion");
  await guardarComposicion(7, 3, 2,
    [{ codigo: "4279", rendimiento: 0.5 }] as never, true);
  expect(apiPut).toHaveBeenCalledWith("/corridas/7/composicion/3", {
    version_base: 2,
    componentes: [{ codigo: "4279", rendimiento: 0.5 }],
    supuestos_confirmados: true,
  });
});

test("aprobarComposicion manda la identidad del APU", async () => {
  const { aprobarComposicion } = await import("./composicion");
  await aprobarComposicion(7, 3, {
    version_base: 2, codigo: "9001", turno: "DIURNO", nombre: "X", grupo: "G",
    unidad: "M3",
  });
  expect(apiPost).toHaveBeenCalledWith("/corridas/7/composicion/3/aprobar", {
    version_base: 2, codigo: "9001", turno: "DIURNO", nombre: "X", grupo: "G",
    unidad: "M3",
  });
});

test("rechazarComposicion manda el motivo", async () => {
  const { rechazarComposicion } = await import("./composicion");
  await rechazarComposicion(7, 3, 2, "no aplica");
  expect(apiPost).toHaveBeenCalledWith("/corridas/7/composicion/3/rechazar", {
    version_base: 2, motivo: "no aplica",
  });
});

test("generarComposicionStream usa el SSE con POST", async () => {
  const { generarComposicionStream } = await import("./composicion");
  await generarComposicionStream(7, 3, () => {});
  expect(consumirSse).toHaveBeenCalled();
  const [path, init] = consumirSse.mock.calls[0];
  expect(path).toBe("/corridas/7/composicion/3/stream");
  expect((init as { method: string }).method).toBe("POST");
});

test("los eventos del stream llegan al callback con la forma del backend", async () => {
  // `consumirSse` entrega `{ event, data }` en inglés: es el contrato que ya usa
  // `revisarCorridaStream`, no se renombra por capricho.
  consumirSse.mockImplementation(
    async (_p: string, _i: unknown,
           onEvent: (e: { event: string; data: unknown }) => void) => {
      onEvent({ event: "recuperando", data: { n_insumos: 40, n_apus: 3 } });
      onEvent({ event: "lista", data: { version: 1 } });
    },
  );
  const { generarComposicionStream } = await import("./composicion");
  const vistos: string[] = [];
  await generarComposicionStream(7, 3, (e) => vistos.push(e.event));
  expect(vistos).toEqual(["recuperando", "lista"]);
});

test("un error del backend se propaga, no se traga", async () => {
  apiPost.mockRejectedValue(new Error("La corrida está congelada."));
  const { rechazarComposicion } = await import("./composicion");
  await expect(rechazarComposicion(7, 3, 1, "x")).rejects.toThrow(/congelada/);
});
