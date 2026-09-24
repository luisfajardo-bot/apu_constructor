import type { ItemCuadro } from "./tipos";

/** Una fila que el umbral puede igualar: está en $0 y el contrato sí la paga.
 *
 *  Misma regla que `_candidata_umbral` en `servicio/corridas.py`, sobre los mismos
 *  campos. Una fila SIN APU siempre cuesta $0, así que entra sola; una CON APU pero
 *  sin precios también, que es el otro caso que deja el cuadro trabado.
 *  `!(x > 0)` y no `x === 0` por el NaN. */
export function esCandidata(it: ItemCuadro): boolean {
  return !it.costo_manual && !(it.costo_unitario > 0) && it.precio_contractual > 0;
}

export interface PreviaUmbral {
  /** En $0 y pagables: el universo sobre el que actúa el techo. */
  candidatas: ItemCuadro[];
  /** Candidatas bajo el techo, por `contractual_total` de mayor a menor. Es la lista
   *  que el diálogo DIBUJA — NO la afectan las exclusiones manuales: si una fila
   *  destildada desapareciera de la tabla, el usuario no podría volver a marcarla. */
  bajoTecho: ItemCuadro[];
  /** `bajoTecho` menos las exclusiones manuales (los destildes): lo que de verdad se
   *  va a igualar. Es una PROPUESTA todavía no aplicada — en la respuesta del backend
   *  `igualadas` significa otra cosa: las filas que YA se escribieron. */
  igualadas: ItemCuadro[];
  /** Candidatas que NO se igualan: las que pasan el techo MÁS las destildadas a mano. */
  restantes: ItemCuadro[];
  sumaIgualadas: number;
  sumaRestantes: number;
  /** Suma de TODAS las filas de la corrida, para los porcentajes. */
  contractualCorrida: number;
  sinApu: number;
  conApu: number;
  /** En $0 pero con contractual ≤ 0: no se pueden igualar (regla «nada en $0»). */
  sinContractual: number;
}

const suma = (xs: ItemCuadro[]) => xs.reduce((s, it) => s + it.contractual_total, 0);

/** Qué pasaría con este umbral.
 *
 *  Cálculo puro sobre los ítems que la página ya tiene: es apoyo a la decisión, no un
 *  número que se persiste ni se emite. La escritura la manda el backend, que
 *  recalcula la candidatura con sus propios números.
 *
 *  `excluidas` son los `seq` que el usuario destildó a mano en el diálogo: sacan la
 *  fila de `igualadas` (y por lo tanto del resumen y del botón) pero no de
 *  `bajoTecho` (la tabla). */
export function previaUmbral(
  items: ItemCuadro[], umbral: number, excluidas?: ReadonlySet<number>,
): PreviaUmbral {
  const candidatas = items.filter(esCandidata);
  // Umbral 0, negativo o NaN: no se iguala nada (y el botón queda deshabilitado).
  const hayTecho = umbral > 0;
  const bajoTecho = candidatas
    .filter((it) => hayTecho && it.contractual_total <= umbral)
    .sort((a, b) => b.contractual_total - a.contractual_total);
  const igualadas = excluidas
    ? bajoTecho.filter((it) => !excluidas.has(it.seq))
    : bajoTecho;
  const marcadas = new Set(igualadas.map((it) => it.seq));
  const restantes = candidatas.filter((it) => !marcadas.has(it.seq));
  return {
    candidatas,
    bajoTecho,
    igualadas,
    restantes,
    sumaIgualadas: suma(igualadas),
    sumaRestantes: suma(restantes),
    contractualCorrida: suma(items),
    sinApu: igualadas.filter((it) => !it.apu_codigo).length,
    conApu: igualadas.filter((it) => !!it.apu_codigo).length,
    sinContractual: items.filter(
      (it) => !it.costo_manual && !(it.costo_unitario > 0) && !(it.precio_contractual > 0),
    ).length,
  };
}

/** Porcentaje del contrato, a prueba de una corrida que suma $0. */
export function porcentaje(parte: number, total: number): number {
  return total > 0 ? (parte / total) * 100 : 0;
}
