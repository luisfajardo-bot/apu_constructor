import { describe, expect, it, vi, beforeEach } from "vitest";
import { listarListas, crearLista, renombrarLista } from "@/api/listas";

function mockFetch(body: unknown) {
  const spy = vi.fn().mockResolvedValue({
    ok: true, status: 200, json: async () => body,
    headers: new Headers({ "content-type": "application/json" }),
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

beforeEach(() => vi.unstubAllGlobals());

describe("api de listas de precios", () => {
  it("listar pega a /api/listas-precios", async () => {
    const spy = mockFetch([{ id: 1, nombre: "Principal", creada_en: "2026-07-27" }]);
    const listas = await listarListas();
    expect(spy.mock.calls[0][0]).toContain("/listas-precios");
    expect(listas[0].nombre).toBe("Principal");
  });

  it("crear manda el nombre por POST", async () => {
    const spy = mockFetch({ id: 2, nombre: "NP Calle 13", creada_en: "2026-07-27" });
    const lista = await crearLista("NP Calle 13");
    expect(spy.mock.calls[0][1].method).toBe("POST");
    expect(JSON.parse(spy.mock.calls[0][1].body as string)).toEqual({ nombre: "NP Calle 13" });
    expect(lista.id).toBe(2);
  });

  it("renombrar usa PATCH sobre el id", async () => {
    const spy = mockFetch({ id: 2, nombre: "NP A2", creada_en: "2026-07-27" });
    await renombrarLista(2, "NP A2");
    expect(spy.mock.calls[0][0]).toContain("/listas-precios/2");
    expect(spy.mock.calls[0][1].method).toBe("PATCH");
  });
});
