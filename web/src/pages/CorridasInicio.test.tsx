import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, test, vi } from "vitest";
import { toast } from "sonner";
import { ErrorApi } from "@/api/client";
// El import va ARRIBA, fuera de los `test`. Cuando estaba adentro
// (`await import("./CorridasInicio")` en cada test), el costo de transformar e importar la
// página se le cobraba al presupuesto de 5 s de cada test: medido en otro archivo con la
// misma forma, 1682-2232 ms de los 5000, y con la máquina cargada eso termina en
// "Test timed out in 5000ms". `vi.mock` lo hoistea vitest antes de los imports, así que los
// mocks de abajo siguen aplicándose igual.
import CorridasInicio from "./CorridasInicio";

// Referencias hoisted para inspeccionar (mock.calls) cómo la pantalla llama a
// `crearCorrida` —en particular, qué trae el FormData— y a dónde navega después.
const { crearCorridaMock, crearSampleMock, navigateMock } = vi.hoisted(() => ({
  crearCorridaMock: vi.fn(async () => ({ id: 7, total: 2, estado: "armando" })),
  crearSampleMock: vi.fn(async () => ({ id: 9, total: 2, estado: "armando" })),
  navigateMock: vi.fn(),
}));

// Mock PARCIAL a propósito: solo se stubean las dos llamadas de red. `corridaEnCurso`
// (el que reconoce el 409 del doble clic y saca el id) queda el REAL, que es justo la
// lógica que estos tests tienen que poder romper.
vi.mock("@/api/corridas", async (original) => ({
  ...(await original<object>()),
  crearCorrida: crearCorridaMock,
  crearSample: crearSampleMock,
}));

// MemoryRouter sigue siendo el de verdad; solo se espía a dónde navega la pantalla.
vi.mock("react-router-dom", async (original) => ({
  ...(await original<object>()),
  useNavigate: () => navigateMock,
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
  crearCarpeta: vi.fn(),
}));

vi.mock("@/api/listas", () => ({
  listarListas: vi.fn(async () => [
    { id: 1, nombre: "Principal", creada_en: "2026-07-27" },
    { id: 2, nombre: "NP Calle 13", creada_en: "2026-07-27" },
  ]),
}));

vi.mock("sonner", () => ({
  toast: { error: vi.fn(), success: vi.fn(), warning: vi.fn() },
}));

beforeEach(() => {
  crearCorridaMock.mockClear();
  crearSampleMock.mockClear();
  navigateMock.mockClear();
  vi.mocked(toast.error).mockClear();
  vi.mocked(toast.warning).mockClear();
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
  expect(crearCorridaMock).not.toHaveBeenCalled();
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

  await waitFor(() => expect(crearCorridaMock).toHaveBeenCalledTimes(1));
  const formPrincipal = crearCorridaMock.mock.calls[0][0] as unknown as FormData;
  expect(formPrincipal.get("lista_id")).toBeNull();

  // Elegir la lista NP: aparece el aviso de inmutabilidad
  fireEvent.change(screen.getByLabelText(/lista de precios/i), { target: { value: "2" } });
  expect(screen.getByText(/no se puede cambiar/i)).toBeTruthy();

  fireEvent.click(btnArmar);
  await waitFor(() => expect(crearCorridaMock).toHaveBeenCalledTimes(2));
  const formNP = crearCorridaMock.mock.calls[1][0] as unknown as FormData;
  expect(formNP.get("lista_id")).toBe("2");
});


// ─── Encolar: la petición vuelve en el acto, el armado sigue en el servidor ──────

/** Deja la pantalla lista para armar: carpeta elegida y archivo puesto. */
async function listoParaArmar() {
  render(<MemoryRouter><CorridasInicio /></MemoryRouter>);
  await screen.findByText("Calle 13");
  fireEvent.change(screen.getByLabelText(/carpeta/i), { target: { value: "1" } });
  const fileInput = document.getElementById("archivo") as HTMLInputElement;
  fireEvent.change(fileInput, {
    target: { files: [new File(["x"], "lic.xlsx", { type: "application/octet-stream" })] },
  });
  return fileInput.form as HTMLFormElement;
}

test("al armar, navega a la corrida encolada en vez de esperar el armado", async () => {
  await listoParaArmar();
  fireEvent.click(screen.getByRole("button", { name: /^armar/i }));

  await waitFor(() => expect(navigateMock).toHaveBeenCalledWith("/corridas/7"));
  expect(vi.mocked(toast.error)).not.toHaveBeenCalled();
});

test("«Usar ejemplo» también encola y navega", async () => {
  render(<MemoryRouter><CorridasInicio /></MemoryRouter>);
  await screen.findByText("Calle 13");

  fireEvent.click(screen.getByRole("button", { name: /usar ejemplo/i }));

  await waitFor(() => expect(navigateMock).toHaveBeenCalledWith("/corridas/9"));
  expect(crearSampleMock).toHaveBeenCalledTimes(1);
});

test("el 409 del doble clic lleva a la corrida que YA se está armando", async () => {
  // Lo que este test protege: que un segundo envío del mismo archivo termine en la
  // corrida que acaba de crear y no en un cartel rojo sin salida.
  crearCorridaMock.mockRejectedValueOnce(
    new ErrorApi("Ya se está armando «lic.xlsx» en esta carpeta (corrida 42).", 409,
                 { mensaje: "Ya se está armando…", corrida_id: 42 }));
  await listoParaArmar();

  fireEvent.click(screen.getByRole("button", { name: /^armar/i }));

  await waitFor(() => expect(navigateMock).toHaveBeenCalledWith("/corridas/42"));
  expect(vi.mocked(toast.warning)).toHaveBeenCalledTimes(1);
  expect(vi.mocked(toast.error)).not.toHaveBeenCalled();
});

test("un 409 que NO trae corrida_id sigue siendo un error, no una navegación", async () => {
  // No todos los 409 son el del doble clic (la carpeta no vacía, p. ej.). Sin este
  // caso, «cualquier 409 navega» pasaría los tests y mandaría a /corridas/undefined.
  crearCorridaMock.mockRejectedValueOnce(
    new ErrorApi("La carpeta no está vacía.", 409, "La carpeta no está vacía."));
  await listoParaArmar();

  fireEvent.click(screen.getByRole("button", { name: /^armar/i }));

  await waitFor(() =>
    expect(vi.mocked(toast.error)).toHaveBeenCalledWith("La carpeta no está vacía."));
  expect(navigateMock).not.toHaveBeenCalled();
});

test("un error normal se muestra y NO navega a ningún lado", async () => {
  crearCorridaMock.mockRejectedValueOnce(new Error("El archivo no es un Excel válido."));
  await listoParaArmar();

  fireEvent.click(screen.getByRole("button", { name: /^armar/i }));

  await waitFor(() =>
    expect(vi.mocked(toast.error)).toHaveBeenCalledWith("El archivo no es un Excel válido."));
  expect(navigateMock).not.toHaveBeenCalled();
});

test("dos envíos seguidos del formulario encolan UNA sola corrida", async () => {
  // El Enter sostenido dispara submits sin pasar por el botón, así que el
  // `disabled` no alcanza: el candado tiene que estar en el handler.
  const form = await listoParaArmar();

  fireEvent.submit(form);
  fireEvent.submit(form);

  await waitFor(() => expect(navigateMock).toHaveBeenCalled());
  expect(crearCorridaMock).toHaveBeenCalledTimes(1);
});
