// Tipos de dominio — shapes exactos que devuelve el backend

export interface Progreso {
  i: number;
  total: number;
  descripcion: string;
  fila?: ItemCuadro; // fila ya costeada del APU recién armado (para la tabla en vivo)
}

export interface CorridaIniciada {
  id: number;
  total: number;
}

export interface Totales {
  contractual: number;
  costo: number;
  margen: number;
  margen_pct: number;
  n_items: number;
  n_revision: number;
}

export interface ItemCuadro {
  seq: number;
  item: string;
  descripcion: string;
  unidad: string;
  cantidad: number;
  apu_codigo: string;
  apu_nombre: string;
  status: string;
  confianza: number;
  precio_contractual: number;
  costo_unitario: number;
  margen_unitario: number;
  margen_pct: number;
  contractual_total: number;
  costo_total: number;
  margen_total: number;
}

export interface Candidato {
  apu_codigo: string;
  apu_nombre: string;
  score: number;
  motivo: string;
}

export interface LineaComposicion {
  insumo_codigo: string;
  insumo_nombre: string;
  unidad: string;
  rendimiento: number;
  precio_unitario: number;
  fuente_precio: string;
  costo: number;
  calidad_cruce: string;
  tipo?: string;
  ref_shift?: string;
}

export interface DetalleItem {
  seq: number;
  descripcion: string;
  apu_codigo: string;
  apu_nombre: string;
  status: string;
  explicacion: string;
  candidatos: Candidato[];
  composicion: LineaComposicion[];
  costo_unitario: number;
}

export interface Insumo {
  id: number;
  codigo: string;
  nombre: string;
  unidad: string;
  grupo: string;
  precio: number;
  fuente: string;
  clasificacion: string;
}

export interface HistorialPrecio {
  precio: number;
  fuente: string;
  clasificacion: string;
  fecha: string;
  vigente: boolean;
}

export interface InsumoDetalle {
  insumo: Insumo;
  historial: HistorialPrecio[];
}

export interface CambioPreview {
  insumo_id: number;
  codigo: string;
  nombre: string;
  precio_actual: number;
  precio_nuevo: number;
  fuente_actual: string;
  fuente_nueva: string;
}

export interface Carpeta {
  id: number;
  nombre: string;
  parent_id: number | null;
}

export interface CarpetaNodo {
  id: number;
  nombre: string;
  parent_id: number | null;
  n_corridas: number;
  hijas: CarpetaNodo[];
}

export interface CorridaResumen {
  id: number;
  nombre: string;
  archivo: string;
  creada_en: string;
  estado: string;
  modo: string;
  n_items: number;
  n_revision: number;
  duracion_ms: number | null;
  contractual: number | null;
  costo: number | null;
  margen: number | null;
  margen_pct: number | null;
  carpeta_id: number | null;
}

// Wrappers de respuesta

export interface StatusResponse {
  insumos: number;
  apus: number;
  ia: boolean;
}

export interface CorridaCreada {
  id: number;
  resumen: Totales;
}

export interface CorridaDetalle {
  id: number;
  nombre: string;
  archivo: string;
  estado: string;
  modo: string;
  items: ItemCuadro[];
  totales: Totales;
  duracion_ms: number | null;
  carpeta_id: number | null;
}

export interface ListaInsumos {
  items: Insumo[];
  total: number;
  limit: number;
  offset: number;
}

export interface CambiosAplicados {
  aplicados: number;
  errores: { insumo_id: number; error: string }[];
}

export interface ImportAmbiguo {
  codigo: string;
  candidatos: { id: number; nombre: string }[];
}

export interface ImportInsumosUpsertPreview {
  crear: InsumoImportFila[];
  actualizar: CambioPreview[];
  ambigua: ImportAmbiguo[];
  no_encontrada: { codigo: string }[];
  invalida: InsumoImportFila[];
}

export interface ImportUpsertResultado {
  creados: number;
  actualizados: number;
  errores: { codigo: string; error: string }[];
}

// ─── Autoría de la base — agregar insumos y APUs ───────────────────────────────

export interface InsumoNuevo {
  codigo: string;
  nombre: string;
  unidad: string;
  grupo: string;
  precio: number;
  fuente: string;
}

export interface ComponenteNuevo {
  insumo_codigo: string;
  rendimiento: number;
  insumo_nombre?: string;
  unidad?: string;
  tipo?: string;
  ref_shift?: string;
}

export interface ApuNuevo {
  codigo: string;
  turno: string;
  nombre: string;
  unidad: string;
  grupo: string;
  componentes: ComponenteNuevo[];
}

export interface ApuEditar {
  nombre: string;
  unidad: string;
  grupo: string;
  componentes: ComponenteNuevo[];
}

export interface ApuResumen {
  codigo: string;
  turno: string;
  nombre: string;
  unidad: string;
  grupo: string;
  n_componentes: number;
  costo_unitario: number;
}

export interface ApuDetalle {
  codigo: string;
  turno: string;
  nombre: string;
  unidad: string;
  grupo: string;
  costo_unitario: number;
  composicion: LineaComposicion[];
  n_corridas?: number;
}

export interface ListaApus {
  items: ApuResumen[];
  total: number;
  limit: number;
  offset: number;
}

// Fila candidata a crear / ya existente en una importación de insumos
export interface InsumoImportFila {
  codigo: string;
  nombre: string;
  unidad: string;
  grupo: string;
  precio: number;
  fuente: string;
}

export interface VinculoSubApu {
  apu_codigo: string;
  apu_turno: string;
  sub_codigo: string;
  sub_turno: string;
  sub_nombre: string;
  origen: "lote" | "biblioteca";
}

export interface ImportApusPreview {
  crear: ApuResumen[];
  ya_existe: ApuResumen[];
  subapus: VinculoSubApu[];
}

export interface ImportResultado {
  creados: number;
  subapus_marcados?: number;
  errores: { codigo: string; turno?: string; error: string }[];
}
