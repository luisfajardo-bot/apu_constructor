import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { DialogoImportarInsumos } from "./DialogoImportarInsumos";

// Regresión del hallazgo Minor (revisión del commit a1df261): tanto el preview
// como el aplicar son caminos de escritura; si se pierde la lista_id, la
// importación termina escribiendo en Principal (el catálogo real de la
// empresa, ~8157 insumos en producción) en vez de en la lista elegida.

const previewImportarInsumos = vi.fn();
const aplicarImportarInsumos = vi.fn();
vi.mock("@/api/insumos", () => ({
  previewImportarInsumos: (...a: unknown[]) => previewImportarInsumos(...a),
  aplicarImportarInsumos: (...a: unknown[]) => aplicarImportarInsumos(...a),
  descargarPlantillaInsumos: vi.fn(),
}));

function archivoDemo(): File {
  return new File(["contenido"], "insumos.xlsx", {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
}

beforeEach(() => {
  previewImportarInsumos.mockReset();
  aplicarImportarInsumos.mockReset();
  previewImportarInsumos.mockResolvedValue({
    crear: [{ codigo: "C1", nombre: "CEMENTO GRIS", unidad: "KG", grupo: "MAT",
              precio: 100, fuente: "PRECIO IDU" }],
    actualizar: [], ambigua: [], no_encontrada: [], invalida: [],
  });
  aplicarImportarInsumos.mockResolvedValue({ creados: 1, actualizados: 0, errores: [] });
});

function seleccionarArchivo() {
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [archivoDemo()] } });
}

describe("DialogoImportarInsumos", () => {
  it("el preview manda la lista_id de la lista seleccionada", async () => {
    render(
      <DialogoImportarInsumos
        open onOpenChange={() => {}} listaId={7} listaNombre="NP Calle 13" onAplicado={() => {}}
      />
    );
    seleccionarArchivo();

    await waitFor(() => expect(previewImportarInsumos).toHaveBeenCalled());
    const form = previewImportarInsumos.mock.calls[0][0] as FormData;
    expect(form.get("lista_id")).toBe("7");
  });

  it("aplicar manda la misma lista_id que el preview", async () => {
    render(
      <DialogoImportarInsumos
        open onOpenChange={() => {}} listaId={7} listaNombre="NP Calle 13" onAplicado={() => {}}
      />
    );
    seleccionarArchivo();
    await screen.findByText("Aplicar (1)");
    fireEvent.click(screen.getByText("Aplicar (1)"));

    await waitFor(() => expect(aplicarImportarInsumos).toHaveBeenCalled());
    const form = aplicarImportarInsumos.mock.calls[0][0] as FormData;
    expect(form.get("lista_id")).toBe("7");
  });

  it("muestra las filas en conflicto con su motivo y no las cuenta para aplicar", async () => {
    previewImportarInsumos.mockResolvedValue({
      crear: [], actualizar: [], ambigua: [], no_encontrada: [], invalida: [],
      conflicto: [{
        codigo: "10014", nombre: "ESTABILIZACION CON RAJON",
        motivo: "El código 10014 ya lo usa el insumo «USO DEL PENETROMETRO».",
      }],
    });
    render(
      <DialogoImportarInsumos
        open onOpenChange={() => {}} listaId={7} listaNombre="NP Calle 13" onAplicado={() => {}}
      />
    );
    seleccionarArchivo();

    expect(await screen.findByText(/En conflicto/i)).toBeTruthy();
    expect(screen.getByText(/ya lo usa el insumo/i)).toBeTruthy();
    // el botón cuenta crear + actualizar: las filas en conflicto no lo habilitan
    expect((screen.getByText("Aplicar (0)") as HTMLButtonElement).disabled).toBe(true);
  });
});
