import { apiGet, apiPost, descargarArchivo } from "@/api/client";
import type {
  ListaInsumos,
  InsumoDetalle,
  CambiosAplicados,
  ImportInsumosUpsertPreview,
  ImportUpsertResultado,
} from "@/lib/tipos";

export interface ListarInsumosParams {
  q?: string;
  grupo?: string;
  fuente?: string;
  clasificacion?: string;
  limit?: number;
  offset?: number;
  lista?: number;
  sin_precio?: boolean;
}

function buildQuery(params: ListarInsumosParams): string {
  const qs = new URLSearchParams();
  if (params.q !== undefined) qs.set("q", params.q);
  if (params.grupo !== undefined) qs.set("grupo", params.grupo);
  if (params.fuente !== undefined) qs.set("fuente", params.fuente);
  if (params.clasificacion !== undefined) qs.set("clasificacion", params.clasificacion);
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  if (params.offset !== undefined) qs.set("offset", String(params.offset));
  if (params.lista !== undefined) qs.set("lista", String(params.lista));
  if (params.sin_precio) qs.set("sin_precio", "true");
  const str = qs.toString();
  return str ? `?${str}` : "";
}

export function listarInsumos(params: ListarInsumosParams = {}): Promise<ListaInsumos> {
  return apiGet<ListaInsumos>(`/insumos${buildQuery(params)}`);
}

export function getGrupos(): Promise<string[]> {
  return apiGet<string[]>("/insumos/grupos");
}

export function getFuentes(lista?: number): Promise<string[]> {
  return apiGet<string[]>(`/insumos/fuentes${lista !== undefined ? `?lista=${lista}` : ""}`);
}

export function getInsumo(id: number, lista?: number): Promise<InsumoDetalle> {
  return apiGet<InsumoDetalle>(`/insumos/${id}${lista !== undefined ? `?lista=${lista}` : ""}`);
}

export interface CambioInput {
  insumo_id: number;
  precio: number;
  fuente: string;
}

export function aplicarCambios(cambios: CambioInput[], lista_id?: number): Promise<CambiosAplicados> {
  return apiPost<CambiosAplicados>("/insumos/cambios", { cambios, lista_id: lista_id ?? null });
}

export function previewImportarInsumos(form: FormData): Promise<ImportInsumosUpsertPreview> {
  return apiPost<ImportInsumosUpsertPreview>("/insumos/importar/preview", form);
}

export function aplicarImportarInsumos(form: FormData): Promise<ImportUpsertResultado> {
  return apiPost<ImportUpsertResultado>("/insumos/importar", form);
}

export function descargarPlantillaInsumos(): Promise<void> {
  return descargarArchivo("/insumos/importar/plantilla", "plantilla_insumos.xlsx");
}
