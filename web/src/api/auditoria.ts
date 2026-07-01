import { apiGet } from "@/api/client";

export type EventoAuditoria = {
  id: number;
  ts: string;
  user_id: string | null;
  user_email: string | null;
  rol: string;
  accion: string;
  entidad_tipo: string;
  entidad_id: string;
  antes: Record<string, unknown> | null;
  despues: Record<string, unknown> | null;
  contexto: Record<string, unknown> | null;
};

export type AuditoriaFiltros = {
  user_id?: string;
  accion?: string;
  entidad_tipo?: string;
  desde?: string;
  hasta?: string;
  lote_id?: string;
  limit?: number;
  offset?: number;
};

export type AuditoriaPagina = {
  items: EventoAuditoria[];
  total: number;
  limit: number;
  offset: number;
};

export function listarAuditoria(f: AuditoriaFiltros = {}): Promise<AuditoriaPagina> {
  const qs = new URLSearchParams();
  Object.entries(f).forEach(([k, v]) => {
    if (v !== undefined && v !== "" && v !== null) qs.set(k, String(v));
  });
  const q = qs.toString();
  return apiGet<AuditoriaPagina>(`/auditoria${q ? `?${q}` : ""}`);
}
