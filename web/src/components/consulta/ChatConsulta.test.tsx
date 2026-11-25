import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import ChatConsulta from "./ChatConsulta";

const chatConsultaStream = vi.fn();
vi.mock("@/api/consulta", () => ({
  chatConsultaStream: (...a: unknown[]) => chatConsultaStream(...a),
}));

type OnEv = (e: { event: string; data: unknown }) => void;

function responder(texto: string, crudo: string) {
  chatConsultaStream.mockImplementationOnce(async (_m: unknown, onEv: OnEv) => {
    onEv({ event: "respuesta",
           data: { texto, crudo, modelo: "m", prompt_version: "consulta/v1" } });
  });
}

function escribirYEnviar(texto: string) {
  fireEvent.change(screen.getByRole("textbox"), { target: { value: texto } });
  fireEvent.click(screen.getByRole("button", { name: /enviar/i }));
}

beforeEach(() => {
  chatConsultaStream.mockReset();
  sessionStorage.clear();
});

test("muestra las cifras pero manda el crudo como historial", async () => {
  responder("El tubo vale $35.000.", "El tubo vale {{precio:insumo:7}}.");
  render(<ChatConsulta iaDisponible />);
  fireEvent.click(screen.getByRole("button", { name: /abrir el agente de consulta/i }));
  escribirYEnviar("cuanto vale el tubo");
  expect(await screen.findByText("El tubo vale $35.000.")).toBeTruthy();

  responder("Ok.", "Ok.");
  escribirYEnviar("y el de 8?");
  await waitFor(() => expect(chatConsultaStream).toHaveBeenCalledTimes(2));
  const historial = chatConsultaStream.mock.calls[1][0] as { rol: string; texto: string }[];
  expect(historial[1]).toEqual({ rol: "agente", texto: "El tubo vale {{precio:insumo:7}}." });
  expect(JSON.stringify(historial)).not.toContain("35.000");
});

test("sin IA el botón queda deshabilitado", () => {
  render(<ChatConsulta iaDisponible={false} />);
  const boton = screen.getByRole("button", { name: /abrir el agente de consulta/i });
  expect((boton as HTMLButtonElement).disabled).toBe(true);
});

test("el hilo sobrevive a recargar (sessionStorage)", () => {
  sessionStorage.setItem("chat-consulta", JSON.stringify({
    abierto: true,
    hilo: [{ id: 1, rol: "usuario", texto: "hola" },
           { id: 2, rol: "agente", texto: "Total $10", crudo: "Total {{costo:corrida:1}}" }],
  }));
  render(<ChatConsulta iaDisponible />);
  expect(screen.getByText("Total $10")).toBeTruthy();
});

test("bloqueado devuelve el mensaje a la caja y avisa", async () => {
  chatConsultaStream.mockImplementationOnce(async (_m: unknown, onEv: OnEv) => {
    onEv({ event: "bloqueado", data: { motivo: "El mensaje parece traer un monto" } });
  });
  render(<ChatConsulta iaDisponible />);
  fireEvent.click(screen.getByRole("button", { name: /abrir el agente de consulta/i }));
  escribirYEnviar("mas de $50.000");
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("mas de $50.000");
});
