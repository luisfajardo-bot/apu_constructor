import { useEffect, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import EstadoBadge from "@/components/corrida/EstadoBadge";
import { getItem, confirmar } from "@/api/corridas";
import { cop } from "@/lib/moneda";
import type { DetalleItem, CorridaDetalle } from "@/lib/tipos";

interface PanelRevisionProps {
  corridaId: number;
  seq: number | null;
  onClose: () => void;
  onConfirmed: (corrida: CorridaDetalle) => void;
}

export default function PanelRevision({
  corridaId,
  seq,
  onClose,
  onConfirmed,
}: PanelRevisionProps) {
  const open = seq !== null;
  const [detalle, setDetalle] = useState<DetalleItem | null>(null);
  const [cargando, setCargando] = useState(false);
  const [confirmando, setConfirmando] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Load item detail whenever seq changes
  useEffect(() => {
    if (seq === null) {
      setDetalle(null);
      setError(null);
      return;
    }
    setCargando(true);
    setError(null);
    getItem(corridaId, seq)
      .then(setDetalle)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "Error al cargar ítem"),
      )
      .finally(() => setCargando(false));
  }, [corridaId, seq]);

  async function handleConfirmar(apuCodigo: string) {
    if (seq === null) return;
    setConfirmando(apuCodigo);
    try {
      const corridaActualizada = await confirmar(corridaId, seq, apuCodigo);
      onConfirmed(corridaActualizada);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al confirmar");
    } finally {
      setConfirmando(null);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="text-sm font-semibold">
            {detalle ? detalle.descripcion : "Cargando…"}
          </DialogTitle>
        </DialogHeader>

        {cargando && (
          <p className="text-xs text-muted-foreground py-4 text-center">
            Cargando detalle…
          </p>
        )}

        {error && (
          <p className="text-xs text-destructive py-2">{error}</p>
        )}

        {detalle && !cargando && (
          <div className="flex flex-col gap-4 text-xs">
            {/* Header info */}
            <div className="flex items-center gap-3 flex-wrap">
              <EstadoBadge status={detalle.status} />
              <span className="font-mono text-muted-foreground">
                APU: {detalle.apu_codigo}
              </span>
              <span className="text-muted-foreground truncate max-w-xs">
                {detalle.apu_nombre}
              </span>
            </div>

            {detalle.explicacion && (
              <p className="text-muted-foreground italic border-l-2 border-muted pl-2">
                {detalle.explicacion}
              </p>
            )}

            {/* Candidates */}
            {detalle.candidatos.length > 0 && (
              <section>
                <h3 className="font-semibold text-xs mb-1 uppercase tracking-wide text-muted-foreground">
                  Candidatos
                </h3>
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
                        <TableCell className="text-xs font-mono">
                          {c.apu_codigo}
                        </TableCell>
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
                            variant={
                              c.apu_codigo === detalle.apu_codigo
                                ? "default"
                                : "outline"
                            }
                            disabled={confirmando !== null}
                            onClick={() => handleConfirmar(c.apu_codigo)}
                          >
                            {confirmando === c.apu_codigo
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

            {/* Costed composition */}
            {detalle.composicion.length > 0 && (
              <section>
                <h3 className="font-semibold text-xs mb-1 uppercase tracking-wide text-muted-foreground">
                  Composición costeada — costo unitario{" "}
                  <span className="font-mono">{cop(detalle.costo_unitario)}</span>
                </h3>
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

            {/* Confirm current APU shortcut */}
            {(detalle.status === "review" ||
              detalle.status === "REVIEW" ||
              detalle.status === "new" ||
              detalle.status === "NEW") && (
              <div className="flex justify-end gap-2 pt-1">
                <Button
                  size="sm"
                  disabled={confirmando !== null}
                  onClick={() => handleConfirmar(detalle.apu_codigo)}
                >
                  {confirmando === detalle.apu_codigo
                    ? "Confirmando…"
                    : `Confirmar APU actual (${detalle.apu_codigo})`}
                </Button>
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
