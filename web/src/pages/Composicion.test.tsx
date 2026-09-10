import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, test, vi } from "vitest";
import Composicion from "./Composicion";
import type { EventoComposicion } from "@/api/composicion";

// `@testing-library/user-event` y `jest-dom` no son dependencias de este repo: se
// usa `fireEvent` y aserciones planas.

const getComposicion = vi.fn();
const guardarComposicion = vi.fn();
const aprobarComposicion = vi.fn();
const rechazarComposicion = vi.fn();
const generarComposicionStream = vi.fn();

vi.mock("@/api/composicion", () => ({
  getComposicion: (...a: unknown[]) => getComposicion(...a),
  guardarComposicion: (...a: unknown[]) => guardarComposicion(...a),
  aprobarComposicion: (...a: unknown[]) => aprobarComposicion(...a),
  rechazarComposicion: (...a: unknown[]) => rechazarComposicion(...a),
  generarComposicionStream: (...a: unknown[]) => generarComposicionStream(...a),
}));
// La mesa importa el buscador de insumos desde el alta de APUs, que arrastra
// @/api/autoria y @/api/insumos -> @/lib/supabase (se cae sin envs reales).
vi.mock("@/api/autoria", () => ({
  crearApu: vi.fn(),
  editarApu: vi.fn(),
  listarApus: vi.fn(async () => ({ items: [], total: 0, limit: 15, offset: 0 })),
  getGruposApu: vi.fn(async () => ["PAVIMENTOS", "EXCAVACIONES"]),
  conflictoApu: vi.fn(async () => ({ campo: null, motivo: null })),
}));
vi.mock("@/api/insumos", () => ({
  listarInsumos: vi.fn(async () => ({
    items: [{ id: 7, codigo: "8801", nombre: "OFICIAL DE OBRA", unidad: "HC",
              grupo: "MO", precio: 0, fuente: "", clasificacion: "", sin_precio: false }],
    total: 1, limit: 15, offset: 0,
  })),
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

let rol: "consulta" | "editor" | "admin" = "editor";
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ perfil: { rol } }) }));

const COMPONENTE = {
  codigo: "4279",
  tipo: "insumo",
  funcion: "mano_de_obra",
  rendimiento: 0.083,
  origen: "calculado_desde_produccion",
  referencias: [{ apu_codigo: "3010", turno: "DIURNO" }],
  hipotesis: { produccion_diaria: "96 m3/día", cuadrilla: "1 oficial + 2 ayudantes" },
  calculo: { operacion: "division", numerador: 8, denominador: 96, resultado: 0.083 },
  justificacion: "Cuadrilla tomada del APU 3010, ajustada por la producción.",
  nivel_evidencia: "medio",
  ref_shift: "",
};

function version() {
  return {
    corrida_id: 1,
    seq: 3,
    version: 2,
    estado: "propuesta",
    actividad: {
      item: "1.3", descripcion: "EXCAVACION MANUAL EN MATERIAL COMUN",
      unidad: "M3", cantidad: 120, shift: "DIURNO",
    },
    ficha: null,
    propuesta: {
      componentes: [COMPONENTE],
      supuestos: [{ campo: "profundidad", supuesto: "menor a 1,5 m",
                    impacto: "por encima cambia el equipo y la entibación" }],
      incertidumbre_declarada: 0.35,
      justificacion: "Se compone desde la excavación manual del 3010.",
    },
    validacion: {
      valido: true, errores: [], advertencias: [],
      metricas: { superadas: 12, totales: 12 },
    },
    confianza: "media",
    confianza_motivos: [
      { senal: "antecedentes", detalle: "3 APUs parecidos en la biblioteca", aporte: 0.4 },
    ],
    antecedentes: {
      codigos_permitidos: ["4279"],
      apus_referencia: [{ codigo: "3010", turno: "DIURNO" }],
    },
    modelo: "claude-sonnet-5",
    prompt_version: "1",
    apu_codigo: null,
    apu_turno: null,
    autor: "luis@x.com",
    creada_en: "2026-09-10T00:00:00Z",
    motivo: null,
  };
}

/** El mapa nombre/unidad/grupo que ahora viaja con la respuesta. No se persiste:
 *  la fila guardada tiene solo el código y el nombre se lee fresco del catálogo. */
const CATALOGO = {
  "4279": { nombre: "CUADRILLA OFICIAL MAS AYUDANTES", unidad: "HR", grupo: "MO" },
  "8801": { nombre: "OFICIAL DE OBRA", unidad: "HC", grupo: "MO" },
};

/** Las cuatro respuestas del expediente traen CUATRO claves. `corrida_modo` por
 *  defecto "activa": la mayoría de los tests no le interesa el candado de
 *  congelada. */
function vista(vigente: unknown, catalogo: unknown = CATALOGO,
               corrida_modo: "activa" | "congelada" = "activa") {
  return { vigente, historial: vigente ? [vigente] : [], catalogo, corrida_modo };
}

function montar() {
  return render(
    <MemoryRouter initialEntries={["/corridas/1/componer/3"]}>
      <Routes>
        <Route path="/corridas/:id/componer/:seq" element={<Composicion />} />
        <Route path="/corridas/:id" element={<p>vuelta a la corrida</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  rol = "editor";
  getComposicion.mockReset();
  guardarComposicion.mockReset();
  aprobarComposicion.mockReset();
  rechazarComposicion.mockReset();
  generarComposicionStream.mockReset();
  getComposicion.mockResolvedValue(vista(version()));
  guardarComposicion.mockResolvedValue(vista(version()));
  aprobarComposicion.mockResolvedValue(vista(version()));
  rechazarComposicion.mockResolvedValue(vista(null, {}));
});

const boton = (re: RegExp) => screen.getByRole("button", { name: re }) as HTMLButtonElement;

test("al abrir pide el expediente de esa línea y pinta la actividad", async () => {
  montar();
  expect(await screen.findByText("EXCAVACION MANUAL EN MATERIAL COMUN")).toBeTruthy();
  expect(getComposicion).toHaveBeenCalledWith(1, 3);
  expect(screen.getByText(/M3 · 120 · DIURNO · ítem 1\.3/)).toBeTruthy();
});

test("pinta los componentes con su origen y su justificación", async () => {
  montar();
  expect(await screen.findByText("4279")).toBeTruthy();
  expect(screen.getByText("calculado_desde_produccion")).toBeTruthy();
  // `nivel_evidencia` solo lo consume la interfaz.
  expect(screen.getByText("medio")).toBeTruthy();
  // La justificación va en el desplegable: en la fila manda el nombre del insumo.
  fireEvent.click(screen.getByLabelText("Ver supuestos de 4279"));
  expect(screen.getByText(/Cuadrilla tomada del APU 3010/)).toBeTruthy();
});

test("al desplegar la fila se ven las hipótesis y la fórmula del cálculo", async () => {
  montar();
  fireEvent.click(await screen.findByLabelText("Ver supuestos de 4279"));
  expect(screen.getByText("produccion_diaria:")).toBeTruthy();
  expect(screen.getByText("96 m3/día")).toBeTruthy();
  expect(screen.getByText(/division: 8 \/ 96 = 0,083/)).toBeTruthy();
});

test("muestra el nivel de confianza y despliega el desglose al pulsar «por qué»", async () => {
  montar();
  expect(await screen.findByText(/Confianza: MEDIA/)).toBeTruthy();
  expect(screen.queryByText("antecedentes")).toBeNull();
  fireEvent.click(boton(/por qué/i));
  expect(screen.getByText("antecedentes")).toBeTruthy();
  expect(screen.getByText(/3 APUs parecidos en la biblioteca/)).toBeTruthy();
});

test("la incertidumbre del modelo se muestra rotulada como suya y aparte del nivel", async () => {
  montar();
  const p = await screen.findByText(/^El modelo declara/);
  expect(p.textContent).toMatch(/35 % de incertidumbre/);
  expect(p.textContent).toMatch(/dato suyo/i);
});

test("editar un rendimiento y guardar manda la versión base y el valor nuevo", async () => {
  montar();
  const input = await screen.findByLabelText("Rendimiento de 4279");
  expect(boton(/Guardar cambios/).disabled).toBe(true);
  fireEvent.change(input, { target: { value: "0.12" } });
  fireEvent.click(boton(/Guardar cambios/));
  await waitFor(() => expect(guardarComposicion).toHaveBeenCalledWith(
    1, 3, 2, [{ ...COMPONENTE, rendimiento: 0.12 }], false));
});

test("borrar un componente lo saca de lo que se guarda", async () => {
  montar();
  fireEvent.click(await screen.findByLabelText("Quitar 4279"));
  fireEvent.click(boton(/Guardar cambios/));
  await waitFor(() =>
    expect(guardarComposicion).toHaveBeenCalledWith(1, 3, 2, [], false));
});

test("con errores bloqueantes aprobar está deshabilitado y los mensajes se ven", async () => {
  getComposicion.mockResolvedValue(vista({
    ...version(),
    validacion: {
      valido: false,
      errores: [{ codigo: "CODIGO_NO_AUTORIZADO",
                  mensaje: "El código 9999 no está en la lista blanca.",
                  componente: "9999" }],
      advertencias: [],
      metricas: { superadas: 11, totales: 12 },
    },
  }));
  montar();
  expect(await screen.findByText(/no está en la lista blanca/)).toBeTruthy();
  expect(boton(/Aprobar y crear APU/).disabled).toBe(true);
});

test("con errores NO se muestra el cociente de validaciones superadas", async () => {
  getComposicion.mockResolvedValue(vista({
    ...version(),
    validacion: {
      valido: false,
      errores: [{ codigo: "CANTIDAD_INVALIDA", mensaje: "Rendimiento en 0.",
                  componente: "4279" }],
      advertencias: [],
      metricas: { superadas: 11, totales: 12 },
    },
  }));
  montar();
  expect(await screen.findByText("1 error")).toBeTruthy();
  expect(screen.queryByText(/validaciones superadas/)).toBeNull();
});

test("con solo advertencias aprobar está habilitado y la advertencia se ve", async () => {
  getComposicion.mockResolvedValue(vista({
    ...version(),
    validacion: {
      valido: true,
      errores: [],
      advertencias: [{ codigo: "RENDIMIENTO_ATIPICO",
                       mensaje: "0,083 HR queda 79 % por debajo del rango observado.",
                       componente: "4279" }],
      metricas: { superadas: 11, totales: 12 },
    },
  }));
  montar();
  expect(await screen.findByText(/79 % por debajo del rango observado/)).toBeTruthy();
  expect(boton(/Aprobar y crear APU/).disabled).toBe(false);
  expect(screen.getByText("11 de 12 validaciones superadas")).toBeTruthy();
});

test("un hallazgo del conjunto (componente vacío) no resalta ninguna fila", async () => {
  getComposicion.mockResolvedValue(vista({
    ...version(),
    validacion: {
      valido: true, errores: [],
      advertencias: [{ codigo: "FALTA_HERRAMIENTA",
                       mensaje: "No hay herramienta menor en la propuesta.",
                       componente: "" }],
      metricas: { superadas: 11, totales: 12 },
    },
  }));
  montar();
  // El mensaje se pinta una sola vez, en el bloque de arriba: ninguna fila lo repite.
  expect((await screen.findAllByText(/No hay herramienta menor/)).length).toBe(1);
});

test("sin composición ofrece «Generar propuesta» y no la pide sola", async () => {
  getComposicion.mockResolvedValue(vista(null, {}));
  montar();
  expect(await screen.findByRole("button", { name: /Generar propuesta/ })).toBeTruthy();
  expect(generarComposicionStream).not.toHaveBeenCalled();
});

test("vigente null con historial no vacío ofrece generar, no rompe", async () => {
  // El seq se reusa: el expediente viejo es de la actividad que ANTES ocupaba la
  // línea. Para esta pantalla eso es "todavía no hay composición".
  getComposicion.mockResolvedValue({
    vigente: null, historial: [version()], catalogo: {},
  });
  montar();
  expect(await screen.findByRole("button", { name: /Generar propuesta/ })).toBeTruthy();
  expect(screen.getByText(/todavía no tiene una propuesta/)).toBeTruthy();
});

test("generar muestra el avance por etapas", async () => {
  getComposicion.mockResolvedValue(vista(null, {}));
  let emitir: (e: EventoComposicion) => void = () => {};
  let terminar: () => void = () => {};
  generarComposicionStream.mockImplementation(
    (_id: number, _seq: number, onEvent: (e: EventoComposicion) => void) => {
      emitir = onEvent;
      return new Promise<void>((res) => { terminar = res; });
    });
  montar();
  fireEvent.click(await screen.findByRole("button", { name: /Generar propuesta/ }));

  expect(await screen.findByText(/Recuperando insumos/)).toBeTruthy();
  emitir({ event: "generando", data: {} });
  expect(await screen.findByText(/Redactando la propuesta con IA/)).toBeTruthy();
  emitir({ event: "validando", data: {} });
  expect(await screen.findByText(/Validando la propuesta/)).toBeTruthy();

  // Al terminar el stream se RELEE: la propuesta la persistió el backend.
  getComposicion.mockResolvedValue(vista(version()));
  terminar();
  expect(await screen.findByText("EXCAVACION MANUAL EN MATERIAL COMUN")).toBeTruthy();
  expect(getComposicion).toHaveBeenCalledTimes(2);
});

test("rechazar manda el motivo y no crea nada", async () => {
  vi.spyOn(window, "prompt").mockReturnValue("La cuadrilla no aplica a este frente.");
  montar();
  fireEvent.click(await screen.findByRole("button", { name: /^Rechazar$/ }));
  await waitFor(() => expect(rechazarComposicion).toHaveBeenCalledWith(
    1, 3, 2, "La cuadrilla no aplica a este frente."));
  expect(aprobarComposicion).not.toHaveBeenCalled();
});

test("aprobar pide la identidad y crea el APU con la versión vigente", async () => {
  montar();
  fireEvent.click(await screen.findByRole("button", { name: /Aprobar y crear APU/ }));
  // El nombre y la unidad vienen precargados con la actividad.
  expect(await screen.findByDisplayValue("EXCAVACION MANUAL EN MATERIAL COMUN")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("Código"), { target: { value: "9001" } });
  fireEvent.change(screen.getByLabelText("Grupo"), { target: { value: "EXCAVACIONES" } });
  fireEvent.click(screen.getByRole("button", { name: /^Crear APU$/ }));
  await waitFor(() => expect(aprobarComposicion).toHaveBeenCalledWith(1, 3, {
    version_base: 2,
    codigo: "9001",
    turno: "DIURNO",
    nombre: "EXCAVACION MANUAL EN MATERIAL COMUN",
    grupo: "EXCAVACIONES",
    unidad: "M3",
  }));
  expect(await screen.findByText("vuelta a la corrida")).toBeTruthy();
});

test("con rol consulta no aparece ninguna acción que escriba", async () => {
  rol = "consulta";
  montar();
  await screen.findByText("EXCAVACION MANUAL EN MATERIAL COMUN");
  expect(screen.queryByRole("button", { name: /Guardar cambios/ })).toBeNull();
  expect(screen.queryByRole("button", { name: /Regenerar/ })).toBeNull();
  expect(screen.queryByRole("button", { name: /^Rechazar$/ })).toBeNull();
  expect(screen.queryByRole("button", { name: /Aprobar y crear APU/ })).toBeNull();
  expect(screen.queryByLabelText("Rendimiento de 4279")).toBeNull();
  expect(screen.queryByLabelText("Quitar 4279")).toBeNull();
  expect(screen.queryByPlaceholderText(/Buscar insumo/i)).toBeNull();
});

test("con rol consulta y sin composición tampoco se ofrece generar", async () => {
  rol = "consulta";
  getComposicion.mockResolvedValue(vista(null, {}));
  montar();
  expect(await screen.findByText(/todavía no tiene una propuesta/)).toBeTruthy();
  expect(screen.queryByRole("button", { name: /Generar propuesta/ })).toBeNull();
});

test("regenerar con cambios sin guardar pide confirmación", async () => {
  const confirmar = vi.spyOn(window, "confirm").mockReturnValue(false);
  montar();
  fireEvent.change(await screen.findByLabelText("Rendimiento de 4279"),
                   { target: { value: "0.5" } });
  fireEvent.click(boton(/Regenerar/));
  expect(confirmar).toHaveBeenCalled();
  expect(generarComposicionStream).not.toHaveBeenCalled();
  confirmar.mockRestore();
});

test("agregar un componente lo suma a lo que se guarda", async () => {
  montar();
  const buscador = await screen.findByPlaceholderText(/Buscar insumo/i);
  fireEvent.change(buscador, { target: { value: "8801" } });
  fireEvent.click(await screen.findByText("OFICIAL DE OBRA"));
  fireEvent.change(await screen.findByLabelText("Rendimiento de 8801"),
                   { target: { value: "0.25" } });
  fireEvent.click(boton(/Guardar cambios/));
  await waitFor(() => {
    const enviados = guardarComposicion.mock.calls[0][3];
    expect(enviados.length).toBe(2);
    expect(enviados[1].codigo).toBe("8801");
    expect(enviados[1].rendimiento).toBe(0.25);
  });
});

test("volver con cambios sin guardar avisa antes de perderlos", async () => {
  const confirmar = vi.spyOn(window, "confirm").mockReturnValue(false);
  montar();
  fireEvent.change(await screen.findByLabelText("Rendimiento de 4279"),
                   { target: { value: "0.9" } });
  fireEvent.click(screen.getByRole("button", { name: /Volver a la corrida/ }));
  expect(confirmar).toHaveBeenCalled();
  expect(screen.queryByText("vuelta a la corrida")).toBeNull();
  confirmar.mockRestore();
});

// ─── el catálogo que enriquece la respuesta ─────────────────────────────────

test("la tabla muestra el nombre del insumo, no solo el código", async () => {
  montar();
  expect(await screen.findByText(/CUADRILLA OFICIAL MAS AYUDANTES/)).toBeTruthy();
  expect(screen.getByText("HR")).toBeTruthy();          // la unidad, del catálogo
});

test("un código sin entrada en el catálogo se ve como problema, no como guion", async () => {
  getComposicion.mockResolvedValue(vista(version(), {}));
  montar();
  // El código sigue visible y al lado dice por qué no hay nombre.
  expect(await screen.findByText("4279")).toBeTruthy();
  expect(screen.getByText(/no está en el catálogo/)).toBeTruthy();
});

test("los nombres siguen ahí después de guardar una edición", async () => {
  montar();
  fireEvent.change(await screen.findByLabelText("Rendimiento de 4279"),
                   { target: { value: "0.12" } });
  fireEvent.click(boton(/Guardar cambios/));
  await waitFor(() => expect(guardarComposicion).toHaveBeenCalled());
  expect(await screen.findByText(/CUADRILLA OFICIAL MAS AYUDANTES/)).toBeTruthy();
});

test("el nombre completo del insumo se lee en el desplegable", async () => {
  // Nombres reales del catálogo llegan a 830 caracteres; acá alcanza con superar
  // los 300 para probar que no depende del `title` nativo.
  const NOMBRE_LARGO = "SUMINISTRO E INSTALACION DE MATERIAL PETREO ".repeat(8).trim();
  getComposicion.mockResolvedValue(
    vista(version(), { "4279": { nombre: NOMBRE_LARGO, unidad: "HR", grupo: "MO" } }));
  montar();
  const celda = (await screen.findByText(NOMBRE_LARGO)).closest("td");
  // La celda lo sigue truncando visualmente (la clase de Tailwind, no un recorte
  // del string): el nombre entero vive en el DOM en un solo sitio hasta desplegar.
  expect(celda?.className).toMatch(/truncate/);
  expect(screen.getAllByText(NOMBRE_LARGO).length).toBe(1);
  fireEvent.click(screen.getByLabelText("Ver supuestos de 4279"));
  expect(screen.getAllByText(NOMBRE_LARGO).length).toBe(2);
});

// ─── corrida congelada: foto inmutable, la mesa se apaga entera ────────────

test("con la corrida congelada la mesa no ofrece ninguna acción que escriba", async () => {
  getComposicion.mockResolvedValue(vista(version(), CATALOGO, "congelada"));
  montar();
  await screen.findByText("EXCAVACION MANUAL EN MATERIAL COMUN");
  expect(screen.queryByRole("button", { name: /Generar propuesta/ })).toBeNull();
  expect(screen.queryByRole("button", { name: /Guardar cambios/ })).toBeNull();
  expect(screen.queryByRole("button", { name: /Regenerar/ })).toBeNull();
  expect(screen.queryByRole("button", { name: /^Rechazar$/ })).toBeNull();
  expect(screen.queryByRole("button", { name: /Aprobar y crear APU/ })).toBeNull();
});

test("con la corrida congelada tampoco se puede editar un rendimiento", async () => {
  getComposicion.mockResolvedValue(vista(version(), CATALOGO, "congelada"));
  montar();
  await screen.findByText("4279");
  expect(screen.queryByLabelText("Rendimiento de 4279")).toBeNull();
  expect(screen.queryByLabelText("Quitar 4279")).toBeNull();
  expect(screen.queryByPlaceholderText(/Buscar insumo/i)).toBeNull();
});

test("una corrida congelada igual muestra el expediente completo", async () => {
  getComposicion.mockResolvedValue(vista({
    ...version(),
    validacion: {
      valido: true, errores: [],
      advertencias: [{ codigo: "RENDIMIENTO_ATIPICO",
                       mensaje: "0,083 HR queda 79 % por debajo del rango observado.",
                       componente: "4279" }],
      metricas: { superadas: 11, totales: 12 },
    },
  }, CATALOGO, "congelada"));
  montar();
  expect(await screen.findByText("4279")).toBeTruthy();
  expect(screen.getByText(/Confianza: MEDIA/)).toBeTruthy();
  expect(screen.getByText(/79 % por debajo del rango observado/)).toBeTruthy();
});

test("con la corrida congelada se explica por qué", async () => {
  getComposicion.mockResolvedValue(vista(version(), CATALOGO, "congelada"));
  montar();
  expect(await screen.findByText(/congelada/i)).toBeTruthy();
});
