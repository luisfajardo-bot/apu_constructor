import { apiGet, apiPost, apiDelete, authHeader, descargarArchivo, mensajeDeError } from "@/api/client";
import type {
  AsignacionIA,
  ComposicionPropuesta,
  StatusResponse,
  CorridaCreada,
  CorridaDetalle,
  CorridaIniciada,
  CorridaResumen,
  DetalleItem,
  LineaNueva,
  PreviewLineas,
  Progreso,
  ProgresoRevision,
  ResumenRevision,
  VeredictoIA,
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

export function renombrarCorrida(id: number, nombre: string): Promise<CorridaDetalle> {
  return apiPost<CorridaDetalle>(`/corridas/${id}/renombrar`, { nombre });
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

/** Confirma varias líneas de una vez. Sin `apu_codigo`, cada línea confirma el APU
 *  que ya tiene. Devuelve la corrida recosteada (misma forma que `confirmar`). */
export function confirmarLote(
  id: number,
  seqs: number[],
  apu_codigo?: string,
  shift?: string,
): Promise<CorridaDetalle> {
  return apiPost<CorridaDetalle>(`/corridas/${id}/items/confirmar-lote`, {
    seqs,
    ...(apu_codigo !== undefined ? { apu_codigo } : {}),
    ...(shift !== undefined ? { shift } : {}),
  });
}

/** Aplica N sugerencias de la IA en un solo recosteo: un APU (y turno) distinto
 *  por fila. Devuelve la corrida recosteada (misma forma que `confirmar`). */
export function aplicarSugerencias(
  id: number,
  asignaciones: AsignacionIA[],
): Promise<CorridaDetalle> {
  return apiPost<CorridaDetalle>(`/corridas/${id}/items/confirmar-lote`, {
    seqs: [],
    asignaciones,
  });
}

/** Propone una composición para una fila `sin_apu`. No persiste nada: crear el
 *  APU sigue siendo el alta normal, con sus validaciones de duplicados. */
export function componerItem(id: number, seq: number): Promise<ComposicionPropuesta> {
  return apiPost<ComposicionPropuesta>(`/corridas/${id}/componer/${seq}`);
}

/** Qué se agregaría con este Excel (y qué ya está en la corrida). No escribe. */
export function previewLineas(id: number, form: FormData): Promise<PreviewLineas> {
  return apiPost<PreviewLineas>(`/corridas/${id}/items/preview`, form);
}

/** Agrega a la corrida las líneas del Excel. Devuelve la corrida recosteada. */
export function importarLineas(id: number, form: FormData): Promise<CorridaDetalle> {
  return apiPost<CorridaDetalle>(`/corridas/${id}/items/importar`, form);
}

/** Agrega líneas cargadas a mano. Devuelve la corrida recosteada. */
export function agregarLineas(id: number, lineas: LineaNueva[]): Promise<CorridaDetalle> {
  return apiPost<CorridaDetalle>(`/corridas/${id}/items`, { lineas });
}

/** Borra las líneas indicadas. No renumera: los seq que quedan no cambian. */
export function borrarLineas(id: number, seqs: number[]): Promise<CorridaDetalle> {
  return apiPost<CorridaDetalle>(`/corridas/${id}/items/borrar`, { seqs });
}

export function congelarCorrida(id: number): Promise<CorridaDetalle> {
  return apiPost<CorridaDetalle>(`/corridas/${id}/congelar`);
}

export function activarCorrida(id: number): Promise<CorridaDetalle> {
  return apiPost<CorridaDetalle>(`/corridas/${id}/activar`);
}

/** Descarga el cuadro xlsx con el token Bearer (una navegación normal no lleva el header). */
export const descargarCuadro = (id: number) =>
  descargarArchivo(`/corridas/${id}/cuadro`, `cuadro_corrida_${id}.xlsx`);

export function descargarPlantillaLicitacion(): Promise<void> {
  return descargarArchivo("/corridas/plantilla", "plantilla_licitacion.xlsx");
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

/** Abre un SSE en `path` y llama a `onEvent` por cada evento parseado. Es el fetch +
 *  auth + chequeo de 401/ok + bucle de lectura del stream, compartido entre
 *  `streamCorrida` (armado) y `revisarCorridaStream` (revisión con IA): cada
 *  consumidor decide qué hacer con cada evento, incluyendo cuándo terminar
 *  (lanzar acá dentro de `onEvent` rechaza la promesa de afuera, tal cual antes). */
async function consumirSse(
  path: string,
  init: RequestInit,
  onEvent: (ev: { event: string; data: unknown }) => void,
): Promise<void> {
  const r = await fetch("/api" + path, {
    ...init,
    headers: { ...(init.headers || {}), ...(await authHeader()) },
  });
  if (r.status === 401) {
    const { supabase } = await import("@/lib/supabase");
    await supabase.auth.signOut();
    throw new Error("Sesión expirada.");
  }
  if (!r.ok || !r.body) {
    throw new Error(mensajeDeError(await r.json().catch(() => null), r.statusText));
  }
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done: fin } = await reader.read();
    if (fin) break;
    buf += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const ev = parseSse(buf.slice(0, idx));
      buf = buf.slice(idx + 2);
      if (ev) onEvent(ev);
    }
  }
}

async function streamCorrida(
  path: string,
  init: RequestInit,
  onProgress: (p: Progreso) => void,
  onStarted?: (c: CorridaIniciada) => void,
): Promise<CorridaCreada> {
  let done: CorridaCreada | null = null;
  await consumirSse(path, init, (ev) => {
    if (ev.event === "started") onStarted?.(ev.data as CorridaIniciada);
    else if (ev.event === "progress") onProgress(ev.data as Progreso);
    else if (ev.event === "done") done = ev.data as CorridaCreada;
    else if (ev.event === "error")
      throw new Error(mensajeDeError(ev.data, "Error al armar"));
  });
  if (!done) throw new Error("La corrida no terminó correctamente.");
  return done;
}

export function crearCorridaStream(
  form: FormData,
  onProgress: (p: Progreso) => void,
  onStarted?: (c: CorridaIniciada) => void,
) {
  return streamCorrida("/corridas/stream", { method: "POST", body: form }, onProgress, onStarted);
}

export function crearSampleStream(
  onProgress: (p: Progreso) => void,
  onStarted?: (c: CorridaIniciada) => void,
) {
  return streamCorrida("/sample/stream", { method: "POST" }, onProgress, onStarted);
}

/** Audita la corrida con IA (barrido + profundización). La IA propone; nunca aplica.
 *  `onVeredicto` llega una vez por fila con veredicto (evento 'veredicto'); `onProgreso`
 *  es opcional y avisa el arranque ('started', con el total), cada lote del triaje
 *  ('barriendo' — el barrido de una corrida grande son varias llamadas seguidas a la
 *  IA, y sin este evento el stream se ve mudo un buen rato) y el fin del triaje
 *  ('barrido', con cuántas filas quedaron marcadas y cuáles no contestaron). Resuelve
 *  con el resumen del evento 'done'; un stream que corta sin 'done', o un evento
 *  'error', rechaza la promesa. */
export async function revisarCorridaStream(
  id: number,
  onVeredicto: (v: VeredictoIA) => void,
  onProgreso?: (p: ProgresoRevision) => void,
): Promise<ResumenRevision> {
  let resumen: ResumenRevision | null = null;
  await consumirSse(`/corridas/${id}/revision/stream`, { method: "POST" }, (ev) => {
    if (ev.event === "veredicto") {
      onVeredicto((ev.data as { veredicto: VeredictoIA }).veredicto);
    } else if (ev.event === "started") {
      onProgreso?.({ evento: "started", ...(ev.data as { total: number; lotes?: number }) });
    } else if (ev.event === "barriendo") {
      onProgreso?.({ evento: "barriendo", ...(ev.data as { lote: number; lotes: number }) });
    } else if (ev.event === "barrido") {
      onProgreso?.({
        evento: "barrido",
        ...(ev.data as { revisar: number; sin_respuesta: number[] }),
      });
    } else if (ev.event === "done") {
      resumen = ev.data as ResumenRevision;
    } else if (ev.event === "error") {
      throw new Error(mensajeDeError(ev.data, "Error al revisar"));
    }
  });
  if (!resumen) throw new Error("La revisión no terminó correctamente.");
  return resumen;
}
