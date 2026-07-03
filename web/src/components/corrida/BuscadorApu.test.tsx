import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { expect, test, vi } from "vitest";

vi.mock("@/api/autoria", () => ({
  listarApus: vi.fn(async () => ({
    items: [
      { codigo: "33333", turno: "DIURNO", nombre: "EXCAVACION MANUAL",
        unidad: "M3", grupo: "MOV", n_componentes: 3 },
    ],
    total: 1, limit: 15, offset: 0,
  })),
}));

test("busca por texto y entrega el APU elegido", async () => {
  const { default: BuscadorApu } = await import("./BuscadorApu");
  const { listarApus } = await import("@/api/autoria");
  const onElegir = vi.fn();
  render(<BuscadorApu onElegir={onElegir} />);

  fireEvent.change(screen.getByPlaceholderText(/Buscar APU/i), {
    target: { value: "333" },
  });

  await waitFor(() =>
    expect(listarApus).toHaveBeenCalledWith({ q: "333", limit: 15 }),
  );
  fireEvent.click(await screen.findByText("EXCAVACION MANUAL"));
  expect(onElegir).toHaveBeenCalledWith(
    expect.objectContaining({ codigo: "33333", turno: "DIURNO" }),
  );
});
