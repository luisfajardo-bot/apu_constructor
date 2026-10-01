import { describe, expect, it } from "vitest";
import { agruparHilos } from "./hilos";
import type { Nota } from "./tipos";

const n = (id: number, responde_a: number | null = null) => ({ id, responde_a } as unknown as Nota);

describe("agruparHilos", () => {
  it("pone cada respuesta bajo su raíz, en orden", () => {
    const h = agruparHilos([n(1), n(2), n(3, 1), n(4, 2), n(5, 1)]);
    expect(h.map((x) => [x.raiz.id, x.respuestas.map((r) => r.id)])).toEqual([[1, [3, 5]], [2, [4]]]);
  });
  it("una respuesta huérfana se muestra como raíz", () => {
    expect(agruparHilos([n(7, 99)]).map((x) => x.raiz.id)).toEqual([7]);
  });
});
