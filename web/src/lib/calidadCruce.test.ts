import { describe, expect, it } from "vitest";
import { etiquetaCalidadCruce } from "@/lib/calidadCruce";

// Vocabulario completo espejo de CALIDAD_CRUCE en apu_tool/nucleo/models.py:
// exacto | aproximado | ambiguo | huerfano | apu | apu_vacio | ciclo |
// sin_precio_lista | sin_precio_catalogo
describe("etiquetaCalidadCruce", () => {
  it("traduce cada valor conocido del vocabulario a español legible", () => {
    expect(etiquetaCalidadCruce("exacto")).toBe("Exacto");
    expect(etiquetaCalidadCruce("aproximado")).toBe("Aproximado");
    expect(etiquetaCalidadCruce("ambiguo")).toBe("Ambiguo");
    expect(etiquetaCalidadCruce("huerfano")).toBe("Huérfano");
    expect(etiquetaCalidadCruce("apu")).toBe("Sub-APU");
    expect(etiquetaCalidadCruce("apu_vacio")).toBe("Sub-APU vacío");
    expect(etiquetaCalidadCruce("ciclo")).toBe("Ciclo");
    expect(etiquetaCalidadCruce("sin_precio_lista")).toBe("Sin tarifa en la lista");
    expect(etiquetaCalidadCruce("sin_precio_catalogo")).toBe("Sin precio en catálogo");
  });

  it("degrada mostrando el valor crudo si es desconocido", () => {
    expect(etiquetaCalidadCruce("valor_futuro_no_mapeado")).toBe("valor_futuro_no_mapeado");
  });

  it("no rompe ni queda vacío con un string vacío", () => {
    expect(etiquetaCalidadCruce("")).toBe("");
  });
});
