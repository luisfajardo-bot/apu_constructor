import { apiDelete, apiGet, apiPatch, apiPost } from "@/api/client";
import type { DuenoNota, Mencion, Mencionable, Nota, NotasPagina } from "@/lib/tipos";

function qs(p: Record<string, string | number | undefined>): string {
  const s = new URLSearchParams();
  for (const [k, v] of Object.entries(p)) if (v !== undefined && v !== "") s.set(k, String(v));
  return s.toString();
}

export const listarNotas = (d: DuenoNota) =>
  apiGet<Nota[]>(`/notas?${qs({ ...d })}`);

export const crearNota = (d: DuenoNota, texto: string, menciones: string[] = [], respondeA?: number) =>
  apiPost<Nota>("/notas", respondeA === undefined
    ? { ...d, texto, menciones }
    : { ...d, texto, menciones, responde_a: respondeA });

export const editarNota = (id: number, texto: string, menciones?: string[]) =>
  apiPatch<Nota>(`/notas/${id}`, menciones === undefined ? { texto } : { texto, menciones });

export const listarMencionables = () => apiGet<Mencionable[]>("/usuarios/mencionables");

export const listarMenciones = () => apiGet<Mencion[]>("/menciones");

export const marcarMencionLeida = (notaId: number) =>
  apiPost<{ leida: number }>(`/menciones/${notaId}/leida`);

export const marcarMencionesLeidas = () => apiPost<{ leidas: boolean }>("/menciones/leidas");

export const borrarNota = (id: number) => apiDelete(`/notas/${id}`);

export const listarTodasNotas = (p: {
  entidad?: string; autor?: string; q?: string; limit?: number; offset?: number;
}) => apiGet<NotasPagina>(`/notas/todas?${qs(p)}`);
