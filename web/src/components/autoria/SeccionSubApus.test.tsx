import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

// DialogoImportarApus.tsx importa "@/api/autoria" (y este, transitivamente,
// el cliente de Supabase); se mockea para poder importar solo SeccionSubApus
// sin depender de VITE_SUPABASE_URL/ANON_KEY en el entorno de test.
vi.mock("@/api/autoria", () => ({
  previewImportarApus: vi.fn(),
  aplicarImportarApus: vi.fn(),
  descargarPlantillaApus: vi.fn(),
}));

import { SeccionSubApus } from "./DialogoImportarApus";

test("lista los sub-APUs detectados con su origen", () => {
  render(
    <SeccionSubApus
      vinculos={[
        { apu_codigo: "3010", apu_turno: "DIURNO", sub_codigo: "7439",
          sub_turno: "DIURNO", sub_nombre: "MARTILLO", origen: "lote" },
        { apu_codigo: "3011", apu_turno: "DIURNO", sub_codigo: "7439",
          sub_turno: "DIURNO", sub_nombre: "MARTILLO", origen: "biblioteca" },
      ]}
    />,
  );
  expect(screen.getByText(/Sub-APUs detectados/)).toBeTruthy();
  expect(screen.getByText("3010")).toBeTruthy();
  expect(screen.getByText(/en el lote/)).toBeTruthy();
  expect(screen.getByText(/en biblioteca/)).toBeTruthy();
});

test("no renderiza nada si no hay vínculos", () => {
  const { container } = render(<SeccionSubApus vinculos={[]} />);
  expect(container.textContent).toBe("");
});
