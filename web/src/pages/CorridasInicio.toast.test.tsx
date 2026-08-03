/**
 * El aviso "Elige una carpeta" se VE, no solo se llama.
 *
 * `CorridasInicio.test.tsx` mockea `sonner` para espiar la llamada, lo cual verifica el
 * cableado pero no que el usuario vea algo. Este archivo usa el sonner REAL y monta el
 * `<Toaster />` igual que `App.tsx`, así que si algún día se desmonta el Toaster o cambia
 * la librería de avisos, este test falla — y ese es justo el escenario que convertiría el
 * arreglo del botón (habilitado + toast) en un clic que no hace nada visible, peor que el
 * botón deshabilitado que había antes.
 */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test, vi } from "vitest";
import { Toaster } from "sonner";
import CorridasInicio from "./CorridasInicio";

vi.mock("@/lib/armado", () => ({
  useArmadoVivo: () => ({ armarArchivo: vi.fn(), armarEjemplo: vi.fn() }),
}));

vi.mock("@/api/carpetas", () => ({
  listarCarpetas: vi.fn(async () => [
    { id: 1, nombre: "Calle 13", parent_id: null, n_corridas: 0, hijas: [] },
  ]),
  crearCarpeta: vi.fn(),
}));

vi.mock("@/api/listas", () => ({
  listarListas: vi.fn(async () => [
    { id: 1, nombre: "Principal", creada_en: "2026-07-27" },
  ]),
}));

test("sin carpeta elegida, el aviso aparece en pantalla", async () => {
  render(
    <MemoryRouter>
      <CorridasInicio />
      <Toaster richColors position="top-right" />
    </MemoryRouter>
  );
  await screen.findByText("Calle 13");

  fireEvent.click(screen.getByRole("button", { name: /armar/i }));

  // El texto tiene que estar en el DOM, renderizado por el Toaster real.
  await waitFor(() => expect(screen.getByText("Elige una carpeta")).toBeTruthy());
});
