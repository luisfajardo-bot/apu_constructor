import { costoDeFila, rendimientoDesdeCosto, costoTotalApu } from "./costoApu";

test("costoDeFila: rendimiento × precio; 0 si el rendimiento no es número", () => {
  expect(costoDeFila("2.5", 2000)).toBe(5000);
  expect(costoDeFila("0", 2000)).toBe(0);
  expect(costoDeFila("", 2000)).toBe(0);
  expect(costoDeFila("abc", 2000)).toBe(0);
});

test("rendimientoDesdeCosto: despeja costo/precio; null cuando no se puede", () => {
  expect(rendimientoDesdeCosto("5000", 2000)).toBe(2.5);
  expect(rendimientoDesdeCosto("5000", 0)).toBeNull();   // precio 0 → no se despeja
  expect(rendimientoDesdeCosto("5000", -3)).toBeNull();
  expect(rendimientoDesdeCosto("", 2000)).toBeNull();
  expect(rendimientoDesdeCosto("abc", 2000)).toBeNull();
});

test("ida y vuelta: despejar y volver a costear da el mismo peso", () => {
  const precio = 3;
  const r = rendimientoDesdeCosto("100", precio);
  expect(r).not.toBeNull();
  expect(Math.round(costoDeFila(String(r), precio))).toBe(100);
});

test("costoTotalApu: suma solo las filas con insumo elegido", () => {
  const filas = [
    { insumo_codigo: "A1", rendimiento: "2", precio: 1000 },    // 2000
    { insumo_codigo: "A2", rendimiento: "1.5", precio: 2000 },  // 3000
    { insumo_codigo: "", rendimiento: "10", precio: 5000 },     // ignorada
  ];
  expect(costoTotalApu(filas)).toBe(5000);
});
