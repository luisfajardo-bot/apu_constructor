import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import DialogoRebuscar from "./DialogoRebuscar";
import type { PropuestaRebusqueda } from "@/lib/tipos";

function propuesta(over: Partial<PropuestaRebusqueda> = {}): PropuestaRebusqueda {
  return {
    seq: 0, item: "1", descripcion: "PANTALLA ACUSTICA", unidad: "M2", cantidad: 10,
    apu_actual: null,
    apu_propuesto: { codigo: "A9", nombre: "PANTALLA ACUSTICA", turno: "DIURNO" },
    score: 0.98, status: "auto", explicacion: "Coincidencia directa (98%).",
    precio_contractual: 900000, costo_unitario: 700000,
    margen_unitario: 200000, margen_pct: 22.2, sin_apu: true, ...over,
  };
}

const previa = (ps: PropuestaRebusqueda[]) => ({
  corrida_id: 1, escaneadas: ps.length + 5, propuestas: ps,
});

describe("DialogoRebuscar", () => {
  it("marca por defecto solo las filas que hoy están sin APU", () => {
    render(<DialogoRebuscar abierto previa={previa([
      propuesta(),
      propuesta({ seq: 1, sin_apu: false,
                  apu_actual: { codigo: "A1", nombre: "OTRO APU" } }),
    ])} aplicando={false} onAplicar={vi.fn()} onCerrar={vi.fn()} />);
    expect((screen.getByLabelText("Marcar línea 1") as HTMLInputElement).checked)
      .toBe(true);
    expect((screen.getByLabelText("Marcar línea 2") as HTMLInputElement).checked)
      .toBe(false);
  });

  it("aplica solo los seq marcados, no todas las propuestas", () => {
    const onAplicar = vi.fn();
    render(<DialogoRebuscar abierto previa={previa([
      propuesta(),
      propuesta({ seq: 1, sin_apu: false,
                  apu_actual: { codigo: "A1", nombre: "OTRO APU" } }),
    ])} aplicando={false} onAplicar={onAplicar} onCerrar={vi.fn()} />);
    // Sin tocar nada: viene marcada SOLO la que está sin APU. Es a propósito que no
    // se marque la segunda antes de aplicar — si el componente mandara todas las
    // propuestas en vez de las marcadas, acá saldría [0, 1] y el test lo cazaría.
    // Con las dos marcadas, los dos comportamientos dan el mismo resultado y el test
    // no probaría nada.
    fireEvent.click(screen.getByRole("button", { name: /Aplicar 1 cambio/ }));
    expect(onAplicar).toHaveBeenCalledWith([0]);
  });

  it("marcar a mano una fila que ya tiene APU la suma", () => {
    const onAplicar = vi.fn();
    render(<DialogoRebuscar abierto previa={previa([
      propuesta(),
      propuesta({ seq: 1, sin_apu: false,
                  apu_actual: { codigo: "A1", nombre: "OTRO APU" } }),
    ])} aplicando={false} onAplicar={onAplicar} onCerrar={vi.fn()} />);
    fireEvent.click(screen.getByLabelText("Marcar línea 2"));
    fireEvent.click(screen.getByRole("button", { name: /Aplicar 2 cambios/ }));
    expect(onAplicar).toHaveBeenCalledWith([0, 1]);
  });

  it("marcar todas alcanza a las que ya tienen APU", () => {
    const onAplicar = vi.fn();
    render(<DialogoRebuscar abierto previa={previa([
      propuesta({ seq: 0, sin_apu: false,
                  apu_actual: { codigo: "A1", nombre: "OTRO" } }),
      propuesta({ seq: 1, sin_apu: false,
                  apu_actual: { codigo: "A2", nombre: "OTRO" } }),
    ])} aplicando={false} onAplicar={onAplicar} onCerrar={vi.fn()} />);
    fireEvent.click(screen.getByLabelText("Marcar todas las líneas"));
    fireEvent.click(screen.getByRole("button", { name: /Aplicar 2/ }));
    expect(onAplicar).toHaveBeenCalledWith([0, 1]);
  });

  it("shift+clic marca el rango desde el ancla", () => {
    const onAplicar = vi.fn();
    // Cuatro filas, ninguna sin APU: arranca todo desmarcado, así el rango se ve solo.
    const conApu = (seq: number) => propuesta({
      seq, sin_apu: false, apu_actual: { codigo: `A${seq}`, nombre: "VIEJO" },
    });
    render(<DialogoRebuscar abierto
      previa={previa([conApu(0), conApu(1), conApu(2), conApu(3)])}
      aplicando={false} onAplicar={onAplicar} onCerrar={vi.fn()} />);

    fireEvent.click(screen.getByLabelText("Marcar línea 2"));                    // ancla
    fireEvent.click(screen.getByLabelText("Marcar línea 4"), { shiftKey: true }); // rango

    fireEvent.click(screen.getByRole("button", { name: /Aplicar 3 cambios/ }));
    expect(onAplicar).toHaveBeenCalledWith([1, 2, 3]);
  });

  it("el botón Cerrar no responde mientras se está aplicando", () => {
    const onCerrar = vi.fn();
    render(<DialogoRebuscar abierto previa={previa([propuesta()])}
      aplicando onAplicar={vi.fn()} onCerrar={onCerrar} />);
    fireEvent.click(screen.getByRole("button", { name: "Cerrar" }));
    // Cerrar no cancela el POST en vuelo: dejarlo apretable engaña al usuario.
    expect(onCerrar).not.toHaveBeenCalled();
  });

  it("sin propuestas lo dice y no ofrece aplicar", () => {
    render(<DialogoRebuscar abierto previa={previa([])} aplicando={false}
                            onAplicar={vi.fn()} onCerrar={vi.fn()} />);
    expect(screen.getByText(/Ninguna actividad encontró un APU mejor/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Aplicar/ })).toBeNull();
  });

  it("muestra el antes y el después de la fila que ya tiene APU", () => {
    render(<DialogoRebuscar abierto previa={previa([
      propuesta({ sin_apu: false, apu_actual: { codigo: "A1", nombre: "VIEJO" } }),
    ])} aplicando={false} onAplicar={vi.fn()} onCerrar={vi.fn()} />);
    expect(screen.getByText(/A1/)).toBeTruthy();
    expect(screen.getByText(/A9/)).toBeTruthy();
  });
});
