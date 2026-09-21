import { apiGet, apiPost, apiDelete, authHeader, descargarArchivo, mensajeDeError, ErrorApi } from "@/api/client";
import type {
  AsignacionIA,
  StatusResponse,
  CorridaDetalle,
  CorridaEncolada,
  CorridaResumen,
  DetalleItem,
  LineaNueva,
  PreviaPresupuesto,
  PreviewLineas,
  ProgresoRevision,
  RebusquedaPrevia,
  ResumenRevision,
  VeredictoIA,
} from "@/lib/tipos";

export function getStatus(): Promise<StatusResponse> {
  return apiGet<StatusResponse>("/status");
}

/** Encola el ejemplo. Vuelve en el acto: `estado` llega en 'armando' y lo que se ve
 *  después sale del poll de `getCorrida`, no de esta respuesta. */
export function crearSample(): Promise<CorridaEncolada> {
  return apiPost<CorridaEncolada>("/sample");
}

/** Encola el armado del archivo subido. Vuelve en el acto (armar 1900 líneas lleva
 *  horas y no cabe en una petición HTTP); el progreso sale del poll de `getCorrida`.
 *  Rebota con 409 si ya hay un armado a medias del mismo archivo en la misma carpeta:
 *  ese error trae el id, y `corridaEnCurso` lo saca. */
export function crearCorrida(form: FormData): Promise<CorridaEncolada> {
  return apiPost<CorridaEncolada>("/corridas", form);
}

/** Qué se detectó en el archivo, SIN crear nada. El navegador se queda con el archivo
 *  y lo reenvía al aprobar: no hay borrador en el servidor que expirar ni limpiar. */
export function previsualizarCorrida(form: FormData): Promise<PreviaPresupuesto> {
  return apiPost<PreviaPresupuesto>("/corridas/previsualizar", form);
}

/** Devuelve a la cola una corrida en `armado_detenido` (rol editor). Lo ya armado se
 *  conserva: el worker entra donde quedó. */
export function reanudarArmado(id: number): Promise<CorridaDetalle> {
  return apiPost<CorridaDetalle>(`/corridas/${id}/reanudar`);
}

/** El id de la corrida que YA se está armando, si `e` es el 409 del doble clic.
 *  `null` para cualquier otro error — incluido un 409 de otra cosa, que no trae id.
 *
 *  Existe porque ese 409 no es un error del usuario: es el mismo armado que acaba de
 *  pedir. Con el id se lo lleva ahí; sin él, el doble clic termina en un cartel rojo. */
export function corridaEnCurso(e: unknown): number | null {
  if (!(e instanceof ErrorApi) || e.status !== 409) return null;
  const id = (e.detail as { corrida_id?: unknown } | null)?.corrida_id;
  return typeof id === "number" ? id : null;
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

/** Copia el precio contractual de cada línea marcada como su costo unitario.
 *  Para proyectos especiales: valen lo que dice el contrato y armarles el APU no paga.
 *  Devuelve la corrida recosteada (misma forma que `confirmarLote`) más `igualadas`
 *  y `rechazadas` (las de contractual ≤ 0, que no se tocan). */
export function igualarCostoAlContractual(
  id: number,
  seqs: number[],
): Promise<CorridaDetalle> {
  return apiPost<CorridaDetalle>(`/corridas/${id}/igualar-costo`, { seqs });
}

/** Iguala al contractual las líneas en $0 cuyo TOTAL contractual no pase el umbral.
 *  `seqs` son las que el usuario dejó marcadas en la previa; el servidor recalcula
 *  la candidatura y devuelve en `salteadas` las que ya no correspondían. */
export function igualarPorUmbral(
  id: number,
  umbral: number,
  seqs: number[],
): Promise<CorridaDetalle> {
  return apiPost<CorridaDetalle>(`/corridas/${id}/igualar-umbral`, {
    umbral_contractual: umbral,
    seqs,
  });
}

/** Borra el costo puesto a mano de las líneas marcadas: vuelven al costeo normal.
 *  Es el reverso de `igualarCostoAlContractual` y de `igualarPorUmbral`. */
export function quitarCostoManual(
  id: number,
  seqs: number[],
): Promise<CorridaDetalle> {
  return apiPost<CorridaDetalle>(`/corridas/${id}/quitar-costo-manual`, { seqs });
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

/** Qué cambiaría si se volviera a matchear la corrida contra la biblioteca de hoy.
 *  NO escribe: propone. */
export function rebuscarApus(id: number): Promise<RebusquedaPrevia> {
  return apiPost<RebusquedaPrevia>(`/corridas/${id}/rebuscar`, {});
}

/** Aplica la re-búsqueda a las líneas marcadas, en un solo recosteo. El servidor
 *  recalcula la propuesta: las que ya no estén vigentes vuelven en `salteadas`. */
export function aplicarRebusqueda(
  id: number,
  seqs: number[],
): Promise<CorridaDetalle> {
  return apiPost<CorridaDetalle>(`/corridas/${id}/rebuscar/aplicar`, { seqs });
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
 *  auth + chequeo de 401/ok + bucle de lectura del stream que usa `revisarCorridaStream`
 *  (revisión con IA): el consumidor decide qué hacer con cada evento, incluyendo cuándo
 *  terminar (lanzar acá dentro de `onEvent` rechaza la promesa de afuera). */
export async function consumirSse(
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
