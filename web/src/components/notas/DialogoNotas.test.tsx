import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { DialogoNotas } from "./DialogoNotas";
import { IconoNotas } from "./IconoNotas";

const listarNotas = vi.fn();
const crearNota = vi.fn();
const editarNota = vi.fn();
const borrarNota = vi.fn();
vi.mock("@/api/notas", () => ({
  listarNotas: (...a: unknown[]) => listarNotas(...a),
  crearNota: (...a: unknown[]) => crearNota(...a),
  editarNota: (...a: unknown[]) => editarNota(...a),
  borrarNota: (...a: unknown[]) => borrarNota(...a),
}));
let rol = "editor";
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ perfil: { rol } }) }));

const DUENO = { entidad: "insumo" as const, codigo: "4520", nombre: "DUCTO PVC", turno: "" };
const nota = (over = {}) => ({
  id: 1, entidad: "insumo", etiqueta: "4520 · DUCTO PVC", texto: "cotización X",
  autor_email: "luis@obra.co", creada_en: "2026-09-30T10:00:00+00:00", editada_en: null,
  es_mia: true, puede_editar: true, puede_borrar: true, dueno: DUENO, ...over,
});

function montar(onCambio = vi.fn()) {
  render(<DialogoNotas dueno={DUENO} etiqueta="4520 · DUCTO PVC" onClose={() => {}}
                       onCambio={onCambio} />);
  return onCambio;
}

beforeEach(() => {
  rol = "editor";
  [listarNotas, crearNota, editarNota, borrarNota].forEach((f) => f.mockReset());
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
    await waitFor(() => expect(crearNota).toHaveBeenCalledWith(DUENO, "nueva"));
    expect(onCambio).toHaveBeenCalled();
  });

  it("edita la propia", async () => {
    editarNota.mockResolvedValue(nota({ texto: "corregida", editada_en: "2026-09-30T11:00:00+00:00" }));
    montar();
    fireEvent.click(await screen.findByRole("button", { name: "Editar" }));
    fireEvent.change(screen.getByLabelText("Editar nota"), { target: { value: "corregida" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(editarNota).toHaveBeenCalledWith(1, "corregida"));
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
