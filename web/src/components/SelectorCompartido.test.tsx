import { render, screen, fireEvent } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import SelectorCompartido, { sinResolver } from "./SelectorCompartido";

const OPCIONES = [
  { nombre: "REDUCCION HD", unidad: "UN", oculto: false },
  { nombre: "SEÑAL VERTICAL", unidad: "UN", oculto: true },
];

test("sin elegir muestra la pregunta y al escoger devuelve la opción", () => {
  const onElegir = vi.fn();
  render(<SelectorCompartido codigo="7406" opciones={OPCIONES} valor="" onElegir={onElegir} />);
  const sel = screen.getByLabelText("Insumo del código 7406") as HTMLSelectElement;
  expect(sel.value).toBe("");
  expect(screen.getByText(/¿Cuál de los/)).toBeTruthy();
  expect(screen.getByText(/SEÑAL VERTICAL · UN \(oculto\)/)).toBeTruthy();
  fireEvent.change(sel, { target: { value: "1" } });
  expect(onElegir).toHaveBeenCalledWith(OPCIONES[1]);
});

test("con un nombre que coincide queda seleccionado", () => {
  render(<SelectorCompartido codigo="7406" opciones={OPCIONES} valor="reduccion hd"
                             onElegir={() => {}} />);
  expect((screen.getByLabelText("Insumo del código 7406") as HTMLSelectElement).value).toBe("0");
});

test("deshabilitado no deja cambiar", () => {
  render(<SelectorCompartido codigo="7406" opciones={OPCIONES} valor="" onElegir={() => {}}
                             deshabilitado />);
  expect((screen.getByLabelText("Insumo del código 7406") as HTMLSelectElement).disabled)
    .toBe(true);
});

test("sinResolver dice si el nombre no coincide con ninguna opción", () => {
  expect(sinResolver(OPCIONES, "")).toBe(true);
  expect(sinResolver(OPCIONES, "otro")).toBe(true);
  expect(sinResolver(OPCIONES, "Señal vertical")).toBe(false);
});
