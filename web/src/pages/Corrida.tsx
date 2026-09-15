import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import ResumenCapitulos from "@/components/corrida/ResumenCapitulos";
import TablaItems from "@/components/corrida/TablaItems";
import { DialogoAgregarLineas } from "@/components/corrida/DialogoAgregarLineas";
import {
  getCorrida, descargarCuadro, congelarCorrida, activarCorrida,
  revisarCorridaStream, aplicarSugerencias, reanudarArmado,
} from "@/api/corridas";
import { cop, pct } from "@/lib/moneda";
import { fmtDuracion } from "@/lib/tiempo";
import { useCorridaTabla, SIN_APU } from "@/lib/corridaTabla";
import { useAuth } from "@/lib/auth";
import { puede } from "@/components/rutas";
import type { AsignacionIA, CorridaDetalle, ItemCuadro, Totales } from "@/lib/tipos";

const REVISABLE = new Set(["review", "new", "REVIEW", "NEW"]);

/** Cada cuánto se relee una corrida que se está armando. 5 s y no 2: el armado dura
 *  de una a tres horas, así que el poll vive miles de ciclos y cada uno recostea la
 *  corrida entera del lado del servidor. */
const POLL_ARMANDO_MS = 5000;

/** Parte el motivo de un armado detenido en lo que le habla a una persona y la cola
 *  técnica que el backend le pega detrás ("Último error: RuntimeError: ..."). Lo
 *  técnico sirve para reportar el problema, pero no puede ser EL mensaje: quien lee
 *  necesita primero saber qué hacer. */
function partirMotivo(motivo: string): { humano: string; tecnico: string } {
  const i = motivo.indexOf("Último error:");
  if (i < 0) return { humano: motivo.trim(), tecnico: "" };
  return { humano: motivo.slice(0, i).trim(), tecnico: motivo.slice(i).trim() };
}

function totalesDe(filas: ItemCuadro[]): Totales {
  const contractual = filas.reduce((s, f) => s + f.contractual_total, 0);
  const costo = filas.reduce((s, f) => s + f.costo_total, 0);
  const margen = contractual - costo;
  return {
    contractual,
    costo,
    margen,
    margen_pct: contractual ? margen / contractual : 0,
    n_items: filas.length,
    n_revision: filas.filter((f) => REVISABLE.has(f.status)).length,
  };
}

export default function Corrida() {
  const { id } = useParams<{ id: string }>();
  const corridaId = Number(id);
  const navigate = useNavigate();
  const { perfil } = useAuth();

  const [corrida, setCorrida] = useState<CorridaDetalle | null>(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [agregando, setAgregando] = useState(false);
  // null = no hay revisión corriendo. Dos fases: el triaje por lotes (`lote` es el
  // último lote TERMINADO, así lo manda el backend) y los veredictos fila por fila.
  const [revision, setRevision] = useState<
    { fase: "triaje" | "veredictos"; lote: number; lotes: number; hechos: number; total: number }
    | null
  >(null);
  const [aplicando, setAplicando] = useState(false);
  const [reanudando, setReanudando] = useState(false);
  // Bumpearlo relanza el efecto de carga —y con él la cadena del poll, que se corta
  // sola cuando la corrida deja de estar 'armando'. Es lo que hace que reanudar
  // vuelva a mostrar el progreso sin recargar la página a mano.
  const [recarga, setRecarga] = useState(0);
  const control = useCorridaTabla(corrida?.items ?? []);
  // La revisión de 300 líneas dura minutos: el usuario se va de la página mucho
  // antes de que termine. El stream sigue (y el backend sigue guardando), pero acá
  // ya no hay a quién avisarle: nada de setState sobre un componente desmontado.
  const montado = useRef(true);
  useEffect(() => {
    montado.current = true;
    return () => { montado.current = false; };
  }, []);

  /** Relee la corrida del backend (los veredictos los persiste el servidor). */
  async function recargarCorrida() {
    try {
      const c = await getCorrida(corridaId);
      if (montado.current) setCorrida(c);
    } catch {
      toast.error("No se pudo recargar la corrida; recarga la página para ver los veredictos.");
    }
  }

  /** Devuelve la corrida a la cola. Refresca por el efecto (no por la respuesta):
   *  así vuelve a arrancar el poll, que la respuesta sola no reanimaría. */
  async function reanudar() {
    if (reanudando) return;
    setReanudando(true);
    try {
      await reanudarArmado(corridaId);
      toast.success("El armado volvió a la cola.");
    } catch (e) {
      // Incluye el 409 "ya está en la cola" de cuando otra persona la reanudó antes:
      // se dice qué pasó y se relee igual, que es lo que deja la pantalla al día.
      toast.error(e instanceof Error ? e.message : "No se pudo reanudar el armado.");
    } finally {
      if (montado.current) {
        setReanudando(false);
        setRecarga((n) => n + 1);
      }
    }
  }

  async function cambiarModo(accion: "congelar" | "activar") {
    try {
      const fn = accion === "congelar" ? congelarCorrida : activarCorrida;
      const actualizada = await fn(corridaId);
      setCorrida(actualizada);
      toast.success(accion === "congelar" ? "Corrida congelada" : "Corrida activada");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "No se pudo cambiar el modo.");
    }
  }

  useEffect(() => {
    let cancelado = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    setError(null);
    const cargar = () => {
      getCorrida(corridaId)
        .then((c) => {
          if (cancelado) return;
          setCorrida(c);
          setCargando(false);
          // El armado corre en el servidor: la pantalla lo mira por el poll hasta que
          // deje de estar 'armando'. `armado_detenido` NO se pollea a propósito: ese
          // estado no cambia solo — solo lo mueve el botón "Reintentar armado", que ya
          // relanza este efecto. Pollearlo sería un request cada 5 s, para siempre,
          // sobre una pestaña olvidada, esperando algo que nadie va a hacer.
          if (c.estado === "armando") timer = setTimeout(cargar, POLL_ARMANDO_MS);
        })
        .catch((err: unknown) => {
          if (cancelado) return;
          setError(err instanceof Error ? err.message : "Error al cargar la corrida");
          setCargando(false);
        });
    };
    cargar();
    return () => {
      cancelado = true;
      if (timer) clearTimeout(timer);
    };
  }, [corridaId, recarga]);

  // El armado ya no vive en esta pestaña: lo corre el servidor y lo único que hay
  // para mostrar es lo persistido, con el progreso que trae la misma vista.
  const data: CorridaDetalle | null = corrida;

  if (cargando) {
    return (
      <div style={{ padding: "1rem" }} className="text-sm text-muted-foreground">
        Cargando corrida #{id}…
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: "1rem" }} className="text-sm text-destructive">
        {error}
      </div>
    );
  }

  if (!data) return null;

  const filas = control.filtradas;
  const totales = totalesDe(filas);
  const armado = data.armado;
  const motivo = armado?.ultimo_error ? partirMotivo(armado.ultimo_error) : null;
  const margenNegativo = totales.margen < 0;
  // Filas sin APU: se cuentan sobre TODOS los ítems, no sobre los filtrados —
  // el candado no depende de lo que estés mirando. El backend devuelve 409 al
  // congelar o descargar el cuadro; acá se ve antes de chocar contra la puerta.
  const nSinApu = data.items.filter((f) => !f.apu_codigo).length;
  const bloqueado = nSinApu > 0;
  const esActivar = data.modo === "congelada";
  const puedeEditar = puede(perfil?.rol, "editor");
  const nFilas = data.items.length;

  // La IA propone; aplicar lo decide el usuario. Se mira el DICTAMEN (nunca "hay
  // apu_sugerido"), igual que la celda de la tabla.
  const sugerencias: AsignacionIA[] = data.items.flatMap((f) => {
    const v = f.revision;
    if (!v || v.dictamen !== "cambiar" || !v.apu_sugerido) return [];
    return [{
      seq: f.seq,
      apu_codigo: v.apu_sugerido,
      ...(v.turno_sugerido ? { shift: v.turno_sugerido } : {}),
    }];
  });

  const motivoNoRevisar = !data.ia_disponible
    ? "El servidor no tiene IA configurada (falta ANTHROPIC_API_KEY)."
    : esActivar
      ? "La corrida está congelada; actívala para revisar."
      : data.estado === "armando"
        ? "Espera a que la corrida termine de armarse."
        : revision
          ? "La revisión con IA ya está corriendo."
          : null;

  async function revisar() {
    // El botón ya está deshabilitado mientras corre; esto es el cinturón contra el
    // doble clic que dispara los dos handlers antes del re-render.
    if (revision || !data) return;
    setRevision({ fase: "triaje", lote: 0, lotes: 0, hechos: 0, total: data.items.length });
    try {
      const resumen = await revisarCorridaStream(
        corridaId,
        // Un veredicto por fila: acá solo se cuenta. Los datos salen de la recarga,
        // que es lo que el backend efectivamente guardó.
        () => setRevision((r) => (r ? { ...r, fase: "veredictos", hechos: r.hechos + 1 } : r)),
        (p) => setRevision((r) => {
          if (!r) return r;
          if (p.evento === "started") return { ...r, total: p.total, lotes: p.lotes ?? r.lotes };
          if (p.evento === "barriendo") return { ...r, fase: "triaje", lote: p.lote, lotes: p.lotes };
          if (p.evento === "barrido") return { ...r, fase: "veredictos" };
          return r;
        }),
      );
      await recargarCorrida();
      const cuenta =
        `Revisión lista: ${resumen.cambiar} por cambiar, ${resumen.dudoso} dudosas, `
        + `${resumen.sin_apu} sin APU.`;
      // Una fila que la IA no contestó NO está aprobada: queda sin auditar. Si el
      // aviso final las omitiera (o las diera por buenas en un tono de éxito
      // tranquilo), el usuario leería "0 por cambiar" con 40 filas sin mirar. De ahí
      // el `warning` y el texto explícito; encontrarlas es el centinela del filtro.
      if (resumen.sin_veredicto > 0) {
        toast.warning(
          `${cuenta} ${resumen.sin_veredicto} sin revisar (la IA no las contestó): `
          + "no significa que estén bien. Fíltralas con «— sin revisar» en la "
          + "columna Veredicto y vuelve a revisar.",
        );
      } else {
        toast.success(cuenta);
      }
    } catch (e) {
      // Un stream que se corta a mitad NO pierde lo ya dictaminado: el backend lo
      // guarda veredicto por veredicto. Se recarga igual y se dice qué pasó.
      await recargarCorrida();
      toast.error(
        `${e instanceof Error ? e.message : "La revisión con IA falló."} `
        + "Los veredictos que alcanzó a guardar se conservan.",
      );
    } finally {
      if (montado.current) setRevision(null);
    }
  }

  /** Las N sugerencias en UNA sola llamada: un recosteo, no N. */
  async function aplicarTodas() {
    if (aplicando || sugerencias.length === 0) return;
    setAplicando(true);
    const n = sugerencias.length;
    try {
      const actualizada = await aplicarSugerencias(corridaId, sugerencias);
      if (montado.current) setCorrida(actualizada);
      toast.success(n === 1 ? "1 sugerencia aplicada" : `${n} sugerencias aplicadas`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "No se pudieron aplicar las sugerencias.");
    } finally {
      if (montado.current) setAplicando(false);
    }
  }

  return (
    <div className="flex flex-col gap-4" style={{ padding: "16px 20px" }}>
      {/* Header row */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-semibold text-foreground">
              Corrida #{data.id}
            </h2>
            {data.lista_precios_id !== null && (
              <span className="px-1.5 py-0.5 rounded text-xs font-medium bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200">
                {data.lista_nombre}
              </span>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-0.5">
            {data.archivo} &mdash; {data.estado}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-[11px] font-semibold rounded-full px-2 py-0.5 ${
            esActivar ? "bg-blue-100 text-blue-800" : "bg-green-100 text-green-800"}`}>
            {esActivar ? "Congelada" : "Activa"}
          </span>
          <Button size="sm" variant="outline"
            disabled={bloqueado && !esActivar}
            title={bloqueado && !esActivar
              ? `${nSinApu} línea(s) sin APU: asígnalas antes de congelar.`
              : undefined}
            aria-describedby={bloqueado ? "candado-sin-apu" : undefined}
            onClick={() => cambiarModo(esActivar ? "activar" : "congelar")}>
            {esActivar ? "Activar" : "Congelar"}
          </Button>
          {!esActivar && data.estado !== "armando" && (
            <Button size="sm" variant="outline" onClick={() => setAgregando(true)}>
              Agregar líneas
            </Button>
          )}
          {puedeEditar && (
            <Button size="sm" variant="outline"
              disabled={motivoNoRevisar !== null}
              title={motivoNoRevisar
                ?? "La IA audita la corrida ya armada y propone; aplicar lo decides tú."}
              onClick={revisar}>
              {revision
                ? "Revisando…"
                : `Revisar ${nFilas} ${nFilas === 1 ? "línea" : "líneas"} con IA`}
            </Button>
          )}
          {puedeEditar && !esActivar && sugerencias.length > 0 && (
            <Button size="sm" variant="outline"
              disabled={aplicando}
              title="Asigna de una vez el APU que la IA propuso para cada línea con dictamen «cambiar»."
              onClick={aplicarTodas}>
              {aplicando
                ? "Aplicando…"
                : `Aplicar ${sugerencias.length} ${
                    sugerencias.length === 1 ? "sugerencia" : "sugerencias"}`}
            </Button>
          )}
          <Button size="sm" variant="outline"
            disabled={bloqueado}
            title={bloqueado
              ? esActivar
                ? `${nSinApu} línea(s) sin APU: actívala, asígnalas y vuelve a congelar.`
                : `${nSinApu} línea(s) sin APU: asígnalas antes de descargar.`
              : undefined}
            aria-describedby={bloqueado ? "candado-sin-apu" : undefined}
            onClick={() => descargarCuadro(corridaId).catch((e) =>
              toast.error(e instanceof Error ? e.message : "No se pudo descargar el cuadro."))}>
            Descargar cuadro
          </Button>
        </div>
      </div>

      {/* Armado detenido: por qué se rindió y cómo volver a intentarlo. Es lo único
          que explica una corrida a medias que dejó de avanzar. */}
      {data.estado === "armado_detenido" && (
        <div className="flex items-start justify-between gap-3 rounded-lg border border-destructive/40 bg-destructive-surface px-3 py-2">
          <div className="min-w-0">
            <p className="text-xs font-semibold text-destructive">
              El armado se detuvo{armado ? ` en ${armado.hechos} de ${armado.total} líneas` : ""}.
            </p>
            {motivo && (
              <>
                <p className="mt-0.5 text-xs text-foreground">{motivo.humano}</p>
                {/* La cola técnica va chica, gris y cortada: sirve para reportar el
                    problema, pero el mensaje de arriba es el que le habla a la persona. */}
                {motivo.tecnico && (
                  <p className="mt-0.5 truncate text-[11px] text-muted-foreground"
                     title={motivo.tecnico}>
                    {motivo.tecnico}
                  </p>
                )}
              </>
            )}
          </div>
          {puedeEditar && (
            <Button size="sm" variant="outline" disabled={reanudando} onClick={reanudar}>
              {reanudando ? "Reanudando…" : "Reintentar armado"}
            </Button>
          )}
        </div>
      )}

      {/* Totals bar */}
      <div
        className="grid gap-px rounded-lg border bg-muted/30 overflow-hidden"
        style={{ gridTemplateColumns: "repeat(4, 1fr)" }}
      >
        <TotalStat label="Contractual" value={cop(totales.contractual)} />
        <TotalStat label="Costo" value={cop(totales.costo)} />
        <TotalStat
          label="Margen"
          value={cop(totales.margen)}
          highlight={margenNegativo ? "neg" : "pos"}
        />
        <TotalStat
          label="Margen %"
          value={pct(totales.margen_pct)}
          highlight={margenNegativo ? "neg" : "pos"}
        />
      </div>

      {/* Counters sub-line */}
      <div className="flex items-center gap-4 text-xs text-muted-foreground">
        {data.estado === "armando" && armado ? (
          <span className="font-medium text-info">
            {armado.posicion_en_cola > 0
              ? `En espera: puesto ${armado.posicion_en_cola} en la cola`
              : `Armando: ${armado.hechos} de ${armado.total}`}
          </span>
        ) : control.hayFiltros ? (
          <span>{filas.length} de {control.totalItems} ítems</span>
        ) : (
          <span>
            {totales.n_items} APUs · armada en {fmtDuracion(data.duracion_ms)}
          </span>
        )}
        {totales.n_revision > 0 && (
          <span className="text-amber-700 font-medium">
            {totales.n_revision} por revisar
          </span>
        )}
        {revision && (
          <span className="text-info font-medium">
            {revision.fase === "triaje"
              ? revision.lotes
                ? `Triaje: ${revision.lote} de ${revision.lotes} lotes listos`
                : "Triaje en curso…"
              : `Veredictos: ${revision.hechos} de ${revision.total} filas`}
          </span>
        )}
        {nSinApu > 0 && (
          <button
            type="button"
            id="candado-sin-apu"
            className="text-red-700 font-semibold underline"
            onClick={() => control.setFiltro("apu", control.filtros.apu === SIN_APU ? "" : SIN_APU)}
            title="Ver solo las líneas sin APU"
          >
            {nSinApu} sin APU
          </button>
        )}
      </div>

      {/* Resumen por capítulo. Solo aparece si la corrida vino de un presupuesto con
          capítulos (ruta IDU). El backend manda las filas YA sumadas: acá no se suma
          dinero, se pinta. */}
      {corrida && (
        <ResumenCapitulos capitulos={corrida.capitulos ?? []}
                          totales={corrida.totales} />
      )}

      {/* Dense table. `onComponer` navega a la mesa de composición y le manda la
          descripción como PISTA: antes de que exista una propuesta el expediente
          todavía no trae la actividad, y sin esto la mesa no tendría qué titular.
          Es opcional — en una recarga en frío cae al número de línea. */}
      <TablaItems
        corridaId={corridaId}
        items={filas}
        onConfirmado={(c) => setCorrida(c)}
        readOnly={data.modo === "congelada"}
        control={control}
        puedeEditar={puedeEditar}
        onComponer={(seq) => navigate(`/corridas/${corridaId}/componer/${seq}`, {
          state: { descripcion: data.items.find((f) => f.seq === seq)?.descripcion },
        })}
      />

      {agregando && (
        <DialogoAgregarLineas
          open
          corridaId={corridaId}
          onOpenChange={(v) => { if (!v) setAgregando(false); }}
          onAgregado={(c) => { setCorrida(c); setAgregando(false); }}
        />
      )}
    </div>
  );
}

// ─── local helper ────────────────────────────────────────────────────────────

function TotalStat({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string;
  highlight?: "pos" | "neg";
}) {
  const valClass =
    highlight === "neg"
      ? "text-red-600"
      : highlight === "pos"
        ? "text-green-700"
        : "text-foreground";

  return (
    <div className="flex flex-col gap-0.5 bg-background px-3 py-2">
      <span className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <span className={`text-sm font-semibold font-mono tabular-nums ${valClass}`}>
        {value}
      </span>
    </div>
  );
}
