import { fireEvent, render, screen, waitFor, act } from "@testing-library/react";
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

test("sin IA el botón queda aria-disabled y no abre el panel", () => {
  render(<ChatConsulta iaDisponible={false} />);
  const boton = screen.getByRole("button", { name: /abrir el agente de consulta/i });
  expect(boton.getAttribute("aria-disabled")).toBe("true");
  expect(boton.getAttribute("aria-describedby")).toBeTruthy();
  expect(screen.getByText(/falta ANTHROPIC_API_KEY/).textContent).toContain(
    "El servidor no tiene IA configurada",
  );
  fireEvent.click(boton);
  expect(screen.queryByRole("complementary")).toBeNull();
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

function abrir() {
  fireEvent.click(screen.getByRole("button", { name: /abrir el agente de consulta/i }));
}

test("un storage malformado no rompe y el primer envío funciona", async () => {
  sessionStorage.setItem("chat-consulta", JSON.stringify({
    abierto: true, hilo: [null, { rol: "agente" }, 5],
  }));
  responder("Ok.", "Ok.");
  render(<ChatConsulta iaDisponible />);
  escribirYEnviar("hola");
  await waitFor(() => expect(chatConsultaStream).toHaveBeenCalledTimes(1));
  expect(chatConsultaStream.mock.calls[0][0]).toEqual([{ rol: "usuario", texto: "hola" }]);
});

test("un mensaje de usuario sin respuesta al final no se restaura", () => {
  sessionStorage.setItem("chat-consulta", JSON.stringify({
    abierto: true,
    hilo: [{ id: 1, rol: "usuario", texto: "uno" },
           { id: 2, rol: "agente", texto: "r", crudo: "r" },
           { id: 3, rol: "usuario", texto: "colgado" }],
  }));
  render(<ChatConsulta iaDisponible />);
  expect(screen.getByText("uno")).toBeTruthy();
  expect(screen.queryByText("colgado")).toBeNull();
});

test("tras restaurar, el primer envío manda el crudo y no las cifras", async () => {
  sessionStorage.setItem("chat-consulta", JSON.stringify({
    abierto: true,
    hilo: [{ id: 1, rol: "usuario", texto: "hola" },
           { id: 2, rol: "agente", texto: "Total $10", crudo: "Total {{costo:corrida:1}}" }],
  }));
  responder("Ok.", "Ok.");
  render(<ChatConsulta iaDisponible />);
  escribirYEnviar("y?");
  await waitFor(() => expect(chatConsultaStream).toHaveBeenCalledTimes(1));
  const h = chatConsultaStream.mock.calls[0][0] as { texto: string }[];
  expect(h[1].texto).toBe("Total {{costo:corrida:1}}");
  expect(JSON.stringify(h)).not.toContain("$10");
});

test("el evento error devuelve el texto a la caja y avisa", async () => {
  chatConsultaStream.mockImplementationOnce(async (_m: unknown, onEv: OnEv) => {
    onEv({ event: "error", data: { detail: "falló" } });
  });
  render(<ChatConsulta iaDisponible />);
  abrir();
  escribirYEnviar("pregunta");
  expect((await screen.findByRole("alert")).textContent).toContain("falló");
  expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("pregunta");
});

test("Escape cierra el panel y deja el foco en el botón", async () => {
  render(<ChatConsulta iaDisponible />);
  abrir();
  const caja = screen.getByRole("textbox");
  expect(document.activeElement).toBe(caja);
  fireEvent.keyDown(caja, { key: "Escape" });
  const boton = await screen.findByRole("button", { name: /abrir el agente de consulta/i });
  expect(document.activeElement).toBe(boton);
});

test("Limpiar restablece estado y línea", async () => {
  chatConsultaStream.mockImplementationOnce(async (_m: unknown, onEv: OnEv) => {
    onEv({ event: "error", data: { detail: "x" } });
  });
  responder("A", "A");
  render(<ChatConsulta iaDisponible />);
  abrir();
  escribirYEnviar("p1");
  await screen.findByText("No pude responder");
  escribirYEnviar("p1");
  await screen.findByText("A");
  chatConsultaStream.mockReset();
  // tras un error previo el estado era "error"; con respuesta quedó en espera: forzamos otro error
  chatConsultaStream.mockImplementationOnce(async (_m: unknown, onEv: OnEv) => {
    onEv({ event: "error", data: { detail: "x" } });
  });
  escribirYEnviar("p2");
  await screen.findByText("No pude responder");
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: /limpiar/i })); });
  expect(screen.queryByText("No pude responder")).toBeNull();
  expect(screen.getByText("Precios, costos y totales")).toBeTruthy();
});
