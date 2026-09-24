import { expect, test } from "vitest";
import { esCandidata, porcentaje, previaUmbral } from "./umbralCosto";
import type { ItemCuadro } from "./tipos";

function item(p: Partial<ItemCuadro>): ItemCuadro {
  return {
    seq: 0, item: "1", descripcion: "X", unidad: "GLB", cantidad: 1,
    apu_codigo: "", apu_nombre: "", status: "new", confianza: 0,
    precio_contractual: 1000, costo_unitario: 0, margen_unitario: 0, margen_pct: 0,
    contractual_total: 1000, costo_total: 0, margen_total: 0,
    costo_manual: false, revision: null, ...p,
  } as ItemCuadro;
}

test("candidata: sin APU está en $0 y el contrato la paga", () => {
  expect(esCandidata(item({}))).toBe(true);
});

test("candidata: con APU pero en $0 también entra", () => {
  expect(esCandidata(item({ apu_codigo: "A1", costo_unitario: 0 }))).toBe(true);
});

test("no es candidata: ya tiene costo, o costo a mano, o el contrato no la paga", () => {
  expect(esCandidata(item({ costo_unitario: 500 }))).toBe(false);
  expect(esCandidata(item({ costo_manual: true, costo_unitario: 1000 }))).toBe(false);
  expect(esCandidata(item({ precio_contractual: 0 }))).toBe(false);
});

test("el techo es inclusivo y parte por el total, no por el unitario", () => {
  const items = [
    item({ seq: 0, contractual_total: 100 }),
    item({ seq: 1, contractual_total: 500 }),
    item({ seq: 2, contractual_total: 501 }),
  ];
  const p = previaUmbral(items, 500);
  expect(p.igualadas.map((i) => i.seq)).toEqual([1, 0]);   // de mayor a menor
  expect(p.restantes.map((i) => i.seq)).toEqual([2]);
  expect(p.sumaIgualadas).toBe(600);
  expect(p.sumaRestantes).toBe(501);
});

test("el contractual de la corrida suma TODAS las filas, no solo las candidatas", () => {
  const items = [
    item({ seq: 0, contractual_total: 100 }),
    item({ seq: 1, contractual_total: 9000, costo_unitario: 50 }),  // ya costeada
  ];
  const p = previaUmbral(items, 500);
  expect(p.candidatas).toHaveLength(1);
  expect(p.contractualCorrida).toBe(9100);
});

// Conteos DISTINTOS a propósito: con 1 y 1, intercambiar `sinApu` por `conApu` no
// movería ninguna aserción y el test no vería el bug que existe para atajar.
test("desglose de las que se igualan: con APU y sin APU", () => {
  const items = [
    item({ seq: 0, contractual_total: 100 }),
    item({ seq: 1, contractual_total: 100 }),
    item({ seq: 2, contractual_total: 100, apu_codigo: "A1" }),
  ];
  const p = previaUmbral(items, 500);
  expect(p.sinApu).toBe(2);
  expect(p.conApu).toBe(1);
});

test("las que están en $0 pero sin contractual se cuentan aparte", () => {
  const p = previaUmbral([item({ precio_contractual: 0, contractual_total: 0 })], 500);
  expect(p.candidatas).toHaveLength(0);
  expect(p.sinContractual).toBe(1);
});

test("destildar saca la fila del impacto, no de la lista", () => {
  const items = [
    item({ seq: 0, contractual_total: 100 }),
    item({ seq: 1, contractual_total: 900 }),
  ];
  const p = previaUmbral(items, 1000, new Set([1]));
  // La tabla sigue mostrando las dos: si la destildada desapareciera, no habría
  // forma de volver a marcarla.
  expect(p.bajoTecho.map((i) => i.seq)).toEqual([1, 0]);
  // Pero el impacto (lo que de verdad se va a igualar) ya no la cuenta.
  expect(p.igualadas.map((i) => i.seq)).toEqual([0]);
  expect(p.restantes.map((i) => i.seq)).toEqual([1]);
  expect(p.sumaIgualadas).toBe(100);
  expect(p.sumaRestantes).toBe(900);
});

test("umbral 0, negativo o NaN no iguala nada", () => {
  const items = [item({ contractual_total: 100 })];
  for (const malo of [0, -5, NaN]) {
    expect(previaUmbral(items, malo).igualadas).toHaveLength(0);
  }
});

test("porcentaje no divide por cero", () => {
  expect(porcentaje(50, 200)).toBe(25);
  expect(porcentaje(50, 0)).toBe(0);
});
