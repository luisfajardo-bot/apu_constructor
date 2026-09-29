// Espejo de config.FUENTES_PRECIO: las ÚNICAS fuentes que se pueden escribir. El
// backend rechaza cualquier otra; lo guardado antes con otras etiquetas se muestra tal cual.
export const FUENTE_IDU = "PRECIO IDU";
export const FUENTE_INTERNA = "COSTO INTERNO";
export const FUENTES_PRECIO = [FUENTE_IDU, FUENTE_INTERNA] as const;

export function esFuenteValida(f: string): boolean {
  return (FUENTES_PRECIO as readonly string[]).includes(f);
}
