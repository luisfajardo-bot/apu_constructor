import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";
import * as api from "@/api/transporte";
import DistanciasProyecto from "@/pages/DistanciasProyecto";

// El componente usa useAuth() para saber si puede editar (mismo patrón que
// Insumos.test.tsx); sin <AuthProvider> real en el árbol de test, se mockea.
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ perfil: { rol: "editor" } }) }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
// `@testing-library/user-event` y `jest-dom` (toBeInTheDocument) no son
// dependencias de este repo (ver otros tests de páginas, p.ej.
// Apus.duplicar.test.tsx): se usa `fireEvent` y `toBeTruthy()` en su lugar.

const VISTA = {
  proyecto: { id: 7, nombre: "Metro" },
  // Peaje por categoría: granulares paga 12.400, mezclas no paga y botadero está
  // sin definir. Los tres estados a la vez, que es el caso real.
  parametros: { km_botadero: 34, km_mezclas: null, km_granulares: 32,
                peaje_botadero_aplica: null, peaje_botadero_valor: null,
                peaje_mezclas_aplica: false, peaje_mezclas_valor: null,
                peaje_granulares_aplica: true, peaje_granulares_valor: 12400 },
  impacto: [{ apu_codigo: "4390", shift: "DIURNO", insumo_codigo: "7462",
              insumo_nombre: "TRANSPORTE DE PETREOS", unidad: "M3-KM",
              rendimiento_actual: 26.25, categoria: "granulares", volumen: 1.05,
              rendimiento_nuevo: 33.6, quitado: false, origen: "distancia",
              sin_clasificar: false },
             { apu_codigo: "4200", shift: "DIURNO", insumo_codigo: "6878",
               insumo_nombre: "TRANSPORTE DE BASES ASFALTICAS", unidad: "M3-KM",
               rendimiento_actual: 26.25, categoria: null, volumen: null,
               rendimiento_nuevo: 26.25, quitado: false, origen: "biblioteca",
               sin_clasificar: true }],
  sin_clasificar: 1,
};

// Insumo distinto al de VISTA.impacto (que también usa "7462"/"6878" con esos
// nombres) para que los asserts por texto no encuentren dos coincidencias.
const AJUSTES = [
  { id: 11, apu_codigo: "4390", shift: "DIURNO", accion: "rendimiento",
    insumo_codigo: "9911", insumo_nombre: "CONCRETO PREMEZCLADO 3000 PSI", unidad: "M3",
    rendimiento: 40, nota: "el rendimiento de biblioteca no aplica a esta obra por el sitio",
    creado_en: "2026-08-20T15:30:00Z", creado_por: "luisfajardo@indugravas.com" },
];

function montar() {
  return render(
    <MemoryRouter initialEntries={["/proyecto/7/distancias"]}>
      <Routes>
        <Route path="/proyecto/:carpetaId/distancias" element={<DistanciasProyecto />} />
      </Routes>
    </MemoryRouter>);
}

describe("DistanciasProyecto", () => {
  // Default sin ajustes: sin este beforeEach, los tests que no mockean
  // listarAjustes explícitamente dispararían la llamada real (fetch) al montar.
  beforeEach(() => {
    vi.spyOn(api, "listarAjustes").mockResolvedValue([]);
  });


  it("muestra los parámetros y el impacto", async () => {
    vi.spyOn(api, "verTransporte").mockResolvedValue(VISTA as never);
    montar();
    expect(await screen.findByDisplayValue("34")).toBeTruthy();
    expect(screen.getByText("TRANSPORTE DE PETREOS")).toBeTruthy();
    expect(screen.getByText("33,6")).toBeTruthy();
    expect(screen.getByText(/1 componente sin clasificar/i)).toBeTruthy();
  });

  it("guarda los parámetros", async () => {
    vi.spyOn(api, "verTransporte").mockResolvedValue(VISTA as never);
    const guardar = vi.spyOn(api, "guardarTransporte").mockResolvedValue(VISTA as never);
    montar();
    const botadero = await screen.findByLabelText(/botadero \(km\)/i);
    fireEvent.change(botadero, { target: { value: "40" } });
    fireEvent.click(screen.getByRole("button", { name: /guardar/i }));
    // El backend hace reemplazo total: si algún día alguien manda solo lo que
    // cambió, borra en silencio los otros parámetros del proyecto. Se fijan
    // las 9 claves (no solo su presencia con objectContaining) para que este
    // test explote si el PUT deja de mandar alguna.
    await waitFor(() => expect(guardar).toHaveBeenLastCalledWith(7, {
      km_botadero: 40,
      km_mezclas: null,
      km_granulares: 32,
      peaje_botadero_aplica: false,      // estaba sin definir -> la casilla no marcada
      peaje_botadero_valor: null,
      peaje_mezclas_aplica: false,
      peaje_mezclas_valor: null,
      peaje_granulares_aplica: true,
      peaje_granulares_valor: 12400,
    }));
  });

  it("basura en un km bloquea el guardado y avisa cuál campo está mal", async () => {
    vi.spyOn(api, "verTransporte").mockResolvedValue(VISTA as never);
    const guardar = vi.spyOn(api, "guardarTransporte").mockResolvedValue(VISTA as never);
    // vitest.config.ts no limpia mocks entre it(): el spy acumula historial de
    // tests anteriores. Se compara contra este conteo, no contra 0.
    const llamadasPrevias = guardar.mock.calls.length;
    montar();
    const mezclas = await screen.findByLabelText(/mezclas \(km\)/i);
    fireEvent.change(mezclas, { target: { value: "3g" } });
    fireEvent.click(screen.getByRole("button", { name: /guardar/i }));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    const mensaje = vi.mocked(toast.error).mock.calls.at(-1)?.[0] as string;
    expect(mensaje).toMatch(/mezclas/i);
    expect(mensaje).toMatch(/3g/);
    expect(guardar.mock.calls.length).toBe(llamadasPrevias);
  });

  it("vaciar un km sí lo guarda como null (no aplica)", async () => {
    vi.spyOn(api, "verTransporte").mockResolvedValue(VISTA as never);
    const guardar = vi.spyOn(api, "guardarTransporte").mockResolvedValue(VISTA as never);
    montar();
    const botadero = await screen.findByLabelText(/botadero \(km\)/i);
    fireEvent.change(botadero, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: /guardar/i }));
    await waitFor(() => expect(guardar).toHaveBeenLastCalledWith(
      7, expect.objectContaining({ km_botadero: null })));
  });

  it("cada categoría tiene su propia casilla y su propio valor de peaje", async () => {
    vi.spyOn(api, "verTransporte").mockResolvedValue(VISTA as never);
    const guardar = vi.spyOn(api, "guardarTransporte").mockResolvedValue(VISTA as never);
    montar();
    // Granulares ya paga (viene en la vista); se agrega el de mezclas.
    const casilla = await screen.findByLabelText(/peaje de mezclas/i);
    fireEvent.click(casilla);
    // Recién al marcarla aparece su campo de valor: antes no existía.
    const valor = await screen.findByLabelText(/peaje mezclas/i);
    fireEvent.change(valor, { target: { value: "8000" } });
    fireEvent.click(screen.getByRole("button", { name: /guardar/i }));
    await waitFor(() => expect(guardar).toHaveBeenLastCalledWith(
      7, expect.objectContaining({
        peaje_mezclas_aplica: true,
        peaje_mezclas_valor: 8000,
        // y las otras dos quedan como estaban
        peaje_granulares_aplica: true,
        peaje_granulares_valor: 12400,
        peaje_botadero_aplica: false,
      })));
  });

  it("desmarcar una categoría no manda su valor viejo", async () => {
    // Desmarcar es decir "acá no se paga", no "vale lo que quedó escrito".
    vi.spyOn(api, "verTransporte").mockResolvedValue(VISTA as never);
    const guardar = vi.spyOn(api, "guardarTransporte").mockResolvedValue(VISTA as never);
    montar();
    fireEvent.click(await screen.findByLabelText(/peaje de granulares/i));
    fireEvent.click(screen.getByRole("button", { name: /guardar/i }));
    await waitFor(() => expect(guardar).toHaveBeenLastCalledWith(
      7, expect.objectContaining({
        peaje_granulares_aplica: false,
        peaje_granulares_valor: null,
      })));
  });

  it("lista los ajustes del proyecto, con la nota visible", async () => {
    vi.spyOn(api, "verTransporte").mockResolvedValue(VISTA as never);
    vi.spyOn(api, "listarAjustes").mockResolvedValue(AJUSTES as never);
    montar();
    expect(await screen.findByText("CONCRETO PREMEZCLADO 3000 PSI")).toBeTruthy();
    expect(screen.getByText(/el rendimiento de biblioteca no aplica/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /borrar/i })).toBeTruthy();
  });

  it("sin ajustes muestra el estado vacío, no una tabla fantasma", async () => {
    vi.spyOn(api, "verTransporte").mockResolvedValue(VISTA as never);
    vi.spyOn(api, "listarAjustes").mockResolvedValue([]);
    montar();
    expect(await screen.findByText(/este proyecto no tiene ajustes de composición/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /borrar/i })).toBeNull();
  });

  it("borrar pide confirmación, llama borrarAjuste(carpetaId, ajusteId) y refresca vista + lista", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const verTransporte = vi.spyOn(api, "verTransporte").mockResolvedValue(VISTA as never);
    const listarAjustes = vi.spyOn(api, "listarAjustes").mockResolvedValue(AJUSTES as never);
    const borrar = vi.spyOn(api, "borrarAjuste").mockResolvedValue(undefined);
    montar();
    await screen.findByText("CONCRETO PREMEZCLADO 3000 PSI");
    const llamadasVerAntes = verTransporte.mock.calls.length;
    const llamadasListarAntes = listarAjustes.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: /borrar/i }));
    await waitFor(() => expect(borrar).toHaveBeenLastCalledWith(7, 11));
    await waitFor(() => expect(verTransporte.mock.calls.length).toBeGreaterThan(llamadasVerAntes));
    await waitFor(() => expect(listarAjustes.mock.calls.length).toBeGreaterThan(llamadasListarAntes));
  });

  it("cancelar la confirmación no borra el ajuste", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    vi.spyOn(api, "verTransporte").mockResolvedValue(VISTA as never);
    vi.spyOn(api, "listarAjustes").mockResolvedValue(AJUSTES as never);
    const borrar = vi.spyOn(api, "borrarAjuste").mockResolvedValue(undefined);
    const llamadasPrevias = borrar.mock.calls.length;
    montar();
    fireEvent.click(await screen.findByRole("button", { name: /borrar/i }));
    expect(borrar.mock.calls.length).toBe(llamadasPrevias);
  });

  it("si el borrado falla, muestra el mensaje del backend", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.spyOn(api, "verTransporte").mockResolvedValue(VISTA as never);
    vi.spyOn(api, "listarAjustes").mockResolvedValue(AJUSTES as never);
    vi.spyOn(api, "borrarAjuste").mockRejectedValue(new Error("No autorizado para borrar ajustes."));
    montar();
    fireEvent.click(await screen.findByRole("button", { name: /borrar/i }));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    const mensaje = vi.mocked(toast.error).mock.calls.at(-1)?.[0] as string;
    expect(mensaje).toMatch(/no autorizado/i);
  });
});


test("dice de que proyecto son las distancias que se estan editando", async () => {
  vi.spyOn(api, "verTransporte").mockResolvedValue(VISTA as never);
  vi.spyOn(api, "listarAjustes").mockResolvedValue([] as never);
  montar();
  // El nombre del proyecto tiene que estar en el encabezado, no solo en la URL.
  const titulo = await screen.findByRole("heading", { name: /distancias del proyecto/i });
  expect(titulo.textContent).toContain("Metro");
});
