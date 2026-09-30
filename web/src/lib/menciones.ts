import type { MencionNota } from "@/lib/tipos";

/** Cómo se escribe a alguien después de la @: su nombre, o su email si no tiene. */
export function etiquetaDe(u: { nombre: string; email: string }): string {
  return u.nombre || u.email;
}

/** Si el cursor está justo después de "@algo" (la @ al inicio o tras un espacio, y sin
 *  espacios entre la @ y el cursor), devuelve dónde empieza y qué se lleva escrito. */
export function consultaMencion(texto: string, cursor: number): { inicio: number; q: string } | null {
  const antes = texto.slice(0, cursor);
  const i = antes.lastIndexOf("@");
  if (i < 0) return null;
  if (i > 0 && !/\s/.test(antes[i - 1])) return null;
  const q = antes.slice(i + 1);
  if (/\s/.test(q)) return null;
  return { inicio: i, q };
}

/** Reemplaza "@consulta" por "@Etiqueta " y deja el cursor después del espacio. */
export function insertarMencion(texto: string, inicio: number, cursor: number,
                                etiqueta: string): { texto: string; cursor: number } {
  const puesto = `@${etiqueta} `;
  return { texto: texto.slice(0, inicio) + puesto + texto.slice(cursor), cursor: inicio + puesto.length };
}

/** Los elegidos cuyo "@Nombre" sigue escrito: borrar el nombre del texto quita la mención.
 *  Usa el mismo buscador que el resaltado, así "@Ana Ruiz" no avisa a "Ana". */
export function mencionesVigentes(texto: string, elegidos: MencionNota[]): string[] {
  const porMarca = new Map(elegidos.filter((e) => e.nombre).map((e) => [`@${e.nombre}`, e.user_id]));
  const ids = partesConMenciones(texto, elegidos.map((e) => e.nombre))
    .filter((p) => p.mencion)
    .map((p) => porMarca.get(p.texto) as string);
  return [...new Set(ids)].sort();
}

/** Parte el texto para resaltar los "@Nombre". Prueba primero los nombres más largos,
 *  para que "@Ana Ruiz" no se corte en "@Ana"; y el nombre debe terminar ahí (después
 *  no sigue una letra ni un dígito), para que "@Anabel" no cuente como "@Ana". */
export function partesConMenciones(texto: string, nombres: string[]): { texto: string; mencion: boolean }[] {
  const marcas = [...new Set(nombres.filter(Boolean))].sort((a, b) => b.length - a.length).map((n) => `@${n}`);
  const termina = (i: number) => i >= texto.length || !/[\p{L}\p{N}]/u.test(texto[i]);
  const partes: { texto: string; mencion: boolean }[] = [];
  let resto = "";
  let i = 0;
  while (i < texto.length) {
    const m = marcas.find((x) => texto.startsWith(x, i) && termina(i + x.length));
    if (m) {
      if (resto) partes.push({ texto: resto, mencion: false });
      partes.push({ texto: m, mencion: true });
      resto = "";
      i += m.length;
    } else {
      resto += texto[i];
      i += 1;
    }
  }
  if (resto) partes.push({ texto: resto, mencion: false });
  return partes;
}
