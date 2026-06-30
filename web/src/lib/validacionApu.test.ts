import {
  rendimientoValido,
  hayRendimientoInvalido,
  componentesValidos,
} from "./validacionApu";

test("rendimientoValido: solo números finitos > 0", () => {
  expect(rendimientoValido("1")).toBe(true);
  expect(rendimientoValido("0.5")).toBe(true);
  expect(rendimientoValido("0")).toBe(false);
  expect(rendimientoValido("-2")).toBe(false);
  expect(rendimientoValido("")).toBe(false);
  expect(rendimientoValido("abc")).toBe(false);
});

test("hayRendimientoInvalido: detecta insumo elegido con rendimiento <= 0", () => {
  expect(
    hayRendimientoInvalido([{ insumo_codigo: "A1", rendimiento: "0" }]),
  ).toBe(true);
  expect(
    hayRendimientoInvalido([{ insumo_codigo: "A1", rendimiento: "2" }]),
  ).toBe(false);
  // Fila sin insumo elegido no cuenta como inválida
  expect(
    hayRendimientoInvalido([{ insumo_codigo: "", rendimiento: "" }]),
  ).toBe(false);
});

test("componentesValidos: filtra filas con insumo y rendimiento > 0", () => {
  const filas = [
    { insumo_codigo: "A1", rendimiento: "2" },
    { insumo_codigo: "A2", rendimiento: "0" },
    { insumo_codigo: "", rendimiento: "5" },
  ];
  expect(componentesValidos(filas)).toEqual([
    { insumo_codigo: "A1", rendimiento: "2" },
  ]);
});
