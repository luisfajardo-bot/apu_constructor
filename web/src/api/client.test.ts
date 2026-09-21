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

test("apiGet adjunta el Bearer del token de sesión", async () => {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify({ ok: 1 }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  const { apiGet } = await import("./client");
  await apiGet("/status");
  const [, init] = fetchMock.mock.calls[0];
  expect((init.headers as Record<string, string>).Authorization).toBe("Bearer TOK");
});

test("401 dispara signOut y lanza", async () => {
  const { supabase } = await import("@/lib/supabase");
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 401 })));
  const { apiGet } = await import("./client");
  await expect(apiGet("/status")).rejects.toThrow();
  expect(supabase.auth.signOut).toHaveBeenCalled();
});

test("mensajeDeError lee detail string, detail objeto y cae al respaldo", async () => {
  const { mensajeDeError } = await import("./client");
  // Caso normal: detail es un string.
  expect(mensajeDeError({ detail: "Sin permisos." }, "respaldo")).toBe("Sin permisos.");
  // El 409 de las filas sin APU: detail es un objeto con mensaje + seqs. Sin esto,
  // `new Error(objeto)` mostraba "[object Object]" y el candado bloqueaba sin explicar.
  expect(
    mensajeDeError({ detail: { mensaje: "2 línea(s) sin APU asignado.", seqs: [1, 7] } }, "respaldo"),
  ).toBe("2 línea(s) sin APU asignado.");
  // El 422 de validación de Pydantic: detail es un array de {loc, msg, type}.
  // Sin este caso caía al respaldo y mostraba "Unprocessable Content".
  expect(
    mensajeDeError({ detail: [{ loc: ["body", "nombre"], msg: "Field required", type: "missing" }] }, "respaldo"),
  ).toBe("Field required");
  // Cuerpo vacío / no-JSON: queda el respaldo (statusText).
  expect(mensajeDeError(null, "Internal Server Error")).toBe("Internal Server Error");
  expect(mensajeDeError({}, "respaldo")).toBe("respaldo");
});

test("un error de la API conserva el status y el `detail` crudo, no solo el texto", async () => {
  // Lo que esto protege: el 409 del armado duplicado trae `corrida_id` en el detail,
  // y con eso la pantalla lleva al usuario a la corrida que YA se está armando. Si
  // `manejar` lanzara un Error pelado, ese id se perdería y el doble clic terminaría
  // en un cartel rojo. El `message` sigue siendo el de siempre.
  const cuerpo = { detail: { mensaje: "Ya se está armando «lic.xlsx».", corrida_id: 42 } };
  vi.stubGlobal("fetch", vi.fn(async () =>
    new Response(JSON.stringify(cuerpo), { status: 409 })));
  const { apiPost, ErrorApi } = await import("./client");

  const e = await apiPost("/corridas", {}).then(() => null, (err) => err);

  expect(e).toBeInstanceOf(ErrorApi);
  expect(e.message).toBe("Ya se está armando «lic.xlsx».");
  expect(e.status).toBe(409);
  expect((e.detail as { corrida_id: number }).corrida_id).toBe(42);
});
