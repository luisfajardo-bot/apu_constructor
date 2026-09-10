import { apiGet, apiPost, apiPut } from "./client";
import { consumirSse } from "./corridas";
import type { ComponentePropuesto, VistaComposicion } from "@/lib/tipos";

/** La versión vigente y el historial. Es lo que hace que recargar la página
 *  funcione: la propuesta vive en la base, no en el estado del navegador. */
export function getComposicion(id: number, seq: number): Promise<VistaComposicion> {
  return apiGet<VistaComposicion>(`/corridas/${id}/composicion/${seq}`);
}

/** Guarda la edición humana. `versionBase` es la versión sobre la que se trabajó:
 *  si alguien se adelantó, el servidor devuelve 409 en vez de pisarla. */
export function guardarComposicion(
  id: number,
  seq: number,
  versionBase: number,
  componentes: ComponentePropuesto[],
  supuestosConfirmados: boolean,
): Promise<VistaComposicion> {
  return apiPut<VistaComposicion>(`/corridas/${id}/composicion/${seq}`, {
    version_base: versionBase,
    componentes,
    supuestos_confirmados: supuestosConfirmados,
  });
}

export interface IdentidadApu {
  version_base: number;
  codigo: string;
  turno: string;
  nombre: string;
  grupo: string;
  unidad: string;
}

/** Crea el APU por el alta de siempre y lo asigna a la fila. La IA nunca escribe en
 *  la biblioteca: este endpoint lo dispara una persona. */
export function aprobarComposicion(
  id: number, seq: number, identidad: IdentidadApu,
): Promise<VistaComposicion> {
  return apiPost<VistaComposicion>(
    `/corridas/${id}/composicion/${seq}/aprobar`, identidad);
}

export function rechazarComposicion(
  id: number, seq: number, versionBase: number, motivo: string,
): Promise<VistaComposicion> {
  return apiPost<VistaComposicion>(`/corridas/${id}/composicion/${seq}/rechazar`, {
    version_base: versionBase,
    motivo,
  });
}

/** La forma que entrega `consumirSse`: `event` y `data`, en inglés. Es el contrato
 *  que ya consume `revisarCorridaStream`. */
export interface EventoComposicion {
  event: string;
  data: unknown;
}

/** Genera la propuesta por SSE. Si la conexión se corta, la propuesta igual quedó
 *  guardada: recargar la página la levanta. */
export function generarComposicionStream(
  id: number,
  seq: number,
  onEvent: (e: EventoComposicion) => void,
): Promise<void> {
  return consumirSse(
    `/corridas/${id}/composicion/${seq}/stream`, { method: "POST" }, onEvent);
}
