// Redondeo a la unidad (peso) en multiplicaciones monetarias. Gemelo de
// apu_tool/nucleo/redondeo.py. Regla: cada producto monetario se redondea a la
// unidad más cercana (medio hacia arriba); un producto positivo que redondearía
// a 0 se fija en 1 (nada en $0 por redondeo); un 0 genuino queda en 0.
export function mulRedondeado(a: number, b: number): number {
  const p = a * b;
  // `!(p > 0)` y NO `p <= 0`: toda comparación con NaN es false, así que un NaN se
  // colaría a Math.round(NaN) = NaN y se pintaría "NaN" en la tabla. Mismo arreglo
  // que en el gemelo de Python (apu_tool/nucleo/redondeo.py).
  if (!(p > 0)) return 0;
  // Math.round en JS es medio-hacia-+∞: Math.round(0.5)=1, Math.round(1312.5)=1313.
  const r = Math.round(p);
  return r !== 0 ? r : 1;
}
