import { describe, it, expect, vi, beforeEach } from "vitest";

// `@/api/client` importa `@/lib/supabase`, que crea el cliente de Supabase en
// tiempo de carga del módulo y lanza si faltan las envs (no seteadas en test).
// Lo mockeamos (como en corridas.estados.test.ts) para poder importar el
// cliente real de corridas y espiar `apiPost` con `vi.spyOn`.
vi.mock("@/api/client", () => ({
  authHeader: vi.fn(),
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiDelete: vi.fn(),
  descargarArchivo: vi.fn(),
}));

import { rebuscarApus, aplicarRebusqueda } from "@/api/corridas";
import * as client from "@/api/client";

describe("volver a buscar APU", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("pide la previa sin cuerpo", async () => {
    const spy = vi.spyOn(client, "apiPost").mockResolvedValue({} as never);
    await rebuscarApus(7);
    expect(spy).toHaveBeenCalledWith("/corridas/7/rebuscar", {});
  });

  it("aplica solo los seq marcados", async () => {
    const spy = vi.spyOn(client, "apiPost").mockResolvedValue({} as never);
    await aplicarRebusqueda(7, [0, 3]);
    expect(spy).toHaveBeenCalledWith("/corridas/7/rebuscar/aplicar", { seqs: [0, 3] });
  });
});
