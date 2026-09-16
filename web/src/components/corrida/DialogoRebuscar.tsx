import { useEffect, useRef, useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { cop } from "@/lib/moneda";
import type { PropuestaRebusqueda, RebusquedaPrevia } from "@/lib/tipos";

interface Props {
  abierto: boolean;
  previa: RebusquedaPrevia;
  aplicando: boolean;
  onAplicar: (seqs: number[]) => void;
  onCerrar: () => void;
}

/** Vista previa de "volver a buscar APU": qué líneas cambiarían de APU contra la
 *  biblioteca de hoy, con el costo y el margen que quedarían. Propone; aplicar es
 *  del usuario, y solo lo que marque. */
export default function DialogoRebuscar({
  abierto, previa, aplicando, onAplicar, onCerrar,
}: Props) {
  const ps = previa.propuestas;
  // Vienen marcadas las que hoy están sin APU: están en $0 y traban el cuadro, así que
  // cualquier APU es mejor que nada. Quién es cuál lo dice el backend (`sin_apu`), no
  // una regla repetida acá.
  const [marcadas, setMarcadas] = useState<Set<number>>(new Set());
  useEffect(() => {
    setMarcadas(new Set(ps.filter((p) => p.sin_apu).map((p) => p.seq)));
  }, [previa]);                                   // eslint-disable-line react-hooks/exhaustive-deps

  // Ancla del último clic SIN Shift, por `seq` (único en la corrida), igual que el
  // diálogo de conflictos del import.
  const anclaRef = useRef<number | null>(null);

  function alternar(idx: number, seq: number, conShift: boolean) {
    const desde = anclaRef.current === null
      ? -1
      : ps.findIndex((p) => p.seq === anclaRef.current);
    if (conShift && desde >= 0) {
      const [a, b] = desde <= idx ? [desde, idx] : [idx, desde];
      const rango = ps.slice(a, b + 1).map((p) => p.seq);
      setMarcadas((prev) => new Set([...prev, ...rango]));
      return;                                     // el ancla del rango no se mueve
    }
    anclaRef.current = seq;
    setMarcadas((prev) => {
      const s = new Set(prev);
      if (s.has(seq)) s.delete(seq); else s.add(seq);
      return s;
    });
  }

  function marcarTodas(marcar: boolean) {
    anclaRef.current = null;
    setMarcadas(marcar ? new Set(ps.map((p) => p.seq)) : new Set());
  }

  const th = "px-2 py-1 text-left font-semibold text-muted-foreground";
  const td = "px-2 py-1 align-top";

  return (
    <Dialog open={abierto} onOpenChange={(v) => { if (!v) onCerrar(); }}>
      <DialogContent className="max-w-5xl">
        <DialogHeader>
          <DialogTitle>Volver a buscar APU</DialogTitle>
        </DialogHeader>
        <p className="text-xs text-muted-foreground -mt-2">
          {ps.length} de {previa.escaneadas}{" "}
          {previa.escaneadas === 1 ? "línea revisada" : "líneas revisadas"} cambiarían
          de APU. Las confirmadas no se tocan.
          {ps.length > 1 && " Shift+clic marca en rango."}
        </p>

        {ps.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            Ninguna actividad encontró un APU mejor que el que ya tiene.
          </p>
        ) : (
          <div className="max-h-[60vh] overflow-auto rounded border border-border">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-muted">
                <tr>
                  <th className={th}>
                    <input type="checkbox" className="cursor-pointer"
                      aria-label="Marcar todas las líneas"
                      checked={marcadas.size === ps.length && ps.length > 0}
                      onChange={(e) => marcarTodas(e.target.checked)} />
                  </th>
                  <th className={th}>#</th>
                  <th className={th}>Actividad</th>
                  <th className={th}>APU actual</th>
                  <th className={th}>APU propuesto</th>
                  <th className={th}>Parecido</th>
                  <th className={`${th} text-right`}>Costo unit.</th>
                  <th className={`${th} text-right`}>Margen unit.</th>
                </tr>
              </thead>
              <tbody>
                {ps.map((p: PropuestaRebusqueda, i) => (
                  <tr key={p.seq} className="border-t border-border hover:bg-muted/40">
                    <td className={td}>
                      {/* `onChange` vacío a propósito: el que sabe del Shift es el
                          `onClick`, y React exige onChange en un input controlado. */}
                      <input type="checkbox" className="cursor-pointer"
                        aria-label={`Marcar línea ${i + 1}`}
                        checked={marcadas.has(p.seq)}
                        onChange={() => {}}
                        onMouseDown={(e) => { if (e.shiftKey) e.preventDefault(); }}
                        onClick={(e) => alternar(i, p.seq, e.shiftKey)} />
                    </td>
                    <td className={`${td} tabular-nums`}>{p.item}</td>
                    <td className={`${td} max-w-[22rem]`}>{p.descripcion}</td>
                    <td className={td}>
                      {p.apu_actual
                        ? <span>{p.apu_actual.codigo} — {p.apu_actual.nombre}</span>
                        : <span className="text-amber-700 font-semibold">— sin APU</span>}
                    </td>
                    <td className={td}>
                      {p.apu_propuesto.codigo} — {p.apu_propuesto.nombre}
                    </td>
                    <td className={`${td} tabular-nums`}>
                      {(p.score * 100).toFixed(0)}%
                      {p.status === "review" && (
                        <span className="ml-1 rounded-full bg-amber-100 px-1.5
                                         text-[10px] font-semibold text-amber-800">
                          revisar
                        </span>
                      )}
                    </td>
                    <td className={`${td} text-right tabular-nums`}>
                      {cop(p.costo_unitario)}
                    </td>
                    <td className={`${td} text-right tabular-nums ${
                      p.margen_unitario < 0 ? "text-red-600" : ""}`}>
                      {cop(p.margen_unitario)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="flex justify-end gap-2 pt-2">
          {/* Deshabilitado mientras aplica, igual que el diálogo de importar: cerrar
              no cancela el POST en vuelo, así que el cuadro se actualizaría y saldría
              un toast después de que el usuario creyó haber cancelado. */}
          <Button size="sm" variant="outline" disabled={aplicando}
            onClick={onCerrar}>Cerrar</Button>
          {ps.length > 0 && (
            <Button size="sm" disabled={marcadas.size === 0 || aplicando}
              onClick={() => onAplicar([...marcadas].sort((a, b) => a - b))}>
              {aplicando
                ? "Aplicando…"
                : `Aplicar ${marcadas.size} ${marcadas.size === 1 ? "cambio" : "cambios"}`}
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
