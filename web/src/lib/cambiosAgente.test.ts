import { expect, test } from "vitest";
import { aplicarCambios } from "./cambiosAgente";
import type { ComponentePropuesto } from "./tipos";

function comp(codigo: string, rendimiento = 1): ComponentePropuesto {
  return {
    codigo, tipo: "insumo", funcion: "material", rendimiento,
    origen: "supuesto_tecnico", referencias: [], hipotesis: {}, calculo: null,
    justificacion: "", nivel_evidencia: "bajo", ref_shift: "",
  };
}

test("agrega al final, quita y modifica por código", () => {
  const r = aplicarCambios([comp("A"), comp("B")], [
    { op: "agregar", codigo: "C", componente: comp("C", 3) },
    { op: "quitar", codigo: "A", componente: null },
    { op: "modificar", codigo: "B", componente: comp("B", 9) },
  ]);
  expect(r.componentes.map((c) => [c.codigo, c.rendimiento])).toEqual([["B", 9], ["C", 3]]);
  expect(r.conflictos).toEqual([]);
});

test("no duplica lo que ya está y lo reporta", () => {
  const r = aplicarCambios([comp("A")], [
    { op: "agregar", codigo: "A", componente: comp("A", 5) },
  ]);
  expect(r.componentes).toEqual([comp("A")]);
  expect(r.conflictos[0]).toMatch(/A ya estaba/);
});

test("quitar o modificar algo que ya no está es conflicto, y el resto se aplica", () => {
  const r = aplicarCambios([comp("A")], [
    { op: "quitar", codigo: "X", componente: null },
    { op: "modificar", codigo: "Y", componente: comp("Y") },
    { op: "agregar", codigo: "B", componente: comp("B") },
  ]);
  expect(r.componentes.map((c) => c.codigo)).toEqual(["A", "B"]);
  expect(r.conflictos).toHaveLength(2);
});

test("el código del cambio manda sobre el del componente", () => {
  const r = aplicarCambios([], [
    { op: "agregar", codigo: "C", componente: comp("OTRO") },
  ]);
  expect(r.componentes[0].codigo).toBe("C");
});

test("no muta la lista de entrada", () => {
  const actuales = [comp("A")];
  aplicarCambios(actuales, [{ op: "quitar", codigo: "A", componente: null }]);
  expect(actuales).toHaveLength(1);
});

test("modificar sin nombre conserva el nombre que ya tenía la fila", () => {
  const base = { ...comp("6092"), nombre: "HERRAMIENTA MENOR" };
  const r = aplicarCambios([base], [
    { op: "modificar", codigo: "6092", componente: { ...base, rendimiento: 2, nombre: "" } },
  ]);
  expect(r.componentes[0]).toMatchObject({ rendimiento: 2, nombre: "HERRAMIENTA MENOR" });
});
