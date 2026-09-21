import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

vi.mock("react-router-dom", () => ({
  useParams: () => ({ id: "1" }),
  // Corrida navega a la mesa de composición desde la columna Acciones.
  useNavigate: () => vi.fn(),
  // `Link` entra al mock porque el encabezado enlaza a las distancias del proyecto;
  // sin el stub, el componente revienta con Link undefined.
  Link: ({ to, children, ...resto }: { to: string; children: React.ReactNode }) => (
    <a href={to} {...resto}>{children}</a>
  ),
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn() },
}));
// Corrida usa useAuth() para calcular `puedeEditar` (rol -> TablaItems y botón
// "Revisar con IA"). El rol es mutable para poder probar el caso sin permisos.
let rol: "consulta" | "editor" | "admin" = "editor";
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ perfil: { rol } }) }));

function fila(p: Record<string, unknown>) {
  return {
    seq: 0, item: "1", descripcion: "X", unidad: "M3", cantidad: 1,
    apu_codigo: "A", apu_nombre: "APU A", status: "auto", confianza: 1,
    precio_contractual: 0, costo_unitario: 0, margen_unitario: 0, margen_pct: 0,
    contractual_total: 0, costo_total: 0, margen_total: 0, ...p,
  };
}

const CORRIDA = {
  id: 1, archivo: "obra.xlsx", estado: "en_revision", modo: "activa", duracion_ms: 1000,
  ia_disponible: true, armado: null,
  items: [
    fila({ seq: 0, descripcion: "Excavación", unidad: "M3", contractual_total: 1000 }),
    fila({ seq: 1, descripcion: "Concreto", unidad: "M2", contractual_total: 500 }),
  ],
  totales: { contractual: 1500, costo: 0, margen: 1500, margen_pct: 1, n_items: 2, n_revision: 0 },
};

vi.mock("@/api/corridas", () => ({
  getCorrida: vi.fn(async () => CORRIDA),
  descargarCuadro: vi.fn(),
  congelarCorrida: vi.fn(),
  activarCorrida: vi.fn(),
  revisarCorridaStream: vi.fn(async () => RESUMEN),
  aplicarSugerencias: vi.fn(async () => CORRIDA),
  reanudarArmado: vi.fn(async () => CORRIDA),
  igualarPorUmbral: vi.fn(async () => CORRIDA),
}));
// TablaItems importa BuscadorApu -> @/api/autoria -> @/api/client -> @/lib/supabase,
// que crea el cliente de Supabase al cargar el módulo (falla sin envs en test). Se
// mockea aquí (igual que en TablaItems.test.tsx) solo para evitar esa carga real.
vi.mock("@/api/autoria", () => ({
  listarApus: vi.fn(async () => ({ items: [], total: 0, limit: 15, offset: 0 })),
}));

const RESUMEN = { total: 2, ok: 0, dudoso: 1, cambiar: 1, sin_apu: 0, sin_veredicto: 0 };

/** Fila con dictamen "cambiar": la única que ofrece aplicar la sugerencia. */
const cambiar = (seq: number, apu: string) => ({
  seq, dictamen: "cambiar", apu_sugerido: apu, turno_sugerido: "NOCTURNO",
  confianza: 0.8, justificacion: "Otro candidato encaja mejor.", nivel: "profundo",
});

const boton = (re: RegExp) => screen.getByRole("button", { name: re }) as HTMLButtonElement;

beforeEach(() => { rol = "editor"; });

test("al filtrar por Und, los totales y el contador recalculan sobre lo filtrado", async () => {
  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);

  // Carga async de la corrida (aparecen las dos filas)
  await screen.findByText("Excavación");
  expect(screen.getByText("Concreto")).toBeTruthy();

  // Filtra a M2 -> queda 1 de 2 ítems
  fireEvent.change(screen.getByLabelText("Filtrar Und"), { target: { value: "M2" } });
  expect(screen.queryByText("Excavación")).toBeNull();
  expect(screen.getByText(/1 de 2 ítems/)).toBeTruthy();

  // Un refactor que fije `disabled` en `true` no debe dejar a todo el mundo sin
  // poder descargar: esta corrida no tiene líneas sin APU.
  expect((screen.getByRole("button", { name: /descargar cuadro/i }) as HTMLButtonElement).disabled)
    .toBe(false);
});

test("muestra la lista de precios de la corrida cuando no es Principal", async () => {
  const { default: Corrida } = await import("./Corrida");
  const { getCorrida } = await import("@/api/corridas");
  (getCorrida as unknown as { mockResolvedValueOnce: (v: unknown) => void }).mockResolvedValueOnce({
    ...CORRIDA,
    lista_precios_id: 2,
    lista_nombre: "NP Calle 13",
  });

  render(<Corrida />);

  await screen.findByText("Excavación");
  expect(screen.getByText("NP Calle 13")).toBeTruthy();
});

test("con la corrida armándose (otra pestaña/F5), el botón Agregar líneas no aparece", async () => {
  const { default: Corrida } = await import("./Corrida");
  const { getCorrida } = await import("@/api/corridas");
  (getCorrida as unknown as { mockResolvedValueOnce: (v: unknown) => void }).mockResolvedValueOnce({
    ...CORRIDA,
    estado: "armando",
    modo: "activa",
  });

  render(<Corrida />);

  await screen.findByText("Excavación");
  expect(screen.queryByText("Agregar líneas")).toBeNull();
});

test("con la corrida en_revision, el botón Agregar líneas sí aparece", async () => {
  const { default: Corrida } = await import("./Corrida");
  const { getCorrida } = await import("@/api/corridas");
  (getCorrida as unknown as { mockResolvedValueOnce: (v: unknown) => void }).mockResolvedValueOnce({
    ...CORRIDA,
    estado: "en_revision",
    modo: "activa",
  });

  render(<Corrida />);

  await screen.findByText("Excavación");
  expect(screen.getByText("Agregar líneas")).toBeTruthy();
});


test("desde la corrida se puede ir a las distancias del proyecto", async () => {
  const { getCorrida } = await import("@/api/corridas");
  (getCorrida as unknown as { mockResolvedValueOnce: (v: unknown) => void }).mockResolvedValueOnce({
    ...CORRIDA, carpeta_id: 7,
    transporte: { km_botadero: 34, km_mezclas: 28, km_granulares: 32,
                  peaje_aplica: true, peaje_valor: 12400, ajustes: 0 },
  });
  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  const enlace = await screen.findByRole("link", { name: /botadero 34 km/i });
  expect(enlace.getAttribute("href")).toBe("/proyecto/7/distancias");
});

test("sin distancias cargadas, la corrida igual ofrece ir a definirlas", async () => {
  const { getCorrida } = await import("@/api/corridas");
  (getCorrida as unknown as { mockResolvedValueOnce: (v: unknown) => void }).mockResolvedValueOnce({
    ...CORRIDA, carpeta_id: 7, transporte: null,
  });
  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  // Es justo cuando MAS hace falta el acceso: no hay distancias que mostrar todavia.
  const enlace = await screen.findByRole("link", { name: /definir distancias del proyecto/i });
  expect(enlace.getAttribute("href")).toBe("/proyecto/7/distancias");
});

// `jest-dom` no es dependencia de este repo: nada de
// toBeDisabled()/toBeInTheDocument(), se mira la propiedad `disabled` del
// <button> y se usa toBeTruthy().
const SIN_APU_ITEMS = [
  fila({ seq: 0, descripcion: "Excavación" }),
  fila({ seq: 1, descripcion: "Actividad rara", apu_codigo: "", apu_nombre: "" }),
];

test("bloquea congelar y descargar cuando hay líneas sin APU", async () => {
  const { getCorrida } = await import("@/api/corridas");
  (getCorrida as unknown as { mockResolvedValueOnce: (v: unknown) => void }).mockResolvedValueOnce({
    ...CORRIDA,
    items: SIN_APU_ITEMS,
  });

  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  await screen.findByText("Actividad rara");

  expect((screen.getByRole("button", { name: /descargar cuadro/i }) as HTMLButtonElement).disabled)
    .toBe(true);
  expect((screen.getByRole("button", { name: /^congelar$/i }) as HTMLButtonElement).disabled)
    .toBe(true);
  expect(screen.getByText(/1 sin APU/)).toBeTruthy();
});

test("el contador de sin APU filtra la tabla a esas líneas", async () => {
  const { getCorrida } = await import("@/api/corridas");
  (getCorrida as unknown as { mockResolvedValueOnce: (v: unknown) => void }).mockResolvedValueOnce({
    ...CORRIDA,
    items: SIN_APU_ITEMS,
  });

  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  await screen.findByText("Actividad rara");

  fireEvent.click(screen.getByText(/1 sin APU/));
  expect(screen.queryByText("Excavación")).toBeNull();
  expect(screen.getByText("Actividad rara")).toBeTruthy();
});

test("en una corrida congelada con líneas sin APU, Activar NO se bloquea", async () => {
  const { getCorrida } = await import("@/api/corridas");
  (getCorrida as unknown as { mockResolvedValueOnce: (v: unknown) => void }).mockResolvedValueOnce({
    ...CORRIDA,
    modo: "congelada",
    items: SIN_APU_ITEMS,
  });

  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  await screen.findByText("Actividad rara");

  // Salir de congelada es justamente lo que hay que poder hacer para ir a
  // asignar los APUs que faltan.
  expect((screen.getByRole("button", { name: /^activar$/i }) as HTMLButtonElement).disabled)
    .toBe(false);
});

test("la caja de filtro de APU usa \"(sin APU)\" como placeholder, no como value", async () => {
  const { getCorrida } = await import("@/api/corridas");
  (getCorrida as unknown as { mockResolvedValueOnce: (v: unknown) => void }).mockResolvedValueOnce({
    ...CORRIDA,
    items: SIN_APU_ITEMS,
  });

  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  await screen.findByText("Actividad rara");

  fireEvent.click(screen.getByText(/1 sin APU/));
  const caja = screen.getByLabelText("Filtrar APU") as HTMLInputElement;
  // El value queda vacío: nada que editar parcialmente. El rótulo es placeholder.
  expect(caja.value).toBe("");
  expect(caja.placeholder).toBe("(sin APU)");

  // Se sale del estado como de cualquier otro filtro: escribir encima lo
  // reemplaza por un filtro de texto normal.
  fireEvent.change(caja, { target: { value: "APU A" } });
  expect((screen.getByLabelText("Filtrar APU") as HTMLInputElement).value).toBe("APU A");
  expect(screen.getByText("Excavación")).toBeTruthy();
  expect(screen.queryByText("Actividad rara")).toBeNull();
});

test("un segundo clic en el contador de sin APU apaga el filtro", async () => {
  const { getCorrida } = await import("@/api/corridas");
  (getCorrida as unknown as { mockResolvedValueOnce: (v: unknown) => void }).mockResolvedValueOnce({
    ...CORRIDA,
    items: SIN_APU_ITEMS,
  });

  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  await screen.findByText("Actividad rara");

  fireEvent.click(screen.getByText(/1 sin APU/));
  expect(screen.queryByText("Excavación")).toBeNull();

  fireEvent.click(screen.getByText(/1 sin APU/));
  expect(screen.getByText("Excavación")).toBeTruthy();
  expect(screen.getByText("Actividad rara")).toBeTruthy();
});


// ─── Revisar con IA ──────────────────────────────────────────────────────────

test("sin IA en el servidor el botón queda deshabilitado y dice por qué", async () => {
  const { getCorrida } = await import("@/api/corridas");
  vi.mocked(getCorrida).mockResolvedValueOnce({ ...CORRIDA, ia_disponible: false });
  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  await screen.findByText("Excavación");

  const b = boton(/revisar .* con IA/i);
  expect(b.disabled).toBe(true);
  expect(b.getAttribute("title")).toMatch(/ANTHROPIC_API_KEY/);
});

test("con la corrida congelada no se puede revisar", async () => {
  const { getCorrida } = await import("@/api/corridas");
  vi.mocked(getCorrida).mockResolvedValueOnce({ ...CORRIDA, modo: "congelada" });
  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  await screen.findByText("Excavación");

  const b = boton(/revisar .* con IA/i);
  expect(b.disabled).toBe(true);
  expect(b.getAttribute("title")).toMatch(/congelada/i);
});

test("el botón de umbral no aparece con la corrida congelada", async () => {
  const { getCorrida } = await import("@/api/corridas");
  vi.mocked(getCorrida).mockResolvedValueOnce({ ...CORRIDA, modo: "congelada" });
  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  await screen.findByText("Excavación");

  expect(screen.queryByText(/Igualar bajo umbral/i)).toBeNull();
});

test("sin rol de editor el botón de revisar no aparece", async () => {
  rol = "consulta";
  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  await screen.findByText("Excavación");

  expect(screen.queryByRole("button", { name: /revisar .* con IA/i })).toBeNull();
});

test("el botón dice cuántas filas va a revisar", async () => {
  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  await screen.findByText("Excavación");

  expect(boton(/revisar 2 líneas con IA/i)).toBeTruthy();
});

test("mientras revisa: botón bloqueado, triaje por lotes y luego veredictos", async () => {
  const { revisarCorridaStream } = await import("@/api/corridas");
  type OnP = (p: Record<string, unknown>) => void;
  let onProgreso: OnP | undefined;
  let terminar: ((r: unknown) => void) | undefined;
  vi.mocked(revisarCorridaStream).mockImplementationOnce(((_id, _onV, onP) => {
    onProgreso = onP as OnP;
    return new Promise((res) => { terminar = res; });
  }) as never);

  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  await screen.findByText("Excavación");
  fireEvent.click(boton(/revisar 2 líneas con IA/i));

  // Doble clic: el segundo no dispara una segunda revisión.
  const enCurso = boton(/revisando/i);
  expect(enCurso.disabled).toBe(true);
  fireEvent.click(enCurso);
  expect(vi.mocked(revisarCorridaStream)).toHaveBeenCalledTimes(1);

  // Fase 1: `lote: 1` significa que el lote 1 YA TERMINÓ ("1 de 3 listos").
  act(() => { onProgreso?.({ evento: "started", total: 2, lotes: 3 }); });
  act(() => { onProgreso?.({ evento: "barriendo", lote: 1, lotes: 3 }); });
  expect(screen.getByText("Triaje: 1 de 3 lotes listos")).toBeTruthy();

  // Fase 2: veredictos fila por fila.
  act(() => { onProgreso?.({ evento: "barrido", revisar: 2, sin_respuesta: [] }); });
  expect(screen.getByText("Veredictos: 0 de 2 filas")).toBeTruthy();

  await act(async () => { terminar?.(RESUMEN); });
});

test("al terminar recarga la corrida y avisa el resumen", async () => {
  const { getCorrida, revisarCorridaStream } = await import("@/api/corridas");
  const { toast } = await import("sonner");
  vi.mocked(getCorrida).mockClear();
  vi.mocked(toast.success).mockClear();
  vi.mocked(revisarCorridaStream).mockResolvedValueOnce(RESUMEN);

  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  await screen.findByText("Excavación");
  const antes = vi.mocked(getCorrida).mock.calls.length;

  fireEvent.click(boton(/revisar 2 líneas con IA/i));

  await waitFor(() =>
    expect(vi.mocked(getCorrida).mock.calls.length).toBe(antes + 1));
  expect(vi.mocked(toast.success).mock.calls[0][0])
    .toBe("Revisión lista: 1 por cambiar, 1 dudosas, 0 sin APU.");
});

test("si quedaron filas sin revisar, el aviso lo dice y no suena a éxito", async () => {
  // El agujero que esto tapa: con la IA fallando 40 de 300 filas el usuario leía
  // "0 por cambiar, 0 dudosas, 0 sin APU" y se quedaba con 40 filas sin auditar.
  const { revisarCorridaStream } = await import("@/api/corridas");
  const { toast } = await import("sonner");
  vi.mocked(toast.success).mockClear();
  vi.mocked(toast.warning).mockClear();
  vi.mocked(revisarCorridaStream).mockResolvedValueOnce(
    { ...RESUMEN, cambiar: 0, dudoso: 0, sin_veredicto: 40 });

  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  await screen.findByText("Excavación");
  fireEvent.click(boton(/revisar 2 líneas con IA/i));

  await waitFor(() => expect(vi.mocked(toast.warning)).toHaveBeenCalledTimes(1));
  const msg = vi.mocked(toast.warning).mock.calls[0][0] as string;
  expect(msg).toMatch(/40 sin revisar/);
  expect(msg).toMatch(/no las contestó/);
  // Y que no se lea como un visto bueno: dice explícitamente que no están bien.
  expect(msg).toMatch(/no significa que estén bien/i);
  // El tono importa: un toast de éxito con 40 filas sin auditar es el bug.
  expect(vi.mocked(toast.success)).not.toHaveBeenCalled();
});

test("sin filas sin revisar, el aviso sigue siendo un éxito seco", async () => {
  const { revisarCorridaStream } = await import("@/api/corridas");
  const { toast } = await import("sonner");
  vi.mocked(toast.success).mockClear();
  vi.mocked(toast.warning).mockClear();
  vi.mocked(revisarCorridaStream).mockResolvedValueOnce(RESUMEN);

  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  await screen.findByText("Excavación");
  fireEvent.click(boton(/revisar 2 líneas con IA/i));

  await waitFor(() => expect(vi.mocked(toast.success)).toHaveBeenCalledTimes(1));
  expect(vi.mocked(toast.success).mock.calls[0][0])
    .toBe("Revisión lista: 1 por cambiar, 1 dudosas, 0 sin APU.");
  expect(vi.mocked(toast.warning)).not.toHaveBeenCalled();
});

test("si el stream falla a mitad, recarga igual y lo dice", async () => {
  const { getCorrida, revisarCorridaStream } = await import("@/api/corridas");
  const { toast } = await import("sonner");
  vi.mocked(getCorrida).mockClear();
  vi.mocked(toast.error).mockClear();
  vi.mocked(revisarCorridaStream).mockRejectedValueOnce(
    new Error("El proxy cortó el stream."));

  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  await screen.findByText("Excavación");
  const antes = vi.mocked(getCorrida).mock.calls.length;

  fireEvent.click(boton(/revisar 2 líneas con IA/i));

  // Lo ya persistido no se pierde: se recarga igual...
  await waitFor(() =>
    expect(vi.mocked(getCorrida).mock.calls.length).toBe(antes + 1));
  // ...y el mensaje del backend no se reemplaza por uno genérico.
  const msg = vi.mocked(toast.error).mock.calls[0][0] as string;
  expect(msg.startsWith("El proxy cortó el stream.")).toBe(true);
  expect(msg).toMatch(/se conservan/i);
  // La revisión terminó: el botón vuelve a ofrecerse.
  await waitFor(() => expect(boton(/revisar 2 líneas con IA/i).disabled).toBe(false));
});

// ─── Aplicar N sugerencias ───────────────────────────────────────────────────

const CON_SUGERENCIAS = {
  ...CORRIDA,
  items: [
    fila({ seq: 0, descripcion: "Excavación", revision: cambiar(0, "222") }),
    fila({ seq: 1, descripcion: "Concreto", revision: cambiar(1, "333") }),
    // dictamen != cambiar: NO entra al lote aunque traiga apu_sugerido.
    fila({ seq: 2, descripcion: "Relleno",
           revision: { ...cambiar(2, "444"), dictamen: "dudoso" } }),
  ],
};

test("Aplicar N sugerencias manda UNA sola llamada con las N asignaciones", async () => {
  const { getCorrida, aplicarSugerencias } = await import("@/api/corridas");
  vi.mocked(getCorrida).mockResolvedValueOnce(CON_SUGERENCIAS);
  vi.mocked(aplicarSugerencias).mockClear();
  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  await screen.findByText("Relleno");

  fireEvent.click(boton(/aplicar 2 sugerencias/i));

  await waitFor(() => expect(vi.mocked(aplicarSugerencias)).toHaveBeenCalledTimes(1));
  expect(vi.mocked(aplicarSugerencias)).toHaveBeenCalledWith(1, [
    { seq: 0, apu_codigo: "222", shift: "NOCTURNO" },
    { seq: 1, apu_codigo: "333", shift: "NOCTURNO" },
  ]);
});

test("sin filas con dictamen 'cambiar' no se ofrece aplicar en lote", async () => {
  const { getCorrida } = await import("@/api/corridas");
  vi.mocked(getCorrida).mockResolvedValueOnce({
    ...CORRIDA,
    items: [fila({ seq: 0, descripcion: "Excavación",
                   revision: { ...cambiar(0, "222"), dictamen: "ok" } })],
  });
  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  await screen.findByText("Excavación");

  expect(screen.queryByRole("button", { name: /aplicar .* sugerencia/i })).toBeNull();
});
