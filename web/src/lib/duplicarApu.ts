// Helpers puros para duplicar un APU. Aislados para testearlos sin montar la UI,
// igual que costoApu.ts / validacionApu.ts.

/** Convención de la empresa: el APU nocturno lleva el código con sufijo " N". */
const MARCA_NOCTURNA = " N";
const RE_MARCA_NOCTURNA = /\s+N$/i;
const RE_SUFIJO_COPIA = /-\d+$/;

/**
 * Base de un código: sin la marca nocturna y sin el sufijo de copia.
 * "3454 N" -> "3454" · "3454-2" -> "3454" · "3454-2 N" -> "3454"
 * Se exporta porque también es el `q` con el que se consultan los códigos ocupados.
 */
export function baseDe(codigo: string): string {
  return codigo
    .trim()
    .replace(RE_MARCA_NOCTURNA, "")
    .trim()
    .replace(RE_SUFIJO_COPIA, "")
    .trim();
}

/**
 * Código sugerido para la copia: el primer `-<n>` libre sobre la base, con la
 * marca nocturna al final si el turno es NOCTURNO. `ocupados` son códigos
 * completos (tal como están en la biblioteca).
 */
export function codigoSugerido(
  codigoOrigen: string,
  turno: string,
  ocupados: string[],
): string {
  const base = baseDe(codigoOrigen);
  const nocturno = turno.trim().toUpperCase() === "NOCTURNO";
  const tomados = new Set(ocupados.map((c) => c.trim().toUpperCase()));
  const arma = (n: number) => `${base}-${n}${nocturno ? MARCA_NOCTURNA : ""}`;
  let n = 2;
  while (tomados.has(arma(n).toUpperCase()) && n < 999) n++;
  return arma(n);
}

/**
 * Mismo criterio que `apu_tool/nucleo/texto.py::normalizar`: sin tildes,
 * MAYÚSCULAS, sin puntuación, espacios colapsados. Espejar el backend evita que
 * el diálogo habilite un guardado que el servidor va a rechazar con 400.
 */
export function normalizarNombre(s: string): string {
  return (s || "")
    .toUpperCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")            // sin tildes
    .replace(/[^A-Z0-9 ]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** La copia necesita nombre propio: vacío o igual al del origen no cuenta. */
export function nombreEsDistinto(nombreOrigen: string, nombreNuevo: string): boolean {
  const nuevo = normalizarNombre(nombreNuevo);
  return nuevo !== "" && nuevo !== normalizarNombre(nombreOrigen);
}

