import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { chatComposicionStream } from "@/api/composicion";
import AvatarIngeniero, { type EstadoAvatar } from "./AvatarIngeniero";
import type {
  CambioAgente,
  ComponentePropuesto,
  MensajeChat,
  RespuestaAgente,
} from "@/lib/tipos";

type EstadoBloque = "pendiente" | "aplicando" | "aplicado" | "descartado";

interface Entrada {
  id: number;
  rol: "usuario" | "agente";
  texto: string;
  respuesta?: RespuestaAgente;
  /** El mensaje del usuario que originó esta respuesta: viaja como rastro al aplicar. */
  instruccion?: string;
  estado?: EstadoBloque;
  conflictos?: string[];
}

interface Props {
  corridaId: number;
  seq: number;
  /** La tabla tal como está en pantalla, sin guardar incluido: es lo que ve el agente. */
  componentes: ComponentePropuesto[];
  /** Motivo por el que el agente no está disponible, o null. */
  deshabilitado: string | null;
  /** Aplica los cambios (tabla + PUT). Devuelve los conflictos, si hubo. */
  onAplicar: (cambios: CambioAgente[], instruccion: string) => Promise<string[]>;
}

const num = (n: number) =>
  Number.isFinite(n) ? n.toLocaleString("es-CO", { maximumFractionDigits: 4 }) : "—";

const SIGNO = { agregar: "+", modificar: "~", quitar: "−" } as const;

/** El servidor recorta a 20 igual; mandar más solo arriesga el 422 del tope del
 *  cuerpo (100 mensajes) y dejaría el chat muerto hasta recargar. */
const MAX_HISTORIAL = 20;
const MAX_TEXTO = 1000;

/** Lo que viaja como turno del agente: su texto más un resumen de lo que propuso y
 *  qué pasó con eso. Sin esto, «sí, pero bájale al segundo» llega sin contexto. Los
 *  rendimientos van con coma decimal y sin separador de miles: un «1.125» parecería
 *  un monto al detector del servidor y el turno viajaría omitido. */
function paraHistorial(e: Entrada): MensajeChat {
  const r = e.respuesta;
  if (e.rol !== "agente" || !r || r.cambios.length === 0) {
    return { rol: e.rol, texto: e.texto };
  }
  const cambios = r.cambios
    .map((c) => `${SIGNO[c.op]} ${c.codigo}`
      + (c.componente ? ` ${String(c.componente.rendimiento).replace(".", ",")}` : ""))
    .join("; ");
  const destino = e.estado === "aplicado" ? "aplicado"
    : e.estado === "descartado" ? "descartado" : "sin decidir";
  // El resumen va PRIMERO: el servidor recorta cada mensaje a MAX_TEXTO y, si el
  // texto del agente es largo, lo que va al final se pierde.
  return { rol: "agente", texto: `(Propuse: ${cambios} — ${destino})\n${e.texto}` };
}

let proximoId = 1;

/** Chat con el agente de composición. El historial vive acá (efímero: recargar lo
 *  borra); lo que queda es cada cambio aplicado, como versión del expediente. */
export default function PanelAgente({
  corridaId, seq, componentes, deshabilitado, onAplicar,
}: Props) {
  const [hilo, setHilo] = useState<Entrada[]>([]);
  const [texto, setTexto] = useState("");
  const [estado, setEstado] = useState<EstadoAvatar>("espera");
  const [linea, setLinea] = useState("");
  const [aviso, setAviso] = useState<string | null>(null);
  const [plegado, setPlegado] = useState(false);
  const montado = useRef(true);
  const temporizador = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancelar = useRef<AbortController | null>(null);
  useEffect(() => {
    montado.current = true;
    return () => {
      montado.current = false;
      // La IA se paga por token: si la persona se fue, no se sigue consumiendo.
      cancelar.current?.abort();
      if (temporizador.current) clearTimeout(temporizador.current);
    };
  }, []);

  const ocupado = estado === "pensando" || estado === "buscando";
  const visible: EstadoAvatar = deshabilitado ? "deshabilitado" : estado;

  function marcar(id: number, cambios: Partial<Entrada>) {
    setHilo((h) => h.map((e) => (e.id === id ? { ...e, ...cambios } : e)));
  }

  async function enviar() {
    const t = texto.trim();
    if (!t || ocupado || deshabilitado) return;
    // Sin esto, el "lista → espera" de la respuesta anterior puede caer en plena
    // petición, rehabilitar la caja y permitir un doble envío.
    if (temporizador.current) clearTimeout(temporizador.current);
    const idUsuario = proximoId++;
    const conMensaje: Entrada[] = [...hilo, { id: idUsuario, rol: "usuario", texto: t }];
    setHilo(conMensaje);
    const control = new AbortController();
    cancelar.current = control;
    setTexto("");
    setAviso(null);
    setEstado("pensando");
    setLinea("Pensando…");
    // Un objeto y no dos `let`: TypeScript no ve las asignaciones dentro del callback
    // y estrecharía las variables a `null` después del `await`.
    const res: { respuesta: RespuestaAgente | null; fallo: string | null; bloqueado: boolean } =
      { respuesta: null, fallo: null, bloqueado: false };
    try {
      await chatComposicionStream(
        corridaId, seq,
        { mensajes: conMensaje.slice(-MAX_HISTORIAL).map(paraHistorial), componentes },
        (ev) => {
          if (!montado.current) return;
          const d = (ev.data ?? {}) as { consulta?: string; motivo?: string; detail?: string };
          if (ev.event === "pensando") {
            setEstado("pensando");
            setLinea("Pensando…");
          } else if (ev.event === "buscando") {
            setEstado("buscando");
            setLinea(`Buscando «${d.consulta ?? ""}» en el catálogo…`);
          } else if (ev.event === "respuesta") {
            res.respuesta = ev.data as RespuestaAgente;
          } else if (ev.event === "bloqueado" || ev.event === "error") {
            res.fallo = d.motivo ?? d.detail ?? "No pude responder, vuelve a intentar.";
            res.bloqueado = ev.event === "bloqueado";
          }
        },
        control.signal);
    } catch (e) {
      res.fallo = e instanceof Error ? e.message : "No pude responder, vuelve a intentar.";
    }
    if (!montado.current) return;
    setLinea("");
    const r = res.respuesta;
    if (r) {
      // Funcional: mientras el agente pensaba, la persona pudo aplicar o descartar una
      // propuesta anterior, y una copia vieja del hilo la devolvería a «pendiente».
      setHilo((h) => [...h, {
        id: proximoId++, rol: "agente", texto: r.texto, respuesta: r, instruccion: t,
        estado: r.cambios.length > 0 ? "pendiente" : undefined,
      }]);
      setEstado("lista");
      temporizador.current = setTimeout(() => {
        if (montado.current) setEstado("espera");
      }, 1500);
    } else {
      // El mensaje vuelve a la caja para corregirlo: no se queda en el hilo un
      // mensaje que el agente nunca recibió.
      setHilo((h) => h.filter((x) => x.id !== idUsuario));
      setTexto(t);
      setAviso(res.fallo ?? "El agente no respondió. Vuelve a intentar.");
      // Bloqueado no es una falla del agente: el mensaje nunca le llegó.
      setLinea(res.bloqueado ? "Mensaje bloqueado: trae un monto" : "No pude responder");
      setEstado("error");
    }
  }

  async function aplicar(e: Entrada) {
    if (!e.respuesta || e.estado !== "pendiente") return;
    marcar(e.id, { estado: "aplicando" });
    try {
      const conflictos = await onAplicar(e.respuesta.cambios, e.instruccion ?? "");
      if (montado.current) marcar(e.id, { estado: "aplicado", conflictos });
    } catch (err) {
      if (!montado.current) return;
      marcar(e.id, { estado: "pendiente" });
      setAviso(err instanceof Error ? err.message : "No se pudieron aplicar los cambios.");
    }
  }

  return (
    <aside
      aria-label="Agente de composición"
      className="flex flex-col gap-2 border-t pt-3 lg:sticky lg:top-3 lg:border-t-0 lg:border-l lg:pt-0 lg:pl-3"
    >
      <div className="flex items-center gap-2">
        <AvatarIngeniero estado={visible} />
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold text-foreground">Agente</p>
          <p aria-live="polite" className="truncate text-[11px] text-muted-foreground">
            {deshabilitado ? "No disponible" : linea || "Listo para ayudarte"}
          </p>
        </div>
        <button
          type="button"
          aria-expanded={!plegado}
          className="text-[11px] text-muted-foreground underline underline-offset-2 hover:text-foreground"
          onClick={() => setPlegado((v) => !v)}
        >
          {plegado ? "Mostrar" : "Plegar"}
        </button>
      </div>

      {!plegado && (
        <>
          {deshabilitado && (
            <p className="border-l-2 border-revisar bg-revisar-surface px-2 py-1 text-xs text-revisar">
              {deshabilitado}
            </p>
          )}

          <div role="log" className="flex max-h-[55vh] flex-col gap-2 overflow-y-auto">
            {hilo.length === 0 && !deshabilitado && (
              <p className="text-xs text-muted-foreground">
                {"Cuéntame qué lleva esta actividad o qué quieres cambiar de la tabla. "
                  + "Por ejemplo: «agrega una cuadrilla de un oficial y dos ayudantes» o "
                  + "«busca una mano de obra que tenga licencia de soldador». Yo propongo "
                  + "y tú decides si lo aplicas. No veo precios."}
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
                {e.respuesta && e.respuesta.cambios.length > 0 && (
                  <ul className="mt-1 flex flex-col gap-0.5 border-l-2 border-info pl-2">
                    {e.respuesta.cambios.map((c, i) => {
                      const info = e.respuesta!.catalogo[c.codigo];
                      const actual = componentes.find((x) => x.codigo === c.codigo);
                      const rend = c.op === "modificar" && actual && c.componente
                        ? `${num(actual.rendimiento)} → ${num(c.componente.rendimiento)}`
                        : c.componente ? num(c.componente.rendimiento) : "";
                      const ref = c.componente?.referencias[0];
                      return (
                        <li key={`${c.codigo}@@${i}`} className="font-mono text-[11px] text-foreground">
                          {SIGNO[c.op]} {c.codigo} {info?.nombre ?? ""} {info?.unidad ?? ""} {rend}
                          {ref && (
                            <span className="text-muted-foreground"> (antecedente APU {ref.apu_codigo})</span>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                )}
                {e.respuesta && e.respuesta.descartados.length > 0 && (
                  <ul className="mt-1 flex flex-col gap-0.5">
                    {e.respuesta.descartados.map((d, i) => (
                      <li key={`${d.codigo}@@${i}`} className="text-[11px] text-revisar">
                        ⚠ {d.codigo}: {d.motivo}
                      </li>
                    ))}
                  </ul>
                )}
                {e.estado === "pendiente" && (
                  <div className="mt-1 flex gap-2">
                    <Button size="sm" onClick={() => void aplicar(e)}>Aplicar</Button>
                    <Button size="sm" variant="outline"
                            onClick={() => marcar(e.id, { estado: "descartado" })}>
                      Descartar
                    </Button>
                  </div>
                )}
                {e.estado === "aplicando" && (
                  <p className="mt-1 text-[11px] text-info">Aplicando…</p>
                )}
                {e.estado === "aplicado" && (
                  <p className="mt-1 text-[11px] text-info">Aplicado: la tabla se revalidó sin IA.</p>
                )}
                {e.estado === "descartado" && (
                  <p className="mt-1 text-[11px] text-muted-foreground">Descartado.</p>
                )}
                {(e.conflictos ?? []).map((c, i) => (
                  <p key={i} className="text-[11px] text-revisar">⚠ {c}</p>
                ))}
              </div>
            ))}
          </div>

          {aviso && (
            <p role="alert" className="border-l-2 border-destructive bg-destructive-surface px-2 py-1 text-xs text-destructive">
              {aviso}
            </p>
          )}

          <div className="flex flex-col gap-1">
            <textarea
              aria-label="Mensaje para el agente"
              rows={3}
              maxLength={MAX_TEXTO}
              value={texto}
              disabled={!!deshabilitado || ocupado}
              placeholder="Escribe tu instrucción… (Enter envía, Shift+Enter baja de línea)"
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
              <Button size="sm" disabled={!!deshabilitado || ocupado || !texto.trim()}
                      onClick={() => void enviar()}>
                {ocupado ? "Esperando…" : "Enviar"}
              </Button>
            </div>
          </div>
        </>
      )}
    </aside>
  );
}
