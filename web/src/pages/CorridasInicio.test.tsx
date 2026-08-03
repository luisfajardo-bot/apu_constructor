import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, test, vi } from "vitest";
import { toast } from "sonner";
// El import va ARRIBA, fuera de los `test`. Cuando estaba adentro
// (`await import("./CorridasInicio")` en cada test), el costo de transformar e importar la
// página se le cobraba al presupuesto de 5 s de cada test: medido en otro archivo con la
// misma forma, 1682-2232 ms de los 5000, y con la máquina cargada eso termina en
// "Test timed out in 5000ms". `vi.mock` lo hoistea vitest antes de los imports, así que los
// mocks de abajo siguen aplicándose igual.
import CorridasInicio from "./CorridasInicio";

// Referencia compartida y hoisted para poder inspeccionar (mock.calls) cómo la
// pantalla llama a armarArchivo — en particular, qué trae el FormData —
// sin cambiar el comportamiento (resuelve enseguida) que ya asumían los tests
// existentes de este archivo.
const { armarArchivoMock, crearCarpetaMock } = vi.hoisted(() => ({
  armarArchivoMock: vi.fn(() => Promise.resolve()),
  crearCarpetaMock: vi.fn(),
}));

vi.mock("@/lib/armado", () => ({
  useArmadoVivo: () => ({ armarArchivo: armarArchivoMock, armarEjemplo: vi.fn() }),
}));

vi.mock("@/api/carpetas", () => ({
  listarCarpetas: vi.fn(async () => [
    {
      id: 1,
      nombre: "Calle 13",
      parent_id: null,
      n_corridas: 0,
      hijas: [
        { id: 2, nombre: "Lote 3", parent_id: 1, n_corridas: 0, hijas: [] },
      ],
    },
  ]),
  crearCarpeta: crearCarpetaMock,
}));

vi.mock("@/api/listas", () => ({
  listarListas: vi.fn(async () => [
    { id: 1, nombre: "Principal", creada_en: "2026-07-27" },
    { id: 2, nombre: "NP Calle 13", creada_en: "2026-07-27" },
  ]),
}));

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}));

beforeEach(() => {
  armarArchivoMock.mockClear();
  vi.mocked(toast.error).mockClear();
});

test('"Armar" avisa que falta la carpeta en vez de quedarse deshabilitado', async () => {
  // Antes el botón se deshabilitaba cuando no había carpeta elegida, y como el campo no
  // está marcado como obligatorio ni el botón se ve gris (usa estilos inline), el usuario
  // se quedaba sin poder armar y sin ningún mensaje. Peor: `handleArmar` YA tenía el
  // toast "Elige una carpeta", pero era código muerto — el guard del botón nunca lo
  // dejaba correr. Encontrado en el smoke test de producción del 2026-08-03.
  render(
    <MemoryRouter>
      <CorridasInicio />
    </MemoryRouter>
  );
  await screen.findByText("Calle 13");           // carpetas cargadas

  const btnArmar = screen.getByRole("button", { name: /armar/i });
  expect(btnArmar.hasAttribute("disabled")).toBe(false);

  fireEvent.click(btnArmar);                     // sin carpeta elegida

  await waitFor(() =>
    expect(vi.mocked(toast.error)).toHaveBeenCalledWith("Elige una carpeta"));
  // Y no dispara una corrida a medias: el aviso reemplaza al bloqueo, no lo saltea.
  expect(armarArchivoMock).not.toHaveBeenCalled();
});

test("al elegir archivo, precarga el Nombre sin extensión", async () => {
  render(<MemoryRouter><CorridasInicio /></MemoryRouter>);
  await screen.findByText("Calle 13");

  const fileInput = document.getElementById("archivo") as HTMLInputElement;
  const file = new File(["x"], "Licitacion Calle 13.xlsx", { type: "application/octet-stream" });
  fireEvent.change(fileInput, { target: { files: [file] } });

  const nombreInput = screen.getByLabelText("Nombre") as HTMLInputElement;
  await waitFor(() => expect(nombreInput.value).toBe("Licitacion Calle 13"));
});

test("no pisa el Nombre si el usuario ya lo editó", async () => {
  render(<MemoryRouter><CorridasInicio /></MemoryRouter>);
  await screen.findByText("Calle 13");

  const nombreInput = screen.getByLabelText("Nombre") as HTMLInputElement;
  fireEvent.change(nombreInput, { target: { value: "Mi alias" } });

  const fileInput = document.getElementById("archivo") as HTMLInputElement;
  const file = new File(["x"], "otra.xlsx", { type: "application/octet-stream" });
  fireEvent.change(fileInput, { target: { files: [file] } });

  expect(nombreInput.value).toBe("Mi alias");
});

test("el aviso de la lista advierte que «Usar ejemplo» usa Principal", async () => {
  // El aviso vive al lado de DOS botones y solo aplica a uno: "Usar ejemplo" pega a
  // /api/sample/stream, que no recibe lista_id (el ejemplo es una demo construida sobre
  // Principal: sus contractuales salen de costo_Principal * (1+margen), pipeline.py).
  // En el smoke test de producción del 2026-08-03 eso sorprendió: se eligió una lista NP,
  // se usó el atajo y la corrida salió costeada con Principal.
  render(
    <MemoryRouter>
      <CorridasInicio />
    </MemoryRouter>
  );
  await waitFor(() => expect(screen.getByLabelText(/lista de precios/i)).toBeTruthy());

  fireEvent.change(screen.getByLabelText(/lista de precios/i), { target: { value: "2" } });

  const aviso = screen.getByText(/no se puede cambiar/i);
  expect(aviso.textContent).toMatch(/usar ejemplo/i);
  expect(aviso.textContent).toMatch(/principal/i);
});

test("ofrece las listas de precios disponibles", async () => {
  render(
    <MemoryRouter>
      <CorridasInicio />
    </MemoryRouter>
  );
  await waitFor(() => expect(screen.getByLabelText(/lista de precios/i)).toBeTruthy());
  expect(screen.getByRole("option", { name: "NP Calle 13" })).toBeTruthy();
  expect(screen.getByRole("option", { name: "Principal" })).toBeTruthy();
});

test("el FormData incluye lista_id solo cuando la lista elegida no es Principal, y avisa que es inmutable", async () => {
  render(
    <MemoryRouter>
      <CorridasInicio />
    </MemoryRouter>
  );

  await screen.findByText("Calle 13");
  await waitFor(() => expect(screen.getByLabelText(/lista de precios/i)).toBeTruthy());

  // Carpeta y archivo, requeridos para poder armar
  fireEvent.change(screen.getByLabelText(/carpeta/i), { target: { value: "1" } });
  const fileInput = document.getElementById("archivo") as HTMLInputElement;
  const file = new File(["x"], "licitacion.xlsx", { type: "application/octet-stream" });
  fireEvent.change(fileInput, { target: { files: [file] } });

  // Sin tocar el selector: por defecto es Principal (id 1), no debe verse el aviso
  expect(screen.queryByText(/no se puede cambiar/i)).toBeNull();

  const btnArmar = screen.getByRole("button", { name: /armar/i });
  fireEvent.click(btnArmar);

  await waitFor(() => expect(armarArchivoMock).toHaveBeenCalledTimes(1));
  const formPrincipal = armarArchivoMock.mock.calls[0][0] as FormData;
  expect(formPrincipal.get("lista_id")).toBeNull();

  // Elegir la lista NP: aparece el aviso de inmutabilidad
  fireEvent.change(screen.getByLabelText(/lista de precios/i), { target: { value: "2" } });
  expect(screen.getByText(/no se puede cambiar/i)).toBeTruthy();

  fireEvent.click(btnArmar);
  await waitFor(() => expect(armarArchivoMock).toHaveBeenCalledTimes(2));
  const formNP = armarArchivoMock.mock.calls[1][0] as FormData;
  expect(formNP.get("lista_id")).toBe("2");
});

test("crear carpeta usa el modal y auto-selecciona la nueva", async () => {
  crearCarpetaMock.mockResolvedValue({ id: 9, nombre: "Obra Nueva", parent_id: null, n_corridas: 0, hijas: [] });
  render(
    <MemoryRouter>
      <CorridasInicio />
    </MemoryRouter>
  );
  await screen.findByText("Calle 13");

  fireEvent.click(screen.getByRole("button", { name: "+ Carpeta" }));
  // Se busca escopado al diálogo: la propia página ya tiene un campo "Nombre" (el de la
  // corrida), y el diálogo usa la etiqueta por defecto de DialogoTexto, también "Nombre" —
  // sin el `within`, `findByLabelText` ambiguaba entre los dos (ambos presentes a la vez en
  // el DOM; el de la página queda aria-hidden por Radix, pero las queries de Testing
  // Library por label no filtran por aria-hidden).
  const dialogo = await screen.findByRole("dialog");
  fireEvent.change(await within(dialogo).findByLabelText("Nombre"), { target: { value: "Obra Nueva" } });
  fireEvent.click(within(dialogo).getByRole("button", { name: "Crear" }));

  await waitFor(() => expect(crearCarpetaMock).toHaveBeenCalledWith("Obra Nueva", null));
});
