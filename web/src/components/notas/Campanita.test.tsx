import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { Campanita } from "./Campanita";

const listarMenciones = vi.fn();
const marcarMencionLeida = vi.fn();
const marcarMencionesLeidas = vi.fn();
const listarNotas = vi.fn(async () => []);
vi.mock("@/api/notas", () => ({
  listarMenciones: (...a: unknown[]) => listarMenciones(...a),
  marcarMencionLeida: (...a: unknown[]) => marcarMencionLeida(...a),
  marcarMencionesLeidas: (...a: unknown[]) => marcarMencionesLeidas(...a),
  listarNotas: (...a: unknown[]) => listarNotas(...(a as [])),
  listarMencionables: vi.fn(async () => []),
  crearNota: vi.fn(), editarNota: vi.fn(), borrarNota: vi.fn(),
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ perfil: { rol: "consulta" } }) }));

const DUENO = { entidad: "insumo" as const, codigo: "4520", nombre: "DUCTO", turno: "" };
const mencion = (over = {}) => ({
  nota_id: 7, etiqueta: "4520 · DUCTO", autor_email: "ana@obra.co",
  creada_en: "2026-09-30T10:00:00+00:00", texto: "@Beto revisa", leida: false, dueno: DUENO, ...over,
});

beforeEach(() => {
  [listarMenciones, marcarMencionLeida, marcarMencionesLeidas].forEach((f) => f.mockReset());
  listarMenciones.mockResolvedValue([mencion(), mencion({ nota_id: 8, leida: true, texto: "vieja" })]);
  marcarMencionLeida.mockResolvedValue({ leida: 7 });
  marcarMencionesLeidas.mockResolvedValue({ leidas: true });
});

describe("Campanita", () => {
  it("muestra el número sin leer solo si hay", () => {
    const { rerender } = render(<Campanita sinLeer={0} onSinLeer={() => {}} />);
    expect(screen.getByRole("button", { name: "Menciones" }).textContent).toBe("");
    rerender(<Campanita sinLeer={3} onSinLeer={() => {}} />);
    expect(screen.getByRole("button", { name: "Menciones (3 sin leer)" }).textContent).toContain("3");
  });

  it("abrir lista las menciones; clic en una la marca leída y abre la nota", async () => {
    const onSinLeer = vi.fn();
    render(<Campanita sinLeer={1} onSinLeer={onSinLeer} />);
    fireEvent.click(screen.getByRole("button", { name: /Menciones/ }));
    fireEvent.click(await screen.findByText("@Beto revisa"));
    await waitFor(() => expect(marcarMencionLeida).toHaveBeenCalledWith(7));
    expect(onSinLeer).toHaveBeenCalledWith(0);
    expect(await screen.findByText("Notas · 4520 · DUCTO")).toBeTruthy();
    expect(listarNotas).toHaveBeenCalledWith(DUENO);
  });

  it("marcar todas como leídas", async () => {
    const onSinLeer = vi.fn();
    render(<Campanita sinLeer={1} onSinLeer={onSinLeer} />);
    fireEvent.click(screen.getByRole("button", { name: /Menciones/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Marcar todas como leídas" }));
    await waitFor(() => expect(marcarMencionesLeidas).toHaveBeenCalled());
    expect(onSinLeer).toHaveBeenCalledWith(0);
  });

  it("sin menciones lo dice", async () => {
    listarMenciones.mockResolvedValue([]);
    render(<Campanita sinLeer={0} onSinLeer={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Menciones" }));
    expect(await screen.findByText("Nadie te ha mencionado todavía.")).toBeTruthy();
  });
});
