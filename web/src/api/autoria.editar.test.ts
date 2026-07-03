import { describe, it, expect, vi, beforeEach } from "vitest";

// `@/api/client` importa `@/lib/supabase`, que crea el cliente de Supabase en
// tiempo de carga del módulo y lanza si faltan las envs (no seteadas en test).
// Lo mockeamos (como en client.test.ts) para poder importar el cliente real
// y espiar `apiPut`/`apiDelete` con `vi.spyOn`.
vi.mock("@/lib/supabase", () => ({
  supabase: { auth: { getSession: vi.fn(async () => ({ data: { session: null } })) } },
}));

import { editarApu, borrarApu } from "@/api/autoria";
import * as client from "@/api/client";

describe("autoria: editar/borrar APU", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("editarApu hace PUT a la ruta con el turno codificado", async () => {
    const spy = vi.spyOn(client, "apiPut").mockResolvedValue({} as never);
    await editarApu("9593 N", "DIURNO", {
      nombre: "X", unidad: "M2", grupo: "G", componentes: [],
    });
    expect(spy).toHaveBeenCalledWith("/apus/9593%20N/DIURNO", {
      nombre: "X", unidad: "M2", grupo: "G", componentes: [],
    });
  });

  it("borrarApu hace DELETE a la ruta", async () => {
    const spy = vi.spyOn(client, "apiDelete").mockResolvedValue(undefined);
    await borrarApu("B2", "DIURNO");
    expect(spy).toHaveBeenCalledWith("/apus/B2/DIURNO");
  });
});
