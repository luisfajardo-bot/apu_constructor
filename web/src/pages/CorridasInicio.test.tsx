import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test, vi } from "vitest";

vi.mock("@/lib/armado", () => ({
  useArmadoVivo: () => ({ armarArchivo: vi.fn(), armarEjemplo: vi.fn() }),
}));

vi.mock("@/api/carpetas", () => ({
  listarCarpetas: vi.fn(async () => [
    {
      id: 1,
      nombre: "Calle 13",
      parent_id: null,
      n_corridas: 0,
      hijas: [
        { id: 2, nombre: "Lote 3", parent_id: 1, n_corridas: 0, hijas: [] },
      ],
    },
  ]),
  crearCarpeta: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

test('"Armar" está deshabilitado hasta elegir carpeta', async () => {
  const { default: CorridasInicio } = await import("./CorridasInicio");
  render(
    <MemoryRouter>
      <CorridasInicio />
    </MemoryRouter>
  );

  // Wait for folders to load (level-1 select appears with "Calle 13" option)
  await screen.findByText("Calle 13");

  const btnArmar = screen.getByRole("button", { name: /armar/i });

  // Button should be disabled before selecting a folder
  expect(btnArmar.hasAttribute("disabled")).toBe(true);

  // Select "Calle 13" (id=1) in the level-1 select
  const selectNivel1 = screen.getByLabelText(/carpeta/i);
  fireEvent.change(selectNivel1, { target: { value: "1" } });

  // Button should now be enabled
  await waitFor(() => expect(btnArmar.hasAttribute("disabled")).toBe(false));
});
