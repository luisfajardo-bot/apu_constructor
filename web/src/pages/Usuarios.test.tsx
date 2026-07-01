import { render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";

vi.mock("@/api/usuarios", () => ({
  listarUsuarios: vi.fn(async () => [
    { user_id: "u1", email: "a@obra.co", rol: "editor", estado: "activo", nombre: "Ana" },
  ]),
  invitarUsuario: vi.fn(async () => ({ user_id: "u2" })),
  cambiarRol: vi.fn(async () => ({})),
  cambiarEstado: vi.fn(async () => ({})),
}));

test("lista los usuarios existentes", async () => {
  const { default: Usuarios } = await import("./Usuarios");
  render(<Usuarios />);
  await waitFor(() => expect(screen.getByText("a@obra.co")).toBeTruthy());
  expect(screen.getByText("editor")).toBeTruthy();
});
