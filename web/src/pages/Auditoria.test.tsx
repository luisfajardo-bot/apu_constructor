import { render, screen, waitFor } from "@testing-library/react";
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
