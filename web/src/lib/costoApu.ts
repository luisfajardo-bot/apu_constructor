// Lógica pura del enlace costo ↔ rendimiento en la composición de un APU.
// Aislada para testear sin montar la UI (como validacionApu.ts).
// El costo NO se persiste: siempre es rendimiento × precio. Editar el costo solo
// despeja el rendimiento (Opción A del diseño): el APU guarda estructura, no dinero.

import { rendimientoValido } from "./validacionApu";

export interface FilaCosto {
  insumo_codigo: string;
  rendimiento: string;
  precio: number;
}

/** Costo de una fila = rendimiento × precio. 0 si el rendimiento no es número. */
export function costoDeFila(rendimiento: string, precio: number): number {
  const r = Number(rendimiento);
  if (!Number.isFinite(r) || rendimiento.trim() === "") return 0;
  return r * precio;
}

/**
 * Despeja el rendimiento desde un costo objetivo: rendimiento = costo / precio.
 * Devuelve null cuando no se puede despejar (precio <= 0, o costo vacío / no numérico).
 */
export function rendimientoDesdeCosto(costo: string, precio: number): number | null {
  if (precio <= 0) return null;
  const c = Number(costo);
  if (!Number.isFinite(c) || costo.trim() === "") return null;
  return c / precio;
}

/**
 * Costo unitario del APU = suma de costos de las filas con insumo elegido y
 * rendimiento válido (> 0). Una fila con rendimiento negativo/cero/vacío no se
 * guardaría (Guardar queda deshabilitado), así que tampoco debe sumar al total.
 */
export function costoTotalApu(filas: FilaCosto[]): number {
  return filas
    .filter((f) => f.insumo_codigo.trim() !== "" && rendimientoValido(f.rendimiento))
    .reduce((acc, f) => acc + costoDeFila(f.rendimiento, f.precio), 0);
}
