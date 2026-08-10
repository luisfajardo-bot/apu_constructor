import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test, vi } from "vitest";

const login = vi.fn(async () => {});
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ login, perfil: null, sesion: null }) }));
const signInWithOAuth = vi.fn(async () => ({ error: null }));
vi.mock("@/lib/supabase", () => ({
  supabase: { auth: { resetPasswordForEmail: vi.fn(), signInWithOAuth } },
}));

test("envía email+password a login()", async () => {
  const { default: Login } = await import("./Login");
  render(<MemoryRouter><Login /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText(/correo/i), { target: { value: "ana@obra.co" } });
  fireEvent.change(screen.getByLabelText(/contraseña/i), { target: { value: "secreta" } });
  fireEvent.click(screen.getByRole("button", { name: /ingresar/i }));
  await waitFor(() => expect(login).toHaveBeenCalledWith("ana@obra.co", "secreta"));
});

test("el botón de Google pide el OAuth con el redirect al origen actual", async () => {
  const { default: Login } = await import("./Login");
  render(<MemoryRouter><Login /></MemoryRouter>);
  fireEvent.click(screen.getByRole("button", { name: /google/i }));
  await waitFor(() => expect(signInWithOAuth).toHaveBeenCalledWith({
    provider: "google",
    options: { redirectTo: `${window.location.origin}/corridas` },
  }));
});
