import { expect, test, vi, beforeEach } from "vitest";

// `descargarCuadro` delega en `descargarArchivo` de client.ts (mismo helper que
// `descargarPlantillaLicitacion`; ver plantillas.descarga.test.ts), que llama al
// `supabase` real para el token -> se mockea solo ese módulo, no todo `@/api/client`.
vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: vi.fn(async () => ({ data: { session: { access_token: "T" } } })),
      signOut: vi.fn(),
    },
  },
}));

beforeEach(() => { vi.restoreAllMocks(); });

test("descargarCuadro usa Bearer y dispara la descarga", async () => {
  const { descargarCuadro } = await import("./corridas");

  const fetchMock = vi.fn(async () => ({
    status: 200, ok: true, blob: async () => new Blob(["x"]),
  })) as unknown as typeof fetch;
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("URL", { createObjectURL: () => "blob:x", revokeObjectURL: () => {} });
  const click = vi.fn();
  vi.spyOn(document, "createElement").mockReturnValue({ click, remove: () => {}, href: "", download: "" } as unknown as HTMLAnchorElement);
  vi.spyOn(document.body, "appendChild").mockImplementation((n) => n as never);

  await descargarCuadro(7);

  const [url, init] = (fetchMock as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
  expect(url).toBe("/api/corridas/7/cuadro");
  expect((init.headers as Record<string, string>).Authorization).toBe("Bearer T");
  expect(click).toHaveBeenCalled();
});
