import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import TablaItems from "./TablaItems";
import { useCorridaTabla } from "@/lib/corridaTabla";

vi.mock("@/api/corridas", () => ({
  getItem: vi.fn(async () => ({
    seq: 0, descripcion: "Concreto", apu_codigo: "111", apu_nombre: "APU VIEJO",
    status: "matched", explicacion: "", candidatos: [], composicion: [], costo_unitario: 0,
  })),
  confirmar: vi.fn(async () => ({
    id: 1, archivo: "x", estado: "en_revision", modo: "activa", items: [], duracion_ms: null,
    totales: { contractual: 0, costo: 0, margen: 0, margen_pct: 0, n_items: 0, n_revision: 0 },
  })),
}));
vi.mock("@/api/autoria", () => ({
  listarApus: vi.fn(async () => ({
    items: [{ codigo: "33333", turno: "DIURNO", nombre: "APU NUEVO",
              unidad: "M3", grupo: "G", n_componentes: 2 }],
    total: 1, limit: 15, offset: 0,
  })),
}));

const ITEM = {
  seq: 0, item: "1", descripcion: "Concreto", unidad: "M3", cantidad: 10,
  apu_codigo: "111", apu_nombre: "APU VIEJO", status: "matched", confianza: 1,
  precio_contractual: 0, costo_unitario: 0, margen_unitario: 0, margen_pct: 0,
  contractual_total: 0, costo_total: 0, margen_total: 0,
};

test("reasigna un ítem matched vía el buscador (pasa el turno elegido)", async () => {
  const { default: TablaItems } = await import("./TablaItems");
  const { confirmar } = await import("@/api/corridas");
  render(<TablaItems corridaId={1} items={[ITEM]} onConfirmado={() => {}} />);

  // Expandir la fila (lazy-fetch del detalle)
  fireEvent.click(screen.getByLabelText("Expandir fila"));

  // El buscador "Cambiar APU" aparece aunque el ítem sea matched
  const input = await screen.findByPlaceholderText(/Buscar APU/i);
  fireEvent.change(input, { target: { value: "333" } });
  fireEvent.click(await screen.findByText("APU NUEVO"));

  await waitFor(() =>
    expect(confirmar).toHaveBeenCalledWith(1, 0, "33333", "DIURNO"),
  );
});

test("muestra el error si la reasignación falla en un ítem matched", async () => {
  const { default: TablaItems } = await import("./TablaItems");
  const mod = await import("@/api/corridas");
  vi.mocked(mod.confirmar).mockRejectedValueOnce(new Error("fallo de red"));
  render(<TablaItems corridaId={1} items={[ITEM]} onConfirmado={() => {}} />);

  fireEvent.click(screen.getByLabelText("Expandir fila"));

  fireEvent.change(await screen.findByPlaceholderText(/Buscar APU/i), {
    target: { value: "333" },
  });
  fireEvent.click(await screen.findByText("APU NUEVO"));

  expect(await screen.findByText("fallo de red")).toBeTruthy();
});

test("oculta el buscador 'Cambiar APU' cuando la corrida está en solo lectura", async () => {
  const { default: TablaItems } = await import("./TablaItems");
  render(
    <TablaItems
      corridaId={1}
      items={[ITEM]}
      onConfirmado={() => {}}
      readOnly={true}
    />,
  );

  // Expandir la fila (lazy-fetch del detalle)
  fireEvent.click(screen.getByLabelText("Expandir fila"));

  // Esperar a que el detalle cargue (aparece el header del APU)
  await screen.findByText(/APU: 111/);

  // El buscador "Cambiar APU" NO debe estar presente en modo solo lectura
  expect(screen.queryByPlaceholderText(/Buscar APU/i)).toBeNull();

  // El aviso de solo lectura sí debe estar presente
  expect(
    screen.getByText(/Corrida congelada \(solo lectura\)/i),
  ).toBeTruthy();
});

test("muestra el código de licitación (Ítem) junto al APU", async () => {
  const { default: TablaItems } = await import("./TablaItems");
  render(
    <TablaItems corridaId={1} items={[{ ...ITEM, item: "OBRA-77" }]} onConfirmado={() => {}} />,
  );
  // el código con el que entró (Ítem) y el APU asignado (del fixture: "111"), ambos visibles
  expect(screen.getByText("OBRA-77")).toBeTruthy();
  expect(screen.getByText("111")).toBeTruthy();
});

function TablaConControl({ items }: { items: typeof ITEM[] }) {
  const control = useCorridaTabla(items);
  return (
    <TablaItems corridaId={1} items={control.filtradas} control={control} onConfirmado={() => {}} />
  );
}

test("filtra por Descripción (contiene) ocultando las filas que no coinciden", async () => {
  await import("./TablaItems");
  const items = [
    { ...ITEM, seq: 0, descripcion: "Excavación manual" },
    { ...ITEM, seq: 1, descripcion: "Concreto clase D" },
  ];
  render(<TablaConControl items={items} />);
  expect(screen.getByText("Excavación manual")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Filtrar Descripción"), { target: { value: "concreto" } });
  expect(screen.queryByText("Excavación manual")).toBeNull();
  expect(screen.getByText("Concreto clase D")).toBeTruthy();
});

test("filtra por el desplegable de Und", async () => {
  await import("./TablaItems");
  const items = [
    { ...ITEM, seq: 0, descripcion: "A", unidad: "M3" },
    { ...ITEM, seq: 1, descripcion: "B", unidad: "M2" },
  ];
  render(<TablaConControl items={items} />);
  fireEvent.change(screen.getByLabelText("Filtrar Und"), { target: { value: "M2" } });
  expect(screen.queryByText("A")).toBeNull();
  expect(screen.getByText("B")).toBeTruthy();
});

test("ordena por Costo al hacer clic en el encabezado", async () => {
  await import("./TablaItems");
  const items = [
    { ...ITEM, seq: 0, descripcion: "Alfa", costo_total: 300 },
    { ...ITEM, seq: 1, descripcion: "Beta", costo_total: 100 },
  ];
  render(<TablaConControl items={items} />);
  fireEvent.click(screen.getByLabelText("Ordenar por Total Costo"));
  const alfa = screen.getByText("Alfa");
  const beta = screen.getByText("Beta");
  // asc: Beta (100) antes que Alfa (300)
  expect(beta.compareDocumentPosition(alfa) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

test("'Limpiar filtros' restablece la vista", async () => {
  await import("./TablaItems");
  const items = [
    { ...ITEM, seq: 0, descripcion: "Excavación manual" },
    { ...ITEM, seq: 1, descripcion: "Concreto clase D" },
  ];
  render(<TablaConControl items={items} />);
  fireEvent.change(screen.getByLabelText("Filtrar Descripción"), { target: { value: "concreto" } });
  expect(screen.queryByText("Excavación manual")).toBeNull();
  fireEvent.click(screen.getByText("Limpiar filtros"));
  expect(screen.getByText("Excavación manual")).toBeTruthy();
});

test("sin control (modo vivo) no aparece la fila de filtros", async () => {
  const { default: TablaItems } = await import("./TablaItems");
  render(<TablaItems corridaId={1} items={[ITEM]} onConfirmado={() => {}} />);
  expect(screen.queryByLabelText("Filtrar Descripción")).toBeNull();
});

test("muestra el unitario contractual y el costo unitario en la fila", async () => {
  await import("./TablaItems");
  const items = [
    { ...ITEM, seq: 0, precio_contractual: 1234, costo_unitario: 567 },
  ];
  render(<TablaConControl items={items} />);
  // cop(): "$" + toLocaleString("es-CO"), sin espacio ni decimales
  expect(screen.getByText("$1.234")).toBeTruthy();
  expect(screen.getByText("$567")).toBeTruthy();
});
