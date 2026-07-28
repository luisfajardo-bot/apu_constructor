import { apiGet, apiPost, apiPatch } from "@/api/client";
import type { ListaPrecios } from "@/lib/tipos";

export function listarListas(): Promise<ListaPrecios[]> {
  return apiGet<ListaPrecios[]>("/listas-precios");
}

export function crearLista(nombre: string): Promise<ListaPrecios> {
  return apiPost<ListaPrecios>("/listas-precios", { nombre });
}

export function renombrarLista(id: number, nombre: string): Promise<ListaPrecios> {
  return apiPatch<ListaPrecios>(`/listas-precios/${id}`, { nombre });
}
