import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test, vi } from "vitest";

vi.mock("@/api/corridas", () => ({ getStatus: vi.fn(async () => ({ insumos: 0, apus: 0, ia: false })) }));
let rol = "consulta";
vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ perfil: { email: "a@obra.co", rol }, logout: vi.fn() }),
}));

test("el link Usuarios solo aparece para Admin", async () => {
  const { default: Layout } = await import("./Layout");
  rol = "editor";
  const { unmount } = render(<MemoryRouter><Layout /></MemoryRouter>);
  expect(screen.queryByText("Usuarios")).toBeNull();
  unmount();
  rol = "admin";
  render(<MemoryRouter><Layout /></MemoryRouter>);
  expect(screen.getByText("Usuarios")).not.toBeNull();
});
