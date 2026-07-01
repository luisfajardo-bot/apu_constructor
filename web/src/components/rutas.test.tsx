import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { expect, test, vi } from "vitest";

let mockAuth: { sesion: unknown; perfil: unknown; cargando: boolean; noAutorizado: boolean };
vi.mock("@/lib/auth", () => ({ useAuth: () => mockAuth }));

test("sin sesión redirige a /login", async () => {
  const { RutaProtegida } = await import("./rutas");
  mockAuth = { sesion: null, perfil: null, cargando: false, noAutorizado: false };
  render(
    <MemoryRouter initialEntries={["/priv"]}>
      <Routes>
        <Route path="/login" element={<div>LOGIN</div>} />
        <Route element={<RutaProtegida />}>
          <Route path="/priv" element={<div>PRIVADO</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
  expect(screen.getByText("LOGIN")).not.toBeNull();
});

test("con perfil muestra el contenido privado", async () => {
  const { RutaProtegida } = await import("./rutas");
  mockAuth = { sesion: {}, perfil: { rol: "consulta" }, cargando: false, noAutorizado: false };
  render(
    <MemoryRouter initialEntries={["/priv"]}>
      <Routes>
        <Route element={<RutaProtegida />}>
          <Route path="/priv" element={<div>PRIVADO</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
  expect(screen.getByText("PRIVADO")).not.toBeNull();
});

test("puede() respeta la jerarquía", async () => {
  const { puede } = await import("./rutas");
  expect(puede("admin", "editor")).toBe(true);
  expect(puede("consulta", "editor")).toBe(false);
});
