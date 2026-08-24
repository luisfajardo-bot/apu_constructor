import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import TablaItems from "./TablaItems";
import { useCorridaTabla } from "@/lib/corridaTabla";

vi.mock("@/api/corridas", () => ({
  getItem: vi.fn(async () => ({
    seq: 0, descripcion: "Concreto", apu_codigo: "111", apu_turno: "DIURNO",
    apu_nombre: "APU VIEJO",
    status: "matched", explicacion: "", candidatos: [], composicion: [], costo_unitario: 0,
  })),
  confirmar: vi.fn(async () => ({
    id: 1, archivo: "x", estado: "en_revision", modo: "activa", items: [], duracion_ms: null,
    totales: { contractual: 0, costo: 0, margen: 0, margen_pct: 0, n_items: 0, n_revision: 0 },
  })),
  confirmarLote: vi.fn(async () => ({
    id: 1, archivo: "x", estado: "en_revision", modo: "activa", items: [], duracion_ms: null,
    totales: { contractual: 0, costo: 0, margen: 0, margen_pct: 0, n_items: 0, n_revision: 0 },
  })),
  borrarLineas: vi.fn(async () => ({
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
  getApuDetalle: vi.fn(async () => ({
    codigo: "3454", turno: "DIURNO", nombre: "MEZCLA MD12", unidad: "M3", grupo: "PAV",
    costo_unitario: 480000,
    composicion: [{
      insumo_codigo: "999", insumo_nombre: "MEZCLA MD12", unidad: "M3",
      rendimiento: 1, precio_unitario: 480000, fuente_precio: "PRECIO IDU",
      costo: 480000, calidad_cruce: "exacto",
    }],
  })),
  crearApu: vi.fn(async () => ({})),
  editarApu: vi.fn(async () => ({})),
  getGruposApu: vi.fn(async () => ["PAVIMENTOS", "REDES DE ACUEDUCTO"]),
}));
vi.mock("@/api/insumos", () => ({
  listarInsumos: vi.fn(async () => ({ items: [], total: 0, limit: 15, offset: 0 })),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

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

function TablaConControl({ items, readOnly }: { items: typeof ITEM[]; readOnly?: boolean }) {
  const control = useCorridaTabla(items);
  return (
    <TablaItems
      corridaId={1}
      items={control.filtradas}
      control={control}
      onConfirmado={() => {}}
      readOnly={readOnly}
    />
  );
}

function itemsCuatro() {
  return [
    { ...ITEM, seq: 0, item: "1", descripcion: "Excavación manual" },
    { ...ITEM, seq: 1, item: "2", descripcion: "Concreto clase D" },
    { ...ITEM, seq: 2, item: "3", descripcion: "Concreto clase E" },
    { ...ITEM, seq: 3, item: "4", descripcion: "Relleno compactado" },
  ];
}

test("el checkbox de una fila la marca y muestra el contador", async () => {
  render(<TablaConControl items={itemsCuatro()} />);
  fireEvent.click(screen.getByLabelText("Marcar ítem 2"));
  expect(await screen.findByText(/1 línea marcada/i)).toBeTruthy();
});

test("Shift+click marca el rango visible", async () => {
  render(<TablaConControl items={itemsCuatro()} />);
  fireEvent.click(screen.getByLabelText("Marcar ítem 1"));
  fireEvent.click(screen.getByLabelText("Marcar ítem 4"), { shiftKey: true });
  expect(await screen.findByText(/4 líneas marcadas/i)).toBeTruthy();
});

test("marcar todo usa solo lo que dejó pasar el filtro", async () => {
  render(<TablaConControl items={itemsCuatro()} />);
  // "concreto" deja 2 de los 4 ítems visibles
  fireEvent.change(screen.getByLabelText("Filtrar Descripción"), { target: { value: "concreto" } });
  fireEvent.click(screen.getByLabelText(/Marcar todas las líneas/i));
  expect(await screen.findByText(/2 líneas marcadas/i)).toBeTruthy();
});

test("cambiar el filtro no arrastra al lote las filas que dejaron de verse", async () => {
  render(<TablaConControl items={itemsCuatro()} />);
  fireEvent.click(screen.getByLabelText(/Marcar todas las líneas/i)); // marca las 4
  expect(await screen.findByText(/4 líneas marcadas/i)).toBeTruthy();
  // filtrar para dejar 1 visible: las otras 3 siguen en `marcadas` pero ya no cuentan
  fireEvent.change(screen.getByLabelText("Filtrar Descripción"), { target: { value: "clase d" } });
  expect(await screen.findByText(/1 línea marcada/i)).toBeTruthy();
});

test("el ancla del rango sigue al seq, no al índice, cuando el filtro cambia entre el click y el Shift+click", async () => {
  // Seq 3 (ítem 4) es el ancla, marcada en la posición 3 de la vista sin filtrar.
  // El filtro "común" deja afuera los ítems 2 y 3 (posiciones 1 y 2): el seq 3
  // pasa a la posición 1 en la vista filtrada, pero sigue visible.
  const items = [
    { ...ITEM, seq: 0, item: "1", descripcion: "Excavación común" },
    { ...ITEM, seq: 1, item: "2", descripcion: "Perfilado especial A" },
    { ...ITEM, seq: 2, item: "3", descripcion: "Perfilado especial B" },
    { ...ITEM, seq: 3, item: "4", descripcion: "Concreto común anchor" },
    { ...ITEM, seq: 4, item: "5", descripcion: "Relleno común medio" },
    { ...ITEM, seq: 5, item: "6", descripcion: "Base común objetivo" },
  ];
  render(<TablaConControl items={items} />);
  fireEvent.click(screen.getByLabelText("Marcar ítem 4"));
  fireEvent.change(screen.getByLabelText("Filtrar Descripción"), { target: { value: "común" } });
  // Shift+click en el seq 5 (objetivo), posición 3 en la vista filtrada. Si el
  // ancla se leyera como el índice viejo (3, de la vista sin filtrar) en vez de
  // recalcularse por seq, el rango saldría [3,3] (solo el objetivo) y perdería
  // la fila del medio (seq 4): 2 líneas marcadas en vez de 3.
  fireEvent.click(screen.getByLabelText("Marcar ítem 6"), { shiftKey: true });
  expect(await screen.findByText(/3 líneas marcadas/i)).toBeTruthy();
});

test("Asignar manda los seqs marcados con el APU elegido", async () => {
  const { confirmarLote } = await import("@/api/corridas");
  render(<TablaConControl items={itemsCuatro()} />);
  fireEvent.click(screen.getByLabelText("Marcar ítem 1"));
  fireEvent.click(screen.getByLabelText("Marcar ítem 3"));
  const input = await screen.findByPlaceholderText(/Buscar APU/i);
  fireEvent.change(input, { target: { value: "333" } });
  fireEvent.click(await screen.findByText("APU NUEVO"));
  await waitFor(() =>
    expect(confirmarLote).toHaveBeenCalledWith(1, [0, 2], "33333", "DIURNO"));
});

test("Confirmar el APU actual manda solo las filas que tienen APU", async () => {
  const { confirmarLote } = await import("@/api/corridas");
  const items = itemsCuatro().map((it) => (it.seq === 2 ? { ...it, apu_codigo: "" } : it));
  render(<TablaConControl items={items} />);
  fireEvent.click(screen.getByLabelText(/Marcar todas las líneas/i));
  fireEvent.click(screen.getByRole("button", { name: /Confirmar el APU actual/i }));
  await waitFor(() =>
    expect(confirmarLote).toHaveBeenCalledWith(1, [0, 1, 3], undefined, undefined));
});

test("después de asignar se limpia la selección", async () => {
  render(<TablaConControl items={itemsCuatro()} />);
  fireEvent.click(screen.getByLabelText("Marcar ítem 1"));
  const input = await screen.findByPlaceholderText(/Buscar APU/i);
  fireEvent.change(input, { target: { value: "333" } });
  fireEvent.click(await screen.findByText("APU NUEVO"));
  await waitFor(() => expect(screen.queryByText(/líneas marcadas|línea marcada/i)).toBeNull());
});

test("si el lote falla, la selección se conserva", async () => {
  const { confirmarLote } = await import("@/api/corridas");
  vi.mocked(confirmarLote).mockRejectedValueOnce(new Error("boom"));
  render(<TablaConControl items={itemsCuatro()} />);
  fireEvent.click(screen.getByLabelText("Marcar ítem 1"));
  fireEvent.click(screen.getByLabelText("Marcar ítem 2"));
  fireEvent.click(screen.getByRole("button", { name: /Confirmar el APU actual/i }));
  expect(await screen.findByText(/2 líneas marcadas/i)).toBeTruthy();
});

test("con readOnly no hay checkboxes", async () => {
  render(<TablaConControl items={itemsCuatro()} readOnly />);
  expect(screen.queryByLabelText(/Marcar todas las líneas/i)).toBeNull();
});

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

test("con rol editor, el ítem ofrece duplicar el APU y usarlo aquí", async () => {
  render(<TablaItems corridaId={1} items={[ITEM]} onConfirmado={() => {}} puedeEditar />);
  fireEvent.click(screen.getByLabelText("Expandir fila"));
  expect(
    await screen.findByRole("button", { name: /Duplicar este APU/i }),
  ).toBeTruthy();
});

test("sin rol editor no ofrece duplicar", async () => {
  render(<TablaItems corridaId={1} items={[ITEM]} onConfirmado={() => {}} />);
  fireEvent.click(screen.getByLabelText("Expandir fila"));
  await screen.findByText(/Cambiar APU/i);
  expect(screen.queryByRole("button", { name: /Duplicar este APU/i })).toBeNull();
});

test("no ofrece duplicar cuando el ítem no tiene APU asignado", async () => {
  const { getItem } = await import("@/api/corridas");
  vi.mocked(getItem).mockResolvedValueOnce({
    seq: 0, descripcion: "Concreto", apu_codigo: "", apu_turno: "DIURNO",
    apu_nombre: "", status: "matched", explicacion: "", candidatos: [], composicion: [],
    costo_unitario: 0,
  });
  render(<TablaItems corridaId={1} items={[ITEM]} onConfirmado={() => {}} puedeEditar />);
  fireEvent.click(screen.getByLabelText("Expandir fila"));
  await screen.findByText(/Cambiar APU/i);
  expect(screen.queryByRole("button", { name: /Duplicar este APU/i })).toBeNull();
});

test("en corrida congelada no ofrece duplicar", async () => {
  render(
    <TablaItems
      corridaId={1}
      items={[ITEM]}
      onConfirmado={() => {}}
      puedeEditar
      readOnly
    />,
  );
  fireEvent.click(screen.getByLabelText("Expandir fila"));
  expect(screen.queryByRole("button", { name: /Duplicar este APU/i })).toBeNull();
});

test("al crear la copia, el ítem queda reasignado al APU nuevo (sin toast de éxito duplicado)", async () => {
  const { confirmar } = await import("@/api/corridas");
  const { toast } = await import("sonner");
  vi.mocked(toast.success).mockClear();
  render(<TablaItems corridaId={1} items={[ITEM]} onConfirmado={() => {}} puedeEditar />);
  fireEvent.click(screen.getByLabelText("Expandir fila"));
  fireEvent.click(await screen.findByRole("button", { name: /Duplicar este APU/i }));
  // el diálogo abre precargado desde la biblioteca
  fireEvent.change(await screen.findByDisplayValue("MEZCLA MD12"), {
    target: { value: "MEZCLA MD13" },
  });
  fireEvent.click(screen.getByRole("button", { name: /Crear APU/i }));
  await waitFor(() =>
    expect(confirmar).toHaveBeenCalledWith(1, ITEM.seq, "3454-2", "DIURNO"));
  // El diálogo ya confirma la creación con su propio toast; TablaItems no debe
  // apilar un segundo toast de éxito por la reasignación (Fix 3 del review final).
  expect(toast.success).toHaveBeenCalledTimes(1);
  expect(toast.success).not.toHaveBeenCalledWith(
    expect.stringContaining("asignado al ítem"),
  );
});

test("si el APU se crea pero la reasignación falla, el toast lo dice (no sugiere que no pasó nada)", async () => {
  const { confirmar } = await import("@/api/corridas");
  const { toast } = await import("sonner");
  vi.mocked(confirmar).mockRejectedValueOnce(new Error("fallo de red"));
  // Los mocks de este archivo no se resetean entre tests: limpiamos el historial
  // del toast para que el "no llamado con X" de abajo mire solo este test.
  vi.mocked(toast.success).mockClear();
  vi.mocked(toast.error).mockClear();
  render(<TablaItems corridaId={1} items={[ITEM]} onConfirmado={() => {}} puedeEditar />);
  fireEvent.click(screen.getByLabelText("Expandir fila"));
  fireEvent.click(await screen.findByRole("button", { name: /Duplicar este APU/i }));
  fireEvent.change(await screen.findByDisplayValue("MEZCLA MD12"), {
    target: { value: "MEZCLA MD13" },
  });
  fireEvent.click(screen.getByRole("button", { name: /Crear APU/i }));
  // El APU quedó creado (llamó confirmar con el código sugerido) pero la
  // reasignación al ítem falló: el toast tiene que decir ambas cosas, no solo
  // reportar el error como si nada se hubiera creado.
  await waitFor(() =>
    expect(toast.error).toHaveBeenCalledWith(
      "APU 3454-2 creado; no se pudo asignar al ítem — asignalo con Cambiar APU.",
    ));
  expect(toast.success).not.toHaveBeenCalledWith(
    expect.stringContaining("asignado al ítem"),
  );
});

test("regresión: con puedeEditar={false}, 'Confirmar APU actual' sigue visible y funcionando", async () => {
  const { getItem, confirmar } = await import("@/api/corridas");
  vi.mocked(getItem).mockResolvedValueOnce({
    seq: 0, descripcion: "Concreto", apu_codigo: "111", apu_turno: "DIURNO",
    apu_nombre: "APU VIEJO", status: "review", explicacion: "", candidatos: [],
    composicion: [], costo_unitario: 0,
  });
  render(
    <TablaItems
      corridaId={1}
      items={[{ ...ITEM, status: "review" }]}
      onConfirmado={() => {}}
      puedeEditar={false}
    />,
  );
  fireEvent.click(screen.getByLabelText("Expandir fila"));
  // La prop nueva `puedeEditar` solo gatea el botón de duplicar: no debe tocar
  // "Confirmar APU actual" (el backend es el que gatea de verdad).
  const boton = await screen.findByRole("button", { name: /Confirmar APU actual/i });
  fireEvent.click(boton);
  await waitFor(() => expect(confirmar).toHaveBeenCalledWith(1, 0, "111", undefined));
});

test("duplicar en dos filas distintas: gana el pedido más reciente, no el que resuelve último", async () => {
  const { getItem } = await import("@/api/corridas");
  const { getApuDetalle } = await import("@/api/autoria");

  // Dos filas con orígenes distinguibles (código y nombre) para poder afirmar
  // cuál quedó mostrado en el diálogo.
  vi.mocked(getItem)
    .mockImplementationOnce(async () => ({
      seq: 0, descripcion: "Item A", apu_codigo: "3454", apu_turno: "DIURNO",
      apu_nombre: "MEZCLA MD12", status: "matched", explicacion: "",
      candidatos: [], composicion: [], costo_unitario: 0,
    }))
    .mockImplementationOnce(async () => ({
      seq: 1, descripcion: "Item B", apu_codigo: "7788", apu_turno: "DIURNO",
      apu_nombre: "BASE GRANULAR", status: "matched", explicacion: "",
      candidatos: [], composicion: [], costo_unitario: 0,
    }));

  // Diferidos: controlamos a mano el orden de resolución (al revés del orden
  // de los clicks) para reproducir la carrera del hallazgo.
  let resolverA: ((v: unknown) => void) | null = null;
  let resolverB: ((v: unknown) => void) | null = null;
  vi.mocked(getApuDetalle)
    .mockImplementationOnce(() => new Promise((res) => { resolverA = res as (v: unknown) => void; }))
    .mockImplementationOnce(() => new Promise((res) => { resolverB = res as (v: unknown) => void; }));

  const items = [
    { ...ITEM, seq: 0, apu_codigo: "3454" },
    { ...ITEM, seq: 1, apu_codigo: "7788" },
  ];
  render(<TablaItems corridaId={1} items={items} onConfirmado={() => {}} puedeEditar />);

  const chevrones = screen.getAllByLabelText("Expandir fila");
  fireEvent.click(chevrones[0]);
  fireEvent.click(chevrones[1]);

  await waitFor(() =>
    expect(screen.getAllByRole("button", { name: /Duplicar este APU/i })).toHaveLength(2),
  );
  const botones = screen.getAllByRole("button", { name: /Duplicar este APU/i });
  fireEvent.click(botones[0]); // pide duplicar A (seq 0) primero
  fireEvent.click(botones[1]); // pide duplicar B (seq 1) después — este es el pedido vigente

  // Resuelve al revés de los clicks: A (el pedido viejo) llega DESPUÉS que B.
  // `waitFor` daría un falso positivo aquí (ver DialogoAgregarApu.test.tsx): el
  // primer chequeo sin lanzar corta antes de que el setState de la promesa
  // termine de propagar. Por eso se resuelve y se drena la cola de microtasks
  // dentro de `act`, y se afirma después con un `expect` plano.
  await act(async () => {
    resolverB!({
      codigo: "7788", turno: "DIURNO", nombre: "BASE GRANULAR", unidad: "M3",
      grupo: "PAV", costo_unitario: 100000, composicion: [],
    });
    await new Promise((r) => setTimeout(r, 0));
  });
  await act(async () => {
    resolverA!({
      codigo: "3454", turno: "DIURNO", nombre: "MEZCLA MD12", unidad: "M3",
      grupo: "PAV", costo_unitario: 480000, composicion: [],
    });
    await new Promise((r) => setTimeout(r, 0));
  });

  // Gana el pedido más reciente (B), aunque el de A haya resuelto después.
  expect(screen.getByText(/Duplicar APU 7788/)).toBeTruthy();
  expect(screen.queryByText(/Duplicar APU 3454/)).toBeNull();
});

test("borra las líneas marcadas después de confirmar", async () => {
  const { borrarLineas } = await import("@/api/corridas");
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<TablaConControl items={itemsCuatro()} />);
  fireEvent.click(screen.getByLabelText("Marcar ítem 1"));
  fireEvent.click(screen.getByLabelText("Marcar ítem 3"));
  fireEvent.click(await screen.findByText("Borrar"));

  expect(confirmSpy).toHaveBeenCalledWith(expect.stringContaining("2 líneas"));
  await waitFor(() => expect(borrarLineas).toHaveBeenCalledWith(1, [0, 2]));
  confirmSpy.mockRestore();
});

test("cancelar la confirmación no borra nada", async () => {
  const { borrarLineas } = await import("@/api/corridas");
  vi.mocked(borrarLineas).mockClear();
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<TablaConControl items={itemsCuatro()} />);
  fireEvent.click(screen.getByLabelText("Marcar ítem 1"));
  fireEvent.click(await screen.findByText("Borrar"));

  expect(borrarLineas).not.toHaveBeenCalled();
  confirmSpy.mockRestore();
});
