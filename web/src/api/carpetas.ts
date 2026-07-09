import { apiGet, apiPost, apiPatch, apiDelete } from "@/api/client";
import type { Carpeta, CarpetaNodo, CorridaDetalle } from "@/lib/tipos";

export function listarCarpetas(): Promise<CarpetaNodo[]> {
  return apiGet<CarpetaNodo[]>("/carpetas");
}

export function crearCarpeta(nombre: string, parent_id: number | null): Promise<Carpeta> {
  return apiPost<Carpeta>("/carpetas", { nombre, parent_id });
}

export function renombrarCarpeta(id: number, nombre: string): Promise<Carpeta> {
  return apiPatch<Carpeta>(`/carpetas/${id}`, { nombre });
}

export function moverCarpeta(id: number, parent_id: number | null): Promise<Carpeta> {
  return apiPatch<Carpeta>(`/carpetas/${id}`, { parent_id, mover: true });
}

export function borrarCarpeta(id: number): Promise<void> {
  return apiDelete(`/carpetas/${id}`);
}

export function moverCorrida(corridaId: number, carpeta_id: number): Promise<CorridaDetalle> {
  return apiPost<CorridaDetalle>(`/corridas/${corridaId}/mover`, { carpeta_id });
}
