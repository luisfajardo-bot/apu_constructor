import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { DialogoAgregarInsumo } from "./DialogoAgregarInsumo";

// Regresión del hallazgo Minor (revisión del commit a1df261): crear un insumo
// es un camino de escritura; si se pierde la lista_id, el insumo se crea en
// Principal (el catálogo real de la empresa) en vez de en la lista elegida.

const crearInsumo = vi.fn();
vi.mock("@/api/autoria", () => ({
  crearInsumo: (...a: unknown[]) => crearInsumo(...a),
}));

// El aviso en vivo llama a este mismo endpoint (ver apu_tool/servicio/rutas.py::
// conflicto_insumo): mockeado acá para que los tests no golpeen la red real.
const conflictoInsumo = vi.fn();
vi.mock("@/api/insumos", () => ({
  conflictoInsumo: (...a: unknown[]) => conflictoInsumo(...a),
}));

beforeEach(() => {
  crearInsumo.mockReset();
  crearInsumo.mockResolvedValue({
    id: 1, codigo: "C1", nombre: "CEMENTO GRIS", unidad: "KG", grupo: "MAT",
    precio: 100, fuente: "PRECIO IDU", clasificacion: "publico", sin_precio: false,
  });
  conflictoInsumo.mockReset();
  conflictoInsumo.mockResolvedValue({ campo: null, motivo: null });
});

function llenarFormulario() {
  fireEvent.change(screen.getByLabelText("Código"), { target: { value: "C1" } });
  fireEvent.change(screen.getByLabelText("Nombre"), { target: { value: "CEMENTO GRIS" } });
  fireEvent.change(screen.getByLabelText("Unidad"), { target: { value: "KG" } });
  fireEvent.change(screen.getByLabelText("Grupo"), { target: { value: "MAT" } });
  fireEvent.change(screen.getByLabelText("Fuente"), { target: { value: "PRECIO IDU" } });
  fireEvent.change(screen.getByLabelText("Precio"), { target: { value: "100" } });
}

describe("DialogoAgregarInsumo", () => {
  it("crea el insumo mandando la lista_id de la lista seleccionada", async () => {
    render(
      <DialogoAgregarInsumo open onOpenChange={() => {}} listaId={7} onCreado={() => {}} />
    );
    llenarFormulario();
    fireEvent.click(screen.getByText("Crear insumo"));

    await waitFor(() => expect(crearInsumo).toHaveBeenCalled());
    const body = crearInsumo.mock.calls[0][0] as { lista_id?: number };
    expect(body.lista_id).toBe(7);
  });

  it("con otra lista seleccionada, manda esa otra lista_id", async () => {
    render(
      <DialogoAgregarInsumo open onOpenChange={() => {}} listaId={1} onCreado={() => {}} />
    );
    llenarFormulario();
    fireEvent.click(screen.getByText("Crear insumo"));

    await waitFor(() => expect(crearInsumo).toHaveBeenCalled());
    const body = crearInsumo.mock.calls[0][0] as { lista_id?: number };
    expect(body.lista_id).toBe(1);
  });

  it("con un conflicto de código, el motivo aparece y bloquea Crear insumo", async () => {
    conflictoInsumo.mockResolvedValue({
      campo: "codigo",
      motivo: "El código C1 ya lo usa el insumo «CEMENTO GRIS».",
    });
    render(
      <DialogoAgregarInsumo open onOpenChange={() => {}} listaId={1} onCreado={() => {}} />
    );
    llenarFormulario();

    await waitFor(
      () => expect(conflictoInsumo).toHaveBeenCalledWith("C1", "CEMENTO GRIS"),
      { timeout: 2000 },
    );
    await screen.findByText("El código C1 ya lo usa el insumo «CEMENTO GRIS».");
    const boton = screen.getByText("Crear insumo") as HTMLButtonElement;
    expect(boton.disabled).toBeTruthy();
  });

  it("si la consulta de conflicto falla, no bloquea el formulario (falla abierta)", async () => {
    conflictoInsumo.mockRejectedValue(new Error("network"));
    render(
      <DialogoAgregarInsumo open onOpenChange={() => {}} listaId={1} onCreado={() => {}} />
    );
    llenarFormulario();

    await waitFor(
      () => expect(conflictoInsumo).toHaveBeenCalledWith("C1", "CEMENTO GRIS"),
      { timeout: 2000 },
    );
    const boton = screen.getByText("Crear insumo") as HTMLButtonElement;
    expect(boton.disabled).toBeFalsy();
  });
});
