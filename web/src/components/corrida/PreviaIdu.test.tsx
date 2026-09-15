import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import PreviaIdu from "@/components/corrida/PreviaIdu";
import type { PreviaPresupuesto } from "@/lib/tipos";

const BASE: PreviaPresupuesto = {
  entidad: "IDU",
  formato: "idu_formulario_1",
  archivo: "f1.xlsx",
  hoja: "PROPUESTA ECONÓMICA",
  fila_encabezado: 10,
  parser_version: "idu-f1/1",
  capitulos: [
    { codigo: "1", nombre: "PRELIMINARES", orden: 1, fila_origen: 13,
      actividades: 2, contractual: 137605594, contractual_sin_aiu: 107565459 },
    { codigo: "2", nombre: "PAVIMENTOS", orden: 2, fila_origen: 21,
      actividades: 42, contractual: 37144267929, contractual_sin_aiu: 29037106963 },
  ],
  actividades: 1939,
  filas_ignoradas: 804,
  totales: { contractual: 158456072140, contractual_sin_aiu: 123871215068 },
  conciliacion: { subtotales_ok: true, diferencia: 0 },
  errores: [],
  advertencias: [],
  filas_senaladas: [],
  puede_aprobar: true,
  requiere_confirmacion: true,
};

const props = (previa: PreviaPresupuesto) => ({
  previa, cargando: false, onAprobar: vi.fn(), onCancelar: vi.fn(),
  onCambiarArchivo: vi.fn(),
});

const botonAprobar = () =>
  screen.getByRole("button", { name: /aprobar y crear corrida/i }) as HTMLButtonElement;

describe("PreviaIdu", () => {
  it("dice cuántos capítulos y actividades se detectaron", () => {
    render(<PreviaIdu {...props(BASE)} />);
    expect(screen.getByText(/2 capítulos y 1\.939 actividades/)).toBeTruthy();
  });

  it("muestra la hoja usada y la fila de encabezado", () => {
    render(<PreviaIdu {...props(BASE)} />);
    expect(screen.getByText(/PROPUESTA ECONÓMICA/)).toBeTruthy();
    expect(screen.getByText(/fila 10/)).toBeTruthy();
  });

  it("lista los capítulos con su contractual en formato colombiano", () => {
    render(<PreviaIdu {...props(BASE)} />);
    expect(screen.getByText("PRELIMINARES")).toBeTruthy();
    expect(screen.getByText("$137.605.594")).toBeTruthy();
    expect(screen.getByText("$107.565.459")).toBeTruthy();
  });

  it("aprueba sin fricción cuando no hay ni errores ni advertencias", () => {
    const p = props(BASE);
    render(<PreviaIdu {...p} />);
    expect(botonAprobar().disabled).toBe(false);
    fireEvent.click(botonAprobar());
    expect(p.onAprobar).toHaveBeenCalledTimes(1);
  });

  it("bloquea la aprobación y muestra los errores", () => {
    const conError = {
      ...BASE, puede_aprobar: false, capitulos: [], actividades: 0,
      errores: ["falta_columna: el archivo no trae la columna cantidad."],
    };
    const p = props(conError);
    render(<PreviaIdu {...p} />);
    expect(botonAprobar().disabled).toBe(true);
    expect(screen.getByRole("alert").textContent).toContain("falta_columna");
    fireEvent.click(botonAprobar());
    expect(p.onAprobar).not.toHaveBeenCalled();
  });

  it("con advertencias exige una confirmación explícita antes de aprobar", () => {
    const conAviso = {
      ...BASE,
      advertencias: [{ tipo: "hoja_ambigua", fila: 0,
                       detalle: "Se usó la hoja «PROPUESTA ECONÓMICA»." }],
    };
    const p = props(conAviso);
    render(<PreviaIdu {...p} />);
    expect(botonAprobar().disabled).toBe(true);
    fireEvent.click(screen.getByLabelText(/entiendo las 1 advertencias/i));
    expect(botonAprobar().disabled).toBe(false);
    fireEvent.click(botonAprobar());
    expect(p.onAprobar).toHaveBeenCalledTimes(1);
  });

  it("muestra el detalle de cada advertencia con su fila", () => {
    const conAviso = {
      ...BASE,
      advertencias: [{ tipo: "capitulo_ambiguo", fila: 412,
                       detalle: "El ítem 3.001 dice capítulo 3 pero está dentro del 2." }],
    };
    render(<PreviaIdu {...props(conAviso)} />);
    expect(screen.getByText(/fila 412/)).toBeTruthy();
    expect(screen.getByText(/dice capítulo 3/)).toBeTruthy();
  });

  it("avisa cuando la conciliación contra el Excel no cuadra", () => {
    const desfasada = {
      ...BASE, conciliacion: { subtotales_ok: false, diferencia: -1200 },
    };
    render(<PreviaIdu {...props(desfasada)} />);
    expect(screen.getByText(/no cuadra/i)).toBeTruthy();
  });

  it("cancelar y volver a elegir archivo avisan al padre", () => {
    const p = props(BASE);
    render(<PreviaIdu {...p} />);
    fireEvent.click(screen.getByRole("button", { name: /cancelar/i }));
    expect(p.onCancelar).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: /volver a seleccionar/i }));
    expect(p.onCambiarArchivo).toHaveBeenCalledTimes(1);
  });

  it("mientras crea la corrida no deja apretar dos veces", () => {
    render(<PreviaIdu {...{ ...props(BASE), cargando: true }} />);
    expect((screen.getByRole("button", { name: /creando/i }) as HTMLButtonElement)
      .disabled).toBe(true);
  });

  it("una previa nueva vuelve a exigir la confirmación de advertencias", () => {
    // Otro archivo: el checkbox de la previa anterior no puede seguir marcado.
    const conAviso = {
      ...BASE,
      advertencias: [{ tipo: "unidad_vacia", fila: 7, detalle: "«X» no trae unidad." }],
    };
    const p = props(conAviso);
    const { rerender } = render(<PreviaIdu {...p} />);
    fireEvent.click(screen.getByLabelText(/entiendo las 1 advertencias/i));
    expect(botonAprobar().disabled).toBe(false);
    rerender(<PreviaIdu {...p} previa={{ ...conAviso, archivo: "otro.xlsx" }} />);
    expect(botonAprobar().disabled).toBe(true);
  });
});
