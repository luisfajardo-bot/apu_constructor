import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test, vi } from "vitest";
import { colorSigno } from "./MisCorridas";

vi.mock("@/api/corridas", () => ({
  listarCorridas: vi.fn(async () => [{
    id: 1, archivo: "lic.xlsx", creada_en: "2026-07-08T10:00:00", estado: "en_revision",
    modo: "activa", n_items: 2, n_revision: 1, duracion_ms: 1000,
    contractual: 4000000, costo: 3675000, margen: 325000, margen_pct: 0.08125,
  }]),
  eliminarCorrida: vi.fn(),
  descargarPlantillaLicitacion: vi.fn(),
}));

test("colorSigno: verde si >=0, rojo si <0, undefined si null", () => {
  expect(colorSigno(10)).toBe("#276749");
  expect(colorSigno(0)).toBe("#276749");
  expect(colorSigno(-5)).toBe("#c53030");
  expect(colorSigno(null)).toBeUndefined();
});

test("MisCorridas muestra contractual, costo, dif y margen % formateados", async () => {
  const { default: MisCorridas } = await import("./MisCorridas");
  render(<MemoryRouter><MisCorridas /></MemoryRouter>);
  await waitFor(() => expect(screen.getByText("$4.000.000")).toBeTruthy());
  expect(screen.getByText("$3.675.000")).toBeTruthy();
  expect(screen.getByText("$325.000")).toBeTruthy();
  expect(screen.getByText("8.1%")).toBeTruthy();
});
