import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test, vi } from "vitest";
// El import va ARRIBA, fuera de los `test`. Adentro (`await import("./Layout")`) el
// costo de transformar e importar el módulo se le cobra al presupuesto de 5 s de cada
// test: medido en Usuarios.test.tsx, 1682-2232 ms de los 5000. `vi.mock` lo hoistea
// vitest antes de los imports, así que los mocks de abajo siguen aplicándose.
import Layout from "./Layout";

// Números distintos entre sí a propósito: con insumos y apus en 0 no se puede
// distinguir una lectura de la otra en el DOM.
vi.mock("@/api/corridas", () => ({
  getStatus: vi.fn(async () => ({ insumos: 7095, apus: 1204, ia: false })),
}));
vi.mock("@/api/presencia", () => ({
  getPresencia: vi.fn(async () => ({
    en_linea: [
      { user_id: "u1", email: "a@obra.co", nombre: "Ana" },
      { user_id: "u2", email: "beto@obra.co", nombre: "Beto" },
    ],
  })),
}));
let rol = "consulta";
vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ perfil: { email: "a@obra.co", rol }, logout: vi.fn() }),
}));

test("el link Usuarios solo aparece para Admin", async () => {
  rol = "editor";
  const { unmount } = render(<MemoryRouter><Layout /></MemoryRouter>);
  expect(screen.queryByText("Usuarios")).toBeNull();
  unmount();
  rol = "admin";
  render(<MemoryRouter><Layout /></MemoryRouter>);
  expect(screen.getByText("Usuarios")).not.toBeNull();
});

test("las cuatro lecturas de estado van separadas, no en una frase", async () => {
  // Antes era una sola cadena interpolada: "7095 insumos · 1204 APUs · IA: fallback".
  // Para sacar un número había que leerla entera. Pasan a ser tres lecturas con su
  // etiqueta y su valor, así que cada valor tiene que existir como nodo propio.
  rol = "editor";
  render(<MemoryRouter><Layout /></MemoryRouter>);

  expect(await screen.findByText("7.095")).not.toBeNull();
  expect(screen.getByText("1.204")).not.toBeNull();
  expect(screen.getByText("fallback")).not.toBeNull();

  // Y la cadena vieja no puede seguir existiendo en ninguna parte.
  expect(screen.queryByText(/insumos · .* APUs/)).toBeNull();
});

test("la sección activa se marca con aria-current (guard anti-regresión)", async () => {
  // NavLink ya pone aria-current="page" solo (react-router: ariaCurrentProp = "page"
  // aplicado cuando isActive). Este test NO agrega comportamiento: evita que la
  // reescritura del shell lo pierda cambiando NavLink por un <a> pelado.
  rol = "editor";
  render(
    <MemoryRouter initialEntries={["/insumos"]}>
      <Layout />
    </MemoryRouter>
  );
  const nav = screen.getByRole("navigation");
  const activa = within(nav).getByRole("link", { current: "page" });
  expect(activa.textContent).toContain("Insumos");
});

test("la navegación es un landmark, separada de las lecturas de estado", async () => {
  // «Insumos» y «APUs» aparecen dos veces en la barra: como sección y como lectura.
  // Que la nav sea un <nav> permite distinguirlas — y es lo que necesita quien
  // navega con lector de pantalla para saltar directo a los destinos.
  rol = "admin";
  render(<MemoryRouter><Layout /></MemoryRouter>);
  const nav = screen.getByRole("navigation");
  const destinos = within(nav).getAllByRole("link").map((a) => a.textContent);
  expect(destinos).toEqual(["Corridas", "Insumos", "APUs", "Usuarios", "Auditoría"]);
});

test("la barra muestra cuánta gente está en línea, y quién", async () => {
  rol = "editor";
  render(<MemoryRouter><Layout /></MemoryRouter>);

  // El conteo es un nodo propio, como las otras lecturas.
  const conteo = await screen.findByText("2");
  expect(conteo).not.toBeNull();

  // Los nombres van en el title: la barra es densa, no caben dos columnas de gente.
  // El propio usuario (a@obra.co, el del mock de useAuth) queda marcado.
  const titulo = conteo.closest("[title]")?.getAttribute("title") ?? "";
  expect(titulo).toContain("Ana (vos)");
  expect(titulo).toContain("Beto");
});

test("el poll de presencia se re-suscribe a visibilitychange y se limpia al desmontar", async () => {
  // No agrega comportamiento nuevo al DOM: es un guard de ciclo de vida (el listener
  // se registra al montar y se retira al desmontar), como el resto de esta suite.
  rol = "editor";
  const addSpy = vi.spyOn(document, "addEventListener");
  const removeSpy = vi.spyOn(document, "removeEventListener");

  const { unmount } = render(<MemoryRouter><Layout /></MemoryRouter>);
  await screen.findByText("2"); // espera el primer poll, para no desmontar a mitad de camino

  expect(addSpy).toHaveBeenCalledWith("visibilitychange", expect.any(Function));
  const [, handler] = addSpy.mock.calls.find(([evento]) => evento === "visibilitychange")!;

  unmount();
  expect(removeSpy).toHaveBeenCalledWith("visibilitychange", handler);

  addSpy.mockRestore();
  removeSpy.mockRestore();
});
