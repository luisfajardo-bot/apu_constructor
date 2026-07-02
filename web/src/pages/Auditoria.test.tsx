import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";

vi.mock("@/api/auditoria", () => ({
  listarAuditoria: vi.fn(async () => ({
    items: [
      {
        id: 1, ts: "2026-07-01T10:00:00+00:00", user_id: "u1", user_email: "a@obra.co",
        rol: "editor", accion: "precio.editar", entidad_tipo: "insumo", entidad_id: "42",
        antes: { precio: 1000 }, despues: { precio: 1500 },
        contexto: { origen: "edicion", lote_id: "L1" },
      },
    ],
    total: 1, limit: 100, offset: 0,
  })),
}));

test("lista los eventos de auditoría", async () => {
  const { default: Auditoria } = await import("./Auditoria");
  render(<Auditoria />);
  await waitFor(() => expect(screen.getByText("a@obra.co")).toBeTruthy());
  expect(screen.getByText("precio.editar")).toBeTruthy();
});

test("agrupa filas de un lote aunque estén intercaladas", async () => {
  const mod = await import("@/api/auditoria");
  vi.spyOn(mod, "listarAuditoria").mockResolvedValue({
    items: [
      { id: 3, ts: "2026-07-01T10:02:00Z", user_id: "u", user_email: "a@o.co", rol: "editor",
        accion: "insumo.crear", entidad_tipo: "insumo", entidad_id: "1",
        antes: null, despues: null, contexto: { origen: "import", lote_id: "L1" } },
      { id: 2, ts: "2026-07-01T10:01:00Z", user_id: "u2", user_email: "b@o.co", rol: "editor",
        accion: "precio.editar", entidad_tipo: "insumo", entidad_id: "9",
        antes: null, despues: null, contexto: { origen: "edicion", lote_id: "L2" } },
      { id: 1, ts: "2026-07-01T10:00:00Z", user_id: "u", user_email: "a@o.co", rol: "editor",
        accion: "insumo.crear", entidad_tipo: "insumo", entidad_id: "2",
        antes: null, despues: null, contexto: { origen: "import", lote_id: "L1" } },
    ],
    total: 3, limit: 200, offset: 0,
  });
  const { default: Auditoria } = await import("./Auditoria");
  render(<Auditoria />);
  // El lote L1 (2 filas no contiguas) aparece como UN grupo con su cabecera.
  await waitFor(() => expect(screen.getByText(/2 eventos/)).toBeTruthy());
  expect(screen.getByText("b@o.co")).toBeTruthy();   // el evento intercalado sigue visible

  // Al expandir el lote L1, sus 2 filas quedan JUNTAS bajo la cabecera:
  // el evento intercalado (entidad #9, lote L2) no debe quedar entre ellas.
  fireEvent.click(screen.getByText(/2 eventos/));
  await waitFor(() => expect(screen.getByText("insumo #1")).toBeTruthy());
  const filas = screen.getAllByRole("row").map((r) => r.textContent ?? "");
  const idxCab = filas.findIndex((t) => t.includes("2 eventos"));
  const idxFila1 = filas.findIndex((t) => t.includes("insumo #1"));
  const idxFila2 = filas.findIndex((t) => t.includes("insumo #2"));
  const idxIntercalada = filas.findIndex((t) => t.includes("insumo #9"));
  expect(idxFila1).toBeGreaterThan(idxCab);
  expect(idxFila2).toBeGreaterThan(idxCab);
  // Ambas filas del lote deben ser inmediatamente contiguas a la cabecera,
  // sin que la fila intercalada (lote L2) se cuele entre ellas.
  expect([idxFila1, idxFila2].sort((a, b) => a - b)).toEqual([idxCab + 1, idxCab + 2]);
  expect(idxIntercalada === -1 || idxIntercalada > idxCab + 2).toBe(true);
});
