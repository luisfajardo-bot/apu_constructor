import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test, vi } from "vitest";
import Login from "./Login";
import DefinirClave from "./DefinirClave";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ login: vi.fn(async () => {}), perfil: null, sesion: null }),
}));
vi.mock("@/lib/supabase", () => ({
  supabase: { auth: { resetPasswordForEmail: vi.fn(), updateUser: vi.fn() } },
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

test("los campos del ingreso no apagan el foco con outline:none inline", () => {
  // Login.tsx:150 y DefinirClave.tsx:122 hacían `outline: "none"` sin ningún
  // reemplazo, y `grep -c focus` daba 0 en los dos archivos: quien entra con
  // teclado no veía dónde estaba parado. jsdom no dibuja el anillo, pero sí puede
  // afirmar que no queda un outline:none inline apagándolo — el anillo real lo
  // aporta el primitivo Input (focus-visible:ring-ring) y su contraste lo verifica
  // scripts/verificar_contraste.py.
  render(<MemoryRouter><Login /></MemoryRouter>);
  for (const id of ["login-email", "login-password"]) {
    const campo = document.getElementById(id) as HTMLInputElement;
    expect(campo).not.toBeNull();
    expect(campo.style.outline).toBe("");
  }
});

test("DefinirClave tampoco apaga el foco", () => {
  render(<MemoryRouter><DefinirClave /></MemoryRouter>);
  const campo = document.getElementById("definir-password") as HTMLInputElement;
  expect(campo).not.toBeNull();
  expect(campo.style.outline).toBe("");
});

test("«Mostrar» revela la contraseña y vuelve a ocultarla", () => {
  render(<MemoryRouter><Login /></MemoryRouter>);
  const campo = screen.getByLabelText("Contraseña") as HTMLInputElement;
  expect(campo.type).toBe("password");

  const boton = screen.getByRole("button", { name: "Mostrar" });
  expect(boton.getAttribute("aria-pressed")).toBe("false");

  fireEvent.click(boton);
  expect(campo.type).toBe("text");
  // El botón cambia de nombre, así que hay que volver a buscarlo: el nombre
  // accesible ES la etiqueta visible, sin aria-label, para no chocar con el
  // getByLabelText(/contraseña/i) del test que ya existía.
  const ocultar = screen.getByRole("button", { name: "Ocultar" });
  expect(ocultar.getAttribute("aria-pressed")).toBe("true");

  fireEvent.click(ocultar);
  expect(campo.type).toBe("password");
});

test("el panel de marca dice qué es la app, sin inventar nada", () => {
  // En lugar del testimonio y los logos de clientes de la referencia —que serían
  // contenido falso— el panel lleva lo que la app hace. Y donde iba «Sign up» va
  // la verdad: no hay registro abierto, el acceso lo habilita un administrador.
  render(<MemoryRouter><Login /></MemoryRouter>);
  expect(screen.getByText(/herramienta de evaluación y generación/i)).not.toBeNull();
  expect(screen.getByText(/uso interno/i)).not.toBeNull();
  expect(screen.getByText(/lo habilita un administrador/i)).not.toBeNull();

  // Y nada de lo que la app no puede cumplir.
  expect(screen.queryByText(/google/i)).toBeNull();
  expect(screen.queryByText(/crear cuenta|registrarse|sign up/i)).toBeNull();
  expect(screen.queryByText(/recordarme|remember/i)).toBeNull();
});
