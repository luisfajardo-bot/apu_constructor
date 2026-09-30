import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { DialogoNotas } from "./DialogoNotas";
import { IconoNotas } from "./IconoNotas";

const listarNotas = vi.fn();
const crearNota = vi.fn();
const editarNota = vi.fn();
const borrarNota = vi.fn();
const listarMencionables = vi.fn();
vi.mock("@/api/notas", () => ({
  listarNotas: (...a: unknown[]) => listarNotas(...a),
  crearNota: (...a: unknown[]) => crearNota(...a),
  editarNota: (...a: unknown[]) => editarNota(...a),
  borrarNota: (...a: unknown[]) => borrarNota(...a),
  listarMencionables: (...a: unknown[]) => listarMencionables(...a),
}));
let rol = "editor";
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ perfil: { rol } }) }));

const DUENO = { entidad: "insumo" as const, codigo: "4520", nombre: "DUCTO PVC", turno: "" };
const nota = (over = {}) => ({
  id: 1, entidad: "insumo", etiqueta: "4520 · DUCTO PVC", texto: "cotización X",
  autor_email: "luis@obra.co", creada_en: "2026-09-30T10:00:00+00:00", editada_en: null,
  es_mia: true, puede_editar: true, puede_borrar: true, dueno: DUENO, menciones: [], ...over,
});

function montar(onCambio = vi.fn()) {
  render(<DialogoNotas dueno={DUENO} etiqueta="4520 · DUCTO PVC" onClose={() => {}}
                       onCambio={onCambio} />);
  return onCambio;
}

beforeEach(() => {
  rol = "editor";
  [listarNotas, crearNota, editarNota, borrarNota, listarMencionables].forEach((f) => f.mockReset());
  listarMencionables.mockResolvedValue([{ user_id: "u-beto", nombre: "Beto", email: "beto@obra.co" }]);
  listarNotas.mockResolvedValue([nota()]);
});
afterEach(() => vi.restoreAllMocks());

describe("DialogoNotas", () => {
  it("lista las notas del dueño", async () => {
    montar();
    expect(await screen.findByText("cotización X")).toBeTruthy();
    expect(listarNotas).toHaveBeenCalledWith(DUENO);
    expect(screen.getByText(/luis@obra.co/)).toBeTruthy();
  });

  it("agrega una nota y avisa el cambio", async () => {
    crearNota.mockResolvedValue(nota({ id: 2, texto: "nueva" }));
    const onCambio = montar();
    await screen.findByText("cotización X");
    fireEvent.change(screen.getByLabelText("Nueva nota"), { target: { value: "nueva" } });
    fireEvent.click(screen.getByRole("button", { name: "Agregar nota" }));
    await waitFor(() => expect(crearNota).toHaveBeenCalledWith(DUENO, "nueva", []));
    expect(onCambio).toHaveBeenCalled();
  });

  it("edita la propia", async () => {
    editarNota.mockResolvedValue(nota({ texto: "corregida", editada_en: "2026-09-30T11:00:00+00:00" }));
    montar();
    fireEvent.click(await screen.findByRole("button", { name: "Editar" }));
    fireEvent.change(screen.getByLabelText("Editar nota"), { target: { value: "corregida" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(editarNota).toHaveBeenCalledWith(1, "corregida", []));
    expect(await screen.findByText("corregida")).toBeTruthy();
    expect(screen.getByText(/editada/)).toBeTruthy();
  });

  it("borra con confirmación", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    borrarNota.mockResolvedValue(undefined);
    const onCambio = montar();
    fireEvent.click(await screen.findByRole("button", { name: "Borrar" }));
    await waitFor(() => expect(borrarNota).toHaveBeenCalledWith(1));
    expect(screen.queryByText("cotización X")).toBeNull();
    expect(onCambio).toHaveBeenCalled();
  });

  it("descarta la respuesta tardía de un dueño anterior", async () => {
    const OTRO = { ...DUENO, codigo: "9999", nombre: "OTRO" };
    let resolverA: (v: unknown) => void = () => {};
    listarNotas.mockImplementation((d: { codigo: string }) =>
      d.codigo === "4520" ? new Promise((r) => { resolverA = r; })
                          : Promise.resolve([nota({ id: 7, texto: "nota de B" })]));
    const { rerender } = render(
      <DialogoNotas dueno={DUENO} etiqueta="A" onClose={() => {}} onCambio={() => {}} />);
    rerender(<DialogoNotas dueno={OTRO} etiqueta="B" onClose={() => {}} onCambio={() => {}} />);
    expect(await screen.findByText("nota de B")).toBeTruthy();
    await act(async () => { resolverA([nota({ id: 1, texto: "nota de A" })]); });
    expect(screen.queryByText("nota de A")).toBeNull();
    expect(screen.getByText("nota de B")).toBeTruthy();
  });

  it("un objeto dueño nuevo con los mismos campos no recarga ni borra lo escrito", async () => {
    const props = { etiqueta: "x", onClose: () => {}, onCambio: () => {} };
    const { rerender } = render(<DialogoNotas dueno={{ ...DUENO }} {...props} />);
    await screen.findByText("cotización X");
    fireEvent.change(screen.getByLabelText("Nueva nota"), { target: { value: "borrador" } });
    rerender(<DialogoNotas dueno={{ ...DUENO }} {...props} />);
    expect(listarNotas).toHaveBeenCalledTimes(1);
    expect((screen.getByLabelText("Nueva nota") as HTMLTextAreaElement).value).toBe("borrador");
  });

  it("si crear falla, conserva el texto escrito", async () => {
    crearNota.mockRejectedValue(new Error("boom"));
    montar();
    await screen.findByText("cotización X");
    fireEvent.change(screen.getByLabelText("Nueva nota"), { target: { value: "no perder" } });
    fireEvent.click(screen.getByRole("button", { name: "Agregar nota" }));
    await waitFor(() => expect(crearNota).toHaveBeenCalled());
    await act(async () => {});
    expect((screen.getByLabelText("Nueva nota") as HTMLTextAreaElement).value).toBe("no perder");
  });

  it("sin permisos no muestra botones; consulta no puede escribir", async () => {
    rol = "consulta";
    listarNotas.mockResolvedValue([nota({ es_mia: false, puede_editar: false, puede_borrar: false })]);
    montar();
    await screen.findByText("cotización X");
    expect(screen.queryByRole("button", { name: "Editar" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Borrar" })).toBeNull();
    expect(screen.queryByLabelText("Nueva nota")).toBeNull();
    expect(listarMencionables).not.toHaveBeenCalled();
  });

  it("escribir @ ofrece usuarios y manda la mención al crear", async () => {
    crearNota.mockResolvedValue(nota({ id: 2, texto: "@Beto mira", menciones: [{ user_id: "u-beto", nombre: "Beto" }] }));
    montar();
    await screen.findByText("cotización X");
    const caja = screen.getByLabelText("Nueva nota") as HTMLTextAreaElement;
    fireEvent.change(caja, { target: { value: "@Be", selectionStart: 3, selectionEnd: 3 } });
    fireEvent.click(await screen.findByRole("button", { name: "Mencionar a Beto" }));
    expect(caja.value).toBe("@Beto ");
    fireEvent.change(caja, { target: { value: "@Beto mira", selectionStart: 10, selectionEnd: 10 } });
    fireEvent.click(screen.getByRole("button", { name: "Agregar nota" }));
    await waitFor(() => expect(crearNota).toHaveBeenCalledWith(DUENO, "@Beto mira", ["u-beto"]));
  });

  it("si borras el @Nombre del texto, no se manda la mención", async () => {
    crearNota.mockResolvedValue(nota({ id: 2, texto: "nada" }));
    montar();
    await screen.findByText("cotización X");
    const caja = screen.getByLabelText("Nueva nota") as HTMLTextAreaElement;
    fireEvent.change(caja, { target: { value: "@Be", selectionStart: 3, selectionEnd: 3 } });
    fireEvent.click(await screen.findByRole("button", { name: "Mencionar a Beto" }));
    fireEvent.change(caja, { target: { value: "nada", selectionStart: 4, selectionEnd: 4 } });
    fireEvent.click(screen.getByRole("button", { name: "Agregar nota" }));
    await waitFor(() => expect(crearNota).toHaveBeenCalledWith(DUENO, "nada", []));
  });

  it("resalta los nombres mencionados en la nota", async () => {
    listarNotas.mockResolvedValue([nota({ texto: "@Beto revisa", menciones: [{ user_id: "u-beto", nombre: "Beto" }] })]);
    montar();
    const resaltado = await screen.findByText("@Beto");
    expect(resaltado.getAttribute("data-mencion")).toBe("si");
  });

  it("editar conserva y manda las menciones vigentes", async () => {
    listarNotas.mockResolvedValue([nota({ texto: "@Beto revisa", menciones: [{ user_id: "u-beto", nombre: "Beto" }] })]);
    editarNota.mockResolvedValue(nota({ texto: "@Beto revisa ya", menciones: [{ user_id: "u-beto", nombre: "Beto" }] }));
    montar();
    fireEvent.click(await screen.findByRole("button", { name: "Editar" }));
    fireEvent.change(screen.getByLabelText("Editar nota"),
                     { target: { value: "@Beto revisa ya", selectionStart: 15, selectionEnd: 15 } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(editarNota).toHaveBeenCalledWith(1, "@Beto revisa ya", ["u-beto"]));
  });

  it("escoger una mención al editar conserva el texto y la mención", async () => {
    editarNota.mockResolvedValue(nota({ texto: "@Beto " }));
    montar();
    fireEvent.click(await screen.findByRole("button", { name: "Editar" }));
    const caja = screen.getByLabelText("Editar nota") as HTMLTextAreaElement;
    fireEvent.change(caja, { target: { value: "@Be", selectionStart: 3, selectionEnd: 3 } });
    fireEvent.click(await screen.findByRole("button", { name: "Mencionar a Beto" }));
    expect(caja.value).toBe("@Beto ");
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(editarNota).toHaveBeenCalledWith(1, expect.stringContaining("@Beto"), ["u-beto"]));
  });

  it("la lista de sugerencias abre hacia abajo al editar y hacia arriba en la nota nueva", async () => {
    montar();
    fireEvent.click(await screen.findByRole("button", { name: "Editar" }));
    const arriba = screen.getByLabelText("Nueva nota") as HTMLTextAreaElement;
    fireEvent.change(arriba, { target: { value: "@Be", selectionStart: 3, selectionEnd: 3 } });
    const popupNueva = (await screen.findByRole("button", { name: "Mencionar a Beto" })).parentElement!;
    expect(popupNueva.className).toContain("bottom-full");
    fireEvent.change(arriba, { target: { value: "", selectionStart: 0, selectionEnd: 0 } });
    const caja = screen.getByLabelText("Editar nota") as HTMLTextAreaElement;
    fireEvent.change(caja, { target: { value: "@Be", selectionStart: 3, selectionEnd: 3 } });
    const popupEdit = (await screen.findByRole("button", { name: "Mencionar a Beto" })).parentElement!;
    expect(popupEdit.className).toContain("top-full");
    expect(popupEdit.className).not.toContain("bottom-full");
  });

  it("Escape con la lista abierta la cierra y no cierra el diálogo", async () => {
    const onClose = vi.fn();
    render(<DialogoNotas dueno={DUENO} etiqueta="4520 · DUCTO PVC" onClose={onClose} onCambio={() => {}} />);
    await screen.findByText("cotización X");
    const caja = screen.getByLabelText("Nueva nota") as HTMLTextAreaElement;
    fireEvent.change(caja, { target: { value: "@Be", selectionStart: 3, selectionEnd: 3 } });
    await screen.findByRole("button", { name: "Mencionar a Beto" });
    caja.focus();
    fireEvent.keyDown(caja, { key: "Escape" });
    expect(screen.queryByRole("button", { name: "Mencionar a Beto" })).toBeNull();
    expect(screen.getByText(/Notas · /)).toBeTruthy();
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe("IconoNotas", () => {
  it("pintado si hay notas, vacío si no; el clic no se propaga a la fila", () => {
    const fila = vi.fn();
    const abrir = vi.fn();
    const { rerender } = render(
      <div onClick={fila}><IconoNotas tiene={false} ultima="" onClick={abrir} /></div>);
    const boton = screen.getByRole("button", { name: "Notas" });
    expect(boton.getAttribute("data-tiene")).toBe("no");
    fireEvent.click(boton);
    expect(abrir).toHaveBeenCalled();
    expect(fila).not.toHaveBeenCalled();
    rerender(<div onClick={fila}><IconoNotas tiene ultima="cotización X" onClick={abrir} /></div>);
    expect(screen.getByRole("button", { name: "Notas" }).getAttribute("data-tiene")).toBe("si");
    expect(screen.getByRole("button", { name: "Notas" }).getAttribute("title")).toBe("cotización X");
  });
});
