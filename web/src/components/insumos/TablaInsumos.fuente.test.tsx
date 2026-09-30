import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { TablaInsumos } from "./TablaInsumos";

// La fuente solo admite PRECIO IDU o COSTO INTERNO. Digitar un precio la pone en
// COSTO INTERNO (es lo normal); si el precio es del IDU, se cambia en el selector.

const aplicarCambios = vi.fn();
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ perfil: { rol: "editor" } }) }));
vi.mock("@/api/insumos", () => ({
  getInsumo: () => Promise.resolve(null),
  aplicarCambios: (...a: unknown[]) => aplicarCambios(...a),
}));

const INSUMOS = [
  { id: 1, codigo: "9", nombre: "CEMENTO GRIS", unidad: "KG", grupo: "MAT",
    precio: 100, fuente: "PRECIO IDU", clasificacion: "publico", sin_precio: false },
  { id: 2, codigo: "8", nombre: "ARENA", unidad: "M3", grupo: "MAT",
    precio: 200, fuente: "COMPRAS ALMACEN 2026", clasificacion: "interno", sin_precio: false },
];

function montar() {
  return render(<TablaInsumos insumos={INSUMOS} listaId={1} onReload={() => {}} puedeEditar />);
}

function digitarPrecio(textoActual: string, valor: string) {
  fireEvent.click(screen.getByText(textoActual));
  const input = screen.getByRole("spinbutton");
  fireEvent.change(input, { target: { value: valor } });
  fireEvent.blur(input);
}

beforeEach(() => {
  aplicarCambios.mockReset();
  aplicarCambios.mockResolvedValue({ aplicados: 1, errores: [] });
});

describe("TablaInsumos: fuente del precio", () => {
  it("digitar un precio pone la fuente en COSTO INTERNO, y se puede volver a PRECIO IDU", async () => {
    montar();
    const fuente = screen.getByLabelText("Fuente de 9") as HTMLSelectElement;
    expect(fuente.value).toBe("PRECIO IDU");

    digitarPrecio("$100", "150");
    expect(fuente.value).toBe("COSTO INTERNO");

    fireEvent.change(fuente, { target: { value: "PRECIO IDU" } });
    fireEvent.click(screen.getByText(/Guardar/));
    await waitFor(() => expect(aplicarCambios).toHaveBeenCalled());
    expect(aplicarCambios.mock.calls[0][0]).toEqual([
      { insumo_id: 1, precio: 150, fuente: "PRECIO IDU" }]);
  });

  it("una etiqueta vieja se ve pero no se ofrece; al editar queda en una de las dos", () => {
    montar();
    const fuente = screen.getByLabelText("Fuente de 8") as HTMLSelectElement;
    expect(fuente.value).toBe("COMPRAS ALMACEN 2026");
    const vieja = Array.from(fuente.options).find((o) => o.value === "COMPRAS ALMACEN 2026");
    expect(vieja?.disabled).toBe(true);

    digitarPrecio("$200", "250");
    expect(fuente.value).toBe("COSTO INTERNO");
    expect(Array.from(fuente.options).map((o) => o.value)).toEqual(["PRECIO IDU", "COSTO INTERNO"]);
  });
});
