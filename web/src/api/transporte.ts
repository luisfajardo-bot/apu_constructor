import { apiGet, apiPost, apiPut, apiDelete } from "@/api/client";
import type {
  AjusteProyecto, ClaseTransporteIn, ListaClasificacion, ParametrosTransporte,
  VistaTransporte,
} from "@/lib/tipos";

export function verTransporte(carpetaId: number): Promise<VistaTransporte> {
  return apiGet<VistaTransporte>(`/carpetas/${carpetaId}/transporte`);
}

export function guardarTransporte(
  carpetaId: number, params: Partial<ParametrosTransporte>,
): Promise<VistaTransporte> {
  return apiPut<VistaTransporte>(`/carpetas/${carpetaId}/transporte`, params);
}

export function listarComponentes(): Promise<ListaClasificacion> {
  return apiGet<ListaClasificacion>("/transporte/componentes");
}

export function clasificar(filas: ClaseTransporteIn[]): Promise<{ aplicados: number }> {
  return apiPut<{ aplicados: number }>("/transporte/componentes", { filas });
}

export function listarAjustes(carpetaId: number): Promise<AjusteProyecto[]> {
  return apiGet<AjusteProyecto[]>(`/carpetas/${carpetaId}/ajustes`);
}

export function crearAjuste(
  carpetaId: number, ajuste: AjusteProyecto,
): Promise<AjusteProyecto> {
  return apiPost<AjusteProyecto>(`/carpetas/${carpetaId}/ajustes`, ajuste);
}

export function borrarAjuste(carpetaId: number, ajusteId: number): Promise<void> {
  return apiDelete(`/carpetas/${carpetaId}/ajustes/${ajusteId}`);
}
