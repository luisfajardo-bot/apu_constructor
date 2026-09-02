import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { DialogoAgregarApu } from "@/components/autoria/DialogoAgregarApu";
import { componerItem } from "@/api/corridas";
import type { ApuDetalle, ComposicionPropuesta } from "@/lib/tipos";

interface Props {
  open: boolean;
  corridaId: number;
  seq: number;
  /** La actividad de la licitación que se está componiendo (para el título). */
  descripcion: string;
  onOpenChange: (open: boolean) => void;
  /** `codigo`/`turno` del APU que el USUARIO acabó de crear con la propuesta. */
  onCreado: (codigo: string, turno: string) => void;
}

/** Turno de la cabecera del alta: su select solo tiene estos dos valores, y un
 *  `shift` raro dejaría el campo en blanco sin que se note. */
function turnoDe(shift: string): string {
  return shift.toUpperCase().startsWith("N") ? "NOCTURNO" : "DIURNO";
}

/** La propuesta con la forma que el alta de APUs sabe precargar. `codigo` y
 *  `grupo` van vacíos A PROPÓSITO: son la identidad del APU y las elige el
 *  usuario; los precios van en 0 porque la IA nunca los vio. */
function apuDesdePropuesta(p: ComposicionPropuesta): ApuDetalle {
  return {
    codigo: "",
    turno: turnoDe(p.shift),
    nombre: p.nombre,
    unidad: p.unidad,
    grupo: "",
    costo_unitario: 0,
    composicion: p.componentes.map((c) => ({
      insumo_codigo: c.insumo_codigo,
      insumo_nombre: c.insumo_nombre,
      unidad: c.unidad,
      rendimiento: c.rendimiento,
      precio_unitario: 0,
      fuente_precio: "",
      costo: 0,
      calidad_cruce: "",
    })),
  };
}

/** Le pide a la IA una composición para una fila sin APU y la MUESTRA. No crea
 *  nada: crear el APU es el alta de siempre, y la dispara el usuario desde acá.
 *  La IA nunca mete un APU en la biblioteca. */
export default function DialogoComposicion({
  open,
  corridaId,
  seq,
  descripcion,
  onOpenChange,
  onCreado,
}: Props) {
  const [propuesta, setPropuesta] = useState<ComposicionPropuesta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cargando, setCargando] = useState(false);
  // Mientras el alta está abierta, este diálogo se esconde (no se desmonta): así
  // no hay dos modales peleándose el foco y cancelar el alta devuelve la propuesta
  // SIN volver a pagarle a la IA.
  const [creando, setCreando] = useState(false);
  // Una sola llamada por diálogo. StrictMode corre los efectos dos veces en dev y
  // cada corrida de esta es plata: el ref lo corta antes del fetch.
  const pedidoRef = useRef(false);

  useEffect(() => {
    if (!open || pedidoRef.current) return;
    pedidoRef.current = true;
    let cancelado = false;
    setCargando(true);
    setError(null);
    (async () => {
      try {
        const p = await componerItem(corridaId, seq);
        if (!cancelado) setPropuesta(p);
      } catch (e) {
        // El mensaje es el del backend (503 sin ANTHROPIC_API_KEY, 422 si la IA no
        // pudo componer): dice qué hacer, y un texto propio lo taparía.
        if (!cancelado) {
          setError(e instanceof Error ? e.message : "No se pudo componer la actividad.");
        }
      } finally {
        // Si el usuario cerró mientras cargaba, no se toca el estado del que se fue.
        if (!cancelado) setCargando(false);
      }
    })();
    return () => {
      cancelado = true;
    };
  }, [open, corridaId, seq]);

  // Identidad estable: el alta precarga en un efecto que depende de `inicial`, y un
  // objeto nuevo por render le borraría al usuario lo que va escribiendo.
  const inicial = useMemo(() => (propuesta ? apuDesdePropuesta(propuesta) : null), [propuesta]);

  const vacia = propuesta !== null && propuesta.componentes.length === 0;

  return (
    <>
      <Dialog
        open={open && !creando}
        // Solo el usuario cierra este diálogo. Esconderlo para abrir el alta NO es
        // un cierre: sin este guardia, el cambio de `open` podría avisar hacia
        // arriba y dejar la fila sin diálogo al cancelar el alta.
        onOpenChange={(v) => {
          if (!creando) onOpenChange(v);
        }}
      >
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle className="text-sm">
              Componer un APU con IA para: {descripcion}
            </DialogTitle>
          </DialogHeader>

          <p className="border-l-2 border-revisar bg-revisar-surface px-2 py-1.5 text-xs text-revisar">
            Esto es una <span className="font-semibold">propuesta</span> de la IA:
            todavía no se creó nada en la biblioteca. El APU lo creás vos en el alta
            de siempre, con sus validaciones. La IA no ve precios ni costos, así que
            <span className="font-semibold"> revisá los rendimientos</span> antes de
            seguir.
          </p>

          {cargando && (
            <p className="py-6 text-center text-xs text-muted-foreground">
              Pidiéndole una propuesta a la IA…
            </p>
          )}

          {error !== null && (
            <p className="border-l-2 border-destructive bg-destructive-surface px-2 py-1.5 text-xs text-destructive">
              {error}
            </p>
          )}

          {propuesta && (
            <div className="flex flex-col gap-2">
              <p className="text-xs text-muted-foreground">
                <span className="font-semibold text-foreground">Por qué lo propone así:</span>{" "}
                {propuesta.justificacion || "La IA no dio una justificación."}
              </p>
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                <span>
                  Nombre: <span className="text-foreground">{propuesta.nombre}</span>
                </span>
                <span>
                  Unidad: <span className="font-mono text-foreground">{propuesta.unidad}</span>
                </span>
                <span>
                  Turno: <span className="text-foreground">{turnoDe(propuesta.shift)}</span>
                </span>
                <span>
                  Confianza:{" "}
                  <span className="text-foreground">
                    {Math.round(propuesta.confianza * 100)}%
                  </span>
                </span>
              </div>

              {vacia ? (
                <p className="py-4 text-center text-xs text-muted-foreground">
                  La IA no propuso ningún insumo. No hay nada que crear: armá el APU a
                  mano desde APUs.
                </p>
              ) : (
                <div className="max-h-72 overflow-y-auto">
                  <table className="w-full border-collapse text-xs">
                    <thead>
                      <tr className="border-b border-border text-left text-muted-foreground">
                        <th className="py-1 pr-2 font-medium">Código</th>
                        <th className="py-1 pr-2 font-medium">Insumo</th>
                        <th className="py-1 pr-2 font-medium">Unidad</th>
                        <th className="py-1 pr-2 text-right font-medium">Rendimiento</th>
                      </tr>
                    </thead>
                    <tbody>
                      {propuesta.componentes.map((c, i) => (
                        <tr key={`${c.insumo_codigo}@@${i}`} className="border-b border-hairline">
                          <td className="py-1 pr-2 font-mono">{c.insumo_codigo}</td>
                          <td className="py-1 pr-2">{c.insumo_nombre}</td>
                          <td className="py-1 pr-2 font-mono text-muted-foreground">{c.unidad}</td>
                          <td className="py-1 pr-2 text-right font-mono tabular-nums">
                            {c.rendimiento.toLocaleString("es-CO")}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          <DialogFooter>
            <Button size="sm" variant="outline" onClick={() => onOpenChange(false)}>
              Descartar
            </Button>
            <Button
              size="sm"
              disabled={propuesta === null || vacia}
              onClick={() => setCreando(true)}
            >
              Crear APU con esto
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {creando && inicial && (
        <DialogoAgregarApu
          open
          onOpenChange={(v) => {
            // Cancelar el alta vuelve a la propuesta, que sigue cargada.
            if (!v) setCreando(false);
          }}
          onCreado={(codigo, turno) => {
            setCreando(false);
            onCreado(codigo, turno);
          }}
          modo="crear"
          inicial={inicial}
        />
      )}
    </>
  );
}
