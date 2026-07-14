import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";

vi.mock("@/api/autoria", () => ({
  crearApu: vi.fn(async () => ({})),
  editarApu: vi.fn(async () => ({})),
  listarApus: vi.fn(async () => ({
    items: [{ codigo: "9001", turno: "DIURNO", nombre: "SUB APU DEMO",
              unidad: "M3", grupo: "G", n_componentes: 2, costo_unitario: 0 }],
    total: 1, limit: 15, offset: 0,
  })),
}));
vi.mock("@/api/insumos", () => ({
  listarInsumos: vi.fn(async () => ({ items: [], total: 0, limit: 15, offset: 0 })),
}));

const inicialDemo = {
  codigo: "100", turno: "DIURNO", nombre: "APU DEMO", unidad: "M3", grupo: "G",
  costo_unitario: 4000,
  composicion: [{
    insumo_codigo: "C1", insumo_nombre: "CEMENTO", unidad: "KG",
    rendimiento: 2, precio_unitario: 2000, fuente_precio: "PRECIO IDU",
    costo: 4000, calidad_cruce: "exacto",
  }],
};

test("componenteDeFila incluye tipo/ref_shift en una fila sub-APU", async () => {
  const { componenteDeFila } = await import("./DialogoAgregarApu");
  const apu = componenteDeFila({
    uid: 1, tipo: "apu", ref_shift: "DIURNO",
    insumo_codigo: "9001", insumo_nombre: "SUB APU DEMO", unidad: "M3",
    rendimiento: "3", precio: 0,
  });
  expect(apu).toEqual({
    insumo_codigo: "9001", rendimiento: 3, insumo_nombre: "SUB APU DEMO",
    unidad: "M3", tipo: "apu", ref_shift: "DIURNO",
  });
  const ins = componenteDeFila({
    uid: 2, tipo: "insumo", ref_shift: "",
    insumo_codigo: "100", insumo_nombre: "CEMENTO", unidad: "KG",
    rendimiento: "2", precio: 0,
  });
  expect(ins).toEqual({
    insumo_codigo: "100", rendimiento: 2, insumo_nombre: "CEMENTO", unidad: "KG",
  });                                   // sin tipo/ref_shift cuando es insumo
});

test("tipoRefDeLinea deduce sub-APU desde calidad_cruce o tipo", async () => {
  const { tipoRefDeLinea } = await import("./DialogoAgregarApu");
  expect(tipoRefDeLinea({ tipo: "apu", ref_shift: "NOCTURNO", calidad_cruce: "apu" }))
    .toEqual({ tipo: "apu", ref_shift: "NOCTURNO" });
  expect(tipoRefDeLinea({ tipo: "", ref_shift: "", calidad_cruce: "apu" }))
    .toEqual({ tipo: "apu", ref_shift: "" });          // respaldo por calidad_cruce
  expect(tipoRefDeLinea({ tipo: "insumo", ref_shift: "", calidad_cruce: "exacto" }))
    .toEqual({ tipo: "insumo", ref_shift: "" });
});

test("'+ Sub-APU' agrega una fila con BuscadorApu y al elegir muestra el chip APU", async () => {
  const { DialogoAgregarApu } = await import("./DialogoAgregarApu");
  render(<DialogoAgregarApu open onOpenChange={() => {}} onCreado={() => {}} />);
  fireEvent.click(screen.getByText("+ Sub-APU"));
  const input = await screen.findByPlaceholderText(/Buscar APU/i);
  fireEvent.change(input, { target: { value: "900" } });
  fireEvent.click(await screen.findByText("SUB APU DEMO"));
  await waitFor(() => expect(screen.getByText("APU")).toBeTruthy());   // chip
  expect(screen.getByText("9001")).toBeTruthy();                        // código elegido
});

test("modo editar muestra el precio del componente (solo lectura)", async () => {
  const { DialogoAgregarApu } = await import("./DialogoAgregarApu");
  render(
    <DialogoAgregarApu
      open onOpenChange={() => {}} onCreado={() => {}}
      modo="editar" inicial={inicialDemo as never}
    />,
  );
  expect(screen.getByText("$2.000")).toBeTruthy();   // precio del insumo
});

test("editar el costo despeja el rendimiento (precio 2000, costo 6000 → rend 3)", async () => {
  const { DialogoAgregarApu } = await import("./DialogoAgregarApu");
  render(
    <DialogoAgregarApu open onOpenChange={() => {}} onCreado={() => {}}
      modo="editar" inicial={inicialDemo as never} />,
  );
  const costo = screen.getByLabelText("Costo") as HTMLInputElement;
  expect(costo.value).toBe("4000");                       // 2 × 2000
  fireEvent.change(costo, { target: { value: "6000" } });
  const rend = screen.getByLabelText("Rendimiento") as HTMLInputElement;
  expect(rend.value).toBe("3");                           // 6000 / 2000
});

test("editar el rendimiento actualiza el costo mostrado (rend 5 → costo 10000)", async () => {
  const { DialogoAgregarApu } = await import("./DialogoAgregarApu");
  render(
    <DialogoAgregarApu open onOpenChange={() => {}} onCreado={() => {}}
      modo="editar" inicial={inicialDemo as never} />,
  );
  const rend = screen.getByLabelText("Rendimiento") as HTMLInputElement;
  fireEvent.change(rend, { target: { value: "5" } });
  const costo = screen.getByLabelText("Costo") as HTMLInputElement;
  expect(costo.value).toBe("10000");                      // 5 × 2000
});

test("el total del APU refleja el costo de las filas y se actualiza al editar", async () => {
  const { DialogoAgregarApu } = await import("./DialogoAgregarApu");
  render(
    <DialogoAgregarApu open onOpenChange={() => {}} onCreado={() => {}}
      modo="editar" inicial={inicialDemo as never} />,
  );
  expect(screen.getByText("Costo unitario del APU:")).toBeTruthy();
  expect(screen.getByText("$4.000")).toBeTruthy();        // total inicial: 2 × 2000
  const rend = screen.getByLabelText("Rendimiento") as HTMLInputElement;
  fireEvent.change(rend, { target: { value: "5" } });
  expect(screen.getByText("$10.000")).toBeTruthy();       // 5 × 2000
});

test("precio 0: no hay input de costo; el rendimiento sigue editable", async () => {
  const inicialSinPrecio = {
    ...inicialDemo,
    composicion: [{ ...inicialDemo.composicion[0], precio_unitario: 0, costo: 0 }],
  };
  const { DialogoAgregarApu } = await import("./DialogoAgregarApu");
  render(
    <DialogoAgregarApu open onOpenChange={() => {}} onCreado={() => {}}
      modo="editar" inicial={inicialSinPrecio as never} />,
  );
  expect(screen.queryByLabelText("Costo")).toBeNull();    // sin input de costo
  expect(screen.getByLabelText("Rendimiento")).toBeTruthy();
});
