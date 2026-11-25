import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { chatConsultaStream } from "@/api/consulta";
import AvatarIngeniero, { type EstadoAvatar } from "@/components/composicion/AvatarIngeniero";
import type { MensajeChat, RespuestaConsulta } from "@/lib/tipos";

interface Entrada {
  id: number;
  rol: "usuario" | "agente";
  /** Lo que se muestra (con cifras, si es del agente). */
  texto: string;
  /** Solo del agente: el texto con MARCADORES. Es lo único que vuelve al servidor. */
  crudo?: string;
}

const CLAVE = "chat-consulta";
const MAX_HISTORIAL = 20;
const MAX_TEXTO = 1000;

function leerGuardado(): { hilo: Entrada[]; abierto: boolean } {
  try {
    const v = JSON.parse(sessionStorage.getItem(CLAVE) ?? "null");
    if (v && Array.isArray(v.hilo)) return { hilo: v.hilo, abierto: !!v.abierto };
  } catch {
    /* storage bloqueado o JSON roto: se arranca vacío */
  }
  return { hilo: [], abierto: false };
}

/** El historial NUNCA lleva las cifras: del agente viaja el `crudo`. Si no lo hay,
 *  viaja vacío y el servidor lo descarta. */
function paraHistorial(e: Entrada): MensajeChat {
  return { rol: e.rol, texto: e.rol === "agente" ? (e.crudo ?? "") : e.texto };
}

/** Chat de consulta: precios de insumos, costos de APUs y totales de corridas o
 *  capítulos. Vive en el Layout, así que sigue abierto al cambiar de página. */
export default function ChatConsulta({ iaDisponible }: { iaDisponible: boolean }) {
  const [guardado] = useState(leerGuardado);
  const [hilo, setHilo] = useState<Entrada[]>(guardado.hilo);
  const [abierto, setAbierto] = useState(guardado.abierto);
  const [texto, setTexto] = useState("");
  const [estado, setEstado] = useState<EstadoAvatar>("espera");
  const [linea, setLinea] = useState("");
  const [aviso, setAviso] = useState<string | null>(null);
  const proximoId = useRef(Math.max(0, ...guardado.hilo.map((e) => e.id)) + 1);
  const cancelar = useRef<AbortController | null>(null);
  const fin = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    try {
      sessionStorage.setItem(CLAVE, JSON.stringify({ hilo, abierto }));
    } catch {
      /* sin storage: el hilo vive solo en memoria */
    }
  }, [hilo, abierto]);

  useEffect(() => () => cancelar.current?.abort(), []);
  useEffect(() => fin.current?.scrollIntoView?.({ block: "end" }), [hilo, abierto]);

  const ocupado = estado === "pensando" || estado === "buscando";
  const visible: EstadoAvatar = iaDisponible ? estado : "deshabilitado";

  async function enviar() {
    const t = texto.trim();
    if (!t || ocupado || !iaDisponible) return;
    const idUsuario = proximoId.current++;
    const conMensaje: Entrada[] = [...hilo, { id: idUsuario, rol: "usuario", texto: t }];
    setHilo(conMensaje);
    setTexto("");
    setAviso(null);
    setEstado("pensando");
    setLinea("Pensando…");
    const control = new AbortController();
    cancelar.current = control;
    const res: { r: RespuestaConsulta | null; fallo: string | null; bloqueado: boolean } =
      { r: null, fallo: null, bloqueado: false };
    try {
      await chatConsultaStream(
        conMensaje.slice(-MAX_HISTORIAL).map(paraHistorial),
        (ev) => {
          const d = (ev.data ?? {}) as { consulta?: string; motivo?: string; detail?: string };
          if (ev.event === "pensando") {
            setEstado("pensando");
            setLinea("Pensando…");
          } else if (ev.event === "buscando") {
            setEstado("buscando");
            setLinea(`Buscando «${d.consulta ?? ""}»…`);
          } else if (ev.event === "respuesta") {
            res.r = ev.data as RespuestaConsulta;
          } else if (ev.event === "bloqueado" || ev.event === "error") {
            res.fallo = d.motivo ?? d.detail ?? "No pude responder, vuelve a intentar.";
            res.bloqueado = ev.event === "bloqueado";
          }
        },
        control.signal,
      );
    } catch (e) {
      res.fallo = e instanceof Error ? e.message : "No pude responder, vuelve a intentar.";
    }
    setLinea("");
    const r = res.r;
    if (r) {
      setHilo((h) => [...h, { id: proximoId.current++, rol: "agente", texto: r.texto, crudo: r.crudo }]);
      setEstado("espera");
    } else {
      // El mensaje vuelve a la caja: no se queda en el hilo algo que el agente no recibió.
      setHilo((h) => h.filter((x) => x.id !== idUsuario));
      setTexto(t);
      setAviso(res.fallo ?? "El agente no respondió. Vuelve a intentar.");
      setLinea(res.bloqueado ? "Mensaje bloqueado: trae un monto" : "No pude responder");
      setEstado("error");
    }
  }

  if (!abierto) {
    return (
      <button
        type="button"
        aria-label="Abrir el agente de consulta"
        title={iaDisponible ? "Pregúntale al agente por precios y totales"
          : "El agente no está disponible: falta ANTHROPIC_API_KEY en el servidor."}
        disabled={!iaDisponible}
        onClick={() => setAbierto(true)}
        className="fixed right-4 bottom-4 z-40 flex items-center gap-2 rounded-full border border-border bg-background py-1 pr-3 pl-1 text-xs text-foreground shadow-md hover:bg-muted disabled:opacity-50"
      >
        <AvatarIngeniero estado={visible} />
        Preguntar
      </button>
    );
  }

  return (
    <aside
      aria-label="Agente de consulta"
      className="fixed right-4 bottom-4 z-40 flex max-h-[75vh] w-[min(400px,calc(100vw-2rem))] flex-col gap-2 rounded border border-border bg-background p-3 shadow-lg"
    >
      <div className="flex items-center gap-2">
        <AvatarIngeniero estado={visible} />
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold text-foreground">Consulta</p>
          <p aria-live="polite" className="truncate text-[11px] text-muted-foreground">
            {iaDisponible ? linea || "Precios, costos y totales" : "No disponible"}
          </p>
        </div>
        {hilo.length > 0 && (
          <button
            type="button"
            disabled={ocupado}
            className="text-[11px] text-muted-foreground underline underline-offset-2 hover:text-foreground disabled:opacity-50"
            onClick={() => { setHilo([]); setAviso(null); }}
          >
            Limpiar
          </button>
        )}
        <button
          type="button"
          aria-label="Cerrar el agente de consulta"
          className="text-muted-foreground hover:text-foreground"
          onClick={() => setAbierto(false)}
        >
          <X className="size-4" />
        </button>
      </div>

      <div role="log" className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto">
        {hilo.length === 0 && (
          <p className="text-xs text-muted-foreground">
            {"Pregúntame por el precio de un insumo, el costo de un APU o los totales de "
              + "una licitación. Por ejemplo: «¿cuánto vale la tubería PVC de 6\"?» o "
              + "«¿cuál es el total de redes húmedas de la Calle 13?». Las cifras las pone "
              + "el sistema: yo no las veo."}
          </p>
        )}
        {hilo.map((e) => (
          <div key={e.id} className={e.rol === "usuario" ? "self-end text-right" : ""}>
            <p
              className={
                "whitespace-pre-wrap text-xs "
                + (e.rol === "usuario"
                  ? "rounded bg-muted px-2 py-1 text-foreground"
                  : "text-foreground")
              }
            >
              {e.texto}
            </p>
          </div>
        ))}
        <div ref={fin} />
      </div>

      {aviso && (
        <p role="alert" className="border-l-2 border-destructive bg-destructive-surface px-2 py-1 text-xs text-destructive">
          {aviso}
        </p>
      )}

      <div className="flex flex-col gap-1">
        <textarea
          aria-label="Pregunta para el agente"
          rows={2}
          maxLength={MAX_TEXTO}
          value={texto}
          disabled={!iaDisponible || ocupado}
          placeholder="Escribe tu pregunta… (Enter envía, Shift+Enter baja de línea)"
          className="w-full resize-y rounded border border-border bg-transparent px-2 py-1 text-xs outline-none focus-visible:border-ring disabled:opacity-50"
          onChange={(ev) => setTexto(ev.target.value)}
          onKeyDown={(ev) => {
            if (ev.key === "Enter" && !ev.shiftKey) {
              ev.preventDefault();
              void enviar();
            }
          }}
        />
        <div className="flex justify-end">
          <Button size="sm" disabled={!iaDisponible || ocupado || !texto.trim()}
                  onClick={() => void enviar()}>
            {ocupado ? "Esperando…" : "Enviar"}
          </Button>
        </div>
      </div>
    </aside>
  );
}
