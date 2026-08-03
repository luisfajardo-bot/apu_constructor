import { render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
// El import va ARRIBA, fuera del `test`, como en los otros 22 archivos de test. Cuando
// estaba adentro (`await import("./Usuarios")`), el costo de transformar e importar la
// página se le cobraba al presupuesto de 5 s del test: medido en la suite completa, 1682-
// 2232 ms de los 5000, y con la máquina cargada cruzaba el límite ("Test timed out in
// 5000ms", ~1 de cada 3 corridas locales). Con el import acá, el cuerpo del test consume
// ~450 ms. `vi.mock` lo hoistea vitest antes de los imports, así que el mock sigue valiendo.
import Usuarios from "./Usuarios";

vi.mock("@/api/usuarios", () => ({
  listarUsuarios: vi.fn(async () => [
    { user_id: "u1", email: "a@obra.co", rol: "editor", estado: "activo", nombre: "Ana" },
  ]),
  invitarUsuario: vi.fn(async () => ({ user_id: "u2" })),
  cambiarRol: vi.fn(async () => ({})),
  cambiarEstado: vi.fn(async () => ({})),
}));

test("lista los usuarios existentes", async () => {
  render(<Usuarios />);
  await waitFor(() => expect(screen.getByText("a@obra.co")).toBeTruthy());
  expect(screen.getByText("editor")).toBeTruthy();
});
