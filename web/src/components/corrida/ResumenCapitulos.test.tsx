import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import ResumenCapitulos from "@/components/corrida/ResumenCapitulos";
import type { CapituloCorrida, Totales } from "@/lib/tipos";

const CAPS: CapituloCorrida[] = [
  { codigo: "1", nombre: "PRELIMINARES", orden: 1, actividades: 2, con_apu: 2,
    sin_apu: 0, contractual: 137605594, contractual_sin_aiu: 107565459,
    costo: 100000000, diferencia: 37605594, margen_pct: 0.2733,
    cobertura: 1, cobertura_valor: 1, completo: true },
  { codigo: "2", nombre: "PAVIMENTOS", orden: 2, actividades: 42, con_apu: 40,
    sin_apu: 2, contractual: 37144267929, contractual_sin_aiu: 29037106963,
    costo: 26000000000, diferencia: 11144267929, margen_pct: 0.3,
    cobertura: 40 / 42, cobertura_valor: 0.68, completo: false },
];

// Los totales los manda el BACKEND: el componente los pinta, no los suma. Acá se
// mandan valores que NO son la suma de las filas, justamente para que el test falle
// si alguien vuelve a calcularlos en el navegador.
const TOTALES: Totales = {
  contractual: 37281873523, costo: 26100000000, margen: 11181873523,
  margen_pct: 0.2999, n_items: 44, n_revision: 2,
};

const pintar = (capitulos = CAPS, totales = TOTALES) =>
  render(<ResumenCapitulos capitulos={capitulos} totales={totales} />);

const fila = (nombre: string) => screen.getByText(nombre).closest("tr")!;

describe("ResumenCapitulos", () => {
  it("muestra una fila por capítulo con contractual y costo", () => {
    pintar();
    expect(screen.getByText("PRELIMINARES")).toBeTruthy();
    expect(screen.getByText("PAVIMENTOS")).toBeTruthy();
    expect(screen.getByText("$137.605.594")).toBeTruthy();
    expect(screen.getByText("$100.000.000")).toBeTruthy();
  });

  it("cuenta las actividades sin APU en vez de esconderlas", () => {
    pintar();
    const f = fila("PAVIMENTOS");
    expect(f.textContent).toContain("40");   // con APU
    expect(f.textContent).toContain("2");    // sin APU
  });

  it("marca el margen como parcial cuando el capítulo está incompleto", () => {
    pintar();
    expect(fila("PAVIMENTOS").textContent).toMatch(/parcial/i);
    expect(fila("PAVIMENTOS").textContent).toMatch(/incompleto/i);
    expect(fila("PRELIMINARES").textContent).not.toMatch(/parcial/i);
    expect(fila("PRELIMINARES").textContent).toMatch(/completo/i);
  });

  it("muestra la cobertura por conteo y por valor", () => {
    pintar();
    const f = fila("PAVIMENTOS");
    expect(f.textContent).toContain("95.2%");   // 40/42 por conteo
    expect(f.textContent).toContain("68.0%");   // por valor
  });

  it("avisa en el encabezado cuántos capítulos no están costeados del todo", () => {
    pintar();
    expect(screen.getByText(/1 sin costear del todo/)).toBeTruthy();
  });

  it("el dinero del total viene del backend, no de sumar las filas", () => {
    // Totales deliberadamente DISTINTOS de la suma de CAPS: si el componente volviera
    // a sumar en el navegador, estos asserts fallarían.
    pintar(CAPS, { ...TOTALES, contractual: 999, costo: 111, margen: 888,
                   margen_pct: 0.888 });
    const total = screen.getByText("TOTAL").closest("tr")!;
    expect(total.textContent).toContain("$999");
    expect(total.textContent).toContain("$111");
    expect(total.textContent).toContain("$888");
    expect(total.textContent).toContain("88.8%");
  });

  it("los conteos si se suman en el cliente: no son dinero", () => {
    pintar();
    const total = screen.getByText("TOTAL").closest("tr")!;
    expect(total.textContent).toContain("44");   // 2 + 42 actividades
    expect(total.textContent).toContain("42");   // 2 + 40 con APU
  });

  it("no se dibuja cuando la corrida no tiene capítulos", () => {
    const { container } = pintar([]);
    expect(container.firstChild).toBeNull();
  });
});
