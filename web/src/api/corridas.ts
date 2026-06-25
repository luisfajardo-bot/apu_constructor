import { apiGet, apiPost } from "@/api/client";
import type {
  StatusResponse,
  CorridaCreada,
  CorridaDetalle,
  DetalleItem,
} from "@/lib/tipos";

export function getStatus(): Promise<StatusResponse> {
  return apiGet<StatusResponse>("/status");
}

export function crearSample(): Promise<CorridaCreada> {
  return apiPost<CorridaCreada>("/sample");
}

export function crearCorrida(form: FormData): Promise<CorridaCreada> {
  return apiPost<CorridaCreada>("/corridas", form);
}

export function getCorrida(id: number): Promise<CorridaDetalle> {
  return apiGet<CorridaDetalle>(`/corridas/${id}`);
}

export function getItem(id: number, seq: number): Promise<DetalleItem> {
  return apiGet<DetalleItem>(`/corridas/${id}/items/${seq}`);
}

export function confirmar(
  id: number,
  seq: number,
  apu_codigo: string,
  shift?: string,
): Promise<CorridaDetalle> {
  return apiPost<CorridaDetalle>(`/corridas/${id}/items/${seq}/confirmar`, {
    apu_codigo,
    ...(shift !== undefined ? { shift } : {}),
  });
}

/** Devuelve la URL para abrir/descargar el cuadro xlsx en una nueva pestaña. */
export function descargarCuadroUrl(id: number): string {
  return `/api/corridas/${id}/cuadro`;
}
