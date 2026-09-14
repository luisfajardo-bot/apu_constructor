import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import ResumenCapitulos from "@/components/corrida/ResumenCapitulos";
import type { CapituloCorrida } from "@/lib/tipos";

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

const fila = (nombre: string) => screen.getByText(nombre).closest("tr")!;

describe("ResumenCapitulos", () => {
  it("muestra una fila por capítulo con contractual y costo", () => {
    render(<ResumenCapitulos capitulos={CAPS} />);
    expect(screen.getByText("PRELIMINARES")).toBeTruthy();
    expect(screen.getByText("PAVIMENTOS")).toBeTruthy();
    expect(screen.getByText("$137.605.594")).toBeTruthy();
    expect(screen.getByText("$100.000.000")).toBeTruthy();
  });

  it("cuenta las actividades sin APU en vez de esconderlas", () => {
    render(<ResumenCapitulos capitulos={CAPS} />);
    const f = fila("PAVIMENTOS");
    expect(f.textContent).toContain("40");   // con APU
    expect(f.textContent).toContain("2");    // sin APU
  });

  it("marca el margen como parcial cuando el capítulo está incompleto", () => {
    render(<ResumenCapitulos capitulos={CAPS} />);
    expect(fila("PAVIMENTOS").textContent).toMatch(/parcial/i);
    expect(fila("PAVIMENTOS").textContent).toMatch(/incompleto/i);
    expect(fila("PRELIMINARES").textContent).not.toMatch(/parcial/i);
    expect(fila("PRELIMINARES").textContent).toMatch(/completo/i);
  });

  it("muestra la cobertura por conteo y por valor", () => {
    render(<ResumenCapitulos capitulos={CAPS} />);
    const f = fila("PAVIMENTOS");
    expect(f.textContent).toContain("95.2%");   // 40/42 por conteo
    expect(f.textContent).toContain("68.0%");   // por valor
  });

  it("avisa en el encabezado cuántos capítulos no están costeados del todo", () => {
    render(<ResumenCapitulos capitulos={CAPS} />);
    expect(screen.getByText(/1 sin costear del todo/)).toBeTruthy();
  });

  it("el total es la suma de las filas", () => {
    render(<ResumenCapitulos capitulos={CAPS} />);
    const total = screen.getByText("TOTAL").closest("tr")!;
    expect(total.textContent).toContain("$37.281.873.523");   // contractual
    expect(total.textContent).toContain("$26.100.000.000");   // costo
    expect(total.textContent).toContain("44");                // actividades
  });

  it("no se dibuja cuando la corrida no tiene capítulos", () => {
    const { container } = render(<ResumenCapitulos capitulos={[]} />);
    expect(container.firstChild).toBeNull();
  });
});
