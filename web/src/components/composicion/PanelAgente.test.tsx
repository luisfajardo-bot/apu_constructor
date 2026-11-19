import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import PanelAgente from "./PanelAgente";
import type { ComponentePropuesto, RespuestaAgente } from "@/lib/tipos";

const chatComposicionStream = vi.fn();
vi.mock("@/api/composicion", () => ({
  chatComposicionStream: (...a: unknown[]) => chatComposicionStream(...a),
}));

const COMP: ComponentePropuesto = {
  codigo: "4279", tipo: "insumo", funcion: "mano_de_obra", rendimiento: 0.62,
  origen: "copiado_de_antecedente", referencias: [], hipotesis: {}, calculo: null,
  justificacion: "", nivel_evidencia: "alto", ref_shift: "",
};

const RESPUESTA: RespuestaAgente = {
  texto: "Te propongo el soldador.",
  cambios: [{ op: "agregar", codigo: "7001",
              componente: { ...COMP, codigo: "7001", rendimiento: 0.1,
                            referencias: [{ apu_codigo: "A1", turno: "DIURNO" }] } }],
  descartados: [{ codigo: "INVENTADO", motivo: "No está en el catálogo (o está oculto)." }],
  catalogo: { "7001": { nombre: "OFICIAL SOLDADOR", unidad: "HR", grupo: "MO" } },
  modelo: "m", prompt_version: "chat/v1",
};

type OnEv = (e: { event: string; data: unknown }) => void;

function montar(props: Partial<Parameters<typeof PanelAgente>[0]> = {}) {
  const onAplicar = vi.fn(async () => [] as string[]);
  render(
    <PanelAgente corridaId={1} seq={3} componentes={[COMP]} deshabilitado={null}
                 onAplicar={onAplicar} {...props} />,
  );
  return { onAplicar };
}

function escribirYEnviar(texto: string) {
  fireEvent.change(screen.getByRole("textbox"), { target: { value: texto } });
  fireEvent.click(screen.getByRole("button", { name: /enviar/i }));
}

beforeEach(() => {
  chatComposicionStream.mockReset();
});

test("manda el historial y la tabla, muestra la búsqueda y luego la propuesta", async () => {
  let soltar!: () => void;
  chatComposicionStream.mockImplementation(
    async (_id: number, _seq: number, _cuerpo: unknown, onEvent: OnEv) => {
      onEvent({ event: "buscando", data: { herramienta: "buscar_insumos", consulta: "soldador" } });
      await new Promise<void>((r) => { soltar = r; });
      onEvent({ event: "respuesta", data: RESPUESTA });
    });
  const { onAplicar } = montar();
  escribirYEnviar("busca un soldador");

  expect(await screen.findByText(/Buscando «soldador»/)).toBeTruthy();
  expect(screen.getByRole("img").getAttribute("data-estado")).toBe("buscando");
  expect(chatComposicionStream).toHaveBeenCalledWith(1, 3, {
    mensajes: [{ rol: "usuario", texto: "busca un soldador" }],
    componentes: [COMP],
  }, expect.any(Function));

  soltar();
  expect(await screen.findByText("Te propongo el soldador.")).toBeTruthy();
  expect(screen.getByText(/OFICIAL SOLDADOR/)).toBeTruthy();
  expect(screen.getByText(/INVENTADO/)).toBeTruthy();          // el descartado se ve

  fireEvent.click(screen.getByRole("button", { name: /^aplicar$/i }));
  await waitFor(() => expect(onAplicar).toHaveBeenCalledWith(
    RESPUESTA.cambios, "busca un soldador"));
  expect(await screen.findByText(/Aplicado/)).toBeTruthy();
});

test("un mensaje bloqueado vuelve a la caja y explica por qué", async () => {
  chatComposicionStream.mockImplementation(
    async (_i: number, _s: number, _c: unknown, onEvent: OnEv) => {
      onEvent({ event: "bloqueado", data: { motivo: "El mensaje parece traer un monto." } });
    });
  montar();
  escribirYEnviar("cuesta $45.000");
  expect(await screen.findByText(/parece traer un monto/)).toBeTruthy();
  expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("cuesta $45.000");
  expect(screen.getByRole("img").getAttribute("data-estado")).toBe("error");
});

test("descartar no llama a aplicar", async () => {
  chatComposicionStream.mockImplementation(
    async (_i: number, _s: number, _c: unknown, onEvent: OnEv) => {
      onEvent({ event: "respuesta", data: RESPUESTA });
    });
  const { onAplicar } = montar();
  escribirYEnviar("busca un soldador");
  fireEvent.click(await screen.findByRole("button", { name: /descartar/i }));
  expect(screen.getByText(/Descartado/)).toBeTruthy();
  expect(onAplicar).not.toHaveBeenCalled();
});

test("deshabilitado: muestra el motivo y no deja escribir", () => {
  montar({ deshabilitado: "El agente necesita ANTHROPIC_API_KEY en el servidor." });
  expect(screen.getByText(/ANTHROPIC_API_KEY/)).toBeTruthy();
  expect((screen.getByRole("textbox") as HTMLTextAreaElement).disabled).toBe(true);
  expect(screen.getByRole("img").getAttribute("data-estado")).toBe("deshabilitado");
});

test("el historial le recuerda al agente lo que propuso y qué pasó con eso", async () => {
  chatComposicionStream.mockImplementation(
    async (_i: number, _s: number, _c: unknown, onEvent: OnEv) => {
      onEvent({ event: "respuesta", data: RESPUESTA });
    });
  montar();
  escribirYEnviar("busca un soldador");
  fireEvent.click(await screen.findByRole("button", { name: /descartar/i }));
  escribirYEnviar("entonces otro");
  await waitFor(() => expect(chatComposicionStream).toHaveBeenCalledTimes(2));
  const cuerpo = chatComposicionStream.mock.calls[1][2] as {
    mensajes: { rol: string; texto: string }[];
  };
  expect(cuerpo.mensajes[1]).toEqual({
    rol: "agente",
    texto: "Te propongo el soldador.\n(Propuse: + 7001 0,1 — descartado)",
  });
});

test("los conflictos de aplicar se muestran", async () => {
  chatComposicionStream.mockImplementation(
    async (_i: number, _s: number, _c: unknown, onEvent: OnEv) => {
      onEvent({ event: "respuesta", data: RESPUESTA });
    });
  const onAplicar = vi.fn(async () => ["7001 ya estaba en la tabla: no se agregó otra vez."]);
  montar({ onAplicar });
  escribirYEnviar("x");
  fireEvent.click(await screen.findByRole("button", { name: /^aplicar$/i }));
  expect(await screen.findByText(/ya estaba en la tabla/)).toBeTruthy();
});
