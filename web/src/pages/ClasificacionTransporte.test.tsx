import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { toast } from "sonner";
import * as api from "@/api/transporte";
import ClasificacionTransporte from "@/pages/ClasificacionTransporte";

// `@testing-library/user-event` y `jest-dom` (toBeInTheDocument) no son
// dependencias de este repo (ver DistanciasProyecto.test.tsx): se usa
// `fireEvent` y `toBeTruthy()` en su lugar.
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const LISTA = {
  items: [
    { apu_codigo: "4390", shift: "DIURNO", apu_nombre: "RELLENO",
      insumo_codigo: "7462", insumo_nombre: "TRANSPORTE DE PETREOS", unidad: "M3-KM",
      rendimiento: 26.25, categoria: null, categoria_sugerida: "granulares",
      volumen: 1.05, km_base: 25, km_implicito: 25 },
    { apu_codigo: "4919", shift: "DIURNO", apu_nombre: "SUMIDERO",
      insumo_codigo: "7462", insumo_nombre: "TRANSPORTE DE PETREOS", unidad: "M3-KM",
      rendimiento: 0.28, categoria: null, categoria_sugerida: "granulares",
      volumen: 0.0112, km_base: 25, km_implicito: 25 },
  ],
  total: 2, categorias: ["botadero", "mezclas", "granulares"], km_base_defecto: 25,
};

function montar() {
  return render(<MemoryRouter><ClasificacionTransporte /></MemoryRouter>);
}

describe("ClasificacionTransporte", () => {
  it("lista las filas con su categoría sugerida y su volumen", async () => {
    vi.spyOn(api, "listarComponentes").mockResolvedValue(LISTA as never);
    montar();
    expect(await screen.findByText("SUMIDERO")).toBeTruthy();
    expect(screen.getAllByDisplayValue("granulares").length).toBe(2);
    expect(screen.getByText("0,0112")).toBeTruthy();
  });

  it("guarda la clasificación en bloque", async () => {
    vi.spyOn(api, "listarComponentes").mockResolvedValue(LISTA as never);
    const guardar = vi.spyOn(api, "clasificar")
      .mockResolvedValue({ aplicados: 2 } as never);
    montar();
    await screen.findByText("SUMIDERO");
    fireEvent.click(screen.getByRole("button", { name: /guardar/i }));
    await waitFor(() => expect(guardar).toHaveBeenCalledWith(
      expect.arrayContaining([expect.objectContaining({
        apu_codigo: "4390", categoria: "granulares", volumen: 1.05 })])));
  });

  it("recalcula el volumen y el km implícito al editar el km base", async () => {
    vi.spyOn(api, "listarComponentes").mockResolvedValue(LISTA as never);
    montar();
    await screen.findByText("SUMIDERO");
    const kmBase = screen.getByLabelText("km base de 4390|DIURNO|7462");
    fireEvent.change(kmBase, { target: { value: "10" } });
    // rendimiento 26.25 / km_base 10 = 2.625 -> "2,625"
    expect(screen.getByText("2,625")).toBeTruthy();
    // km implícito vuelve a ser el rendimiento original: 26.25 / 2.625 = 10
    expect(screen.getByText("10")).toBeTruthy();
  });

  it("un km base de 0 no produce Infinity ni NaN", async () => {
    vi.spyOn(api, "listarComponentes").mockResolvedValue(LISTA as never);
    montar();
    await screen.findByText("SUMIDERO");
    const kmBase = screen.getByLabelText("km base de 4390|DIURNO|7462");
    fireEvent.change(kmBase, { target: { value: "0" } });
    expect(screen.queryByText(/infinity/i)).toBeNull();
    expect(screen.queryByText(/nan/i)).toBeNull();
  });

  it("no manda filas sin categoría al guardar", async () => {
    const lista = {
      ...LISTA,
      items: [
        { ...LISTA.items[0], categoria_sugerida: null },
        LISTA.items[1],
      ],
    };
    vi.spyOn(api, "listarComponentes").mockResolvedValue(lista as never);
    const guardar = vi.spyOn(api, "clasificar")
      .mockResolvedValue({ aplicados: 1 } as never);
    montar();
    await screen.findByText("SUMIDERO");
    fireEvent.click(screen.getByRole("button", { name: /guardar/i }));
    await waitFor(() => expect(guardar).toHaveBeenCalled());
    // .at(-1): en este archivo los spies no se resetean entre tests (no hay
    // clearMocks en vitest.config.ts), así que .calls[0] sería el de otro test.
    const filas = guardar.mock.calls.at(-1)?.[0] as { apu_codigo: string }[];
    expect(filas.length).toBe(1);
    expect(filas[0].apu_codigo).toBe("4919");
  });

  it("muestra el error del backend si falla el guardado", async () => {
    vi.spyOn(api, "listarComponentes").mockResolvedValue(LISTA as never);
    vi.spyOn(api, "clasificar").mockRejectedValue(new Error("Categoría inválida"));
    montar();
    await screen.findByText("SUMIDERO");
    fireEvent.click(screen.getByRole("button", { name: /guardar/i }));
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Categoría inválida"));
  });
});
