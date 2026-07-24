import { expect, test } from "vitest";
import { mulRedondeado } from "./redondeo";

test("mulRedondeado: unidad más cercana, medio hacia arriba", () => {
  expect(mulRedondeado(1.05, 1250)).toBe(1313);   // 1312.5 -> 1313
  expect(mulRedondeado(1.0, 1312.4)).toBe(1312);  // 1312.4 -> 1312
  expect(mulRedondeado(0.5, 1)).toBe(1);          // 0.5 -> 1
});

test("mulRedondeado: producto entero exacto sin cambio", () => {
  expect(mulRedondeado(1.05, 350000)).toBe(367500);
  expect(mulRedondeado(2.5, 2000)).toBe(5000);
});

test("mulRedondeado: mínimo 1 si positivo redondea a 0", () => {
  expect(mulRedondeado(0.0003, 1000)).toBe(1);    // 0.3 -> 1
  expect(mulRedondeado(0.4, 1)).toBe(1);
});

test("mulRedondeado: 0 genuino queda en 0", () => {
  expect(mulRedondeado(2, 0)).toBe(0);
  expect(mulRedondeado(0, 1000)).toBe(0);
});
