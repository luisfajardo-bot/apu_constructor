// Validación pura para el formulario de "Agregar APU".
// Aislada para poder testearla sin montar la UI.

export interface FilaCompInput {
  insumo_codigo: string;
  rendimiento: string;
}

/** Un rendimiento es válido cuando es un número finito mayor que 0. */
export function rendimientoValido(rendimiento: string): boolean {
  const n = Number(rendimiento);
  return Number.isFinite(n) && n > 0;
}

/** Hay filas con insumo elegido pero rendimiento no válido (> 0). */
export function hayRendimientoInvalido(filas: FilaCompInput[]): boolean {
  return filas.some(
    (f) => f.insumo_codigo.trim() !== "" && !rendimientoValido(f.rendimiento),
  );
}

/** Componentes utilizables: insumo elegido y rendimiento > 0. */
export function componentesValidos(filas: FilaCompInput[]): FilaCompInput[] {
  return filas.filter(
    (f) => f.insumo_codigo.trim() !== "" && rendimientoValido(f.rendimiento),
  );
}
