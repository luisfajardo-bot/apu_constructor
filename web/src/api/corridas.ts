import { apiGet, apiPost, apiDelete } from "@/api/client";
import type {
  StatusResponse,
  CorridaCreada,
  CorridaDetalle,
  CorridaResumen,
  DetalleItem,
  Progreso,
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

export function listarCorridas(): Promise<CorridaResumen[]> {
  return apiGet<CorridaResumen[]>("/corridas");
}

export function eliminarCorrida(id: number): Promise<void> {
  return apiDelete(`/corridas/${id}`);
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

export function parseSse(block: string): { event: string; data: unknown } | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return null;
  try {
    return { event, data: JSON.parse(dataLines.join("\n")) };
  } catch {
    return null;
  }
}

async function streamCorrida(
  path: string,
  init: RequestInit,
  onProgress: (p: Progreso) => void,
): Promise<CorridaCreada> {
  const r = await fetch("/api" + path, init);
  if (!r.ok || !r.body) {
    const err = await r.json().catch(() => ({}) as { detail?: string });
    throw new Error(err.detail || r.statusText);
  }
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let done: CorridaCreada | null = null;
  for (;;) {
    const { value, done: fin } = await reader.read();
    if (fin) break;
    buf += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const ev = parseSse(buf.slice(0, idx));
      buf = buf.slice(idx + 2);
      if (!ev) continue;
      if (ev.event === "progress") onProgress(ev.data as Progreso);
      else if (ev.event === "done") done = ev.data as CorridaCreada;
      else if (ev.event === "error")
        throw new Error((ev.data as { detail?: string }).detail || "Error al armar");
    }
  }
  if (!done) throw new Error("La corrida no terminó correctamente.");
  return done;
}

export function crearCorridaStream(form: FormData, onProgress: (p: Progreso) => void) {
  return streamCorrida("/corridas/stream", { method: "POST", body: form }, onProgress);
}

export function crearSampleStream(onProgress: (p: Progreso) => void) {
  return streamCorrida("/sample/stream", { method: "POST" }, onProgress);
}
