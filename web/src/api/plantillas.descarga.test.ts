import { expect, test, vi, beforeEach } from "vitest";

vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: vi.fn(async () => ({ data: { session: { access_token: "T" } } })),
      signOut: vi.fn(),
    },
  },
}));

beforeEach(() => {
  vi.restoreAllMocks();
});

test("descargarArchivo usa Bearer y dispara la descarga", async () => {
  const { descargarArchivo } = await import("./client");

  const fetchMock = vi.fn(async () => ({
    status: 200,
    ok: true,
    blob: async () => new Blob(["x"]),
  })) as unknown as typeof fetch;
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("URL", { createObjectURL: () => "blob:x", revokeObjectURL: () => {} });
  const click = vi.fn();
  vi.spyOn(document, "createElement").mockReturnValue({
    click, remove: () => {}, href: "", download: "",
  } as unknown as HTMLAnchorElement);
  vi.spyOn(document.body, "appendChild").mockImplementation((n) => n as never);

  await descargarArchivo("/apus/importar/plantilla", "plantilla_apus.xlsx");

  const [url, init] = (fetchMock as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
  expect(url).toBe("/api/apus/importar/plantilla");
  expect((init.headers as Record<string, string>).Authorization).toBe("Bearer T");
  expect(click).toHaveBeenCalled();
});
