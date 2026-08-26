import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test, vi } from "vitest";

const login = vi.fn(async () => {});
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ login, perfil: null, sesion: null }) }));
const signInWithOAuth = vi.fn(async () => ({ error: null }));
vi.mock("@/lib/supabase", () => ({
  supabase: { auth: { resetPasswordForEmail: vi.fn(), signInWithOAuth } },
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

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

test("sin error en la URL, no muestra ningún toast al montar", async () => {
  // Va antes del test de abajo a propósito: el mock de `toast.error` es del módulo
  // y no se limpia entre tests, así que probar "no se llamó" DESPUÉS de un test que
  // sí lo llama daría un falso negativo.
  window.history.replaceState(null, "", "/login");
  const { toast } = await import("sonner");
  const { default: Login } = await import("./Login");
  render(<MemoryRouter><Login /></MemoryRouter>);
  expect(toast.error).not.toHaveBeenCalled();
});

test("si el redirect de Google vuelve con un error en el hash, lo muestra y limpia la URL", async () => {
  // `signInWithOAuth` navega, así que casi nunca devuelve `error` (ver el test de
  // arriba); el error real de un provider sin habilitar o un consentimiento
  // cancelado vuelve como `#error=...&error_description=...` en el redirect.
  window.history.replaceState(null, "", "/login#error=server_error&error_description=No+se+pudo+enlazar");
  const { toast } = await import("sonner");
  const { default: Login } = await import("./Login");
  render(<MemoryRouter><Login /></MemoryRouter>);
  await waitFor(() => expect(toast.error).toHaveBeenCalledWith("No se pudo enlazar"));
  // Se limpia para que el error no reaparezca si el usuario recarga la página.
  expect(window.location.hash).toBe("");
  expect(window.location.search).toBe("");
});
