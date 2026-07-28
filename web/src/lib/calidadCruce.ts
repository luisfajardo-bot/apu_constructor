// Etiquetas legibles para CostedComponent.calidad_cruce (apu_tool/nucleo/models.py).
// Único lugar donde se traduce el vocabulario crudo (snake_case) a español para el
// usuario: úsalo en cualquier sitio que pinte `calidad_cruce`, no lo dupliques.
//
// Vocabulario espejo del comentario de `calidad_cruce` en models.py:
// exacto | aproximado | ambiguo | huerfano | apu | apu_vacio | ciclo |
// sin_precio_lista | sin_precio_catalogo
const ETIQUETAS_CALIDAD_CRUCE: Record<string, string> = {
  exacto: "Exacto",
  aproximado: "Aproximado",
  ambiguo: "Ambiguo",
  huerfano: "Huérfano",
  apu: "Sub-APU",
  apu_vacio: "Sub-APU vacío",
  ciclo: "Ciclo",
  sin_precio_lista: "Sin tarifa en la lista",
  sin_precio_catalogo: "Sin precio en catálogo",
};

/** Traduce un valor de `calidad_cruce` a español. Si es desconocido, degrada al valor crudo. */
export function etiquetaCalidadCruce(valor: string): string {
  return ETIQUETAS_CALIDAD_CRUCE[valor] ?? valor;
}
