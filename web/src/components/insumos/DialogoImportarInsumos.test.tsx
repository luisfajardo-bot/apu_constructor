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

function seleccionarFuente(valor = "PRECIO IDU") {
  const input = screen.getByLabelText(/Fuente de esta importación/i);
  fireEvent.change(input, { target: { value: valor } });
  fireEvent.blur(input);
}

function montar() {
  return render(
    <DialogoImportarInsumos
      open onOpenChange={() => {}} listaId={7} listaNombre="NP Calle 13"
      fuentes={["PRECIO IDU", "COSTO INTERNO"]} onAplicado={() => {}}
    />
  );
}

describe("DialogoImportarInsumos", () => {
  it("el preview manda la lista_id de la lista seleccionada", async () => {
    montar();
    seleccionarFuente();
    seleccionarArchivo();

    await waitFor(() => expect(previewImportarInsumos).toHaveBeenCalled());
    const form = previewImportarInsumos.mock.calls[0][0] as FormData;
    expect(form.get("lista_id")).toBe("7");
  });

  it("aplicar manda la misma lista_id que el preview", async () => {
    montar();
    seleccionarFuente();
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
    montar();
    seleccionarFuente();
    seleccionarArchivo();

    expect(await screen.findByText(/En conflicto/i)).toBeTruthy();
    expect(screen.getByText(/ya lo usa el insumo/i)).toBeTruthy();
    // el botón cuenta crear + actualizar: las filas en conflicto no lo habilitan
    expect((screen.getByText("Aplicar (0)") as HTMLButtonElement).disabled).toBe(true);
  });

  it("no deja escoger archivo hasta declarar la fuente", () => {
    montar();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input.disabled).toBe(true);
    seleccionarFuente();
    expect(input.disabled).toBe(false);
  });

  it("manda la fuente declarada en el preview y en el aplicar", async () => {
    montar();
    seleccionarFuente("COSTO INTERNO");
    seleccionarArchivo();

    await waitFor(() => expect(previewImportarInsumos).toHaveBeenCalled());
    expect((previewImportarInsumos.mock.calls[0][0] as FormData).get("fuente_import"))
      .toBe("COSTO INTERNO");

    fireEvent.click(await screen.findByText("Aplicar (1)"));
    await waitFor(() => expect(aplicarImportarInsumos).toHaveBeenCalled());
    expect((aplicarImportarInsumos.mock.calls[0][0] as FormData).get("fuente_import"))
      .toBe("COSTO INTERNO");
  });

  it("recalcula el preview si cambia la fuente con un archivo ya elegido", async () => {
    montar();
    seleccionarFuente("PRECIO IDU");
    seleccionarArchivo();
    await waitFor(() => expect(previewImportarInsumos).toHaveBeenCalledTimes(1));

    seleccionarFuente("COSTO INTERNO");
    await waitFor(() => expect(previewImportarInsumos).toHaveBeenCalledTimes(2));
    expect((previewImportarInsumos.mock.calls[1][0] as FormData).get("fuente_import"))
      .toBe("COSTO INTERNO");
  });

  it("avisa cuando la fuente declarada clasifica como interna", async () => {
    // El caso del typo: "PRECIO IDU 2026" clasifica INTERNO y el candado no protege
    // nada. El aviso es lo único que lo delata antes de aplicar.
    previewImportarInsumos.mockResolvedValue({
      crear: [], actualizar: [], ambigua: [], no_encontrada: [], invalida: [],
      protegida: [], clasificacion_import: "interno",
    });
    montar();
    seleccionarFuente("PRECIO IDU 2026");
    seleccionarArchivo();

    expect(await screen.findByText(/INTERNA/)).toBeTruthy();
  });

  it("no avisa de nada cuando la fuente declarada clasifica como pública", async () => {
    // Sin esta prueba, la anterior pasaría igual si el componente pintara "INTERNA"
    // siempre: hace falta cubrir también la rama pública.
    previewImportarInsumos.mockResolvedValue({
      crear: [], actualizar: [], ambigua: [], no_encontrada: [], invalida: [],
      protegida: [], clasificacion_import: "publico",
    });
    montar();
    seleccionarFuente();
    seleccionarArchivo();

    await screen.findByText(/PÚBLICA/i);
    expect(screen.queryByText(/INTERNA/)).toBeNull();
  });

  it("muestra las filas protegidas y no las cuenta para aplicar", async () => {
    previewImportarInsumos.mockResolvedValue({
      crear: [], actualizar: [], ambigua: [], no_encontrada: [], invalida: [],
      protegida: [{
        codigo: "500", nombre: "MANO DE OBRA OFICIAL",
        fuente_actual: "COSTO INTERNO", precio_actual: 25000, precio_archivo: 9,
      }],
    });
    montar();
    seleccionarFuente();
    seleccionarArchivo();

    expect(await screen.findByText(/Protegidas/i)).toBeTruthy();
    expect(screen.getByText("COSTO INTERNO")).toBeTruthy();
    expect((screen.getByText("Aplicar (0)") as HTMLButtonElement).disabled).toBe(true);
  });

  it("borrar la fuente deshabilita Aplicar aunque ya haya preview", async () => {
    montar();
    seleccionarFuente();
    seleccionarArchivo();
    await screen.findByText("Aplicar (1)");

    const input = screen.getByLabelText(/Fuente de esta importación/i);
    fireEvent.change(input, { target: { value: "" } });

    expect((screen.getByText("Aplicar (1)") as HTMLButtonElement).disabled).toBe(true);
  });

  it("un click en Aplicar en el mismo tick que el blur de la fuente no aplica con otra fuente", async () => {
    // El caso delicado: el blur (que recalcula el preview) dispara antes que el
    // click, así que el botón queda deshabilitado y no se aplica con una fuente
    // distinta a la que se previsualizó. Es exactamente lo que un refactor rompe
    // en silencio.
    montar();
    seleccionarFuente("PRECIO IDU");
    seleccionarArchivo();
    await screen.findByText("Aplicar (1)");

    const input = screen.getByLabelText(/Fuente de esta importación/i);
    fireEvent.change(input, { target: { value: "COSTO INTERNO" } });
    fireEvent.blur(input);
    fireEvent.click(screen.getByText(/Aplicar/));

    // El blur dispara un segundo correrPreview (recalcula con la fuente nueva); hay
    // que esperar a que resuelva antes de terminar el test, o su continuación
    // (setEstado) corre después del test y React se queja de un act() colgado.
    await waitFor(() => expect(previewImportarInsumos).toHaveBeenCalledTimes(2));
    expect(aplicarImportarInsumos).not.toHaveBeenCalled();
  });
});
