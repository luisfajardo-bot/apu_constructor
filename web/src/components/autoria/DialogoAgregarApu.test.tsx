import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { DialogoAgregarApu } from "./DialogoAgregarApu";
import { listarApus } from "@/api/autoria";

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

const origenDemo = {
  codigo: "3454", turno: "DIURNO", nombre: "MEZCLA MD12", unidad: "M3", grupo: "PAV",
  costo_unitario: 480000,
  composicion: [{
    insumo_codigo: "999", insumo_nombre: "MEZCLA MD12", unidad: "M3",
    rendimiento: 1, precio_unitario: 480000, fuente_precio: "PRECIO IDU",
    costo: 480000, calidad_cruce: "exacto",
  }],
};

test("modo duplicar precarga el código sugerido y deja código y turno editables", async () => {
  const { DialogoAgregarApu } = await import("./DialogoAgregarApu");
  render(
    <DialogoAgregarApu
      open onOpenChange={() => {}} onCreado={() => {}}
      modo="duplicar" inicial={origenDemo as never}
    />,
  );
  const codigo = await screen.findByDisplayValue("3454-2");
  expect((codigo as HTMLInputElement).disabled).toBe(false);
  const turno = screen.getByDisplayValue("DIURNO");
  expect((turno as HTMLSelectElement).disabled).toBe(false);
  // la composición del origen viene copiada
  expect(screen.getByText("MEZCLA MD12")).toBeTruthy();
});

test("modo duplicar bloquea el guardado mientras el nombre sea el del origen", async () => {
  const { DialogoAgregarApu } = await import("./DialogoAgregarApu");
  render(
    <DialogoAgregarApu
      open onOpenChange={() => {}} onCreado={() => {}}
      modo="duplicar" inicial={origenDemo as never}
    />,
  );
  const boton = await screen.findByRole("button", { name: /Crear APU/i });
  expect((boton as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText(/nombre debe ser distinto/i)).toBeTruthy();

  fireEvent.change(screen.getByDisplayValue("MEZCLA MD12"), {
    target: { value: "MEZCLA MD13" },
  });
  await waitFor(() =>
    expect((screen.getByRole("button", { name: /Crear APU/i }) as HTMLButtonElement)
      .disabled).toBe(false));
});

test("modo duplicar manda duplicado_de en el payload y avisa el código creado", async () => {
  const { DialogoAgregarApu } = await import("./DialogoAgregarApu");
  const { crearApu } = await import("@/api/autoria");
  const onCreado = vi.fn();
  render(
    <DialogoAgregarApu
      open onOpenChange={() => {}} onCreado={onCreado}
      modo="duplicar" inicial={origenDemo as never}
    />,
  );
  fireEvent.change(await screen.findByDisplayValue("MEZCLA MD12"), {
    target: { value: "MEZCLA MD13" },
  });
  fireEvent.click(screen.getByRole("button", { name: /Crear APU/i }));

  await waitFor(() => expect(crearApu).toHaveBeenCalled());
  const payload = (crearApu as unknown as { mock: { calls: unknown[][] } }).mock.calls[0][0] as {
    codigo: string; nombre: string; duplicado_de?: { codigo: string; turno: string };
  };
  expect(payload.codigo).toBe("3454-2");
  expect(payload.nombre).toBe("MEZCLA MD13");
  expect(payload.duplicado_de).toEqual({ codigo: "3454", turno: "DIURNO" });
  await waitFor(() => expect(onCreado).toHaveBeenCalledWith("3454-2", "DIURNO"));
});

test("modo duplicar recalcula el código al cambiar el turno si no lo tocaste", async () => {
  const { DialogoAgregarApu } = await import("./DialogoAgregarApu");
  render(
    <DialogoAgregarApu
      open onOpenChange={() => {}} onCreado={() => {}}
      modo="duplicar" inicial={origenDemo as never}
    />,
  );
  await screen.findByDisplayValue("3454-2");
  fireEvent.change(screen.getByDisplayValue("DIURNO"), { target: { value: "NOCTURNO" } });
  await waitFor(() => expect(screen.getByDisplayValue("3454-2 N")).toBeTruthy());
});

test("modo duplicar NO recalcula el código si ya lo escribiste a mano", async () => {
  const { DialogoAgregarApu } = await import("./DialogoAgregarApu");
  render(
    <DialogoAgregarApu
      open onOpenChange={() => {}} onCreado={() => {}}
      modo="duplicar" inicial={origenDemo as never}
    />,
  );
  fireEvent.change(await screen.findByDisplayValue("3454-2"), {
    target: { value: "9999" },
  });
  fireEvent.change(screen.getByDisplayValue("DIURNO"), { target: { value: "NOCTURNO" } });
  await waitFor(() => expect(screen.getByDisplayValue("9999")).toBeTruthy());
});

test("modo duplicar NO pisa el código tipeado si listarApus resuelve después (carrera con autoFocus)", async () => {
  // Diferido: controlamos a mano cuándo resuelve, para simular que la respuesta
  // llega después de que el usuario ya empezó a escribir (autoFocus + red lenta).
  let resolver: ((v: unknown) => void) | null = null;
  vi.mocked(listarApus).mockImplementationOnce(
    () => new Promise((res) => { resolver = res as (v: unknown) => void; }),
  );
  render(
    <DialogoAgregarApu
      open onOpenChange={() => {}} onCreado={() => {}}
      modo="duplicar" inicial={origenDemo as never}
    />,
  );
  // El código sugerido inicial ("3454-2") se calcula sin esperar la consulta.
  fireEvent.change(await screen.findByDisplayValue("3454-2"), {
    target: { value: "9999" },
  });
  // Recién ahora resuelve `listarApus`, con un ocupado que forzaría el sugerido
  // a "3454-3" si el efecto no respetara que el usuario ya escribió a mano.
  // `waitFor` no sirve para confirmar que un valor "no cambia": si ya es cierto
  // en el primer chequeo, vuelve enseguida sin esperar a que la promesa
  // resuelta termine de propagar su actualización de estado. Por eso se
  // resuelve y se deja correr la cola de microtasks dentro de `act` antes de
  // afirmar nada.
  await act(async () => {
    resolver!({
      items: [{ codigo: "3454-2", turno: "DIURNO", nombre: "MEZCLA MD12",
                unidad: "M3", grupo: "PAV", n_componentes: 1, costo_unitario: 0 }],
      total: 1, limit: 100, offset: 0,
    });
    await new Promise((r) => setTimeout(r, 0));
  });
  expect(screen.getByDisplayValue("9999")).toBeTruthy();
});
