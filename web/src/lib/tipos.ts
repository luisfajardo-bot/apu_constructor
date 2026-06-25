// Tipos de dominio — shapes exactos que devuelve el backend

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
  archivo: string;
  estado: string;
  items: ItemCuadro[];
  totales: Totales;
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

export interface ImportarPreviewResponse {
  cambios: CambioPreview[];
  ambiguos: unknown[];
  no_encontrados: unknown[];
}

export interface TransformarPreviewResponse {
  cambios: CambioPreview[];
  afectados: number;
}
