import { useState } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import EstadoBadge from "@/components/corrida/EstadoBadge";
import { cop, pct } from "@/lib/moneda";
import type { ItemCuadro } from "@/lib/tipos";

interface TablaItemsProps {
  items: ItemCuadro[];
  onSelectItem: (seq: number) => void;
}

const REVISABLE = new Set(["review", "new", "REVIEW", "NEW"]);

export default function TablaItems({ items, onSelectItem }: TablaItemsProps) {
  const [soloRevision, setSoloRevision] = useState(false);

  const nPorRevisar = items.filter((it) => REVISABLE.has(it.status)).length;
  const visible = soloRevision
    ? items.filter((it) => REVISABLE.has(it.status))
    : items;

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
            const clickable = REVISABLE.has(it.status);
            return (
              <TableRow
                key={it.seq}
                className={clickable ? "cursor-pointer hover:bg-muted/60" : ""}
                onClick={clickable ? () => onSelectItem(it.seq) : undefined}
              >
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
            );
          })}
          {visible.length === 0 && (
            <TableRow>
              <TableCell colSpan={9} className="text-center text-xs text-muted-foreground py-6">
                No hay ítems{soloRevision ? " por revisar" : ""}.
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
}
