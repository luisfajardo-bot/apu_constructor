import { useMemo, useState } from "react";
import type { DictamenIA, ItemCuadro, VeredictoIA } from "@/lib/tipos";

export type ClaveColumna =
  | "descripcion" | "unidad" | "cantidad" | "item" | "apu" | "status" | "veredicto"
  | "precio_contractual" | "costo_unitario"
  | "contractual_total" | "costo_total" | "margen_total" | "margen_pct";

export type DireccionOrden = "asc" | "desc";
export type EstadoOrden = { clave: ClaveColumna; dir: DireccionOrden } | null;

export type FiltroRango = { min: string; max: string };

export interface FiltrosColumna {
  descripcion: string;
  unidad: string;
  cantidad: FiltroRango;
  item: string;
  apu: string;
  status: string;
  veredicto: string;
  precio_contractual: FiltroRango;
  costo_unitario: FiltroRango;
  contractual_total: FiltroRango;
  costo_total: FiltroRango;
  margen_total: FiltroRango;
  margen_pct: FiltroRango;
}

export const FILTROS_VACIOS: FiltrosColumna = {
  descripcion: "", unidad: "", cantidad: { min: "", max: "" }, item: "",
  apu: "", status: "", veredicto: "",
  precio_contractual: { min: "", max: "" }, costo_unitario: { min: "", max: "" },
  contractual_total: { min: "", max: "" },
  costo_total: { min: "", max: "" }, margen_total: { min: "", max: "" },
  margen_pct: { min: "", max: "" },
};

/** Valor centinela del filtro de APU: deja solo las filas SIN APU asignado. */
export const SIN_APU = "__sin__";

/** Valor centinela del filtro de Veredicto: deja solo las filas SIN veredicto (la IA
 *  no las contestó, o se agregaron después de revisar). Centinela propio y no el de
 *  APU: son dos columnas distintas y compartirlo ataría el filtro de una al de la
 *  otra. Un valor imposible como dictamen, así que el filtro exacto del resto del
 *  vocabulario (`valorVeredicto(it) !== f.veredicto`) sigue igual. */
export const SIN_VEREDICTO = "__sin_veredicto__";

/** Etiqueta corta y color de cada dictamen de la revisión con IA. Los colores
 *  salen del vocabulario de "significado" de index.css (positivo / revisar /
 *  info / destructivo), no de la paleta cruda de Tailwind. */
export const VEREDICTO_UI: Record<DictamenIA, { label: string; cls: string }> = {
  ok:      { label: "✔ ok",      cls: "text-margen-pos" },
  dudoso:  { label: "⚠ dudoso",  cls: "text-revisar" },
  cambiar: { label: "↔ cambiar", cls: "text-info" },
  sin_apu: { label: "✖ sin APU", cls: "text-destructive" },
};

export function etiquetaVeredicto(dictamen: string): string {
  if (dictamen === SIN_VEREDICTO) return "— sin revisar";
  return VEREDICTO_UI[dictamen as DictamenIA]?.label ?? dictamen;
}

/** El nivel del veredicto, en palabras de persona: `barrido` es un triaje que NO
 *  miró la composición (no tiene la autoridad de un análisis a fondo) y `profundo`
 *  sí vio los insumos y rendimientos del asignado y de cada candidato. */
const NIVEL_TEXTO: Record<VeredictoIA["nivel"], string> = {
  barrido: "Triaje rápido",
  profundo: "Análisis a fondo",
};

/** Texto del `title` de la celda: nivel + confianza + la justificación. La etiqueta
 *  visible se queda corta a propósito (la tabla es densa), así que el matiz —cuánto
 *  miró la IA y qué tan segura está— vive acá. */
export function tituloVeredicto(v: VeredictoIA): string {
  const cabecera = `${NIVEL_TEXTO[v.nivel] ?? v.nivel} · confianza ${
    Math.round(v.confianza * 100)}%`;
  return v.justificacion ? `${cabecera} — ${v.justificacion}` : cabecera;
}

/** Texto por el que se filtra y ordena la columna Veredicto. "" cuando la fila
 *  no tiene veredicto (la corrida no se revisó, o la IA no contestó esa fila). */
export function valorVeredicto(it: ItemCuadro): string {
  return it.revision?.dictamen ?? "";
}

const REVISABLE = new Set(["review", "new", "REVIEW", "NEW"]);
const CLAVES_TEXTO: ClaveColumna[] = ["descripcion", "unidad", "item", "apu", "status", "veredicto"];

export function normalizar(s: string): string {
  return (s ?? "").normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase().trim();
}

function contiene(valor: string, q: string): boolean {
  if (!q.trim()) return true;
  return normalizar(valor).includes(normalizar(q));
}

function enRango(valor: number, r: FiltroRango, escala = 1): boolean {
  const min = r.min.trim() === "" ? null : Number(r.min) * escala;
  const max = r.max.trim() === "" ? null : Number(r.max) * escala;
  if (min !== null && !Number.isNaN(min) && valor < min) return false;
  if (max !== null && !Number.isNaN(max) && valor > max) return false;
  return true;
}

export function filtrar(items: ItemCuadro[], f: FiltrosColumna, soloRevision: boolean): ItemCuadro[] {
  return items.filter((it) => {
    if (soloRevision && !REVISABLE.has(it.status)) return false;
    if (!contiene(it.descripcion, f.descripcion)) return false;
    if (f.unidad && it.unidad !== f.unidad) return false;
    if (!enRango(it.cantidad, f.cantidad)) return false;
    if (!contiene(it.item, f.item)) return false;
    // "__sin__" es un centinela dentro del filtro de texto de APU, no un estado
    // aparte: el contador rojo de "sin APU" reusa la maquinaria de filtros que ya
    // existe (y el botón "Limpiar" lo apaga como a cualquier otro filtro).
    if (f.apu === SIN_APU) {
      if (it.apu_codigo) return false;
    } else if (!contiene(`${it.apu_codigo} ${it.apu_nombre}`, f.apu)) return false;
    if (f.status && it.status !== f.status) return false;
    // El vacío SIGNIFICA algo en Veredicto (la IA no contestó esa fila), así que
    // tiene su propio centinela: sin esto no habría forma de encontrar esas filas.
    if (f.veredicto === SIN_VEREDICTO) {
      if (it.revision) return false;
    } else if (f.veredicto && valorVeredicto(it) !== f.veredicto) return false;
    if (!enRango(it.precio_contractual, f.precio_contractual)) return false;
    if (!enRango(it.costo_unitario, f.costo_unitario)) return false;
    if (!enRango(it.contractual_total, f.contractual_total)) return false;
    if (!enRango(it.costo_total, f.costo_total)) return false;
    if (!enRango(it.margen_total, f.margen_total)) return false;
    if (!enRango(it.margen_pct, f.margen_pct, 0.01)) return false;
    return true;
  });
}

function valorTexto(it: ItemCuadro, clave: ClaveColumna): string {
  switch (clave) {
    case "descripcion": return it.descripcion;
    case "unidad": return it.unidad;
    case "item": return it.item;
    case "apu": return it.apu_codigo;
    case "status": return it.status;
    case "veredicto": return valorVeredicto(it);
    default: return "";
  }
}

function valorNumero(it: ItemCuadro, clave: ClaveColumna): number {
  switch (clave) {
    case "cantidad": return it.cantidad;
    case "precio_contractual": return it.precio_contractual;
    case "costo_unitario": return it.costo_unitario;
    case "contractual_total": return it.contractual_total;
    case "costo_total": return it.costo_total;
    case "margen_total": return it.margen_total;
    case "margen_pct": return it.margen_pct;
    default: return 0;
  }
}

export function ordenar(items: ItemCuadro[], orden: EstadoOrden): ItemCuadro[] {
  if (!orden) return items;
  const { clave, dir } = orden;
  const factor = dir === "asc" ? 1 : -1;
  const esTexto = CLAVES_TEXTO.includes(clave);
  return [...items].sort((a, b) => {
    const cmp = esTexto
      ? valorTexto(a, clave).localeCompare(valorTexto(b, clave), "es-CO", { numeric: true })
      : valorNumero(a, clave) - valorNumero(b, clave);
    return cmp * factor;
  });
}

export function opcionesDe(
  items: ItemCuadro[],
  clave: "unidad" | "status" | "veredicto",
): string[] {
  const set = new Set<string>();
  let hayVacio = false;
  for (const it of items) {
    const v = clave === "unidad" ? it.unidad
      : clave === "status" ? it.status
      : valorVeredicto(it);
    if (v) set.add(v);
    else hayVacio = true;
  }
  const ordenadas = [...set].sort((a, b) => a.localeCompare(b, "es-CO", { numeric: true }));
  // Solo Veredicto ofrece el vacío como opción: en Und y Estado un vacío es un dato
  // que falta, acá es el resultado de que la IA no contestara esa fila — y sin la
  // opción no hay forma de filtrarlas. Va al final y aparte del sort: es un
  // centinela, no un valor del vocabulario.
  if (clave === "veredicto" && hayVacio) ordenadas.push(SIN_VEREDICTO);
  return ordenadas;
}

export function siguienteOrden(prev: EstadoOrden, clave: ClaveColumna): EstadoOrden {
  if (!prev || prev.clave !== clave) return { clave, dir: "asc" };
  if (prev.dir === "asc") return { clave, dir: "desc" };
  return null;
}

export function hayFiltrosActivos(f: FiltrosColumna, orden: EstadoOrden, soloRevision: boolean): boolean {
  if (orden || soloRevision) return true;
  return JSON.stringify(f) !== JSON.stringify(FILTROS_VACIOS);
}

export interface ControlCorridaTabla {
  filtradas: ItemCuadro[];
  totalItems: number;
  orden: EstadoOrden;
  alternarOrden: (clave: ClaveColumna) => void;
  filtros: FiltrosColumna;
  setFiltro: (clave: ClaveColumna, valor: string | FiltroRango) => void;
  soloRevision: boolean;
  setSoloRevision: (v: boolean) => void;
  limpiar: () => void;
  hayFiltros: boolean;
  opcionesUnidad: string[];
  opcionesStatus: string[];
  opcionesVeredicto: string[];
}

export function useCorridaTabla(items: ItemCuadro[]): ControlCorridaTabla {
  const [orden, setOrden] = useState<EstadoOrden>(null);
  const [filtros, setFiltros] = useState<FiltrosColumna>(FILTROS_VACIOS);
  const [soloRevision, setSoloRevision] = useState(false);

  const filtradas = useMemo(
    () => ordenar(filtrar(items, filtros, soloRevision), orden),
    [items, filtros, soloRevision, orden],
  );
  const opcionesUnidad = useMemo(() => opcionesDe(items, "unidad"), [items]);
  const opcionesStatus = useMemo(() => opcionesDe(items, "status"), [items]);
  const opcionesVeredicto = useMemo(() => opcionesDe(items, "veredicto"), [items]);
  const hayFiltros = hayFiltrosActivos(filtros, orden, soloRevision);

  return {
    filtradas,
    totalItems: items.length,
    orden,
    alternarOrden: (clave) => setOrden((prev) => siguienteOrden(prev, clave)),
    filtros,
    setFiltro: (clave, valor) => setFiltros((prev) => ({ ...prev, [clave]: valor })),
    soloRevision,
    setSoloRevision,
    limpiar: () => { setFiltros(FILTROS_VACIOS); setOrden(null); setSoloRevision(false); },
    hayFiltros,
    opcionesUnidad,
    opcionesStatus,
    opcionesVeredicto,
  };
}
