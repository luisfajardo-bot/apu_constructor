import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import DialogoUmbralCosto from "./DialogoUmbralCosto";
import type { ItemCuadro } from "@/lib/tipos";

function item(p: Partial<ItemCuadro>): ItemCuadro {
  return {
    seq: 0, item: "1", descripcion: "ACTIVIDAD", unidad: "GLB", cantidad: 1,
    apu_codigo: "", apu_nombre: "", status: "new", confianza: 0,
    precio_contractual: 1000, costo_unitario: 0, margen_unitario: 0, margen_pct: 0,
    contractual_total: 1000, costo_total: 0, margen_total: 0,
    costo_manual: false, revision: null, ...p,
  } as ItemCuadro;
}

const ITEMS = [
  item({ seq: 0, item: "1", contractual_total: 100 }),
  item({ seq: 1, item: "2", contractual_total: 900 }),
  item({ seq: 2, item: "3", contractual_total: 5000 }),
];

function abrir(onAplicar = vi.fn()) {
  render(<DialogoUmbralCosto abierto items={ITEMS} aplicando={false}
                             onAplicar={onAplicar} onCerrar={vi.fn()} />);
  return onAplicar;
}

function escribirUmbral(valor: string) {
  fireEvent.change(screen.getByLabelText("Umbral de total contractual"),
                   { target: { value: valor } });
}

describe("DialogoUmbralCosto", () => {
  it("sin umbral no propone nada y el botón está deshabilitado", () => {
    abrir();
    // Sin jest-dom en este proyecto: se mira la propiedad, no un matcher.
    const btn = screen.getByRole("button", { name: /Igualar/ }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it("el techo es inclusivo: con 900 entran las de 100 y 900, no la de 5000", () => {
    abrir();
    escribirUmbral("900");
    expect(screen.getByLabelText("Marcar línea 1")).toBeTruthy();
    expect(screen.getByLabelText("Marcar línea 2")).toBeTruthy();
    expect(screen.queryByLabelText("Marcar línea 3")).toBeNull();
  });

  it("aplica el umbral y solo los seq marcados", () => {
    const onAplicar = abrir();
    escribirUmbral("900");
    // La lista va de mayor a menor: la línea 1 es el seq 1 ($900).
    fireEvent.click(screen.getByLabelText("Marcar línea 1"));
    fireEvent.click(screen.getByRole("button", { name: /Igualar/ }));
    expect(onAplicar).toHaveBeenCalledWith(900, [0]);
  });

  it("cambiar el umbral rehace las marcas", () => {
    const onAplicar = abrir();
    escribirUmbral("900");
    fireEvent.click(screen.getByLabelText("Marcar línea 1"));   // destilda el seq 1
    escribirUmbral("5000");
    fireEvent.click(screen.getByRole("button", { name: /Igualar/ }));
    expect(onAplicar).toHaveBeenCalledWith(5000, [0, 1, 2]);
  });

  it("avisa de las que están en $0 pero el contrato no paga", () => {
    render(<DialogoUmbralCosto abierto aplicando={false} onAplicar={vi.fn()}
                               onCerrar={vi.fn()}
                               items={[item({ precio_contractual: 0, contractual_total: 0 })]} />);
    expect(screen.getByText(/sin precio contractual/i)).toBeTruthy();
  });
});
