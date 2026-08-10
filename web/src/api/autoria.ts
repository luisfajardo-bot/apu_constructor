import { apiGet, apiPost, apiPut, apiDelete, descargarArchivo } from "@/api/client";
import type {
  Insumo,
  InsumoNuevo,
  ApuNuevo,
  ApuEditar,
  ApuResumen,
  ApuDetalle,
  ListaApus,
  ImportApusPreview,
  ImportResultado,
  ConflictoAlta,
} from "@/lib/tipos";

// ─── Insumos: crear individual ─────────────────────────────────────────────────

export function crearInsumo(body: InsumoNuevo): Promise<Insumo> {
  return apiPost<Insumo>("/insumos/crear", body);
}

// ─── APUs: listar, detalle, crear e importar ───────────────────────────────────

export interface ListarApusParams {
  q?: string;
  grupo?: string;
  turno?: string;
  limit?: number;
  offset?: number;
  codigo?: string;
  nombre?: string;
}

function buildQuery(params: ListarApusParams): string {
  const qs = new URLSearchParams();
  if (params.q !== undefined) qs.set("q", params.q);
  if (params.grupo !== undefined) qs.set("grupo", params.grupo);
  if (params.turno !== undefined) qs.set("turno", params.turno);
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  if (params.offset !== undefined) qs.set("offset", String(params.offset));
  if (params.codigo !== undefined) qs.set("codigo", params.codigo);
  if (params.nombre !== undefined) qs.set("nombre", params.nombre);
  const str = qs.toString();
  return str ? `?${str}` : "";
}

export function listarApus(params: ListarApusParams = {}): Promise<ListaApus> {
  return apiGet<ListaApus>(`/apus${buildQuery(params)}`);
}

export function getGruposApu(): Promise<string[]> {
  return apiGet<string[]>("/apus/grupos");
}

export function getApuDetalle(codigo: string, turno: string): Promise<ApuDetalle> {
  // `codigo` puede tener espacios (p.ej. "9593 N") → encodeURIComponent.
  return apiGet<ApuDetalle>(
    `/apus/${encodeURIComponent(codigo)}/${encodeURIComponent(turno)}`,
  );
}

export function crearApu(body: ApuNuevo): Promise<ApuResumen> {
  return apiPost<ApuResumen>("/apus/crear", body);
}

// Chequeo en vivo del alta: mismo endpoint que arma el 400 al guardar
// (ver `conflictoInsumo` en @/api/insumos: misma razón de ser).
export function conflictoApu(
  codigo: string,
  turno: string,
  nombre: string,
): Promise<ConflictoAlta> {
  return apiGet<ConflictoAlta>(`/apus/conflicto${buildQuery({ codigo, turno, nombre })}`);
}

export function editarApu(
  codigo: string,
  turno: string,
  body: ApuEditar,
): Promise<ApuResumen> {
  return apiPut<ApuResumen>(
    `/apus/${encodeURIComponent(codigo)}/${encodeURIComponent(turno)}`,
    body,
  );
}

export function borrarApu(codigo: string, turno: string): Promise<void> {
  return apiDelete(
    `/apus/${encodeURIComponent(codigo)}/${encodeURIComponent(turno)}`,
  );
}

export function previewImportarApus(form: FormData): Promise<ImportApusPreview> {
  return apiPost<ImportApusPreview>("/apus/importar/preview", form);
}

export function aplicarImportarApus(form: FormData): Promise<ImportResultado> {
  return apiPost<ImportResultado>("/apus/importar", form);
}

export function descargarPlantillaApus(): Promise<void> {
  return descargarArchivo("/apus/importar/plantilla", "plantilla_apus.xlsx");
}
