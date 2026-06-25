import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { Insumo, InsumoDetalle } from "@/lib/tipos";
import { getInsumo, aplicarCambios } from "@/api/insumos";
import { useDirtyRows } from "@/lib/useDirtyRows";
import { cop as fmtMoneda } from "@/lib/moneda";

interface TablaInsumosProps {
  insumos: Insumo[];
  onReload: () => void;
}

export function TablaInsumos({ insumos, onReload }: TablaInsumosProps) {
  const { setCampo, descartar, cambios, count, dirty } = useDirtyRows(
    insumos.map((i) => ({ id: i.id, precio: i.precio, fuente: i.fuente }))
  );

  const [detalle, setDetalle] = useState<InsumoDetalle | null>(null);
  const [detalleOpen, setDetalleOpen] = useState(false);
  const [guardando, setGuardando] = useState(false);

  async function abrirDetalle(id: number) {
    try {
      const d = await getInsumo(id);
      setDetalle(d);
      setDetalleOpen(true);
    } catch {
      toast.error("No se pudo cargar el detalle del insumo");
    }
  }

  async function guardar() {
    const cs = cambios();
    if (cs.length === 0) return;
    setGuardando(true);
    try {
      const res = await aplicarCambios(cs);
      const errCount = res.errores?.length ?? 0;
      if (errCount === 0) {
        toast.success(`${res.aplicados} cambio(s) guardado(s) correctamente`);
      } else {
        toast.warning(
          `${res.aplicados} aplicado(s), ${errCount} error(es): ` +
            res.errores.map((e) => `#${e.insumo_id}: ${e.error}`).join("; ")
        );
      }
      descartar();
      onReload();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Error desconocido";
      toast.error(`No se pudo guardar: ${msg}`);
    } finally {
      setGuardando(false);
    }
  }

  return (
    <div className="flex flex-col flex-1 overflow-hidden relative">
      {/* Table area */}
      <div className="flex-1 overflow-auto">
        <table className="w-full text-xs border-collapse">
          <thead className="sticky top-0 z-10 bg-muted/80 backdrop-blur">
            <tr>
              <th className="px-2 py-1.5 text-left font-medium text-muted-foreground border-b w-28">
                Código
              </th>
              <th className="px-2 py-1.5 text-left font-medium text-muted-foreground border-b">
                Nombre
              </th>
              <th className="px-2 py-1.5 text-left font-medium text-muted-foreground border-b w-14">
                Unidad
              </th>
              <th className="px-2 py-1.5 text-left font-medium text-muted-foreground border-b w-28">
                Grupo
              </th>
              <th className="px-2 py-1.5 text-right font-medium text-muted-foreground border-b w-28">
                Precio
              </th>
              <th className="px-2 py-1.5 text-left font-medium text-muted-foreground border-b w-32">
                Fuente
              </th>
              <th className="px-2 py-1.5 text-left font-medium text-muted-foreground border-b w-20">
                Clasif.
              </th>
            </tr>
          </thead>
          <tbody>
            {insumos.map((ins) => {
              const isDirty = !!dirty[ins.id];
              const precioEdit =
                dirty[ins.id]?.precio !== undefined
                  ? dirty[ins.id].precio
                  : ins.precio;
              const fuenteEdit =
                dirty[ins.id]?.fuente !== undefined
                  ? dirty[ins.id].fuente
                  : ins.fuente;

              return (
                <tr
                  key={ins.id}
                  className={
                    isDirty
                      ? "bg-amber-50 dark:bg-amber-950/30 hover:bg-amber-100 dark:hover:bg-amber-900/40"
                      : "hover:bg-muted/40 even:bg-muted/10"
                  }
                >
                  {/* Clickable zone - código */}
                  <td
                    className="px-2 py-1 font-mono cursor-pointer select-none"
                    onClick={() => abrirDetalle(ins.id)}
                    title="Ver detalle e historial"
                  >
                    {ins.codigo}
                  </td>
                  {/* Clickable zone - nombre */}
                  <td
                    className="px-2 py-1 cursor-pointer select-none truncate max-w-xs"
                    onClick={() => abrirDetalle(ins.id)}
                    title={ins.nombre}
                  >
                    {ins.nombre}
                  </td>
                  {/* Clickable zone - unidad */}
                  <td
                    className="px-2 py-1 text-muted-foreground cursor-pointer"
                    onClick={() => abrirDetalle(ins.id)}
                  >
                    {ins.unidad}
                  </td>
                  {/* Clickable zone - grupo */}
                  <td
                    className="px-2 py-1 text-muted-foreground truncate cursor-pointer"
                    onClick={() => abrirDetalle(ins.id)}
                  >
                    {ins.grupo}
                  </td>
                  {/* Editable - precio */}
                  <td className="px-1 py-0.5 text-right">
                    <Input
                      type="number"
                      className="h-6 w-24 text-xs text-right ml-auto"
                      value={precioEdit as number}
                      min={0}
                      step="any"
                      onChange={(e) =>
                        setCampo(ins.id, "precio", parseFloat(e.target.value) || 0)
                      }
                    />
                  </td>
                  {/* Editable - fuente */}
                  <td className="px-1 py-0.5">
                    <Input
                      type="text"
                      className="h-6 text-xs"
                      value={fuenteEdit as string}
                      onChange={(e) => setCampo(ins.id, "fuente", e.target.value)}
                      list={`fuentes-${ins.id}`}
                    />
                  </td>
                  {/* Clasif */}
                  <td
                    className="px-2 py-1 text-muted-foreground cursor-pointer"
                    onClick={() => abrirDetalle(ins.id)}
                  >
                    <span
                      className={
                        ins.clasificacion === "publico"
                          ? "text-blue-600 dark:text-blue-400"
                          : "text-orange-600 dark:text-orange-400"
                      }
                    >
                      {ins.clasificacion}
                    </span>
                  </td>
                </tr>
              );
            })}
            {insumos.length === 0 && (
              <tr>
                <td
                  colSpan={7}
                  className="px-3 py-8 text-center text-muted-foreground text-sm"
                >
                  Sin resultados
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Sticky bottom action bar */}
      {count > 0 && (
        <div className="sticky bottom-0 z-20 flex items-center gap-3 border-t bg-background px-4 py-2 shadow-[0_-2px_8px_rgba(0,0,0,.08)]">
          <span className="text-sm text-amber-700 dark:text-amber-400 font-medium">
            {count} cambio{count !== 1 ? "s" : ""} sin guardar
          </span>
          <div className="ml-auto flex gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={descartar}
              disabled={guardando}
            >
              Descartar
            </Button>
            <Button size="sm" onClick={guardar} disabled={guardando}>
              {guardando ? "Guardando…" : "Guardar"}
            </Button>
          </div>
        </div>
      )}

      {/* Detail drawer/dialog */}
      <Dialog open={detalleOpen} onOpenChange={setDetalleOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="text-sm font-mono">
              {detalle?.insumo.codigo} — {detalle?.insumo.nombre}
            </DialogTitle>
          </DialogHeader>
          {detalle && (
            <div className="space-y-3">
              {/* Current data */}
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                <span className="text-muted-foreground">Unidad</span>
                <span>{detalle.insumo.unidad}</span>
                <span className="text-muted-foreground">Grupo</span>
                <span>{detalle.insumo.grupo}</span>
                <span className="text-muted-foreground">Precio vigente</span>
                <span className="font-medium">{fmtMoneda(detalle.insumo.precio)}</span>
                <span className="text-muted-foreground">Fuente</span>
                <span>{detalle.insumo.fuente}</span>
                <span className="text-muted-foreground">Clasificación</span>
                <span>{detalle.insumo.clasificacion}</span>
              </div>

              {/* History */}
              <div>
                <p className="text-xs font-medium text-muted-foreground mb-1 uppercase tracking-wide">
                  Historial de precios
                </p>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs border-collapse">
                    <thead>
                      <tr className="bg-muted/60">
                        <th className="px-2 py-1 text-left font-medium border-b">Fecha</th>
                        <th className="px-2 py-1 text-right font-medium border-b">Precio</th>
                        <th className="px-2 py-1 text-left font-medium border-b">Fuente</th>
                        <th className="px-2 py-1 text-left font-medium border-b">Clasif.</th>
                        <th className="px-2 py-1 text-center font-medium border-b">Vigente</th>
                      </tr>
                    </thead>
                    <tbody>
                      {detalle.historial.map((h, i) => (
                        <tr
                          key={i}
                          className={h.vigente ? "font-medium bg-green-50 dark:bg-green-950/20" : "hover:bg-muted/30"}
                        >
                          <td className="px-2 py-0.5 font-mono">{h.fecha}</td>
                          <td className="px-2 py-0.5 text-right">{fmtMoneda(h.precio)}</td>
                          <td className="px-2 py-0.5">{h.fuente}</td>
                          <td className="px-2 py-0.5 text-muted-foreground">{h.clasificacion}</td>
                          <td className="px-2 py-0.5 text-center">
                            {h.vigente ? (
                              <span className="text-green-600 dark:text-green-400">si</span>
                            ) : (
                              <span className="text-muted-foreground">-</span>
                            )}
                          </td>
                        </tr>
                      ))}
                      {detalle.historial.length === 0 && (
                        <tr>
                          <td colSpan={5} className="px-2 py-4 text-center text-muted-foreground">
                            Sin historial
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
