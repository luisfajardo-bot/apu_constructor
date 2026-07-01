import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test, vi } from "vitest";

const login = vi.fn(async () => {});
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ login, perfil: null, sesion: null }) }));
vi.mock("@/lib/supabase", () => ({ supabase: { auth: { resetPasswordForEmail: vi.fn() } } }));

test("envía email+password a login()", async () => {
  const { default: Login } = await import("./Login");
  render(<MemoryRouter><Login /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText(/correo/i), { target: { value: "ana@obra.co" } });
  fireEvent.change(screen.getByLabelText(/contraseña/i), { target: { value: "secreta" } });
  fireEvent.click(screen.getByRole("button", { name: /ingresar/i }));
  await waitFor(() => expect(login).toHaveBeenCalledWith("ana@obra.co", "secreta"));
});
