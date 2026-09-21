import { afterEach, expect, test, vi } from "vitest";

vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: vi.fn(async () => ({ data: { session: { access_token: "TOK" } } })),
      signOut: vi.fn(async () => ({})),
    },
  },
}));

afterEach(() => vi.restoreAllMocks());

// Arma el cuerpo de un stream SSE a partir de bloques "event: X\ndata: {...}".
function sse(...bloques: string[]): string {
  return bloques.join("\n\n") + "\n\n";
}

const VEREDICTO_OK = {
  seq: 1, dictamen: "ok", apu_sugerido: null, turno_sugerido: null,
  confianza: 0, justificacion: "Sin objeciones en el barrido.", nivel: "barrido",
};
const VEREDICTO_CAMBIAR = {
  seq: 2, dictamen: "cambiar", apu_sugerido: "999", turno_sugerido: "DIURNO",
  confianza: 0.8, justificacion: "Otro candidato encaja mejor.", nivel: "profundo",
};
const RESUMEN_DONE = { total: 2, ok: 1, dudoso: 0, cambiar: 1, sin_apu: 0, sin_veredicto: 0 };

test("revisarCorridaStream llama a onVeredicto por cada fila y resuelve con el resumen del done", async () => {
  const body = sse(
    'event: started\ndata: {"total":2}',
    `event: veredicto\ndata: ${JSON.stringify({ seq: 1, veredicto: VEREDICTO_OK })}`,
    `event: veredicto\ndata: ${JSON.stringify({ seq: 2, veredicto: VEREDICTO_CAMBIAR })}`,
    `event: done\ndata: ${JSON.stringify(RESUMEN_DONE)}`,
  );
  vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { status: 200 })));
  const { revisarCorridaStream } = await import("./corridas");

  const onVeredicto = vi.fn();
  const resumen = await revisarCorridaStream(7, onVeredicto);

  expect(onVeredicto).toHaveBeenCalledTimes(2);
  expect(onVeredicto).toHaveBeenNthCalledWith(1, VEREDICTO_OK);
  expect(onVeredicto).toHaveBeenNthCalledWith(2, VEREDICTO_CAMBIAR);
  expect(resumen).toEqual(RESUMEN_DONE);
});

test("revisarCorridaStream reporta 'barriendo' (progreso por lote) vía onProgreso", async () => {
  const body = sse(
    'event: started\ndata: {"total":2}',
    'event: barriendo\ndata: {"lote":1,"lotes":1}',
    'event: barrido\ndata: {"revisar":0,"sin_respuesta":[]}',
    `event: veredicto\ndata: ${JSON.stringify({ seq: 1, veredicto: VEREDICTO_OK })}`,
    `event: done\ndata: ${JSON.stringify({ total: 1, ok: 1, dudoso: 0, cambiar: 0, sin_apu: 0, sin_veredicto: 0 })}`,
  );
  vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { status: 200 })));
  const { revisarCorridaStream } = await import("./corridas");

  const onProgreso = vi.fn();
  await revisarCorridaStream(7, vi.fn(), onProgreso);

  expect(onProgreso).toHaveBeenCalledWith({ evento: "started", total: 2 });
  expect(onProgreso).toHaveBeenCalledWith({ evento: "barriendo", lote: 1, lotes: 1 });
  expect(onProgreso).toHaveBeenCalledWith({ evento: "barrido", revisar: 0, sin_respuesta: [] });
});

test("un evento error en el stream rechaza con el mensaje del backend", async () => {
  const body = sse(
    'event: started\ndata: {"total":1}',
    'event: error\ndata: {"detail":"La revisión con IA necesita ANTHROPIC_API_KEY en el servidor."}',
  );
  vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { status: 200 })));
  const { revisarCorridaStream } = await import("./corridas");

  await expect(revisarCorridaStream(7, vi.fn())).rejects.toThrow(
    "La revisión con IA necesita ANTHROPIC_API_KEY en el servidor.",
  );
});

test("un stream que termina sin done no resuelve en silencio", async () => {
  const body = sse(
    'event: started\ndata: {"total":1}',
    `event: veredicto\ndata: ${JSON.stringify({ seq: 1, veredicto: VEREDICTO_OK })}`,
  );
  vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { status: 200 })));
  const { revisarCorridaStream } = await import("./corridas");

  await expect(revisarCorridaStream(7, vi.fn())).rejects.toThrow();
});

test("aplicarSugerencias manda seqs vacío + asignaciones al confirmar-lote", async () => {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify({ id: 7 }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  const { aplicarSugerencias } = await import("./corridas");

  const asignaciones = [{ seq: 2, apu_codigo: "999", shift: "DIURNO" }];
  await aplicarSugerencias(7, asignaciones);

  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe("/api/corridas/7/items/confirmar-lote");
  expect(init?.method).toBe("POST");
  expect(JSON.parse(init?.body as string)).toEqual({ seqs: [], asignaciones });
});
