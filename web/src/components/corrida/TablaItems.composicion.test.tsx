import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, expect, it, test, vi } from "vitest";
import * as apiTte from "@/api/transporte";
import TablaItems, { FilaComposicion } from "@/components/corrida/TablaItems";

// `@testing-library/user-event` y `jest-dom` (toBeInTheDocument) no son
// dependencias de este repo (ver otros tests de páginas, p.ej.
// DistanciasProyecto.test.tsx): se usa `fireEvent` y `toBeTruthy()` en su lugar.

const LINEA = {
  insumo_codigo: "7462", insumo_nombre: "TRANSPORTE DE PETREOS", unidad: "M3-KM",
  rendimiento: 33.6, precio_unitario: 1000, fuente_precio: "COSTO INTERNO",
  costo: 33600, calidad_cruce: "exacto",
};

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/api/transporte", () => ({
  crearAjuste: vi.fn(async () => ({})),
}));
vi.mock("@/api/autoria", () => ({
  listarApus: vi.fn(async () => ({ items: [], total: 0, limit: 15, offset: 0 })),
}));
vi.mock("@/api/insumos", () => ({
  listarInsumos: vi.fn(async () => ({ items: [], total: 0, limit: 15, offset: 0 })),
}));
vi.mock("@/api/corridas", () => ({
  getItem: vi.fn(async () => ({
    seq: 0, descripcion: "Concreto", apu_codigo: "4390", apu_turno: "DIURNO",
    apu_nombre: "APU X", status: "matched", explicacion: "", candidatos: [],
    composicion: [LINEA], costo_unitario: 33600,
  })),
  confirmar: vi.fn(), confirmarLote: vi.fn(),
}));

describe("FilaComposicion", () => {
  it("permite ajustar el rendimiento para el proyecto", async () => {
    const crear = vi.spyOn(apiTte, "crearAjuste").mockResolvedValue({} as never);
    const onCambio = vi.fn();
    render(<table><tbody>
      <FilaComposicion linea={LINEA} apuCodigo="4390" turno="DIURNO"
                       carpetaId={7} editable onCambio={onCambio} />
    </tbody></table>);
    fireEvent.click(screen.getByRole("button", { name: /ajustar/i }));
    const campo = screen.getByLabelText(/rendimiento del proyecto/i);
    fireEvent.change(campo, { target: { value: "40" } });
    fireEvent.click(screen.getByRole("button", { name: /aplicar/i }));
    await waitFor(() => expect(crear).toHaveBeenCalledWith(7, expect.objectContaining({
      apu_codigo: "4390", shift: "DIURNO", accion: "rendimiento",
      insumo_codigo: "7462", rendimiento: 40 })));
    expect(onCambio).toHaveBeenCalled();
  });

  it("sin carpeta o sin permiso no muestra el botón", () => {
    render(<table><tbody>
      <FilaComposicion linea={LINEA} apuCodigo="4390" turno="DIURNO"
                       carpetaId={7} editable={false} onCambio={() => {}} />
    </tbody></table>);
    expect(screen.queryByRole("button", { name: /ajustar/i })).toBeNull();
  });

  it("el toast de éxito aclara que el ajuste es del proyecto y no toca la biblioteca", async () => {
    vi.spyOn(apiTte, "crearAjuste").mockResolvedValue({} as never);
    const { toast } = await import("sonner");
    render(<table><tbody>
      <FilaComposicion linea={LINEA} apuCodigo="4390" turno="DIURNO"
                       carpetaId={7} editable onCambio={() => {}} />
    </tbody></table>);
    fireEvent.click(screen.getByRole("button", { name: /ajustar/i }));
    fireEvent.click(screen.getByRole("button", { name: /aplicar/i }));
    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    const mensaje = vi.mocked(toast.success).mock.calls.at(-1)?.[0] as string;
    expect(mensaje).toMatch(/proyecto/i);
    expect(mensaje).toMatch(/biblioteca no cambió/i);
  });
});

// ─── integración con TablaItems: quién decide `editable` ──────────────────────
// `editable` depende de tres cosas que ya viven en TablaItems/Corrida.tsx: si la
// corrida está congelada (`readOnly`), si el usuario tiene rol editor
// (`puedeEditar`) y si la corrida pertenece a una carpeta (`carpetaId`).

const ITEM = {
  seq: 0, item: "1", descripcion: "Concreto", unidad: "M3", cantidad: 10,
  apu_codigo: "4390", apu_nombre: "APU X", status: "matched", confianza: 1,
  precio_contractual: 0, costo_unitario: 33600, margen_unitario: 0, margen_pct: 0,
  contractual_total: 0, costo_total: 0, margen_total: 0,
};

test("con carpeta, rol editor y corrida activa, la composición ofrece Ajustar", async () => {
  render(
    <TablaItems corridaId={1} items={[ITEM]} onConfirmado={() => {}}
      puedeEditar carpetaId={7} />,
  );
  fireEvent.click(screen.getByLabelText("Expandir fila"));
  expect(await screen.findByRole("button", { name: /ajustar/i })).toBeTruthy();
});

test("corrida congelada: la composición no ofrece Ajustar aunque haya carpeta y rol editor", async () => {
  render(
    <TablaItems corridaId={1} items={[ITEM]} onConfirmado={() => {}}
      puedeEditar carpetaId={7} readOnly />,
  );
  fireEvent.click(screen.getByLabelText("Expandir fila"));
  await screen.findByText(/APU: 4390/);
  expect(screen.queryByRole("button", { name: /ajustar/i })).toBeNull();
});

test("sin rol editor, la composición no ofrece Ajustar", async () => {
  render(
    <TablaItems corridaId={1} items={[ITEM]} onConfirmado={() => {}} carpetaId={7} />,
  );
  fireEvent.click(screen.getByLabelText("Expandir fila"));
  await screen.findByText(/APU: 4390/);
  expect(screen.queryByRole("button", { name: /ajustar/i })).toBeNull();
});

test("sin carpeta (corrida sin proyecto), la composición no ofrece Ajustar", async () => {
  render(
    <TablaItems corridaId={1} items={[ITEM]} onConfirmado={() => {}} puedeEditar />,
  );
  fireEvent.click(screen.getByLabelText("Expandir fila"));
  await screen.findByText(/APU: 4390/);
  expect(screen.queryByRole("button", { name: /ajustar/i })).toBeNull();
});

test("ajustar desde la tabla recarga el detalle del ítem sin colapsar la fila", async () => {
  const { getItem } = await import("@/api/corridas");
  render(
    <TablaItems corridaId={1} items={[ITEM]} onConfirmado={() => {}}
      puedeEditar carpetaId={7} />,
  );
  fireEvent.click(screen.getByLabelText("Expandir fila"));
  fireEvent.click(await screen.findByRole("button", { name: /ajustar/i }));
  const campo = screen.getByLabelText(/rendimiento del proyecto/i);
  fireEvent.change(campo, { target: { value: "40" } });
  vi.mocked(getItem).mockClear();
  fireEvent.click(screen.getByRole("button", { name: /aplicar/i }));
  // Se vuelve a pedir el detalle (mismo camino que usa `confirmar`) y la fila
  // sigue expandida (el header del APU sigue visible).
  await waitFor(() => expect(getItem).toHaveBeenCalledWith(1, 0));
  expect(screen.getByText(/APU: 4390/)).toBeTruthy();
});
