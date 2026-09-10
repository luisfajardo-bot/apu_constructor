// Tipos de dominio — shapes exactos que devuelve el backend

// La lista 1 es SIEMPRE 'Principal' (el catálogo). Gemelo de config.LISTA_PRINCIPAL_ID.
export const LISTA_PRINCIPAL_ID = 1;

export interface ListaPrecios {
  id: number;
  nombre: string;
  creada_en: string;
}

/** Respuesta de crear una corrida: se ENCOLÓ, no se armó. Armar 1900 líneas lleva
 *  horas y la petición vuelve en el acto; el progreso sale del poll de la corrida. */
export interface CorridaEncolada {
  id: number;
  total: number;
  estado: string;
}

/** Cómo va el armado que corre en el servidor. `null` cuando la corrida ya terminó
 *  de armarse: un progreso al 100 % que no se apaga es peor que nada. */
export interface ProgresoArmado {
  hechos: number;
  total: number;
  /** 0 = le toca ahora (o ya está armándose); > 0 = está esperando su turno. */
  posicion_en_cola: number;
  intentos: number;
  /** Motivo por el que se rindió. Puede traer pegada la cola técnica del error real. */
  ultimo_error: string | null;
}

export interface Totales {
  contractual: number;
  costo: number;
  margen: number;
  margen_pct: number;
  n_items: number;
  n_revision: number;
}

// ─── Revisión con IA ────────────────────────────────────────────────────────

export type DictamenIA = "ok" | "dudoso" | "cambiar" | "sin_apu";

export interface VeredictoIA {
  seq: number;
  dictamen: DictamenIA;
  apu_sugerido: string | null;
  turno_sugerido: string | null;
  confianza: number; // 0..1
  justificacion: string;
  // barrido = triaje sin objeción (nunca miró la composición completa);
  // profundo = la IA sí vio la composición del asignado y de cada candidato.
  nivel: "barrido" | "profundo";
}

/** Progreso del stream de revisión. 'started' llega una vez con el total de filas;
 *  'barriendo' llega una vez POR LOTE del barrido (así el stream no se queda mudo
 *  en corridas grandes, donde el triaje son varias llamadas seguidas a la IA);
 *  'barrido' llega una vez, al terminar el triaje completo. */
export type ProgresoRevision =
  // `lotes` viaja en el mismo 'started' (el backend lo calcula ANTES del primer
  // yield justo para esto): así el triaje se puede pintar "0 de N" desde el
  // arranque y no como un indeterminado de varios minutos. Opcional porque el
  // dato es del contador, no del contrato mínimo del evento.
  | { evento: "started"; total: number; lotes?: number }
  | { evento: "barriendo"; lote: number; lotes: number }
  | { evento: "barrido"; revisar: number; sin_respuesta: number[] };

/** Resumen final ('done') de la revisión: conteo de filas por dictamen más las
 *  que quedaron sin veredicto porque el barrido no las contestó. */
export interface ResumenRevision {
  total: number;
  ok: number;
  dudoso: number;
  cambiar: number;
  sin_apu: number;
  sin_veredicto: number;
}

/** Un componente propuesto, con todo lo que lo explica. Espejo del contrato de
 *  `apu_tool/dominio/composicion.py`. Ningún campo es monetario, a propósito. */
export interface ComponentePropuesto {
  codigo: string;
  tipo: "insumo" | "apu";
  funcion: string;              // "" = la IA no dijo un rol legible
  rendimiento: number;
  origen: string;
  referencias: { apu_codigo: string; turno: string }[];
  hipotesis: Record<string, unknown>;
  calculo: {
    operacion: string; numerador: number; denominador: number; resultado: number;
  } | null;
  justificacion: string;
  nivel_evidencia: "alto" | "medio" | "bajo";
  ref_shift: string;
}

export interface Hallazgo {
  codigo: string;
  mensaje: string;
  componente: string;           // "" = hallazgo del conjunto, no de una fila
}

export interface ValidacionComposicion {
  valido: boolean;
  errores: Hallazgo[];
  advertencias: Hallazgo[];
  metricas: { superadas: number; totales: number };
}

/** El nivel lo calcula la plataforma. `incertidumbre_declarada` (lo que el modelo
 *  dice de sí mismo) va aparte y NO influye: se muestra rotulada como dato suyo. */
export type NivelConfianza = "alta" | "media" | "baja" | "insuficiente";

export interface MotivoConfianza {
  senal: string;
  /** `detalle` y no `valor`: "valor" está en la denylist de privacidad del backend
   *  (por valor_unitario / valor_total) y el guardián mira nombres de clave. */
  detalle: string;
  aporte: number;
}

export type EstadoComposicion =
  | "generando" | "propuesta" | "editada" | "aprobada" | "rechazada" | "error";

export interface ComposicionVersion {
  corrida_id: number;
  seq: number;
  version: number;
  estado: EstadoComposicion;
  actividad: {
    item: string; descripcion: string; unidad: string; cantidad: number;
    shift: string;
  };
  ficha: null;                  // fase 2
  propuesta: {
    componentes: ComponentePropuesto[];
    supuestos: { campo: string; supuesto: string; impacto: string }[];
    incertidumbre_declarada: number;
    justificacion: string;
  } | null;
  validacion: ValidacionComposicion | null;
  confianza: NivelConfianza | null;
  confianza_motivos: MotivoConfianza[] | null;
  antecedentes: {
    codigos_permitidos: string[];
    apus_referencia: { codigo: string; turno: string }[];
  } | null;
  modelo: string | null;
  prompt_version: string | null;
  apu_codigo: string | null;
  apu_turno: string | null;
  autor: string | null;
  creada_en: string;
  motivo: string | null;
}

export interface VistaComposicion {
  vigente: ComposicionVersion | null;
  historial: ComposicionVersion[];
}

/** Un APU distinto por fila para aplicar sugerencias de la IA en un solo recosteo. */
export interface AsignacionIA {
  seq: number;
  apu_codigo: string;
  shift?: string;
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
  /** El costo lo puso una persona (igualado al contractual), no lo calculó el motor. */
  costo_manual: boolean;
  // Veredicto de la última revisión con IA, o null si esta fila no se revisó.
  revision: VeredictoIA | null;
}

/** Una línea tal como la leyó el Excel, antes de armarse. */
export interface LineaPreview {
  item: string;
  descripcion: string;
  unidad: string;
  cantidad: number;
  precio_contractual: number;
  shift: string;
  /** Presente solo en `duplicadas`: el seq de la línea que ya está en la corrida. */
  seq_existente?: number;
}

export interface PreviewLineas {
  total: number;
  nuevas: LineaPreview[];
  duplicadas: LineaPreview[];
  modo: string;
  tope: number;
}

/** Línea cargada a mano. `shift` vacío = el turno por defecto de la corrida. */
export interface LineaNueva {
  descripcion: string;
  unidad?: string;
  cantidad?: number;
  precio_contractual?: number;
  shift?: string;
  item?: string;
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
  apu_turno: string;
  apu_nombre: string;
  status: string;
  explicacion: string;
  candidatos: Candidato[];
  composicion: LineaComposicion[];
  costo_unitario: number;
  costo_manual: boolean;
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
  // true = no hay tarifa en la lista consultada. Distinto de un $0 genuino, que
  // la regla de negocio prohíbe y hay que seguir mostrando como $0.
  sin_precio: boolean;
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
  lista_precios_id: number | null;
  lista_nombre: string;
}

// Wrappers de respuesta

export interface StatusResponse {
  insumos: number;
  apus: number;
  ia: boolean;
}

export interface UsuarioEnLinea {
  email: string;
  nombre: string;
}

export interface PresenciaResponse {
  en_linea: UsuarioEnLinea[];
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
  lista_precios_id: number | null;
  lista_nombre: string;
  // Apaga el botón "Revisar con IA" cuando el servidor no tiene ANTHROPIC_API_KEY.
  ia_disponible: boolean;
  /** Solo con estado 'armando' o 'armado_detenido'; `null` si ya terminó de armarse. */
  armado: ProgresoArmado | null;
  /** Solo en la respuesta de `igualarCostoAlContractual`. */
  igualadas?: number[];
  /** Seqs con contractual ≤ 0: no se tocan (regla "nada en $0"). */
  rechazadas?: number[];
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

export interface ImportConflicto {
  codigo: string;
  nombre: string;
  turno?: string;   // solo en el import de APUs
  motivo: string;
}

export interface ImportInsumosUpsertPreview {
  crear: InsumoImportFila[];
  actualizar: CambioPreview[];
  ambigua: ImportAmbiguo[];
  no_encontrada: { codigo: string }[];
  invalida: InsumoImportFila[];
  conflicto?: ImportConflicto[];
}

export interface ImportUpsertResultado {
  creados: number;
  actualizados: number;
  errores: { codigo: string; error: string }[];
}

// ─── Autoría de la base — agregar insumos y APUs ───────────────────────────────

// Chequeo en vivo (mientras se escribe) del alta de insumo/APU: el mismo motivo
// que devolvería el 400 al guardar, la MISMA regla expuesta en dos formas.
export interface ConflictoAlta {
  campo: "codigo" | "nombre" | null;
  motivo: string | null;
}

export interface InsumoNuevo {
  codigo: string;
  nombre: string;
  unidad: string;
  grupo: string;
  precio: number;
  fuente: string;
  lista_id?: number | null;
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
  // Presente solo cuando el alta es una copia de otro APU: el backend hereda de
  // ahí el precio histórico de respaldo y las marcas de sub-APU.
  duplicado_de?: { codigo: string; turno: string };
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

// Fila candidata a crear / ya existente en una importación de insumos.
// `motivo`: solo presente en filas de `invalida` cuando el backend puede explicar
// por qué (p.ej. sin precio en el archivo y sin tarifa previa en la lista destino);
// ausente cuando la fila es inválida por no traer código.
export interface InsumoImportFila {
  codigo: string;
  nombre: string;
  unidad: string;
  grupo: string;
  precio: number;
  fuente: string;
  motivo?: string;
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
  conflicto?: ImportConflicto[];
  subapus: VinculoSubApu[];
}

export interface ImportResultado {
  creados: number;
  subapus_marcados?: number;
  errores: { codigo: string; turno?: string; error: string }[];
}
