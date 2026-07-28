import { describe, expect, it, vi, beforeEach } from "vitest";
import { listarInsumos } from "@/api/insumos";

beforeEach(() => vi.unstubAllGlobals());

describe("listarInsumos con lista", () => {
  it("propaga lista y sin_precio como query params", async () => {
    const spy = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ items: [], total: 0, limit: 100, offset: 0 }),
      headers: new Headers({ "content-type": "application/json" }),
    });
    vi.stubGlobal("fetch", spy);
    await listarInsumos({ lista: 7, sin_precio: true });
    const url = String(spy.mock.calls[0][0]);
    expect(url).toContain("lista=7");
    expect(url).toContain("sin_precio=true");
  });
});
