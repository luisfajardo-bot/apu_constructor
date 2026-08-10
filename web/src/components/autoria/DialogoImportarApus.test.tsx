import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { DialogoImportarApus } from "./DialogoImportarApus";

// La spec (2026-08-10-sin-duplicados-alta-design.md) pide la sección de conflicto
// en los dos diálogos de import; el de insumos ya la cubre en
// DialogoImportarInsumos.test.tsx, este es el que faltaba para el de APUs.

const previewImportarApus = vi.fn();
const aplicarImportarApus = vi.fn();
vi.mock("@/api/autoria", () => ({
  previewImportarApus: (...a: unknown[]) => previewImportarApus(...a),
  aplicarImportarApus: (...a: unknown[]) => aplicarImportarApus(...a),
  descargarPlantillaApus: vi.fn(),
}));

function archivoDemo(): File {
  return new File(["contenido"], "apus.xlsx", {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
}

beforeEach(() => {
  previewImportarApus.mockReset();
  aplicarImportarApus.mockReset();
  previewImportarApus.mockResolvedValue({
    crear: [{ codigo: "3010", turno: "DIURNO", nombre: "EXCAVACION MANUAL",
              unidad: "M3", grupo: "EXCAVACIONES", n_componentes: 1, costo_unitario: 0 }],
    ya_existe: [], conflicto: [], subapus: [],
  });
  aplicarImportarApus.mockResolvedValue({ creados: 1, subapus_marcados: 0, errores: [] });
});

function seleccionarArchivo() {
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [archivoDemo()] } });
}

describe("DialogoImportarApus", () => {
  it("muestra las filas en conflicto con su motivo y no las cuenta para crear", async () => {
    previewImportarApus.mockResolvedValue({
      crear: [], ya_existe: [], subapus: [],
      conflicto: [{
        codigo: "3010", turno: "NOCTURNO", nombre: "OTRO NOMBRE",
        motivo: "El código 3010 ya lo usa el APU DIURNO «EXCAVACION MANUAL».",
      }],
    });
    render(<DialogoImportarApus open onOpenChange={() => {}} onAplicado={() => {}} />);
    seleccionarArchivo();

    expect(await screen.findByText(/En conflicto/i)).toBeTruthy();
    expect(screen.getByText(/ya lo usa el APU/i)).toBeTruthy();
    // el botón cuenta solo `crear`: las filas en conflicto no lo habilitan
    expect((screen.getByText("Crear los 0") as HTMLButtonElement).disabled).toBe(true);
  });
});
