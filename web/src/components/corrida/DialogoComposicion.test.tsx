import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { expect, it, vi, beforeEach } from "vitest";
import DialogoComposicion from "./DialogoComposicion";

// `@testing-library/user-event` y `jest-dom` (toBeInTheDocument, toBeDisabled) no
// son dependencias de este repo: se usa `fireEvent` y aserciones planas.

const componerItem = vi.fn();
const crearApu = vi.fn();
vi.mock("@/api/corridas", () => ({
  componerItem: (...a: unknown[]) => componerItem(...a),
}));
vi.mock("@/api/autoria", () => ({
  crearApu: (...a: unknown[]) => crearApu(...a),
  editarApu: vi.fn(),
  listarApus: vi.fn(async () => ({ items: [], total: 0, limit: 15, offset: 0 })),
  getGruposApu: vi.fn(async () => ["CONCRETOS", "EXCAVACIONES"]),
  conflictoApu: vi.fn(async () => ({ campo: null, motivo: null })),
}));
vi.mock("@/api/insumos", () => ({
  listarInsumos: vi.fn(async () => ({ items: [], total: 0, limit: 15, offset: 0 })),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const PROPUESTA = {
  seq: 3,
  nombre: "SUMINISTRO E INSTALACIÓN DE SARDINEL A-10",
  unidad: "ML",
  shift: "DIURNO",
  justificacion: "No hay sardineles A-10 en la biblioteca; se compone desde A-80.",
  confianza: 0.62,
  componentes: [
    { insumo_codigo: "1105", insumo_nombre: "CONCRETO 3000 PSI", unidad: "M3", rendimiento: 0.045 },
    { insumo_codigo: "8801", insumo_nombre: "OFICIAL DE OBRA", unidad: "HC", rendimiento: 0.12 },
  ],
};

function montar(props: Partial<React.ComponentProps<typeof DialogoComposicion>> = {}) {
  return render(
    <DialogoComposicion
      open
      corridaId={1}
      seq={3}
      descripcion="SARDINEL A-10"
      onOpenChange={() => {}}
      onCreado={() => {}}
      {...props}
    />,
  );
}

beforeEach(() => {
  componerItem.mockReset();
  crearApu.mockReset();
  componerItem.mockResolvedValue(PROPUESTA);
  crearApu.mockResolvedValue({});
});

it("muestra la propuesta de la IA con sus componentes", async () => {
  montar();
  expect(await screen.findByText(/no hay sardineles a-10 en la biblioteca/i)).toBeTruthy();
  expect(screen.getByText("1105")).toBeTruthy();
  expect(screen.getByText("CONCRETO 3000 PSI")).toBeTruthy();
  expect(screen.getByText("8801")).toBeTruthy();
  expect(screen.getByText("0,045")).toBeTruthy();
  expect(componerItem).toHaveBeenCalledWith(1, 3);
});

it("dice que es una propuesta y que todavía no se creó nada", async () => {
  montar();
  await screen.findByText("1105");
  // El aviso tiene que estar en el DOM (no en un `title`): es lo que evita que
  // alguien crea que la IA ya metió el APU en la biblioteca.
  const aviso = screen.getByText(/todavía no se creó nada/i);
  expect(aviso.textContent).toMatch(/propuesta/i);
  expect(aviso.textContent).toMatch(/biblioteca/i);
  expect(aviso.textContent).toMatch(/creás vos/i);
  // Y que conviene revisar los rendimientos, porque la IA no ve precios.
  expect(aviso.textContent).toMatch(/revisá los rendimientos/i);
  expect(aviso.textContent).toMatch(/no ve precios/i);
});

it("mientras carga lo dice, y no ofrece crear nada", () => {
  componerItem.mockReturnValue(new Promise(() => {}));   // nunca resuelve
  montar();
  expect(screen.getByText(/pidiéndole una propuesta a la ia/i)).toBeTruthy();
  const crear = screen.getByRole("button", { name: /crear apu con esto/i }) as HTMLButtonElement;
  expect(crear.disabled).toBe(true);
});

it("un 503 del backend se muestra con su mensaje, y se puede salir", async () => {
  componerItem.mockRejectedValue(
    new Error("Componer un APU con IA necesita ANTHROPIC_API_KEY en el servidor."),
  );
  const onOpenChange = vi.fn();
  montar({ onOpenChange });
  expect(await screen.findByText(/necesita ANTHROPIC_API_KEY en el servidor/)).toBeTruthy();
  const crear = screen.getByRole("button", { name: /crear apu con esto/i }) as HTMLButtonElement;
  expect(crear.disabled).toBe(true);
  // El diálogo no queda sin salida: Descartar sigue ahí.
  fireEvent.click(screen.getByRole("button", { name: /descartar/i }));
  expect(onOpenChange).toHaveBeenCalledWith(false);
});

it("un 422 del backend se muestra con su mensaje", async () => {
  componerItem.mockRejectedValue(
    new Error("La IA no pudo componer esta actividad. Ármala a mano o agrega el APU a la biblioteca."),
  );
  montar();
  expect(await screen.findByText(/la ia no pudo componer esta actividad/i)).toBeTruthy();
});

it("una propuesta sin componentes lo dice y no deja crear", async () => {
  componerItem.mockResolvedValue({ ...PROPUESTA, componentes: [] });
  montar();
  expect(await screen.findByText(/no propuso ningún insumo/i)).toBeTruthy();
  const crear = screen.getByRole("button", { name: /crear apu con esto/i }) as HTMLButtonElement;
  expect(crear.disabled).toBe(true);
});

it("'Crear APU con esto' abre el alta precargada con la propuesta", async () => {
  montar();
  fireEvent.click(await screen.findByRole("button", { name: /crear apu con esto/i }));
  // El alta de siempre, en modo crear (su botón dice "Crear APU", no "Guardar cambios").
  expect(await screen.findByRole("button", { name: /^crear apu$/i })).toBeTruthy();
  // Precargada: nombre, unidad y los componentes de la propuesta.
  expect((screen.getByDisplayValue(PROPUESTA.nombre) as HTMLInputElement).value)
    .toBe(PROPUESTA.nombre);
  expect(screen.getByDisplayValue("ML")).toBeTruthy();
  expect(screen.getByDisplayValue("0.045")).toBeTruthy();
  expect(screen.getByDisplayValue("0.12")).toBeTruthy();
  expect(screen.getByText(/CONCRETO 3000 PSI/)).toBeTruthy();
  // El código y el grupo los elige el usuario: la IA no le pone identidad al APU.
  expect((screen.getByLabelText(/código/i) as HTMLInputElement).value).toBe("");
  expect((screen.getByLabelText(/grupo/i, { selector: "select" }) as HTMLSelectElement).value)
    .toBe("");
});

it("el alta no se autoguarda: el APU lo crea el usuario", async () => {
  montar();
  fireEvent.click(await screen.findByRole("button", { name: /crear apu con esto/i }));
  await screen.findByRole("button", { name: /^crear apu$/i });
  expect(crearApu).not.toHaveBeenCalled();
});

it("cancelar el alta vuelve a la propuesta sin volver a llamar a la IA", async () => {
  montar();
  fireEvent.click(await screen.findByRole("button", { name: /crear apu con esto/i }));
  fireEvent.click(await screen.findByRole("button", { name: /cancelar/i }));
  // La propuesta sigue ahí (no se perdió) y no se le pagó de nuevo a la IA.
  expect(await screen.findByText("1105")).toBeTruthy();
  expect(componerItem).toHaveBeenCalledTimes(1);
});

it("al crear el APU avisa hacia arriba con su código y turno", async () => {
  const onCreado = vi.fn();
  montar({ onCreado });
  fireEvent.click(await screen.findByRole("button", { name: /crear apu con esto/i }));
  await screen.findByRole("button", { name: /^crear apu$/i });
  // El usuario completa lo que la IA no propone: identidad y grupo.
  fireEvent.change(screen.getByLabelText(/código/i), { target: { value: "9001" } });
  fireEvent.change(screen.getByLabelText(/grupo/i, { selector: "select" }), {
    target: { value: "CONCRETOS" },
  });
  await waitFor(() =>
    expect((screen.getByRole("button", { name: /^crear apu$/i }) as HTMLButtonElement).disabled)
      .toBe(false));
  fireEvent.click(screen.getByRole("button", { name: /^crear apu$/i }));
  await waitFor(() => expect(onCreado).toHaveBeenCalledWith("9001", "DIURNO"));
  expect(crearApu).toHaveBeenCalledWith(expect.objectContaining({
    codigo: "9001",
    turno: "DIURNO",
    nombre: PROPUESTA.nombre,
    unidad: "ML",
    componentes: [
      expect.objectContaining({ insumo_codigo: "1105", rendimiento: 0.045 }),
      expect.objectContaining({ insumo_codigo: "8801", rendimiento: 0.12 }),
    ],
  }));
});

it("no llama a la IA con el diálogo cerrado", () => {
  montar({ open: false });
  expect(componerItem).not.toHaveBeenCalled();
});

it("cerrar mientras carga no revienta ni deja la propuesta a medias", async () => {
  let resolver: (v: unknown) => void = () => {};
  componerItem.mockReturnValue(new Promise((r) => { resolver = r; }));
  const { unmount } = montar();
  unmount();
  resolver(PROPUESTA);            // llega tarde, ya no hay a quién avisarle
  await Promise.resolve();
  expect(screen.queryByText("1105")).toBeNull();
});
