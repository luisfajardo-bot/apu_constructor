import type { Nota } from "@/lib/tipos";

/** Agrupa la lista plana del servidor en hilos de un nivel: cada raíz con sus
 *  respuestas debajo, en el orden en que llegaron. Una respuesta cuya raíz no vino
 *  (no debería pasar) se muestra como raíz para no perderla. */
export function agruparHilos(notas: Nota[]): { raiz: Nota; respuestas: Nota[] }[] {
  const ids = new Set(notas.map((n) => n.id));
  const hilos: { raiz: Nota; respuestas: Nota[] }[] = [];
  const porRaiz = new Map<number, Nota[]>();
  for (const n of notas) {
    if (n.responde_a !== null && ids.has(n.responde_a)) {
      porRaiz.set(n.responde_a, [...(porRaiz.get(n.responde_a) ?? []), n]);
    }
  }
  for (const n of notas) {
    if (n.responde_a === null || !ids.has(n.responde_a)) {
      hilos.push({ raiz: n, respuestas: porRaiz.get(n.id) ?? [] });
    }
  }
  return hilos;
}
