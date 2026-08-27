import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import * as api from "@/api/transporte";
import DistanciasProyecto from "@/pages/DistanciasProyecto";

// El componente usa useAuth() para saber si puede editar (mismo patrón que
// Insumos.test.tsx); sin <AuthProvider> real en el árbol de test, se mockea.
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ perfil: { rol: "editor" } }) }));
// `@testing-library/user-event` y `jest-dom` (toBeInTheDocument) no son
// dependencias de este repo (ver otros tests de páginas, p.ej.
// Apus.duplicar.test.tsx): se usa `fireEvent` y `toBeTruthy()` en su lugar.

const VISTA = {
  parametros: { km_botadero: 34, km_mezclas: null, km_granulares: 32,
                peaje_aplica: true, peaje_valor: 12400 },
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

function montar() {
  return render(
    <MemoryRouter initialEntries={["/proyecto/7/distancias"]}>
      <Routes>
        <Route path="/proyecto/:carpetaId/distancias" element={<DistanciasProyecto />} />
      </Routes>
    </MemoryRouter>);
}

describe("DistanciasProyecto", () => {
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
    const botadero = await screen.findByLabelText(/botadero/i);
    fireEvent.change(botadero, { target: { value: "40" } });
    fireEvent.click(screen.getByRole("button", { name: /guardar/i }));
    await waitFor(() => expect(guardar).toHaveBeenCalledWith(
      7, expect.objectContaining({ km_botadero: 40 })));
  });
});
