import { apiGet, apiPost } from "@/api/client";
import type {
  ListaInsumos,
  InsumoDetalle,
  CambiosAplicados,
  ImportarPreviewResponse,
  TransformarPreviewResponse,
} from "@/lib/tipos";

export interface ListarInsumosParams {
  q?: string;
  grupo?: string;
  fuente?: string;
  clasificacion?: string;
  limit?: number;
  offset?: number;
}

function buildQuery(params: ListarInsumosParams): string {
  const qs = new URLSearchParams();
  if (params.q !== undefined) qs.set("q", params.q);
  if (params.grupo !== undefined) qs.set("grupo", params.grupo);
  if (params.fuente !== undefined) qs.set("fuente", params.fuente);
  if (params.clasificacion !== undefined) qs.set("clasificacion", params.clasificacion);
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  if (params.offset !== undefined) qs.set("offset", String(params.offset));
  const str = qs.toString();
  return str ? `?${str}` : "";
}

export function listarInsumos(params: ListarInsumosParams = {}): Promise<ListaInsumos> {
  return apiGet<ListaInsumos>(`/insumos${buildQuery(params)}`);
}

export function getGrupos(): Promise<string[]> {
  return apiGet<string[]>("/insumos/grupos");
}

export function getFuentes(): Promise<string[]> {
  return apiGet<string[]>("/insumos/fuentes");
}

export function getInsumo(id: number): Promise<InsumoDetalle> {
  return apiGet<InsumoDetalle>(`/insumos/${id}`);
}

export interface CambioInput {
  insumo_id: number;
  precio: number;
  fuente: string;
}

export function aplicarCambios(cambios: CambioInput[]): Promise<CambiosAplicados> {
  return apiPost<CambiosAplicados>("/insumos/cambios", { cambios });
}

export function importarPreview(form: FormData): Promise<ImportarPreviewResponse> {
  return apiPost<ImportarPreviewResponse>("/insumos/importar/preview", form);
}

export interface TransformarBody {
  filtro: unknown;
  operacion: unknown;
}

export function transformarPreview(body: TransformarBody): Promise<TransformarPreviewResponse> {
  return apiPost<TransformarPreviewResponse>("/insumos/transformar/preview", body);
}
