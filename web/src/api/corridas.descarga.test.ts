import { expect, test, vi, beforeEach } from "vitest";

vi.mock("@/api/client", () => ({
  authHeader: vi.fn(async () => ({ Authorization: "Bearer T" })),
  apiGet: vi.fn(), apiPost: vi.fn(), apiDelete: vi.fn(),
}));

beforeEach(() => { vi.restoreAllMocks(); });

test("descargarCuadro usa Bearer y dispara la descarga", async () => {
  // Importar antes de stubear `URL`: el module runner de Vitest usa el `URL`
  // global de Node para resolver el import dinámico, así que el stub debe
  // instalarse después de que el módulo ya esté cargado.
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

  const [, init] = (fetchMock as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
  expect((init.headers as Record<string, string>).Authorization).toBe("Bearer T");
  expect(click).toHaveBeenCalled();
});
