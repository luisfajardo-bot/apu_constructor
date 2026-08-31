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
  // Cuerpo vacío / no-JSON: queda el respaldo (statusText).
  expect(mensajeDeError(null, "Internal Server Error")).toBe("Internal Server Error");
  expect(mensajeDeError({}, "respaldo")).toBe("respaldo");
});
