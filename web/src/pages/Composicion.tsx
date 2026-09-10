import { Fragment, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { BuscadorInsumo } from "@/components/autoria/DialogoAgregarApu";
import { getGruposApu } from "@/api/autoria";
import {
  aprobarComposicion,
  generarComposicionStream,
  getComposicion,
  guardarComposicion,
  rechazarComposicion,
} from "@/api/composicion";
import { useAuth } from "@/lib/auth";
import { puede } from "@/components/rutas";
import type {
  ComponentePropuesto,
  Hallazgo,
  VistaComposicion,
} from "@/lib/tipos";

/** Las etapas del stream, en palabras de persona. Las claves son los `event` que
 *  emite `dominio/composicion_agente.componer`. */
const ETAPAS: Record<string, string> = {
  recuperando: "Recuperando insumos y APUs parecidos del histórico…",
  generando: "Redactando la propuesta con IA…",
  validando: "Validando la propuesta contra el catálogo…",
};

/** Chevron + Código + Insumo + Un. + Rend. + Función + Origen + Ev. La celda de
 *  quitar se suma aparte, solo sin `soloLectura` (rol editor y corrida activa). */
const COLS_TABLA = 8;

const num = (n: number) =>
  Number.isFinite(n) ? n.toLocaleString("es-CO", { maximumFractionDigits: 4 }) : "—";

/** Fila editable de la mesa. El rendimiento vive como TEXTO mientras se escribe
 *  (mismo criterio que el alta de APUs): un número obligaría a normalizar en cada
 *  tecla y "0," dejaría de poder tipearse. */
interface Fila {
  uid: number;
  c: ComponentePropuesto;
  rend: string;
}

let proximoUid = 1;

function filasDe(cs: ComponentePropuesto[]): Fila[] {
  return cs.map((c) => ({ uid: proximoUid++, c, rend: String(c.rendimiento) }));
}

function componentesDe(filas: Fila[]): ComponentePropuesto[] {
  return filas.map((f) => {
    const r = Number(f.rend);
    return { ...f.c, rendimiento: Number.isFinite(r) ? r : 0 };
  });
}

/** Componente agregado a mano: sin antecedente ni cálculo, y lo dice. El validador
 *  del servidor decide si pasa; acá no se adivina nada por él. */
function componenteNuevo(codigo: string): ComponentePropuesto {
  return {
    codigo,
    tipo: "insumo",
    funcion: "",
    rendimiento: 0,
    origen: "supuesto_tecnico",
    referencias: [],
    hipotesis: {},
    calculo: null,
    justificacion: "Agregado a mano en la revisión.",
    nivel_evidencia: "bajo",
    ref_shift: "",
  };
}

export default function Composicion() {
  const { id, seq } = useParams<{ id: string; seq: string }>();
  const corridaId = Number(id);
  const linea = Number(seq);
  const navigate = useNavigate();
  const location = useLocation();
  const { perfil } = useAuth();
  const puedeEditar = puede(perfil?.rol, "editor");

  // La VISTA entera, no solo la versión: `catalogo` (nombre y unidad de cada
  // código) viaja con la respuesta y sin él la tabla muestra códigos pelados.
  const [vista, setVista] = useState<VistaComposicion | null>(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filas, setFilas] = useState<Fila[]>([]);
  const [supuestosOk, setSupuestosOk] = useState(false);
  const [etapa, setEtapa] = useState<string | null>(null);
  const [guardando, setGuardando] = useState(false);
  const [porQue, setPorQue] = useState(false);
  const [abierta, setAbierta] = useState<number | null>(null);
  const [identidad, setIdentidad] = useState(false);
  // La generación dura minutos: si el usuario se fue, el backend igual persiste la
  // propuesta (recargar la levanta) pero acá ya no hay a quién avisarle.
  const montado = useRef(true);
  useEffect(() => {
    montado.current = true;
    return () => { montado.current = false; };
  }, []);

  /** Adopta lo que devolvió el servidor como la verdad de la pantalla. Los cuatro
   *  endpoints devuelven la vista completa, así que los nombres del catálogo no se
   *  pierden después de guardar una edición ni de rechazar. */
  function adoptar(v: VistaComposicion) {
    setVista(v);
    setFilas(filasDe(v.vigente?.propuesta?.componentes ?? []));
    setSupuestosOk(false);
    setAbierta(null);
  }

  async function recargar(): Promise<void> {
    const v = await getComposicion(corridaId, linea);
    // `vigente` puede venir null con historial: el seq se reusa, y un expediente de
    // la actividad que ANTES ocupaba esta línea no habla de la de hoy. Para esta
    // pantalla eso es "todavía no hay composición", no un error.
    if (montado.current) adoptar(v);
  }

  useEffect(() => {
    let cancelado = false;
    setCargando(true);
    setError(null);
    getComposicion(corridaId, linea)
      .then((v) => {
        if (cancelado) return;
        adoptar(v);
        setCargando(false);
      })
      .catch((e: unknown) => {
        if (cancelado) return;
        setError(e instanceof Error ? e.message : "No se pudo leer la composición.");
        setCargando(false);
      });
    return () => { cancelado = true; };
    // Generar NO va acá a propósito: cada corrida de la IA es plata y la dispara
    // una persona, nunca el montaje de la pantalla.
  }, [corridaId, linea]);

  const vigente = vista?.vigente ?? null;
  const catalogo = vista?.catalogo ?? {};
  // `corrida_modo` es una FOTO del momento de cargar (ver `VistaComposicion`): si la
  // congelan con la mesa abierta, esto no se entera y el 409 de la primera escritura
  // sigue siendo la red. Es la misma condición que el rol `consulta` — las dos
  // apagan la escritura por igual — así que se junta en una sola derivada en vez de
  // repetir "puedeEditar && !congelada" en cada gate de la mesa.
  const congelada = vista?.corrida_modo === "congelada";
  const soloLectura = !puedeEditar || congelada;
  const propuesta = vigente?.propuesta ?? null;
  const validacion = vigente?.validacion ?? null;
  const actividad = vigente?.actividad ?? null;
  // Sin expediente todavía no hay actividad que mostrar. La corrida ya la conoce, así
  // que la manda como pista al navegar; en una recarga en frío queda solo el número.
  const descripcion = actividad?.descripcion
    ?? (location.state as { descripcion?: string } | null)?.descripcion
    ?? `Línea #${linea}`;

  const componentes = componentesDe(filas);
  const hayCambios =
    propuesta !== null
    && (supuestosOk
        || JSON.stringify(componentes) !== JSON.stringify(propuesta.componentes));

  const hallazgosDe = (codigo: string): Hallazgo[] => [
    ...(validacion?.errores ?? []).filter((h) => h.componente === codigo),
    ...(validacion?.advertencias ?? []).filter((h) => h.componente === codigo),
  ];

  // ─── acciones ──────────────────────────────────────────────────────────────

  /** Los rendimientos editados viven SOLO acá hasta que se guardan: irse sin
   *  guardar los pierde, así que se avisa. */
  function volver() {
    if (hayCambios && !window.confirm(
      "Tenés cambios sin guardar en esta propuesta. Si volvés se pierden. ¿Seguir?")) {
      return;
    }
    navigate(`/corridas/${corridaId}`);
  }

  async function generar() {
    if (etapa !== null) return;                      // cinturón contra el doble clic
    if (hayCambios && !window.confirm(
      "Regenerar pide una propuesta nueva y descarta los cambios que hiciste en "
      + "esta. ¿Seguir?")) return;
    setEtapa("recuperando");
    let detalle: string | null = null;
    try {
      await generarComposicionStream(corridaId, linea, (ev) => {
        if (ev.event === "error") {
          detalle = (ev.data as { detail?: string })?.detail ?? "No se pudo componer.";
        } else if (ETAPAS[ev.event] && montado.current) {
          setEtapa(ev.event);
        }
      });
      // La propuesta la persiste el backend apenas sale: se relee en vez de armarla
      // con el evento, que es lo mismo que ve una recarga de la página.
      await recargar();
      if (detalle) toast.error(detalle);
    } catch (e) {
      // Un stream cortado no pierde nada: si alcanzó a guardarse, la relectura la trae.
      await recargar().catch(() => {});
      toast.error(e instanceof Error ? e.message : "No se pudo componer la actividad.");
    } finally {
      if (montado.current) setEtapa(null);
    }
  }

  async function guardar() {
    if (!vigente || guardando) return;
    setGuardando(true);
    try {
      const v = await guardarComposicion(
        corridaId, linea, vigente.version, componentes, supuestosOk);
      if (montado.current) adoptar(v);
      toast.success("Cambios guardados. La propuesta se revalidó sin IA.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "No se pudieron guardar los cambios.");
    } finally {
      if (montado.current) setGuardando(false);
    }
  }

  async function rechazar() {
    if (!vigente || guardando) return;
    const motivo = window.prompt("¿Por qué se rechaza esta propuesta?");
    if (motivo === null) return;
    setGuardando(true);
    try {
      const v = await rechazarComposicion(
        corridaId, linea, vigente.version, motivo.trim());
      if (montado.current) adoptar(v);
      toast.success("Propuesta rechazada. No se creó ningún APU.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "No se pudo rechazar la propuesta.");
    } finally {
      if (montado.current) setGuardando(false);
    }
  }

  async function aprobar(datos: {
    codigo: string; turno: string; nombre: string; grupo: string; unidad: string;
  }) {
    if (!vigente) return;
    await aprobarComposicion(corridaId, linea, { version_base: vigente.version, ...datos });
    toast.success(`APU ${datos.codigo} creado y asignado a la línea.`);
    navigate(`/corridas/${corridaId}`);
  }

  // ─── render ────────────────────────────────────────────────────────────────

  if (cargando) {
    return (
      <div style={{ padding: "16px 20px" }} className="text-sm text-muted-foreground">
        Cargando la composición de la línea #{linea}…
      </div>
    );
  }
  if (error) {
    return (
      <div style={{ padding: "16px 20px" }} className="text-sm text-destructive">
        {error}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3" style={{ padding: "16px 20px" }}>
      {/* Cabecera */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <button
          type="button"
          className="text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground"
          onClick={volver}
        >
          ◄ Volver a la corrida
        </button>
        <div className="min-w-0 text-right">
          <h2 className="text-sm font-semibold text-foreground">{descripcion}</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {actividad
              ? `${actividad.unidad} · ${num(actividad.cantidad)} · ${actividad.shift}`
                + ` · ítem ${actividad.item}`
              : `Corrida #${corridaId} · línea #${linea}`}
            {vigente && ` · ${vigente.estado} v${vigente.version}`}
          </p>
        </div>
      </div>

      {/* Tono `info` (azul) y no `destructive`/`revisar`: esto no es un error de la
          propuesta, es el estado de la corrida — no debe competir visualmente con
          los hallazgos de la validación de más abajo. Va primero porque explica por
          qué el resto de la mesa está apagada. */}
      {congelada && (
        <p className="border-l-2 border-info bg-info-surface px-2 py-1.5 text-xs text-info">
          Esta corrida está <span className="font-semibold">congelada</span>: es una
          foto fija y esta mesa quedó de solo lectura, aunque el expediente se sigue
          viendo entero. Si querés componer o editar esta propuesta, activá la
          corrida desde su vista.
        </p>
      )}

      <p className="border-l-2 border-revisar bg-revisar-surface px-2 py-1.5 text-xs text-revisar">
        Esto es una <span className="font-semibold">propuesta</span> de la IA: todavía
        no se creó nada en la biblioteca. La IA no ve precios ni costos, así que
        <span className="font-semibold"> revisá los rendimientos</span> antes de aprobar.
      </p>

      {/* Sin composición: se ofrece generarla, nunca se genera sola */}
      {!propuesta && (
        <div className="flex flex-col items-start gap-2 rounded-lg border border-dashed px-3 py-4">
          <p className="text-xs text-muted-foreground">
            Esta línea todavía no tiene una propuesta.
            {vigente?.estado === "error" && vigente.motivo
              ? ` El último intento falló: ${vigente.motivo}`
              : ""}
          </p>
          {!soloLectura && (
            <Button size="sm" disabled={etapa !== null} onClick={generar}>
              {etapa !== null ? "Componiendo…" : "Generar propuesta"}
            </Button>
          )}
          {etapa !== null && (
            <p className="text-xs font-medium text-info">{ETAPAS[etapa] ?? etapa}</p>
          )}
        </div>
      )}

      {propuesta && (
        <>
          {/* Confianza + incertidumbre declarada */}
          <div className="flex flex-col gap-1 rounded-lg border bg-muted/20 px-3 py-2">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="font-semibold text-foreground">
                Confianza: {(vigente?.confianza ?? "sin nivel").toUpperCase()}
              </span>
              <button
                type="button"
                aria-expanded={porQue}
                className="text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground"
                onClick={() => setPorQue((v) => !v)}
              >
                por qué
              </button>
            </div>
            {porQue && (
              <ul className="mt-0.5 flex flex-col gap-0.5">
                {(vigente?.confianza_motivos ?? []).map((m, i) => (
                  <li key={`${m.senal}@@${i}`} className="text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">{m.senal}</span>
                    {" — "}{m.detalle}
                    <span className="ml-1 font-mono tabular-nums">
                      ({m.aporte >= 0 ? "+" : ""}{num(m.aporte)})
                    </span>
                  </li>
                ))}
                {(vigente?.confianza_motivos ?? []).length === 0 && (
                  <li className="text-xs text-muted-foreground">
                    La plataforma no registró señales para esta propuesta.
                  </li>
                )}
              </ul>
            )}
            {/* Aparte del nivel y rotulada: es lo que el modelo dice de sí mismo y
                NO entra en el cálculo de la plataforma. */}
            <p className="text-xs text-muted-foreground">
              El modelo declara {num(propuesta.incertidumbre_declarada * 100)} % de
              incertidumbre — dato suyo, no cuenta para el nivel de arriba.
            </p>
            {propuesta.justificacion && (
              <p className="text-xs text-muted-foreground">
                <span className="font-medium text-foreground">Por qué lo propone así:</span>{" "}
                {propuesta.justificacion}
              </p>
            )}
          </div>

          {/* Validación: errores, advertencias y el cociente */}
          <div className="flex flex-col gap-1">
            {(validacion?.errores ?? []).map((h, i) => (
              <p key={`err-${i}`}
                 className="border-l-2 border-destructive bg-destructive-surface px-2 py-1 text-xs text-destructive">
                ✖ {h.mensaje}
              </p>
            ))}
            {(validacion?.advertencias ?? []).map((h, i) => (
              <p key={`adv-${i}`}
                 className="border-l-2 border-revisar bg-revisar-surface px-2 py-1 text-xs text-revisar">
                ⚠ {h.mensaje}
              </p>
            ))}
            {validacion && (
              <p className="text-xs text-muted-foreground">
                {validacion.valido
                  // El cociente SOLO cuando pasa: un "11 de 12" al lado de un cartel
                  // de bloqueo tranquiliza sobre algo que no se puede aprobar.
                  ? `${validacion.metricas.superadas} de ${validacion.metricas.totales} validaciones superadas`
                  : `${validacion.errores.length} ${
                      validacion.errores.length === 1 ? "error" : "errores"}`}
              </p>
            )}
          </div>

          {/* Componentes */}
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-6 px-1" />
                <TableHead className="text-xs w-20">Código</TableHead>
                <TableHead className="text-xs">Insumo</TableHead>
                <TableHead className="text-xs w-12">Un.</TableHead>
                <TableHead className="text-xs w-24 text-right">Rend.</TableHead>
                <TableHead className="text-xs w-28">Función</TableHead>
                <TableHead className="text-xs w-36">Origen</TableHead>
                <TableHead className="text-xs w-16">Ev.</TableHead>
                {!soloLectura && <TableHead className="text-xs w-8" />}
              </TableRow>
            </TableHeader>
            <TableBody>
              {filas.map((f) => {
                const hs = hallazgosDe(f.c.codigo);
                const abiertaEsta = abierta === f.uid;
                const hipotesis = Object.entries(f.c.hipotesis ?? {});
                // Un código que el catálogo no tiene NO es un hueco de datos: es un
                // insumo que no existe. El validador ya lo dijo con
                // CODIGO_INEXISTENTE, así que la fila se lee como problema y no
                // como un guion mudo.
                const ficha = catalogo[f.c.codigo];
                return (
                  <Fragment key={f.uid}>
                    <TableRow className={!ficha
                      ? "bg-destructive-surface/60"
                      : hs.length > 0 ? "bg-revisar-surface/50" : undefined}>
                      <TableCell className="w-6 px-1 py-1 align-top">
                        <button
                          type="button"
                          aria-label={abiertaEsta
                            ? `Colapsar ${f.c.codigo}`
                            : `Ver supuestos de ${f.c.codigo}`}
                          aria-expanded={abiertaEsta}
                          className="text-xs text-muted-foreground hover:text-foreground"
                          onClick={() => setAbierta(abiertaEsta ? null : f.uid)}
                        >
                          {abiertaEsta ? "▾" : "▸"}
                        </button>
                      </TableCell>
                      <TableCell className="text-xs font-mono align-top">
                        {f.c.codigo}
                        {f.c.tipo === "apu" && (
                          <span className="ml-1 rounded bg-muted px-1 text-[10px] font-sans">
                            sub-APU {f.c.ref_shift}
                          </span>
                        )}
                      </TableCell>
                      {/* El nombre puede ser larguísimo (830 caracteres en el
                          catálogo real): la celda lo trunca a una línea. El completo
                          va en el desplegable de la fila (ver más abajo) y NO en un
                          `title` nativo — el tooltip del sistema tarda ~1s en salir y
                          lo parte en muchas líneas, el peor lugar para el campo que
                          dice QUÉ ES el insumo. Dos formas de leer lo mismo, y una
                          mala, es una de más. */}
                      <TableCell className="max-w-[22rem] truncate text-xs align-top">
                        {ficha ? (
                          <span>{ficha.nombre}</span>
                        ) : (
                          <span className="font-medium text-destructive">
                            no está en el catálogo
                          </span>
                        )}
                        {hs.length > 0 && (
                          <span className="ml-1 font-medium text-revisar"
                                title={hs.map((h) => h.mensaje).join(" · ")}>
                            ⚠ {hs.length}
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-xs font-mono text-muted-foreground align-top">
                        {ficha?.unidad || "—"}
                      </TableCell>
                      <TableCell className="text-xs text-right align-top">
                        {!soloLectura ? (
                          <input
                            type="number"
                            min="0"
                            step="any"
                            aria-label={`Rendimiento de ${f.c.codigo}`}
                            className="h-6 w-full rounded border border-border bg-transparent px-1 text-right text-[11px] outline-none focus-visible:border-ring"
                            value={f.rend}
                            onChange={(e) => setFilas((prev) => prev.map((x) =>
                              x.uid === f.uid ? { ...x, rend: e.target.value } : x))}
                          />
                        ) : (
                          <span className="font-mono tabular-nums">{num(Number(f.rend))}</span>
                        )}
                      </TableCell>
                      <TableCell className="text-xs align-top">
                        {f.c.funcion || <span className="text-muted-foreground">—</span>}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground align-top">
                        {f.c.origen}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground align-top">
                        {/* La interfaz es el ÚNICO consumidor de `nivel_evidencia`: ni
                            el validador ni la confianza lo leen. */}
                        {f.c.nivel_evidencia}
                      </TableCell>
                      {!soloLectura && (
                        <TableCell className="w-8 px-1 py-1 align-top">
                          <button
                            type="button"
                            aria-label={`Quitar ${f.c.codigo}`}
                            className="text-xs text-muted-foreground hover:text-destructive"
                            onClick={() => setFilas((prev) =>
                              prev.filter((x) => x.uid !== f.uid))}
                          >
                            ⨯
                          </button>
                        </TableCell>
                      )}
                    </TableRow>

                    {abiertaEsta && (
                      <TableRow className="bg-muted/20 hover:bg-muted/20">
                        <TableCell colSpan={COLS_TABLA + (!soloLectura ? 1 : 0)}
                                   className="px-8 py-2">
                          <div className="flex flex-col gap-0.5 text-xs text-muted-foreground">
                            {/* El nombre completo del insumo: la celda de la fila lo
                                trunca, acá se lee entero con el ancho de la fila
                                entera — el lugar cómodo para el campo que dice qué
                                ES el insumo, no el tooltip nativo. */}
                            {ficha && (
                              <span className="font-medium text-foreground">{ficha.nombre}</span>
                            )}
                            {f.c.justificacion && <span>{f.c.justificacion}</span>}
                            {f.c.calculo && (
                              <span className="font-mono text-[11px] text-foreground">
                                {f.c.calculo.operacion}: {num(f.c.calculo.numerador)} /{" "}
                                {num(f.c.calculo.denominador)} = {num(f.c.calculo.resultado)}
                              </span>
                            )}
                            {/* `hipotesis` es un dict cuyas claves las pone el modelo:
                                se muestra como TEXTO y no se interpreta. */}
                            {hipotesis.map(([k, v]) => (
                              <span key={k} className="text-[11px]">
                                <span className="font-medium text-foreground">{k}:</span>{" "}
                                {String(v)}
                              </span>
                            ))}
                            {f.c.referencias.map((r, i) => (
                              <span key={i} className="text-[11px]">
                                Antecedente: APU {r.apu_codigo} ({r.turno})
                              </span>
                            ))}
                            {!f.c.justificacion && !f.c.calculo && hipotesis.length === 0
                              && f.c.referencias.length === 0 && (
                              <span className="text-[11px]">
                                Sin supuestos ni cálculo declarados.
                              </span>
                            )}
                          </div>
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                );
              })}
              {filas.length === 0 && (
                <TableRow>
                  <TableCell colSpan={COLS_TABLA + (!soloLectura ? 1 : 0)}
                             className="py-4 text-center text-xs text-muted-foreground">
                    La propuesta quedó sin componentes.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>

          {!soloLectura && (
            <div className="max-w-md">
              <BuscadorInsumo
                codigo=""
                nombre=""
                onElegir={(ins) => setFilas((prev) => [
                  ...prev, ...filasDe([componenteNuevo(ins.codigo)]),
                ])}
              />
            </div>
          )}

          {/* Supuestos y referencias */}
          {propuesta.supuestos.length > 0 && (
            <div className="flex flex-col gap-1">
              <h3 className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Supuestos
              </h3>
              {propuesta.supuestos.map((s, i) => (
                <p key={i} className="text-xs text-muted-foreground">
                  <span className="font-medium text-foreground">{s.campo}:</span>{" "}
                  {s.supuesto} — {s.impacto}
                </p>
              ))}
              {!soloLectura && (
                <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={supuestosOk}
                    onChange={(e) => setSupuestosOk(e.target.checked)}
                  />
                  Confirmo los supuestos (se guarda con los cambios)
                </label>
              )}
            </div>
          )}

          {(vigente?.antecedentes?.apus_referencia ?? []).length > 0 && (
            <p className="text-xs text-muted-foreground">
              <span className="font-medium text-foreground">Referencias:</span>{" "}
              {vigente!.antecedentes!.apus_referencia
                .map((a) => `APU ${a.codigo} (${a.turno})`).join(" · ")}
            </p>
          )}

          {/* Acciones */}
          {!soloLectura && (
            <div className="sticky bottom-0 z-10 flex flex-wrap items-center gap-2 border-t bg-background/95 px-2 py-2 backdrop-blur">
              <Button size="sm" variant="outline" disabled={!hayCambios || guardando}
                      onClick={guardar}>
                {guardando ? "Guardando…" : "Guardar cambios"}
              </Button>
              <Button size="sm" variant="outline" disabled={etapa !== null}
                      title="Pide una propuesta nueva a la IA. Descarta lo que hayas editado."
                      onClick={generar}>
                {etapa !== null ? "Componiendo…" : "Regenerar"}
              </Button>
              <Button size="sm" variant="destructive" disabled={guardando}
                      onClick={rechazar}>
                Rechazar
              </Button>
              {etapa !== null && (
                <span className="text-xs font-medium text-info">
                  {ETAPAS[etapa] ?? etapa}
                </span>
              )}
              <div className="ml-auto">
                <Button
                  size="sm"
                  disabled={!validacion?.valido}
                  title={validacion?.valido
                    ? "Crea el APU con el alta de siempre y lo asigna a esta línea."
                    : "Hay errores bloqueantes: corregilos antes de aprobar."}
                  onClick={() => setIdentidad(true)}
                >
                  Aprobar y crear APU
                </Button>
              </div>
            </div>
          )}
        </>
      )}

      {identidad && actividad && (
        <DialogoIdentidad
          descripcion={actividad.descripcion}
          unidad={actividad.unidad}
          shift={actividad.shift}
          onCancelar={() => setIdentidad(false)}
          onAceptar={aprobar}
        />
      )}
    </div>
  );
}

// ─── identidad del APU ───────────────────────────────────────────────────────
// No reusa `DialogoAgregarApu` a propósito: ese diálogo trae la tabla de
// componentes entera y obligaría a editar los rendimientos DOS veces, acá y allá.
// Los componentes salen de la versión vigente (el backend los toma de ahí, nunca
// del cuerpo); lo único que pone el humano es la identidad.

const inputCls =
  "h-7 w-full rounded border border-border bg-transparent px-1.5 text-xs outline-none focus-visible:border-ring";

function DialogoIdentidad({
  descripcion, unidad, shift, onCancelar, onAceptar,
}: {
  descripcion: string;
  unidad: string;
  shift: string;
  onCancelar: () => void;
  onAceptar: (d: {
    codigo: string; turno: string; nombre: string; grupo: string; unidad: string;
  }) => Promise<void>;
}) {
  const [codigo, setCodigo] = useState("");
  const [turno, setTurno] = useState(
    (shift || "").toUpperCase().startsWith("N") ? "NOCTURNO" : "DIURNO");
  const [nombre, setNombre] = useState(descripcion);
  const [grupo, setGrupo] = useState("");
  const [und, setUnd] = useState(unidad);
  const [grupos, setGrupos] = useState<string[]>([]);
  const [creando, setCreando] = useState(false);

  useEffect(() => {
    let cancelado = false;
    getGruposApu()
      .then((gs) => { if (!cancelado) setGrupos(gs); })
      .catch(() => toast.error("No se pudo cargar el vocabulario de grupos."));
    return () => { cancelado = true; };
  }, []);

  const valido = codigo.trim() !== "" && nombre.trim() !== ""
    && grupo.trim() !== "" && und.trim() !== "";

  async function aceptar() {
    if (!valido || creando) return;
    setCreando(true);
    try {
      await onAceptar({
        codigo: codigo.trim(), turno, nombre: nombre.trim(),
        grupo: grupo.trim(), unidad: und.trim(),
      });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "No se pudo crear el APU.");
      setCreando(false);
    }
  }

  return (
    <Dialog open onOpenChange={(v) => { if (!v) onCancelar(); }}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="text-sm">Crear el APU con esta propuesta</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-2">
          <label className="flex flex-col gap-0.5 text-xs">
            Código
            <input className={inputCls} value={codigo} aria-label="Código"
                   onChange={(e) => setCodigo(e.target.value)} />
          </label>
          <label className="flex flex-col gap-0.5 text-xs">
            Turno
            <select className={inputCls} value={turno} aria-label="Turno"
                    onChange={(e) => setTurno(e.target.value)}>
              <option value="DIURNO">DIURNO</option>
              <option value="NOCTURNO">NOCTURNO</option>
            </select>
          </label>
          <label className="flex flex-col gap-0.5 text-xs">
            Nombre
            <input className={inputCls} value={nombre} aria-label="Nombre"
                   onChange={(e) => setNombre(e.target.value)} />
          </label>
          <label className="flex flex-col gap-0.5 text-xs">
            Grupo
            <select className={inputCls} value={grupo} aria-label="Grupo"
                    onChange={(e) => setGrupo(e.target.value)}>
              <option value="">(elegí un grupo)</option>
              {grupos.map((g) => <option key={g} value={g}>{g}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-0.5 text-xs">
            Unidad
            <input className={inputCls} value={und} aria-label="Unidad"
                   onChange={(e) => setUnd(e.target.value)} />
          </label>
        </div>
        <DialogFooter>
          <Button size="sm" variant="outline" onClick={onCancelar}>Cancelar</Button>
          <Button size="sm" disabled={!valido || creando} onClick={aceptar}>
            {creando ? "Creando…" : "Crear APU"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
