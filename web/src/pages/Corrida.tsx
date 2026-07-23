import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import TablaItems from "@/components/corrida/TablaItems";
import { getCorrida, descargarCuadro, congelarCorrida, activarCorrida } from "@/api/corridas";
import { cop, pct } from "@/lib/moneda";
import { fmtDuracion } from "@/lib/tiempo";
import { useArmadoVivo } from "@/lib/armado";
import { useCorridaTabla } from "@/lib/corridaTabla";
import type { CorridaDetalle, ItemCuadro, Totales } from "@/lib/tipos";

const REVISABLE = new Set(["review", "new", "REVIEW", "NEW"]);

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
  const vivo = useArmadoVivo();
  const live = vivo.corridaId === corridaId && vivo.estado === "armando";

  const [corrida, setCorrida] = useState<CorridaDetalle | null>(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const control = useCorridaTabla(corrida?.items ?? []);

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
    if (live) {
      // Mientras se arma en vivo en esta pestaña, la tabla viene del stream; no se
      // consulta el backend (al terminar, `live` pasa a false y se relee abajo).
      setCargando(false);
      return;
    }
    let cancelado = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    setError(null);
    const cargar = () => {
      getCorrida(corridaId)
        .then((c) => {
          if (cancelado) return;
          setCorrida(c);
          setCargando(false);
          // Recarga durante un armado sin stream local (p. ej. otra pestaña):
          // refrescar hasta que deje de estar 'armando'.
          if (c.estado === "armando") timer = setTimeout(cargar, 2000);
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
  }, [corridaId, live]);

  // Datos a mostrar: en vivo desde el stream, o lo persistido.
  const data: CorridaDetalle | null = live
    ? {
        id: corridaId,
        nombre: "(armando)",
        archivo: "(armando)",
        estado: "armando",
        items: vivo.filas,
        totales: totalesDe(vivo.filas),
        duracion_ms: null,
        modo: "activa",
        carpeta_id: null,
      }
    : corrida;

  if (!live && cargando) {
    return (
      <div style={{ padding: "1rem" }} className="text-sm text-muted-foreground">
        Cargando corrida #{id}…
      </div>
    );
  }

  if (!live && error) {
    return (
      <div style={{ padding: "1rem" }} className="text-sm text-destructive">
        {error}
      </div>
    );
  }

  if (!data) return null;

  const filas = live ? data.items : control.filtradas;
  const totales = live ? data.totales : totalesDe(filas);
  const margenNegativo = totales.margen < 0;

  return (
    <div className="flex flex-col gap-4" style={{ padding: "16px 20px" }}>
      {/* Header row */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h2 className="text-sm font-semibold text-foreground">
            Corrida #{data.id}
          </h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            {data.archivo} &mdash; {data.estado}
          </p>
        </div>
        {!live && (
          <div className="flex items-center gap-2">
            <span className={`text-[11px] font-semibold rounded-full px-2 py-0.5 ${
              data.modo === "congelada" ? "bg-blue-100 text-blue-800" : "bg-green-100 text-green-800"}`}>
              {data.modo === "congelada" ? "Congelada" : "Activa"}
            </span>
            <Button size="sm" variant="outline"
              onClick={() => cambiarModo(data.modo === "congelada" ? "activar" : "congelar")}>
              {data.modo === "congelada" ? "Activar" : "Congelar"}
            </Button>
            <Button size="sm" variant="outline"
              onClick={() => descargarCuadro(corridaId).catch((e) =>
                toast.error(e instanceof Error ? e.message : "No se pudo descargar el cuadro."))}>
              Descargar cuadro
            </Button>
          </div>
        )}
      </div>

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
        {live ? (
          <span className="text-blue-700 font-medium">
            Armando {vivo.filas.length}/{vivo.total}…
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
      </div>

      {/* Dense table (se llena APU por APU en vivo) */}
      <TablaItems
        corridaId={corridaId}
        items={filas}
        onConfirmado={(c) => setCorrida(c)}
        readOnly={data.modo === "congelada"}
        control={live ? undefined : control}
      />
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
