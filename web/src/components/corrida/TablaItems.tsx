import { useState, Fragment } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import EstadoBadge from "@/components/corrida/EstadoBadge";
import BuscadorApu from "@/components/corrida/BuscadorApu";
import { cop, pct } from "@/lib/moneda";
import { getItem, confirmar } from "@/api/corridas";
import type { ItemCuadro, DetalleItem, CorridaDetalle } from "@/lib/tipos";

interface TablaItemsProps {
  corridaId: number;
  items: ItemCuadro[];
  onConfirmado: (corridaActualizada: CorridaDetalle) => void;
}

const REVISABLE = new Set(["review", "new", "REVIEW", "NEW"]);

type EstadoExpansion = DetalleItem | "cargando" | "error";

export default function TablaItems({
  corridaId,
  items,
  onConfirmado,
}: TablaItemsProps) {
  const [soloRevision, setSoloRevision] = useState(false);
  // Record<seq, EstadoExpansion | undefined>
  const [expandido, setExpandido] = useState<Record<number, EstadoExpansion | undefined>>({});
  const [confirmando, setConfirmando] = useState<string | null>(null);
  const [errorConfirm, setErrorConfirm] = useState<Record<number, string>>({});

  const nPorRevisar = items.filter((it) => REVISABLE.has(it.status)).length;
  const visible = soloRevision
    ? items.filter((it) => REVISABLE.has(it.status))
    : items;

  async function toggleExpand(seq: number) {
    const actual = expandido[seq];

    if (actual !== undefined) {
      // Colapsar
      setExpandido((prev) => ({ ...prev, [seq]: undefined }));
      return;
    }

    // Primer despliegue: lazy fetch
    setExpandido((prev) => ({ ...prev, [seq]: "cargando" }));
    try {
      const detalle = await getItem(corridaId, seq);
      setExpandido((prev) => ({ ...prev, [seq]: detalle }));
    } catch {
      setExpandido((prev) => ({ ...prev, [seq]: "error" }));
    }
  }

  async function handleConfirmar(seq: number, apuCodigo: string, shift?: string) {
    setConfirmando(apuCodigo + "@" + seq);
    setErrorConfirm((prev) => ({ ...prev, [seq]: "" }));
    try {
      const corridaActualizada = await confirmar(corridaId, seq, apuCodigo, shift);
      // Colapsar la fila y refrescar el detalle para mostrar nuevo estado
      setExpandido((prev) => ({ ...prev, [seq]: undefined }));
      onConfirmado(corridaActualizada);
    } catch (err) {
      setErrorConfirm((prev) => ({
        ...prev,
        [seq]: err instanceof Error ? err.message : "Error al confirmar",
      }));
    } finally {
      setConfirmando(null);
    }
  }

  // Total columns = 1 (chevron) + 9 data cols = 10
  const TOTAL_COLS = 10;

  return (
    <div className="flex flex-col gap-2">
      {/* Filter bar */}
      <div className="flex items-center gap-3 px-1">
        <label className="flex items-center gap-1.5 cursor-pointer select-none text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={soloRevision}
            onChange={(e) => setSoloRevision(e.target.checked)}
            className="cursor-pointer"
          />
          Solo revisión
        </label>
        {nPorRevisar > 0 && (
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-800">
            {nPorRevisar} por revisar
          </span>
        )}
      </div>

      {/* Dense table */}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-6 px-1" />
            <TableHead className="text-xs">Descripción</TableHead>
            <TableHead className="text-xs w-12">Und</TableHead>
            <TableHead className="text-xs w-20 text-right">Cantidad</TableHead>
            <TableHead className="text-xs w-28">APU</TableHead>
            <TableHead className="text-xs w-20">Estado</TableHead>
            <TableHead className="text-xs w-28 text-right">Contractual</TableHead>
            <TableHead className="text-xs w-28 text-right">Costo</TableHead>
            <TableHead className="text-xs w-28 text-right">Margen</TableHead>
            <TableHead className="text-xs w-16 text-right">%</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {visible.map((it) => {
            const estado = expandido[it.seq];
            const abierto = estado !== undefined;

            return (
              <Fragment key={it.seq}>
                <TableRow className="hover:bg-muted/40">
                  {/* Chevron control */}
                  <TableCell className="w-6 px-1 py-1">
                    <button
                      type="button"
                      aria-label={abierto ? "Colapsar fila" : "Expandir fila"}
                      onClick={() => toggleExpand(it.seq)}
                      className="flex items-center justify-center w-5 h-5 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
                    >
                      <svg
                        xmlns="http://www.w3.org/2000/svg"
                        viewBox="0 0 16 16"
                        fill="currentColor"
                        className={`w-3 h-3 transition-transform ${abierto ? "rotate-90" : ""}`}
                      >
                        <path
                          fillRule="evenodd"
                          d="M6.22 4.22a.75.75 0 0 1 1.06 0l3.25 3.25a.75.75 0 0 1 0 1.06l-3.25 3.25a.75.75 0 0 1-1.06-1.06L9.19 8 6.22 5.03a.75.75 0 0 1 0-1.06Z"
                          clipRule="evenodd"
                        />
                      </svg>
                    </button>
                  </TableCell>
                  <TableCell className="text-xs max-w-[240px] truncate">
                    {it.descripcion}
                  </TableCell>
                  <TableCell className="text-xs">{it.unidad}</TableCell>
                  <TableCell className="text-xs text-right font-mono">
                    {it.cantidad.toLocaleString("es-CO")}
                  </TableCell>
                  <TableCell className="text-xs font-mono text-muted-foreground">
                    {it.apu_codigo}
                  </TableCell>
                  <TableCell className="text-xs">
                    <EstadoBadge status={it.status} />
                  </TableCell>
                  <TableCell className="text-xs text-right font-mono tabular-nums">
                    {cop(it.contractual_total)}
                  </TableCell>
                  <TableCell className="text-xs text-right font-mono tabular-nums">
                    {cop(it.costo_total)}
                  </TableCell>
                  <TableCell className="text-xs text-right font-mono tabular-nums">
                    {cop(it.margen_total)}
                  </TableCell>
                  <TableCell className="text-xs text-right font-mono tabular-nums">
                    {pct(it.margen_pct)}
                  </TableCell>
                </TableRow>

                {/* Inline expansion row */}
                {abierto && (
                  <TableRow key={`expand-${it.seq}`} className="bg-muted/20 hover:bg-muted/20">
                    <TableCell colSpan={TOTAL_COLS} className="px-8 py-3">
                      {estado === "cargando" && (
                        <p className="text-xs text-muted-foreground py-2">
                          cargando…
                        </p>
                      )}
                      {estado === "error" && (
                        <p className="text-xs text-destructive py-2">
                          Error al cargar el detalle.
                        </p>
                      )}
                      {estado !== "cargando" && estado !== "error" && (
                        <DetalleExpandido
                          detalle={estado}
                          seq={it.seq}
                          confirmando={confirmando}
                          errorConfirm={errorConfirm[it.seq]}
                          onConfirmar={handleConfirmar}
                        />
                      )}
                    </TableCell>
                  </TableRow>
                )}
              </Fragment>
            );
          })}
          {visible.length === 0 && (
            <TableRow>
              <TableCell
                colSpan={TOTAL_COLS}
                className="text-center text-xs text-muted-foreground py-6"
              >
                No hay ítems{soloRevision ? " por revisar" : ""}.
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
}

// ─── inline expand content ────────────────────────────────────────────────────

interface DetalleExpandidoProps {
  detalle: DetalleItem;
  seq: number;
  confirmando: string | null;
  errorConfirm: string | undefined;
  onConfirmar: (seq: number, apuCodigo: string, shift?: string) => void;
}

function DetalleExpandido({
  detalle,
  seq,
  confirmando,
  errorConfirm,
  onConfirmar,
}: DetalleExpandidoProps) {
  const esRevisable = REVISABLE.has(detalle.status);

  return (
    <div className="flex flex-col gap-3">
      {/* APU header */}
      <div className="flex items-center gap-3 flex-wrap text-xs">
        <EstadoBadge status={detalle.status} />
        <span className="font-mono text-muted-foreground">APU: {detalle.apu_codigo}</span>
        <span className="text-muted-foreground truncate max-w-xs">{detalle.apu_nombre}</span>
      </div>

      {/* Explicacion (review/new) */}
      {detalle.explicacion && (
        <p className="text-xs text-muted-foreground italic border-l-2 border-muted pl-2">
          {detalle.explicacion}
        </p>
      )}

      {/* Candidates (review/new only) */}
      {detalle.candidatos.length > 0 && (
        <section>
          <h4 className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground mb-1">
            Candidatos
          </h4>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-xs">Código</TableHead>
                <TableHead className="text-xs">Nombre</TableHead>
                <TableHead className="text-xs w-14 text-right">Score</TableHead>
                <TableHead className="text-xs">Motivo</TableHead>
                <TableHead className="text-xs w-24" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {detalle.candidatos.map((c) => (
                <TableRow key={c.apu_codigo}>
                  <TableCell className="text-xs font-mono">{c.apu_codigo}</TableCell>
                  <TableCell className="text-xs max-w-[200px] truncate">
                    {c.apu_nombre}
                  </TableCell>
                  <TableCell className="text-xs text-right font-mono">
                    {(c.score * 100).toFixed(0)}%
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground max-w-[160px] truncate">
                    {c.motivo}
                  </TableCell>
                  <TableCell className="text-xs">
                    <Button
                      size="xs"
                      variant={c.apu_codigo === detalle.apu_codigo ? "default" : "outline"}
                      disabled={confirmando !== null}
                      onClick={() => onConfirmar(seq, c.apu_codigo)}
                    >
                      {confirmando === c.apu_codigo + "@" + seq
                        ? "Confirmando…"
                        : "Elegir"}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </section>
      )}

      {/* Reasignar a cualquier APU de la biblioteca (todos los ítems) */}
      <section>
        <h4 className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground mb-1">
          Cambiar APU
        </h4>
        <BuscadorApu
          disabled={confirmando !== null}
          onElegir={(apu) => onConfirmar(seq, apu.codigo, apu.turno)}
        />
      </section>

      {errorConfirm && (
        <p className="text-xs text-destructive">{errorConfirm}</p>
      )}

      {/* Composition table */}
      {detalle.composicion.length > 0 && (
        <section>
          <h4 className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground mb-1">
            Composición costeada &mdash; costo unitario{" "}
            <span className="font-mono">{cop(detalle.costo_unitario)}</span>
          </h4>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-xs">Insumo</TableHead>
                <TableHead className="text-xs w-12">Und</TableHead>
                <TableHead className="text-xs w-16 text-right">Rend.</TableHead>
                <TableHead className="text-xs w-24 text-right">Precio</TableHead>
                <TableHead className="text-xs w-24 text-right">Costo</TableHead>
                <TableHead className="text-xs w-16">Cruce</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {detalle.composicion.map((lin, i) => (
                <TableRow key={i}>
                  <TableCell className="text-xs max-w-[200px] truncate">
                    {lin.insumo_nombre}
                  </TableCell>
                  <TableCell className="text-xs">{lin.unidad}</TableCell>
                  <TableCell className="text-xs text-right font-mono tabular-nums">
                    {lin.rendimiento.toLocaleString("es-CO", {
                      maximumFractionDigits: 4,
                    })}
                  </TableCell>
                  <TableCell className="text-xs text-right font-mono tabular-nums">
                    {cop(lin.precio_unitario)}
                  </TableCell>
                  <TableCell className="text-xs text-right font-mono tabular-nums">
                    {cop(lin.costo)}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {lin.calidad_cruce}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </section>
      )}

      {/* Confirm current APU (review/new) */}
      {esRevisable && (
        <div className="flex items-center justify-between gap-2 pt-1">
          <div className="ml-auto">
            <Button
              size="sm"
              disabled={confirmando !== null}
              onClick={() => onConfirmar(seq, detalle.apu_codigo)}
            >
              {confirmando === detalle.apu_codigo + "@" + seq
                ? "Confirmando…"
                : `Confirmar APU actual (${detalle.apu_codigo})`}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
