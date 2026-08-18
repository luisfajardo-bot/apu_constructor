import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { DialogoAgregarLineas } from "./DialogoAgregarLineas";

const previewLineas = vi.fn();
const importarLineas = vi.fn();
const agregarLineas = vi.fn();
vi.mock("@/api/corridas", () => ({
  previewLineas: (...a: unknown[]) => previewLineas(...a),
  importarLineas: (...a: unknown[]) => importarLineas(...a),
  agregarLineas: (...a: unknown[]) => agregarLineas(...a),
  descargarPlantillaLicitacion: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const CORRIDA = {
  id: 7, nombre: "Calle 13", archivo: "lic.xlsx", estado: "en_revision", modo: "activa",
  items: [], duracion_ms: null, carpeta_id: null, lista_precios_id: null,
  lista_nombre: "Principal",
  totales: { contractual: 0, costo: 0, margen: 0, margen_pct: 0, n_items: 0, n_revision: 0 },
};

function archivoDemo(): File {
  return new File(["contenido"], "faltantes.xlsx", {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
}

beforeEach(() => {
  previewLineas.mockReset();
  importarLineas.mockReset();
  agregarLineas.mockReset();
  previewLineas.mockResolvedValue({
    total: 2, tope: 100, modo: "activa",
    nuevas: [{ item: "9", descripcion: "SARDINEL A-10", unidad: "ML", cantidad: 5,
               precio_contractual: 40000, shift: "DIURNO" }],
    duplicadas: [{ item: "10", descripcion: "CONCRETO CLASE D", unidad: "M3", cantidad: 1,
                   precio_contractual: 400000, shift: "DIURNO", seq_existente: 0 }],
  });
  importarLineas.mockResolvedValue(CORRIDA);
  agregarLineas.mockResolvedValue(CORRIDA);
});

describe("DialogoAgregarLineas", () => {
  it("agrega una línea a mano con el turno elegido", async () => {
    const onAgregado = vi.fn();
    render(<DialogoAgregarLineas open corridaId={7} onOpenChange={() => {}}
                                 onAgregado={onAgregado} />);
    fireEvent.change(screen.getByLabelText("Descripción de la actividad"),
                     { target: { value: "Sardinel A-10" } });
    fireEvent.change(screen.getByLabelText("Unidad"), { target: { value: "ML" } });
    fireEvent.change(screen.getByLabelText("Cantidad"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Precio contractual"), { target: { value: "40000" } });
    fireEvent.change(screen.getByLabelText("Turno"), { target: { value: "NOCTURNO" } });
    fireEvent.click(screen.getByText("Agregar la línea"));

    await waitFor(() => expect(agregarLineas).toHaveBeenCalledWith(7, [{
      descripcion: "Sardinel A-10", unidad: "ML", cantidad: 5,
      precio_contractual: 40000, shift: "NOCTURNO",
    }]));
    expect(onAgregado).toHaveBeenCalledWith(CORRIDA);
  });

  it("no deja agregar una línea sin descripción", async () => {
    render(<DialogoAgregarLineas open corridaId={7} onOpenChange={() => {}}
                                 onAgregado={() => {}} />);
    expect((screen.getByText("Agregar la línea") as HTMLButtonElement).disabled).toBe(true);
    expect(agregarLineas).not.toHaveBeenCalled();
  });

  it("el Excel muestra la previa con las duplicadas antes de aplicar", async () => {
    render(<DialogoAgregarLineas open corridaId={7} onOpenChange={() => {}}
                                 onAgregado={() => {}} />);
    fireEvent.click(screen.getByText("Desde Excel"));
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [archivoDemo()] } });

    await waitFor(() => expect(previewLineas).toHaveBeenCalled());
    expect(await screen.findByText("SARDINEL A-10")).toBeTruthy();
    expect(screen.getByText(/ya está en la corrida/i)).toBeTruthy();
    expect(screen.getByText(/línea 0/i)).toBeTruthy();
    expect(importarLineas).not.toHaveBeenCalled();          // la previa no aplica

    fireEvent.click(screen.getByText("Agregar 2 líneas"));
    await waitFor(() => expect(importarLineas).toHaveBeenCalled());
    expect((importarLineas.mock.calls[0][1] as FormData).get("archivo")).toBeTruthy();
  });
});
