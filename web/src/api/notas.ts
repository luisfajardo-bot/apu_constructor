import { apiDelete, apiGet, apiPatch, apiPost } from "@/api/client";
import type { DuenoNota, Nota, NotasPagina } from "@/lib/tipos";

function qs(p: Record<string, string | number | undefined>): string {
  const s = new URLSearchParams();
  for (const [k, v] of Object.entries(p)) if (v !== undefined && v !== "") s.set(k, String(v));
  return s.toString();
}

export const listarNotas = (d: DuenoNota) =>
  apiGet<Nota[]>(`/notas?${qs({ ...d })}`);

export const crearNota = (d: DuenoNota, texto: string) =>
  apiPost<Nota>("/notas", { ...d, texto });

export const editarNota = (id: number, texto: string) =>
  apiPatch<Nota>(`/notas/${id}`, { texto });

export const borrarNota = (id: number) => apiDelete(`/notas/${id}`);

export const listarTodasNotas = (p: {
  entidad?: string; autor?: string; q?: string; limit?: number; offset?: number;
}) => apiGet<NotasPagina>(`/notas/todas?${qs(p)}`);
