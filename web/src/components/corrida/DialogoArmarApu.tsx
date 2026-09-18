import { useState } from "react";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { DialogoAgregarApu } from "@/components/autoria/DialogoAgregarApu";
import BuscadorApu from "@/components/corrida/BuscadorApu";
import { getApuDetalle } from "@/api/autoria";
import type { ApuDetalle, DetalleItem } from "@/lib/tipos";

interface Props {
  abierto: boolean;
  /** La fila desde la que se arma. */
  detalle: DetalleItem;
  onCerrar: () => void;
  /** El APU quedó creado. El llamador lo asigna a la fila. */
  onCreado: (codigo: string, turno: string) => void;
}

/** Elige el punto de partida para armar un APU parado en una fila de corrida y le
 *  entrega a `DialogoAgregarApu` el `(modo, inicial)` que corresponda.
 *
 *  Existe para NO tocar `DialogoAgregarApu`: tiene 822 líneas y lo usan otras dos
 *  pantallas. Sus modos `crear` y `duplicar` con `inicial` ya hacen lo que hace falta;
 *  lo que faltaba era el camino de entrada. */
export default function DialogoArmarApu({ abierto, detalle, onCerrar, onCreado }: Props) {
  // null = todavía estás eligiendo. Con valor, se muestra el alta ya cargada.
  const [partida, setPartida] = useState<
    { modo: "crear" | "duplicar"; inicial: ApuDetalle } | null
  >(null);
  const [cargando, setCargando] = useState(false);

  /** Lee el APU real de la biblioteca: la composición de la fila es la costeada y no
   *  trae las marcas de sub-APU, así que duplicar desde ahí perdería información. */
  async function partirDe(codigo: string, turno: string) {
    if (cargando) return;
    setCargando(true);
    try {
      setPartida({ modo: "duplicar", inicial: await getApuDetalle(codigo, turno) });
    } catch {
      toast.error("No se pudo leer ese APU de la biblioteca.");
    } finally {
      setCargando(false);
    }
  }

  function desdeCero() {
    setPartida({
      modo: "crear",
      inicial: {
        // El código que pedía el presupuesto. Si ese APU existiera, el armado ya lo
        // habría asignado: que la fila no lo tenga es justamente por qué hay que crearlo.
        codigo: detalle.codigo_sugerido,
        turno: detalle.apu_turno,
        nombre: detalle.descripcion,
        unidad: detalle.unidad,
        grupo: "",                 // lo eliges en el alta
        costo_unitario: 0,
        composicion: [],           // el alta abre con una fila en blanco
      },
    });
  }

  if (partida) {
    return (
      <DialogoAgregarApu
        open
        onOpenChange={(v) => { if (!v) onCerrar(); }}
        onCreado={onCreado}
        modo={partida.modo}
        inicial={partida.inicial}
      />
    );
  }

  return (
    <Dialog open={abierto} onOpenChange={(v) => { if (!v) onCerrar(); }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Armar APU para esta línea</DialogTitle>
        </DialogHeader>
        <p className="text-xs text-muted-foreground -mt-2 break-words">
          {detalle.descripcion}
        </p>

        <div className="flex flex-col gap-2 pt-1">
          {detalle.apu_codigo && (
            <Button variant="outline" className="justify-start h-auto py-2"
              disabled={cargando}
              onClick={() => partirDe(detalle.apu_codigo, detalle.apu_turno)}>
              <span className="flex flex-col items-start gap-0.5 text-left">
                <span className="text-xs font-semibold">Duplicar el APU asignado</span>
                <span className="text-[11px] text-muted-foreground">
                  {detalle.apu_codigo} — {detalle.apu_nombre}
                </span>
              </span>
            </Button>
          )}

          <Button variant="outline" className="justify-start h-auto py-2"
            disabled={cargando} onClick={desdeCero}>
            <span className="flex flex-col items-start gap-0.5 text-left">
              <span className="text-xs font-semibold">Desde cero</span>
              <span className="text-[11px] text-muted-foreground">
                Con el nombre, la unidad y el código de la actividad ya puestos.
              </span>
            </span>
          </Button>

          <div className="rounded border border-border p-2">
            <p className="text-[11px] font-semibold mb-1">Partir de otro APU</p>
            <BuscadorApu disabled={cargando}
              placeholder="Buscar el APU del que quieres partir…"
              onElegir={(apu) => partirDe(apu.codigo, apu.turno)} />
          </div>
        </div>

        <div className="flex justify-end pt-2">
          <Button size="sm" variant="outline" onClick={onCerrar}>Cancelar</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
