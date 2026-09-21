import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import TablaItems from "./TablaItems";
import { useCorridaTabla } from "@/lib/corridaTabla";

vi.mock("@/api/corridas", () => ({
  getItem: vi.fn(async () => ({
    seq: 0, descripcion: "Concreto", apu_codigo: "111", apu_turno: "DIURNO",
    apu_nombre: "APU VIEJO", codigo_sugerido: "", unidad: "M3",
    status: "matched", explicacion: "", candidatos: [], composicion: [], costo_unitario: 0,
    costo_manual: false,
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
  aplicarSugerencias: vi.fn(async () => ({
    id: 1, archivo: "x", estado: "en_revision", modo: "activa", items: [], duracion_ms: null,
    totales: { contractual: 0, costo: 0, margen: 0, margen_pct: 0, n_items: 0, n_revision: 0 },
  })),
  igualarCostoAlContractual: vi.fn(async () => ({
    id: 1, archivo: "x", estado: "en_revision", modo: "activa", items: [], duracion_ms: null,
    totales: { contractual: 0, costo: 0, margen: 0, margen_pct: 0, n_items: 0, n_revision: 0 },
    igualadas: [0], rechazadas: [],
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
  conflictoApu: vi.fn(async () => ({ campo: null, motivo: null })),
}));
vi.mock("@/api/insumos", () => ({
  listarInsumos: vi.fn(async () => ({ items: [], total: 0, limit: 15, offset: 0 })),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const ITEM = {
  seq: 0, item: "1", descripcion: "Concreto", unidad: "M3", cantidad: 10,
  apu_codigo: "111", apu_nombre: "APU VIEJO", status: "matched", confianza: 1,
  precio_contractual: 0, costo_unitario: 0, margen_unitario: 0, margen_pct: 0,
  contractual_total: 0, costo_total: 0, margen_total: 0, revision: null,
  costo_manual: false,
};

/** Veredicto "cambiar" con APU y turno sugeridos: el único que ofrece Aplicar. */
const VEREDICTO_CAMBIAR = {
  seq: 0, dictamen: "cambiar", apu_sugerido: "222", turno_sugerido: "NOCTURNO",
  confianza: 0.9, justificacion: "El asignado es de otra unidad.", nivel: "profundo",
};

/** La etiqueta del veredicto EN LA FILA. El <option> del filtro de la cabecera
 *  lleva el mismo texto, así que un getByText pelado encuentra dos nodos. */
const celdaVeredicto = (texto: string) =>
  screen.getAllByText(texto).filter((el) => el.tagName === "SPAN")[0];

const veredicto = (seq: number, dictamen: string) => ({
  ...VEREDICTO_CAMBIAR, seq, dictamen,
  apu_sugerido: dictamen === "cambiar" ? "222" : null,
});

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

function TablaConControl({ items, readOnly, puedeEditar }: {
  items: typeof ITEM[]; readOnly?: boolean; puedeEditar?: boolean;
}) {
  const control = useCorridaTabla(items);
  return (
    <TablaItems
      corridaId={1}
      items={control.filtradas}
      control={control}
      onConfirmado={() => {}}
      readOnly={readOnly}
      puedeEditar={puedeEditar}
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
    expect(confirmarLote).toHaveBeenCalledWith(1, [0, 1, 3]));
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

test("al crear la copia, el ítem queda reasignado al APU nuevo (sin toast de éxito duplicado)", async () => {
  const { confirmar } = await import("@/api/corridas");
  const { toast } = await import("sonner");
  vi.mocked(toast.success).mockClear();
  render(<TablaItems corridaId={1} items={[ITEM]} onConfirmado={() => {}} puedeEditar />);
  fireEvent.click(screen.getByLabelText("Expandir fila"));
  fireEvent.click(await screen.findByRole("button", { name: /Armar APU/ }));
  fireEvent.click(await screen.findByRole("button", { name: /Duplicar el APU asignado/ }));
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
  fireEvent.click(await screen.findByRole("button", { name: /Armar APU/ }));
  fireEvent.click(await screen.findByRole("button", { name: /Duplicar el APU asignado/ }));
  fireEvent.change(await screen.findByDisplayValue("MEZCLA MD12"), {
    target: { value: "MEZCLA MD13" },
  });
  fireEvent.click(screen.getByRole("button", { name: /Crear APU/i }));
  // El APU quedó creado (llamó confirmar con el código sugerido) pero la
  // reasignación al ítem falló: el toast tiene que decir ambas cosas, no solo
  // reportar el error como si nada se hubiera creado.
  await waitFor(() =>
    expect(toast.error).toHaveBeenCalledWith(
      "APU 3454-2 creado; no se pudo asignar al ítem — asígnalo con Cambiar APU.",
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

// ─── columna Veredicto (revisión con IA) ─────────────────────────────────────

test("los cuatro dictámenes se muestran con etiqueta y color distinguibles", () => {
  const items = ["ok", "dudoso", "cambiar", "sin_apu"].map((d, i) => ({
    ...ITEM, seq: i, item: String(i + 1), descripcion: `Fila ${i}`,
    revision: veredicto(i, d),
  }));
  render(<TablaConControl items={items} />);
  const etiquetas = ["✔ ok", "⚠ dudoso", "↔ cambiar", "✖ sin APU"];
  const clases = etiquetas.map((t) => celdaVeredicto(t).className);
  // las cuatro presentes...
  expect(clases).toHaveLength(4);
  // ...y con cuatro colores distintos (si compartieran clase, no se distinguen)
  expect(new Set(clases).size).toBe(4);
});

test("una fila sin veredicto muestra un guion y no rompe la tabla", () => {
  // Con la columna condicionada a que HAYA veredictos, el caso interesante es la
  // fila sin revisar en una corrida ya revisada (no la corrida entera sin revisar).
  render(<TablaConControl items={[
    { ...ITEM, seq: 0, revision: null },
    { ...ITEM, seq: 1, item: "2", descripcion: "Otra", revision: { ...VEREDICTO_CAMBIAR, seq: 1 } },
  ]} />);
  expect(screen.getByText("—")).toBeTruthy();
  expect(screen.getByText("Concreto")).toBeTruthy();
  expect(screen.queryByRole("button", { name: /^Aplicar$/ })).toBeNull();
});

test("el title de la celda dice el nivel en palabras, la confianza y la justificación", () => {
  render(<TablaConControl items={[{ ...ITEM, revision: VEREDICTO_CAMBIAR }]} />);
  // Un análisis a fondo SÍ miró la composición: la celda tiene que poder decirlo.
  expect(celdaVeredicto("↔ cambiar").getAttribute("title"))
    .toBe("Análisis a fondo · confianza 90% — El asignado es de otra unidad.");
});

test("un veredicto de barrido se anuncia como triaje, no como análisis a fondo", () => {
  const revision = {
    ...VEREDICTO_CAMBIAR, dictamen: "ok", apu_sugerido: null, turno_sugerido: null,
    nivel: "barrido", confianza: 0, justificacion: "Sin objeciones en el barrido.",
  };
  render(<TablaConControl items={[{ ...ITEM, revision }]} />);
  const title = celdaVeredicto("✔ ok").getAttribute("title") ?? "";
  expect(title.startsWith("Triaje rápido · confianza 0%")).toBe(true);
  expect(title.includes("Análisis a fondo")).toBe(false);
});

// ─── la columna solo existe si hay algo que mostrar ──────────────────────────

/** Columnas de la primera fila de la cabecera (la de los rótulos). */
const colsCabecera = () =>
  document.querySelectorAll("thead tr")[0].querySelectorAll("th").length;

test("sin un solo veredicto, la columna Veredicto no se dibuja", () => {
  render(<TablaConControl items={[{ ...ITEM, revision: null }]} />);
  expect(screen.queryByLabelText("Ordenar por Veredicto")).toBeNull();
  expect(screen.queryByLabelText("Filtrar Veredicto")).toBeNull();
});

test("con al menos un veredicto, la columna Veredicto aparece", () => {
  render(<TablaConControl items={[
    { ...ITEM, seq: 0, revision: null },
    { ...ITEM, seq: 1, item: "2", descripcion: "Otra", revision: { ...VEREDICTO_CAMBIAR, seq: 1 } },
  ]} />);
  expect(screen.getByLabelText("Ordenar por Veredicto")).toBeTruthy();
  expect(screen.getByLabelText("Filtrar Veredicto")).toBeTruthy();
});

test("el colSpan de la fila expandida cuadra con la cabecera SIN veredictos", async () => {
  render(<TablaConControl items={[{ ...ITEM, revision: null }]} />);
  fireEvent.click(screen.getByLabelText("Expandir fila"));
  await waitFor(() => {
    const celda = document.querySelector("tbody td[colspan]") as HTMLTableCellElement;
    expect(Number(celda.getAttribute("colspan"))).toBe(colsCabecera());
  });
});

test("el colSpan de la fila expandida cuadra con la cabecera CON veredictos", async () => {
  render(<TablaConControl items={[{ ...ITEM, revision: VEREDICTO_CAMBIAR }]} />);
  fireEvent.click(screen.getByLabelText("Expandir fila"));
  await waitFor(() => {
    const celda = document.querySelector("tbody td[colspan]") as HTMLTableCellElement;
    expect(Number(celda.getAttribute("colspan"))).toBe(colsCabecera());
  });
});

test("Aplicar manda el seq, el APU sugerido y el turno de la sugerencia", async () => {
  const { aplicarSugerencias } = await import("@/api/corridas");
  vi.mocked(aplicarSugerencias).mockClear();
  const items = [{ ...ITEM, seq: 7, revision: { ...VEREDICTO_CAMBIAR, seq: 7 } }];
  render(<TablaConControl items={items} puedeEditar />);
  fireEvent.click(screen.getByRole("button", { name: /^Aplicar$/ }));
  await waitFor(() =>
    expect(aplicarSugerencias).toHaveBeenCalledWith(1, [
      { seq: 7, apu_codigo: "222", shift: "NOCTURNO" },
    ]));
});

test("un dictamen que no es 'cambiar' no ofrece Aplicar aunque traiga APU sugerido", () => {
  // El backend garantiza que el código no sobrevive con otro dictamen; la
  // interfaz decide por el dictamen igual, sin apoyarse en esa garantía.
  const items = [{
    ...ITEM, revision: { ...VEREDICTO_CAMBIAR, dictamen: "ok", apu_sugerido: "222" },
  }];
  render(<TablaConControl items={items} puedeEditar />);
  expect(screen.queryByRole("button", { name: /^Aplicar$/ })).toBeNull();
});

test("sin rol editor no aparece Aplicar", () => {
  render(<TablaConControl items={[{ ...ITEM, revision: VEREDICTO_CAMBIAR }]} />);
  expect(screen.queryByRole("button", { name: /^Aplicar$/ })).toBeNull();
});

test("en corrida congelada no aparece Aplicar", () => {
  render(
    <TablaConControl items={[{ ...ITEM, revision: VEREDICTO_CAMBIAR }]} puedeEditar readOnly />,
  );
  expect(screen.queryByRole("button", { name: /^Aplicar$/ })).toBeNull();
});

test("si aplicar la sugerencia falla, lo dice con un toast de error", async () => {
  const { aplicarSugerencias } = await import("@/api/corridas");
  const { toast } = await import("sonner");
  vi.mocked(aplicarSugerencias).mockRejectedValueOnce(new Error("fallo de red"));
  vi.mocked(toast.error).mockClear();
  render(<TablaConControl items={[{ ...ITEM, revision: VEREDICTO_CAMBIAR }]} puedeEditar />);
  fireEvent.click(screen.getByRole("button", { name: /^Aplicar$/ }));
  await waitFor(() => expect(toast.error).toHaveBeenCalledWith("fallo de red"));
});

test("filtra por el desplegable de Veredicto", () => {
  const items = [
    { ...ITEM, seq: 0, descripcion: "Alfa", revision: veredicto(0, "ok") },
    { ...ITEM, seq: 1, descripcion: "Beta", revision: veredicto(1, "cambiar") },
    { ...ITEM, seq: 2, descripcion: "Gama", revision: null },
  ];
  render(<TablaConControl items={items} />);
  fireEvent.change(screen.getByLabelText("Filtrar Veredicto"), { target: { value: "cambiar" } });
  expect(screen.queryByText("Alfa")).toBeNull();
  expect(screen.getByText("Beta")).toBeTruthy();
  expect(screen.queryByText("Gama")).toBeNull();
});

test("el desplegable de Veredicto encuentra las filas sin revisar", () => {
  // El caso que importa: la IA falló 40 de 300 filas. Sin esta opción esas filas
  // salen con un guion igual que cualquier otra y no hay forma de localizarlas.
  const items = [
    { ...ITEM, seq: 0, descripcion: "Alfa", revision: veredicto(0, "ok") },
    { ...ITEM, seq: 1, descripcion: "Beta", revision: null },
    { ...ITEM, seq: 2, descripcion: "Gama", revision: null },
  ];
  render(<TablaConControl items={items} />);
  const select = screen.getByLabelText("Filtrar Veredicto") as HTMLSelectElement;
  const sinRevisar = [...select.options].find((o) => o.text === "— sin revisar");
  expect(sinRevisar).toBeTruthy();

  fireEvent.change(select, { target: { value: sinRevisar!.value } });
  expect(screen.queryByText("Alfa")).toBeNull();
  expect(screen.getByText("Beta")).toBeTruthy();
  expect(screen.getByText("Gama")).toBeTruthy();
});

test("si todas las filas tienen veredicto, no se ofrece \"sin revisar\"", () => {
  render(<TablaConControl items={[
    { ...ITEM, seq: 0, descripcion: "Alfa", revision: veredicto(0, "ok") },
  ]} />);
  const select = screen.getByLabelText("Filtrar Veredicto") as HTMLSelectElement;
  expect([...select.options].map((o) => o.text)).toEqual(["(todas)", "✔ ok"]);
});

// ─── La puerta de entrada a la mesa de composición ───────────────────────────
// Componer ya NO depende de haber corrido la revisión con IA sobre toda la corrida:
// se ofrece en cualquier fila sin APU (o con veredicto `sin_apu`), desde la columna
// Acciones. El botón solo AVISA al padre con el seq; navegar es de la página, que es
// la que está dentro del Router (esta tabla se monta sin él en estos tests).

/** Veredicto `sin_apu`: el que ofrece Componer aunque la fila SÍ tenga APU. */
const VEREDICTO_SIN_APU = {
  seq: 0, dictamen: "sin_apu", apu_sugerido: null, turno_sugerido: null,
  confianza: 0.8, justificacion: "No hay sardineles A-10.", nivel: "profundo",
};

test("con dictamen sin_apu y rol editor aparece Componer", () => {
  render(
    <TablaItems corridaId={1} items={[{ ...ITEM, revision: VEREDICTO_SIN_APU }]}
      onConfirmado={() => {}} onComponer={() => {}} puedeEditar />,
  );
  expect(screen.getByRole("button", { name: /^Componer$/ })).toBeTruthy();
});

test("los demás dictámenes no ofrecen Componer", () => {
  const items = [
    { ...ITEM, seq: 0, descripcion: "Alfa", revision: veredicto(0, "ok") },
    { ...ITEM, seq: 1, descripcion: "Beta", revision: veredicto(1, "cambiar") },
    { ...ITEM, seq: 2, descripcion: "Gama", revision: veredicto(2, "dudoso") },
  ];
  render(<TablaItems corridaId={1} items={items} onConfirmado={() => {}}
                     onComponer={() => {}} puedeEditar />);
  expect(screen.queryByRole("button", { name: /^Componer$/ })).toBeNull();
});

test("sin rol editor no aparece Componer", () => {
  render(
    <TablaItems corridaId={1} items={[{ ...ITEM, revision: VEREDICTO_SIN_APU }]}
      onConfirmado={() => {}} onComponer={() => {}} />,
  );
  expect(screen.queryByRole("button", { name: /^Componer$/ })).toBeNull();
});

test("en corrida congelada no aparece Componer", () => {
  render(
    <TablaItems corridaId={1} items={[{ ...ITEM, revision: VEREDICTO_SIN_APU }]}
      onConfirmado={() => {}} onComponer={() => {}} puedeEditar readOnly />,
  );
  expect(screen.queryByRole("button", { name: /^Componer$/ })).toBeNull();
});

test("una fila sin APU ofrece componer sin haber corrido la revisión", () => {
  render(
    <TablaItems corridaId={1}
      items={[{ ...ITEM, apu_codigo: "", apu_nombre: "", revision: null }]}
      onConfirmado={() => {}} onComponer={() => {}} puedeEditar />,
  );
  expect(screen.getByRole("button", { name: /^Componer$/ })).toBeTruthy();
});

test("una fila CON APU y sin veredicto no ofrece componer", () => {
  render(
    <TablaItems corridaId={1} items={[{ ...ITEM, revision: null }]}
      onConfirmado={() => {}} onComponer={() => {}} puedeEditar />,
  );
  expect(screen.queryByRole("button", { name: /^Componer$/ })).toBeNull();
});

test("una fila con costo puesto a mano SÍ ofrece componer", () => {
  // Igualar al contractual era la salida cuando no había APU: es justo la fila que
  // más necesita poder componerse. Asignar un APU de verdad borra el costo manual
  // solo (`actualizar_eleccion`), así que bloquearla acá cerraría el camino en las
  // líneas que más lo piden (pedido explícito del dueño del producto).
  render(
    <TablaItems corridaId={1}
      items={[{ ...ITEM, apu_codigo: "", apu_nombre: "", costo_manual: true }]}
      onConfirmado={() => {}} onComponer={() => {}} puedeEditar />,
  );
  expect(screen.getByRole("button", { name: /^Componer$/ })).toBeTruthy();
});

test("Componer avisa al padre con el seq de ESA fila", () => {
  const onComponer = vi.fn();
  const items = [
    { ...ITEM, seq: 0, descripcion: "Alfa" },
    { ...ITEM, seq: 5, item: "2", descripcion: "SARDINEL A-10",
      apu_codigo: "", apu_nombre: "" },
  ];
  render(<TablaItems corridaId={1} items={items} onConfirmado={() => {}}
                     onComponer={onComponer} puedeEditar />);
  fireEvent.click(screen.getByRole("button", { name: /^Componer$/ }));
  expect(onComponer).toHaveBeenCalledWith(5);
});

// ─── Igualar costo al contractual (proyectos especiales) ────────────────────

test("con filas marcadas aparece el botón de igualar al contractual", async () => {
  render(<TablaConControl items={itemsCuatro()} puedeEditar />);
  fireEvent.click(screen.getByLabelText("Marcar ítem 1"));
  expect(await screen.findByText(/Igualar costo al contractual/i)).toBeTruthy();
});

test("igualar manda los seqs marcados", async () => {
  const { igualarCostoAlContractual } = await import("@/api/corridas");
  render(<TablaConControl items={itemsCuatro()} puedeEditar />);
  fireEvent.click(screen.getByLabelText("Marcar ítem 1"));
  fireEvent.click(screen.getByLabelText("Marcar ítem 2"));
  fireEvent.click(await screen.findByText(/Igualar costo al contractual/i));
  await waitFor(() =>
    expect(igualarCostoAlContractual).toHaveBeenCalledWith(1, [0, 1]),
  );
});

test("sin permiso de editor no hay botón de igualar", async () => {
  render(<TablaConControl items={itemsCuatro()} puedeEditar={false} />);
  fireEvent.click(screen.getByLabelText("Marcar ítem 1"));
  // La barra sí aparece (confirmar y borrar los puede un rol consulta), el botón no.
  expect(await screen.findByText(/Confirmar el APU actual/i)).toBeTruthy();
  expect(screen.queryByText(/Igualar costo al contractual/i)).toBeNull();
});

test("una respuesta con rechazadas muestra un toast de error", async () => {
  const { igualarCostoAlContractual } = await import("@/api/corridas");
  const { toast } = await import("sonner");
  vi.mocked(toast.error).mockClear();
  vi.mocked(igualarCostoAlContractual).mockResolvedValueOnce({
    id: 1, archivo: "x", estado: "en_revision", modo: "activa", items: [], duracion_ms: null,
    totales: { contractual: 0, costo: 0, margen: 0, margen_pct: 0, n_items: 0, n_revision: 0 },
    igualadas: [], rechazadas: [0],
  });
  render(<TablaConControl items={itemsCuatro()} puedeEditar />);
  fireEvent.click(screen.getByLabelText("Marcar ítem 1"));
  fireEvent.click(await screen.findByText(/Igualar costo al contractual/i));
  await waitFor(() => expect(toast.error).toHaveBeenCalledWith(
    expect.stringContaining("Sin tocar por contractual en $0"),
  ));
});

test("si igualar falla, muestra un toast de error y NO limpia la selección", async () => {
  const { igualarCostoAlContractual } = await import("@/api/corridas");
  const { toast } = await import("sonner");
  vi.mocked(toast.error).mockClear();
  vi.mocked(igualarCostoAlContractual).mockRejectedValueOnce(new Error("boom"));
  render(<TablaConControl items={itemsCuatro()} puedeEditar />);
  fireEvent.click(screen.getByLabelText("Marcar ítem 1"));
  fireEvent.click(await screen.findByText(/Igualar costo al contractual/i));
  await waitFor(() => expect(toast.error).toHaveBeenCalledWith("boom"));
  // La selección sobrevive a propósito: el usuario puede reintentar sin volver a marcar.
  expect(await screen.findByText(/1 línea marcada/i)).toBeTruthy();
});

test("la fila con costo a mano muestra el badge", () => {
  render(
    <TablaConControl
      items={[{ ...ITEM, seq: 0, costo_unitario: 92106000, costo_manual: true }]}
    />,
  );
  expect(screen.getByText("a mano")).toBeTruthy();
});

test("sin costo a mano no hay badge", () => {
  render(<TablaConControl items={[{ ...ITEM, seq: 0, costo_manual: false }]} />);
  expect(screen.queryByText("a mano")).toBeNull();
});

test("en solo lectura no hay botón de igualar", () => {
  render(<TablaConControl items={itemsCuatro()} readOnly={true} />);
  expect(screen.queryByText(/Igualar costo al contractual/i)).toBeNull();
});

test("confirmar el APU actual no toca las filas con costo a mano", async () => {
  const { confirmarLote } = await import("@/api/corridas");
  render(
    <TablaConControl
      items={[
        { ...ITEM, seq: 0, item: "1", costo_manual: true },
        { ...ITEM, seq: 1, item: "2", costo_manual: false },
      ]}
    />,
  );
  fireEvent.click(screen.getByLabelText(/Marcar todas las líneas/i));
  fireEvent.click(await screen.findByText(/Confirmar el APU actual/i));
  await waitFor(() => expect(confirmarLote).toHaveBeenCalledWith(1, [1]));
});

/** El badge de estado EN LA FILA. El <option> del filtro de la cabecera lleva el mismo
 *  texto, así que un getByText pelado encuentra dos nodos (igual que celdaVeredicto). */
const badgeEstado = (texto: string) =>
  screen.queryAllByText(texto).filter((el) => el.tagName === "SPAN");

test("la fila con costo a mano muestra el estado CONTRACTUAL, no CONFIRM", () => {
  render(
    <TablaConControl
      items={[{ ...ITEM, seq: 0, status: "confirmed", costo_manual: true }]}
    />,
  );
  expect(badgeEstado("CONTRACTUAL")).toHaveLength(1);
  expect(badgeEstado("CONFIRM")).toHaveLength(0);
});

test("una fila confirmada normal sigue mostrando CONFIRM", () => {
  render(
    <TablaConControl
      items={[{ ...ITEM, seq: 0, status: "confirmed", costo_manual: false }]}
    />,
  );
  expect(badgeEstado("CONFIRM")).toHaveLength(1);
  expect(badgeEstado("CONTRACTUAL")).toHaveLength(0);
});

test("al desplegar una fila se ve la descripción completa de la actividad", async () => {
  const LARGA =
    "SUMINISTRO E INSTALACION DE TUBERIA PVC SANITARIA DE 6 PULGADAS INCLUYE " +
    "ACCESORIOS, EXCAVACION, CAMA DE ARENA Y RETIRO DE SOBRANTES A BOTADERO AUTORIZADO";
  const { default: TablaItems } = await import("./TablaItems");
  const mod = await import("@/api/corridas");
  vi.mocked(mod.getItem).mockResolvedValueOnce({
    seq: 0, descripcion: LARGA, apu_codigo: "111", apu_turno: "DIURNO",
    apu_nombre: "APU VIEJO", status: "matched", explicacion: "",
    candidatos: [], composicion: [], costo_unitario: 0, costo_manual: false,
  });
  render(
    <TablaItems
      corridaId={1}
      items={[{ ...ITEM, descripcion: LARGA }]}
      onConfirmado={() => {}}
    />,
  );

  // Colapsada: la descripción vive solo en la fila.
  expect(screen.getAllByText(LARGA)).toHaveLength(1);

  fireEvent.click(screen.getByLabelText("Expandir fila"));
  await screen.findByText(/APU: 111/);

  // Desplegada: el panel la repite completa, bajo su propio encabezado.
  expect(screen.getByText(/Actividad de la licitación/i)).toBeTruthy();
  expect(screen.getAllByText(LARGA)).toHaveLength(2);
});

// ─── Armar APU (reemplaza a Duplicar) ────────────────────────────────────────

test("el botón Armar APU aparece en una fila CON APU, y ya no el de duplicar", async () => {
  const { default: TablaItems } = await import("./TablaItems");
  render(<TablaItems corridaId={1} items={[ITEM]} onConfirmado={() => {}}
                     puedeEditar />);

  fireEvent.click(screen.getByLabelText("Expandir fila"));
  await screen.findByText(/APU: 111/);          // el detalle ya cargó

  expect(screen.getByRole("button", { name: /Armar APU/ })).toBeTruthy();
  // El botón viejo era condicional y con otro texto: ya no existe.
  expect(screen.queryByRole("button", { name: /Duplicar este APU y usarlo aquí/ }))
    .toBeNull();
});

test("el botón Armar APU aparece también en una fila SIN APU", async () => {
  // Es el caso que antes NO tenía botón: sin APU no había nada que duplicar.
  const { getItem } = await import("@/api/corridas");
  vi.mocked(getItem).mockResolvedValueOnce({
    seq: 0, descripcion: "Concreto", apu_codigo: "", apu_turno: "DIURNO",
    apu_nombre: "(sin base — armar manual)", codigo_sugerido: "9001", unidad: "M3",
    status: "new", explicacion: "", candidatos: [], composicion: [],
    costo_unitario: 0, costo_manual: false,
  });
  const { default: TablaItems } = await import("./TablaItems");
  render(<TablaItems corridaId={1} onConfirmado={() => {}} puedeEditar
                     items={[{ ...ITEM, apu_codigo: null, status: "new" }]} />);

  fireEvent.click(screen.getByLabelText("Expandir fila"));

  expect(await screen.findByRole("button", { name: /Armar APU/ })).toBeTruthy();
});

test("sin rol editor el botón Armar APU no aparece", async () => {
  const { default: TablaItems } = await import("./TablaItems");
  // `puedeEditar` es false por defecto en el componente.
  render(<TablaItems corridaId={1} items={[ITEM]} onConfirmado={() => {}} />);

  fireEvent.click(screen.getByLabelText("Expandir fila"));
  await screen.findByText(/APU: 111/);

  expect(screen.queryByRole("button", { name: /Armar APU/ })).toBeNull();
});

test("con la corrida congelada el botón Armar APU no aparece", async () => {
  const { default: TablaItems } = await import("./TablaItems");
  render(<TablaItems corridaId={1} items={[ITEM]} onConfirmado={() => {}}
                     puedeEditar readOnly />);

  fireEvent.click(screen.getByLabelText("Expandir fila"));
  await screen.findByText(/APU: 111/);

  expect(screen.queryByRole("button", { name: /Armar APU/ })).toBeNull();
});
