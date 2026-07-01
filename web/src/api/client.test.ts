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
