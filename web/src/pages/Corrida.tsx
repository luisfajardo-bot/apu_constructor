import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Button } from "@/components/ui/button";
import TablaItems from "@/components/corrida/TablaItems";
import { getCorrida, descargarCuadroUrl } from "@/api/corridas";
import { cop, pct } from "@/lib/moneda";
import { fmtDuracion } from "@/lib/tiempo";
import type { CorridaDetalle } from "@/lib/tipos";

export default function Corrida() {
  const { id } = useParams<{ id: string }>();
  const corridaId = Number(id);

  const [corrida, setCorrida] = useState<CorridaDetalle | null>(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setCargando(true);
    setError(null);
    getCorrida(corridaId)
      .then(setCorrida)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Error al cargar la corrida"),
      )
      .finally(() => setCargando(false));
  }, [corridaId]);

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

  if (!corrida) return null;

  const { totales } = corrida;
  const margenNegativo = totales.margen < 0;

  return (
    <div className="flex flex-col gap-4" style={{ padding: "16px 20px" }}>
      {/* Header row */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h2 className="text-sm font-semibold text-foreground">
            Corrida #{corrida.id}
          </h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            {corrida.archivo} &mdash; {corrida.estado}
          </p>
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={() => window.open(descargarCuadroUrl(corridaId))}
        >
          Descargar cuadro
        </Button>
      </div>

      {/* Totals bar */}
      <div
        className="grid gap-px rounded-lg border bg-muted/30 overflow-hidden"
        style={{ gridTemplateColumns: "repeat(4, 1fr)" }}
      >
        <TotalStat
          label="Contractual"
          value={cop(totales.contractual)}
        />
        <TotalStat
          label="Costo"
          value={cop(totales.costo)}
        />
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
        <span>{totales.n_items} APUs · armada en {fmtDuracion(corrida.duracion_ms)}</span>
        {totales.n_revision > 0 && (
          <span className="text-amber-700 font-medium">
            {totales.n_revision} por revisar
          </span>
        )}
      </div>

      {/* Dense table */}
      <TablaItems
        corridaId={corridaId}
        items={corrida.items}
        onConfirmado={(c) => setCorrida(c)}
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
