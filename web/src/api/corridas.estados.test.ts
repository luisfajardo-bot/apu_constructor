import { describe, it, expect, vi, beforeEach } from "vitest";

// `@/api/client` importa `@/lib/supabase`, que crea el cliente de Supabase en
// tiempo de carga del módulo y lanza si faltan las envs (no seteadas en test).
// Lo mockeamos (como en corridas.descarga.test.ts) para poder importar el
// cliente real de corridas y espiar `apiPost` con `vi.spyOn`.
vi.mock("@/api/client", () => ({
  authHeader: vi.fn(),
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiDelete: vi.fn(),
  descargarArchivo: vi.fn(),
}));

import { congelarCorrida, activarCorrida } from "@/api/corridas";
import * as client from "@/api/client";

describe("corridas: congelar/activar", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("congelarCorrida hace POST a /corridas/{id}/congelar", async () => {
    const spy = vi.spyOn(client, "apiPost").mockResolvedValue({} as never);
    await congelarCorrida(7);
    expect(spy).toHaveBeenCalledWith("/corridas/7/congelar");
  });

  it("activarCorrida hace POST a /corridas/{id}/activar", async () => {
    const spy = vi.spyOn(client, "apiPost").mockResolvedValue({} as never);
    await activarCorrida(7);
    expect(spy).toHaveBeenCalledWith("/corridas/7/activar");
  });
});
