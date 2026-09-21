import { useMemo, useRef, useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { cop } from "@/lib/moneda";
import { porcentaje, previaUmbral } from "@/lib/umbralCosto";
import type { ItemCuadro } from "@/lib/tipos";

interface Props {
  abierto: boolean;
  /** Todos los ítems de la corrida: el techo es una decisión de presupuesto, no de
   *  vista, así que NO se filtra por lo que la tabla esté mostrando. */
  items: ItemCuadro[];
  aplicando: boolean;
  onAplicar: (umbral: number, seqs: number[]) => void;
  onCerrar: () => void;
}

/** Pone un techo en pesos sobre el total contractual de una línea: todas las
 *  actividades en $0 que caigan debajo se igualan al contractual de un gesto.
 *
 *  Para priorizar: un puñado de actividades se lleva casi todo el presupuesto y
 *  armarle el APU a la cola larga cuesta semanas sin mover la evaluación. */
export default function DialogoUmbralCosto({
  abierto, items, aplicando, onAplicar, onCerrar,
}: Props) {
  const [texto, setTexto] = useState("");
  const umbral = Number(texto);
  const p = useMemo(() => previaUmbral(items, umbral), [items, umbral]);

  // Las marcas se DERIVAN del umbral y se rehacen cuando cambia: la lista es otra, y
  // conservar destildes de una lista anterior sería adivinar. `destildadas` guarda
  // solo lo que el usuario sacó a mano de la lista de hoy.
  const [destildadas, setDestildadas] = useState<Set<number>>(new Set());
  const [ultimoTecho, setUltimoTecho] = useState("");
  if (ultimoTecho !== texto) {                 // patrón de estado derivado, sin efecto
    setUltimoTecho(texto);
    setDestildadas(new Set());
  }
  const marcados = p.igualadas
    .filter((it) => !destildadas.has(it.seq))
    .map((it) => it.seq);

  // Ancla del último clic SIN Shift, por `seq` (único en la corrida), igual que
  // DialogoRebuscar.
  const anclaRef = useRef<number | null>(null);

  function alternar(idx: number, seq: number, conShift: boolean) {
    const desde = anclaRef.current === null
      ? -1
      : p.igualadas.findIndex((it) => it.seq === anclaRef.current);
    if (conShift && desde >= 0) {
      const [a, b] = desde <= idx ? [desde, idx] : [idx, desde];
      const rango = p.igualadas.slice(a, b + 1).map((it) => it.seq);
      setDestildadas((prev) => {
        const s = new Set(prev);
        for (const seqRango of rango) s.delete(seqRango);   // el rango MARCA
        return s;
      });
      return;                                  // el ancla del rango no se mueve
    }
    anclaRef.current = seq;
    setDestildadas((prev) => {
      const s = new Set(prev);
      if (s.has(seq)) s.delete(seq); else s.add(seq);
      return s;
    });
  }

  const pctIgualadas = porcentaje(p.sumaIgualadas, p.contractualCorrida);
  const pctRestantes = porcentaje(p.sumaRestantes, p.contractualCorrida);
  const th = "px-2 py-1 text-left font-semibold text-muted-foreground";
  const td = "px-2 py-1 align-top";

  return (
    <Dialog open={abierto} onOpenChange={(v) => { if (!v) onCerrar(); }}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle>Igualar bajo umbral</DialogTitle>
        </DialogHeader>

        <p className="text-xs text-muted-foreground -mt-2">
          Las actividades en $0 cuyo total contractual no pase el umbral se igualan al
          precio contractual, para poder evaluar sin armarles el APU. Se puede
          deshacer con «Quitar costo a mano».
        </p>

        <div className="flex flex-wrap items-center gap-2">
          <label className="text-xs font-medium" htmlFor="umbral-contractual">
            Umbral de total contractual
          </label>
          <input
            id="umbral-contractual"
            aria-label="Umbral de total contractual"
            className="h-8 w-48 rounded border border-border bg-transparent px-2
                       text-sm tabular-nums outline-none focus-visible:border-ring"
            type="number" min="0" step="1000000" value={texto}
            placeholder="500000000"
            onChange={(e) => setTexto(e.target.value)}
          />
          {/* El monto escrito, en letras de gente: son nueve dígitos. */}
          <span className="text-sm font-semibold tabular-nums">
            {umbral > 0 ? cop(umbral) : "—"}
          </span>
        </div>

        <div className="rounded border border-border bg-muted/40 p-2 text-xs">
          <div className="flex justify-between">
            <span>Actividades en $0</span>
            <span className="tabular-nums">
              {p.candidatas.length} · {cop(p.sumaIgualadas + p.sumaRestantes)}
            </span>
          </div>
          <div className="flex justify-between text-emerald-700 dark:text-emerald-400">
            <span>Se igualan al contractual</span>
            <span className="tabular-nums">
              {p.igualadas.length} · {cop(p.sumaIgualadas)} · {pctIgualadas.toFixed(1)}%
              {" "}del contrato
            </span>
          </div>
          <div className="flex justify-between">
            <span>Quedan por armar</span>
            <span className="tabular-nums">
              {p.restantes.length} · {cop(p.sumaRestantes)} · {pctRestantes.toFixed(1)}%
              {" "}del contrato
            </span>
          </div>
          {p.igualadas.length > 0 && (
            <div className="pt-1 text-muted-foreground">
              Se igualan: {p.sinApu} sin APU · {p.conApu} con APU pero sin precios.
            </div>
          )}
          {p.sinContractual > 0 && (
            <div className="pt-1 text-amber-700 dark:text-amber-400">
              {p.sinContractual} en $0 sin precio contractual: no se pueden igualar
              (nada queda en $0).
            </div>
          )}
        </div>

        {p.igualadas.length > 0 && (
          <div className="max-h-[45vh] overflow-auto rounded border border-border">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-muted">
                <tr>
                  <th className={th}> </th>
                  <th className={th}>#</th>
                  <th className={th}>Actividad</th>
                  <th className={th}>APU</th>
                  <th className={`${th} text-right`}>Total contractual</th>
                </tr>
              </thead>
              <tbody>
                {p.igualadas.map((it, i) => (
                  <tr key={it.seq} className="border-t border-border hover:bg-muted/40">
                    <td className={td}>
                      {/* `onChange` vacío a propósito: el que sabe del Shift es el
                          `onClick`, y React exige onChange en un input controlado. */}
                      <input type="checkbox" className="cursor-pointer"
                        aria-label={`Marcar línea ${i + 1}`}
                        checked={!destildadas.has(it.seq)}
                        onChange={() => {}}
                        onMouseDown={(e) => { if (e.shiftKey) e.preventDefault(); }}
                        onClick={(e) => alternar(i, it.seq, e.shiftKey)} />
                    </td>
                    <td className={`${td} tabular-nums`}>{it.item}</td>
                    <td className={`${td} max-w-[24rem]`}>{it.descripcion}</td>
                    <td className={td}>
                      {it.apu_codigo
                        ? <span>{it.apu_codigo} — {it.apu_nombre}</span>
                        : <span className="text-amber-700 font-semibold">— sin APU</span>}
                    </td>
                    <td className={`${td} text-right tabular-nums`}>
                      {cop(it.contractual_total)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="flex justify-end gap-2 pt-2">
          {/* Deshabilitado mientras aplica: cerrar no cancela el POST en vuelo. */}
          <Button size="sm" variant="outline" disabled={aplicando}
            onClick={onCerrar}>Cerrar</Button>
          <Button size="sm" disabled={marcados.length === 0 || aplicando}
            onClick={() => onAplicar(umbral, [...marcados].sort((a, b) => a - b))}>
            {aplicando
              ? "Aplicando…"
              : `Igualar ${marcados.length} ${
                  marcados.length === 1 ? "línea" : "líneas"}`}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
