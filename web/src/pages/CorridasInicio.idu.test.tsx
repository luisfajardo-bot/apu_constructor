import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import CorridasInicio from "@/pages/CorridasInicio";

const previsualizar = vi.fn();
const crear = vi.fn();

vi.mock("@/api/corridas", () => ({
  previsualizarCorrida: (...a: unknown[]) => previsualizar(...a),
  crearCorrida: (...a: unknown[]) => crear(...a),
  crearSample: vi.fn(),
  corridaEnCurso: () => null,
}));
vi.mock("@/api/carpetas", () => ({
  listarCarpetas: async () => [{ id: 1, nombre: "Obras", hijas: [] }],
  crearCarpeta: vi.fn(),
}));
vi.mock("@/api/listas", () => ({
  listarListas: async () => [{ id: 1, nombre: "Principal" }],
}));

const PREVIA = {
  entidad: "IDU", formato: "idu_formulario_1", archivo: "f1.xlsx",
  hoja: "PROPUESTA ECONÓMICA", fila_encabezado: 10, parser_version: "idu-f1/1",
  capitulos: [{ codigo: "1", nombre: "PRELIMINARES", orden: 1, fila_origen: 13,
                actividades: 2, contractual: 100, contractual_sin_aiu: 80 }],
  actividades: 2, filas_ignoradas: 5,
  totales: { contractual: 100, contractual_sin_aiu: 80 },
  conciliacion: { subtotales_ok: true, diferencia: 0 },
  errores: [], advertencias: [], filas_senaladas: [],
  puede_aprobar: true, requiere_confirmacion: true,
};

function pintar() {
  return render(<MemoryRouter><CorridasInicio /></MemoryRouter>);
}

async function prepararIdu() {
  pintar();
  fireEvent.change(await screen.findByLabelText(/entidad o fuente/i),
                   { target: { value: "IDU" } });
  fireEvent.change(await screen.findByLabelText(/^carpeta/i), { target: { value: "1" } });
  const input = screen.getByLabelText(/archivo de licitación/i) as HTMLInputElement;
  fireEvent.change(input, { target: { files: [new File(["x"], "f1.xlsx")] } });
}

describe("CorridasInicio · entidad", () => {
  beforeEach(() => {
    previsualizar.mockReset().mockResolvedValue(PREVIA);
    crear.mockReset().mockResolvedValue({ id: 7, total: 2, estado: "armando" });
  });

  it("ofrece las seis entidades y arranca en No identificada", async () => {
    pintar();
    const sel = (await screen.findByLabelText(/entidad o fuente/i)) as HTMLSelectElement;
    expect(sel.value).toBe("NO_IDENTIFICADA");
    const valores = Array.from(sel.options).map((o) => o.value);
    for (const v of ["IDU", "METRO_BOGOTA", "INVIAS", "OTRA_PUBLICA", "PRIVADA",
                     "NO_IDENTIFICADA"]) {
      expect(valores).toContain(v);
    }
  });

  it("con IDU el botón dice Previsualizar y NO crea la corrida", async () => {
    await prepararIdu();
    fireEvent.click(screen.getByRole("button", { name: /previsualizar/i }));
    await waitFor(() => expect(previsualizar).toHaveBeenCalledTimes(1));
    expect(crear).not.toHaveBeenCalled();
    expect(await screen.findByText(/Estructura detectada/)).toBeTruthy();
  });

  it("aprobar reenvía el mismo archivo con confirmada=true", async () => {
    await prepararIdu();
    fireEvent.click(screen.getByRole("button", { name: /previsualizar/i }));
    fireEvent.click(await screen.findByRole("button", { name: /aprobar y crear/i }));
    await waitFor(() => expect(crear).toHaveBeenCalledTimes(1));
    const form = crear.mock.calls[0][0] as FormData;
    expect(form.get("entidad")).toBe("IDU");
    expect(form.get("confirmada")).toBe("true");
    expect(form.get("carpeta_id")).toBe("1");
    expect(form.get("archivo")).toBeInstanceOf(File);
    // Y la previsualización mandó el MISMO archivo, sin confirmar.
    const formPrevia = previsualizar.mock.calls[0][0] as FormData;
    expect(formPrevia.get("confirmada")).toBeNull();
    expect((formPrevia.get("archivo") as File).name).toBe("f1.xlsx");
  });

  it("cancelar cierra la previa sin crear nada", async () => {
    await prepararIdu();
    fireEvent.click(screen.getByRole("button", { name: /previsualizar/i }));
    fireEvent.click(await screen.findByRole("button", { name: /cancelar/i }));
    await waitFor(() => expect(screen.queryByText(/Estructura detectada/)).toBeNull());
    expect(crear).not.toHaveBeenCalled();
  });

  it("cambiar de entidad descarta la previa", async () => {
    await prepararIdu();
    fireEvent.click(screen.getByRole("button", { name: /previsualizar/i }));
    await screen.findByText(/Estructura detectada/);
    fireEvent.change(screen.getByLabelText(/entidad o fuente/i),
                     { target: { value: "INVIAS" } });
    await waitFor(() => expect(screen.queryByText(/Estructura detectada/)).toBeNull());
  });

  it("con otra entidad el flujo de siempre no se toca", async () => {
    pintar();
    fireEvent.change(await screen.findByLabelText(/entidad o fuente/i),
                     { target: { value: "INVIAS" } });
    fireEvent.change(await screen.findByLabelText(/^carpeta/i), { target: { value: "1" } });
    const input = screen.getByLabelText(/archivo de licitación/i) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(["x"], "plana.xlsx")] } });
    fireEvent.click(screen.getByRole("button", { name: /^armar$/i }));
    await waitFor(() => expect(crear).toHaveBeenCalledTimes(1));
    expect(previsualizar).not.toHaveBeenCalled();
    expect((crear.mock.calls[0][0] as FormData).get("entidad")).toBe("INVIAS");
  });

  it("sin carpeta avisa en vez de dejar el botón muerto", async () => {
    // La lección del smoke test del 2026-08-03: nunca un botón inerte sin explicación.
    pintar();
    fireEvent.change(await screen.findByLabelText(/entidad o fuente/i),
                     { target: { value: "IDU" } });
    const input = screen.getByLabelText(/archivo de licitación/i) as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(["x"], "f1.xlsx")] } });
    const boton = screen.getByRole("button", { name: /previsualizar/i }) as HTMLButtonElement;
    expect(boton.disabled).toBe(false);
    fireEvent.click(boton);
    await waitFor(() => expect(previsualizar).not.toHaveBeenCalled());
  });
});
