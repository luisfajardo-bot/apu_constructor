import { useMemo, useState } from "react";
import type { ItemCuadro } from "@/lib/tipos";

export type ClaveColumna =
  | "descripcion" | "unidad" | "cantidad" | "item" | "apu" | "status"
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
  contractual_total: FiltroRango;
  costo_total: FiltroRango;
  margen_total: FiltroRango;
  margen_pct: FiltroRango;
}

export const FILTROS_VACIOS: FiltrosColumna = {
  descripcion: "", unidad: "", cantidad: { min: "", max: "" }, item: "",
  apu: "", status: "", contractual_total: { min: "", max: "" },
  costo_total: { min: "", max: "" }, margen_total: { min: "", max: "" },
  margen_pct: { min: "", max: "" },
};

const REVISABLE = new Set(["review", "new", "REVIEW", "NEW"]);
const CLAVES_TEXTO: ClaveColumna[] = ["descripcion", "unidad", "item", "apu", "status"];

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
    if (!contiene(`${it.apu_codigo} ${it.apu_nombre}`, f.apu)) return false;
    if (f.status && it.status !== f.status) return false;
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
    default: return "";
  }
}

function valorNumero(it: ItemCuadro, clave: ClaveColumna): number {
  switch (clave) {
    case "cantidad": return it.cantidad;
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
      ? valorTexto(a, clave).localeCompare(valorTexto(b, clave), "es", { numeric: true })
      : valorNumero(a, clave) - valorNumero(b, clave);
    return cmp * factor;
  });
}

export function opcionesDe(items: ItemCuadro[], clave: "unidad" | "status"): string[] {
  const set = new Set<string>();
  for (const it of items) {
    const v = clave === "unidad" ? it.unidad : it.status;
    if (v) set.add(v);
  }
  return [...set].sort((a, b) => a.localeCompare(b, "es", { numeric: true }));
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
  };
}
