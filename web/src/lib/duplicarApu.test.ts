import { expect, test } from "vitest";
import { baseDe, codigoSugerido, nombreEsDistinto, normalizarNombre } from "./duplicarApu";

test("baseDe quita la marca nocturna y el sufijo de copia", () => {
  expect(baseDe("3454")).toBe("3454");
  expect(baseDe("3454 N")).toBe("3454");
  expect(baseDe("3454-2")).toBe("3454");
  expect(baseDe("3454-2 N")).toBe("3454");
});

test("codigoSugerido agrega el sufijo -2 sobre la base", () => {
  expect(codigoSugerido("3454", "DIURNO", [])).toBe("3454-2");
});

test("codigoSugerido salta los códigos ocupados", () => {
  expect(codigoSugerido("3454", "DIURNO", ["3454-2", "3454-3"])).toBe("3454-4");
});

test("codigoSugerido no anida cuando el origen ya es una copia", () => {
  expect(codigoSugerido("3454-2", "DIURNO", ["3454-2"])).toBe("3454-3");
});

test("codigoSugerido pone la ' N' al final en nocturno", () => {
  expect(codigoSugerido("3454 N", "NOCTURNO", [])).toBe("3454-2 N");
  expect(codigoSugerido("3454", "NOCTURNO", [])).toBe("3454-2 N");
  expect(codigoSugerido("3454 N", "DIURNO", [])).toBe("3454-2");
  expect(codigoSugerido("3454 N", "NOCTURNO", ["3454-2 N"])).toBe("3454-3 N");
});

test("normalizarNombre replica el criterio del backend", () => {
  expect(normalizarNombre("  Mezcla   MD12. ")).toBe("MEZCLA MD12");
  expect(normalizarNombre("MEZCLÁ MD12")).toBe("MEZCLA MD12");
});

test("nombreEsDistinto ignora espacios, mayúsculas, tildes y puntuación", () => {
  expect(nombreEsDistinto("MEZCLA MD12", "  mezcla   md12 ")).toBe(false);
  expect(nombreEsDistinto("MEZCLA MD12", "MEZCLA MD12.")).toBe(false);
  expect(nombreEsDistinto("MEZCLA MD12", "MEZCLA MD13")).toBe(true);
  expect(nombreEsDistinto("MEZCLA MD12", "   ")).toBe(false);
});
