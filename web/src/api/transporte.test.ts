import { describe, expect, it, vi, beforeEach } from "vitest";
import * as client from "@/api/client";
import { verTransporte, guardarTransporte, listarComponentes, clasificar,
         listarAjustes, crearAjuste, borrarAjuste } from "@/api/transporte";

describe("api/transporte", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("usa las rutas del contrato", async () => {
    const get = vi.spyOn(client, "apiGet").mockResolvedValue({} as never);
    const put = vi.spyOn(client, "apiPut").mockResolvedValue({} as never);
    const post = vi.spyOn(client, "apiPost").mockResolvedValue({} as never);
    const del = vi.spyOn(client, "apiDelete").mockResolvedValue(undefined as never);
    await verTransporte(7);
    expect(get).toHaveBeenCalledWith("/carpetas/7/transporte");
    await guardarTransporte(7, { km_botadero: 34 });
    expect(put).toHaveBeenCalledWith("/carpetas/7/transporte", { km_botadero: 34 });
    await listarComponentes();
    expect(get).toHaveBeenCalledWith("/transporte/componentes");
    await clasificar([{ apu_codigo: "4390", shift: "DIURNO", insumo_codigo: "7462",
                       insumo_nombre: "TTE", categoria: "granulares", volumen: 1.05,
                       km_base: 25 }]);
    expect(put).toHaveBeenCalledWith("/transporte/componentes", { filas: expect.any(Array) });
    await listarAjustes(7);
    expect(get).toHaveBeenCalledWith("/carpetas/7/ajustes");
    await crearAjuste(7, { apu_codigo: "4390", shift: "DIURNO", accion: "quitar",
                           insumo_codigo: "1", insumo_nombre: "X" });
    expect(post).toHaveBeenCalledWith("/carpetas/7/ajustes", expect.any(Object));
    await borrarAjuste(7, 3);
    expect(del).toHaveBeenCalledWith("/carpetas/7/ajustes/3");
  });
});
