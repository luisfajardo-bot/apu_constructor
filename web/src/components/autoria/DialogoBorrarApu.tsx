import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { ApuDetalle } from "@/lib/tipos";
import { borrarApu } from "@/api/autoria";

interface DialogoBorrarApuProps {
  apu: ApuDetalle | null;
  onOpenChange: (open: boolean) => void;
  onBorrado: () => void;
}

export function DialogoBorrarApu({ apu, onOpenChange, onBorrado }: DialogoBorrarApuProps) {
  const [borrando, setBorrando] = useState(false);
  const n = apu?.n_corridas ?? 0;

  async function confirmar() {
    if (!apu) return;
    setBorrando(true);
    try {
      await borrarApu(apu.codigo, apu.turno);
      toast.success(`APU ${apu.codigo} (${apu.turno}) borrado`);
      onOpenChange(false);
      onBorrado();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Error al borrar el APU");
    } finally {
      setBorrando(false);
    }
  }

  return (
    <Dialog open={apu !== null} onOpenChange={(v) => { if (!v) onOpenChange(false); }}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="text-sm">Borrar APU</DialogTitle>
        </DialogHeader>
        {apu && (
          <div className="flex flex-col gap-2 text-xs">
            <p>
              ¿Borrar el APU <span className="font-mono">{apu.codigo}</span> ({apu.turno})
              — {apu.nombre}?
            </p>
            {n > 0 && (
              <p className="text-muted-foreground">
                Este APU está referenciado en {n} corrida{n === 1 ? "" : "s"}. Las corridas
                ya armadas conservan su composición y no se verán afectadas.
              </p>
            )}
          </div>
        )}
        <DialogFooter>
          <Button size="sm" variant="outline" onClick={() => onOpenChange(false)} disabled={borrando}>
            Cancelar
          </Button>
          <Button size="sm" variant="destructive" onClick={confirmar} disabled={borrando}>
            {borrando ? "Borrando…" : "Borrar"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
