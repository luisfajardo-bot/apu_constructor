import { expect, test } from "vitest";
import {
  filtrar, ordenar, opcionesDe, siguienteOrden, hayFiltrosActivos,
  normalizar, FILTROS_VACIOS,
} from "./corridaTabla";
import type { ItemCuadro } from "./tipos";

function item(p: Partial<ItemCuadro>): ItemCuadro {
  return {
    seq: 0, item: "1", descripcion: "X", unidad: "M3", cantidad: 1,
    apu_codigo: "A", apu_nombre: "APU A", status: "auto", confianza: 1,
    precio_contractual: 0, costo_unitario: 0, margen_unitario: 0, margen_pct: 0,
    contractual_total: 0, costo_total: 0, margen_total: 0, ...p,
  };
}

test("normalizar quita tildes y baja a minúsculas", () => {
  expect(normalizar("Excavación")).toBe("excavacion");
});

test("filtrar: texto 'contiene' insensible a tildes/mayúsculas", () => {
  const items = [item({ descripcion: "Excavación manual" }), item({ descripcion: "Concreto" })];
  const f = { ...FILTROS_VACIOS, descripcion: "excavacion" };
  expect(filtrar(items, f, false).map((i) => i.descripcion)).toEqual(["Excavación manual"]);
});

test("filtrar: desplegable de unidad es coincidencia exacta", () => {
  const items = [item({ unidad: "M3" }), item({ unidad: "M2" })];
  expect(filtrar(items, { ...FILTROS_VACIOS, unidad: "M2" }, false)).toHaveLength(1);
});

test("filtrar: rango numérico inclusivo, extremos vacíos = sin límite", () => {
  const items = [item({ contractual_total: 100 }), item({ contractual_total: 200 }), item({ contractual_total: 300 })];
  const f = { ...FILTROS_VACIOS, contractual_total: { min: "200", max: "300" } };
  expect(filtrar(items, f, false).map((i) => i.contractual_total)).toEqual([200, 300]);
  const soloMax = { ...FILTROS_VACIOS, contractual_total: { min: "", max: "150" } };
  expect(filtrar(items, soloMax, false).map((i) => i.contractual_total)).toEqual([100]);
});

test("filtrar: % se interpreta en puntos (12 => 0.12)", () => {
  const items = [item({ margen_pct: 0.05 }), item({ margen_pct: 0.12 }), item({ margen_pct: 0.20 })];
  const f = { ...FILTROS_VACIOS, margen_pct: { min: "12", max: "" } };
  expect(filtrar(items, f, false).map((i) => i.margen_pct)).toEqual([0.12, 0.20]);
});

test("filtrar: soloRevision deja solo review/new", () => {
  const items = [item({ status: "auto" }), item({ status: "review" }), item({ status: "new" })];
  expect(filtrar(items, FILTROS_VACIOS, true).map((i) => i.status)).toEqual(["review", "new"]);
});

test("filtrar: combina filtros con Y", () => {
  const items = [
    item({ unidad: "M3", margen_total: -5 }),
    item({ unidad: "M3", margen_total: 10 }),
    item({ unidad: "M2", margen_total: -5 }),
  ];
  const f = { ...FILTROS_VACIOS, unidad: "M3", margen_total: { min: "", max: "0" } };
  expect(filtrar(items, f, false)).toHaveLength(1);
});

test("ordenar: numérico asc y desc", () => {
  const items = [item({ costo_total: 300 }), item({ costo_total: 100 }), item({ costo_total: 200 })];
  expect(ordenar(items, { clave: "costo_total", dir: "asc" }).map((i) => i.costo_total)).toEqual([100, 200, 300]);
  expect(ordenar(items, { clave: "costo_total", dir: "desc" }).map((i) => i.costo_total)).toEqual([300, 200, 100]);
});

test("ordenar: texto con orden natural (1.2 antes de 1.10)", () => {
  const items = [item({ item: "1.10" }), item({ item: "1.2" }), item({ item: "1.1" })];
  expect(ordenar(items, { clave: "item", dir: "asc" }).map((i) => i.item)).toEqual(["1.1", "1.2", "1.10"]);
});

test("ordenar: null conserva el orden original", () => {
  const items = [item({ costo_total: 3 }), item({ costo_total: 1 })];
  expect(ordenar(items, null).map((i) => i.costo_total)).toEqual([3, 1]);
});

test("opcionesDe: distintos y ordenados", () => {
  const items = [item({ unidad: "M3" }), item({ unidad: "M2" }), item({ unidad: "M3" })];
  expect(opcionesDe(items, "unidad")).toEqual(["M2", "M3"]);
});

test("siguienteOrden: ciclo asc -> desc -> null -> asc", () => {
  expect(siguienteOrden(null, "costo_total")).toEqual({ clave: "costo_total", dir: "asc" });
  expect(siguienteOrden({ clave: "costo_total", dir: "asc" }, "costo_total")).toEqual({ clave: "costo_total", dir: "desc" });
  expect(siguienteOrden({ clave: "costo_total", dir: "desc" }, "costo_total")).toBeNull();
  expect(siguienteOrden({ clave: "costo_total", dir: "asc" }, "margen_total")).toEqual({ clave: "margen_total", dir: "asc" });
});

test("hayFiltrosActivos: falso en vacío, verdadero con algún filtro", () => {
  expect(hayFiltrosActivos(FILTROS_VACIOS, null, false)).toBe(false);
  expect(hayFiltrosActivos({ ...FILTROS_VACIOS, item: "1" }, null, false)).toBe(true);
  expect(hayFiltrosActivos(FILTROS_VACIOS, { clave: "item", dir: "asc" }, false)).toBe(true);
  expect(hayFiltrosActivos(FILTROS_VACIOS, null, true)).toBe(true);
});
