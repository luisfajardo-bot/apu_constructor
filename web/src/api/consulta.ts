import { consumirSse } from "@/api/corridas";
import type { MensajeChat } from "@/lib/tipos";

/** Chat de consulta (SSE). Eventos: `pensando`, `buscando` {herramienta, consulta},
 *  `respuesta` (RespuestaConsulta), `bloqueado` {motivo}, `error` {detail}.
 *  No persiste nada. */
export function chatConsultaStream(
  mensajes: MensajeChat[],
  onEvent: (e: { event: string; data: unknown }) => void,
  signal?: AbortSignal,
): Promise<void> {
  return consumirSse(
    "/consulta/chat",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mensajes }),
      signal,
    },
    onEvent,
  );
}
