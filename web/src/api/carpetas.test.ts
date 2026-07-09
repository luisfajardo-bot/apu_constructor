import { describe, it, expect, vi, beforeEach } from "vitest";

// `@/api/client` importa `@/lib/supabase`, que crea el cliente de Supabase en
// tiempo de carga del módulo y lanza si faltan las envs (no seteadas en test).
// Lo mockeamos (como en corridas.estados.test.ts) para espiar los helpers.
vi.mock("@/api/client", () => ({
  authHeader: vi.fn(),
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
  descargarArchivo: vi.fn(),
}));

import {
  listarCarpetas,
  crearCarpeta,
  renombrarCarpeta,
  moverCarpeta,
  borrarCarpeta,
  moverCorrida,
} from "@/api/carpetas";
import * as client from "@/api/client";

describe("api/carpetas", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("listarCarpetas hace GET /carpetas", async () => {
    const spy = vi.spyOn(client, "apiGet").mockResolvedValue([] as never);
    await listarCarpetas();
    expect(spy).toHaveBeenCalledWith("/carpetas");
  });

  it("crearCarpeta hace POST con nombre y parent_id", async () => {
    const spy = vi.spyOn(client, "apiPost").mockResolvedValue({} as never);
    await crearCarpeta("Obra", null);
    expect(spy).toHaveBeenCalledWith("/carpetas", { nombre: "Obra", parent_id: null });
  });

  it("renombrarCarpeta hace PATCH con nombre", async () => {
    const spy = vi.spyOn(client, "apiPatch").mockResolvedValue({} as never);
    await renombrarCarpeta(3, "Nuevo");
    expect(spy).toHaveBeenCalledWith("/carpetas/3", { nombre: "Nuevo" });
  });

  it("moverCarpeta hace PATCH con parent_id y mover=true", async () => {
    const spy = vi.spyOn(client, "apiPatch").mockResolvedValue({} as never);
    await moverCarpeta(3, 1);
    expect(spy).toHaveBeenCalledWith("/carpetas/3", { parent_id: 1, mover: true });
  });

  it("borrarCarpeta hace DELETE /carpetas/:id", async () => {
    const spy = vi.spyOn(client, "apiDelete").mockResolvedValue(undefined as never);
    await borrarCarpeta(5);
    expect(spy).toHaveBeenCalledWith("/carpetas/5");
  });

  it("moverCorrida hace POST /corridas/:id/mover con carpeta_id", async () => {
    const spy = vi.spyOn(client, "apiPost").mockResolvedValue({} as never);
    await moverCorrida(9, 2);
    expect(spy).toHaveBeenCalledWith("/corridas/9/mover", { carpeta_id: 2 });
  });
});
