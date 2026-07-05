import { TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { ClaveColumna, ControlCorridaTabla, FiltroRango } from "@/lib/corridaTabla";

const inputCls =
  "h-6 w-full rounded border border-border bg-transparent px-1 text-[11px] outline-none focus-visible:border-ring";
const miniCls =
  "h-5 w-full rounded border border-border bg-transparent px-1 text-[10px] outline-none focus-visible:border-ring";

type Tipo = "texto" | "select" | "num";
interface Col { clave: ClaveColumna; label: string; tipo: Tipo; ancho: string; derecha?: boolean }

const COLS: Col[] = [
  { clave: "descripcion", label: "Descripción", tipo: "texto", ancho: "" },
  { clave: "unidad", label: "Und", tipo: "select", ancho: "w-12" },
  { clave: "cantidad", label: "Cantidad", tipo: "num", ancho: "w-20", derecha: true },
  { clave: "item", label: "Ítem", tipo: "texto", ancho: "w-24" },
  { clave: "apu", label: "APU", tipo: "texto", ancho: "w-28" },
  { clave: "status", label: "Estado", tipo: "select", ancho: "w-20" },
  { clave: "contractual_total", label: "Contractual", tipo: "num", ancho: "w-28", derecha: true },
  { clave: "costo_total", label: "Costo", tipo: "num", ancho: "w-28", derecha: true },
  { clave: "margen_total", label: "Margen", tipo: "num", ancho: "w-28", derecha: true },
  { clave: "margen_pct", label: "%", tipo: "num", ancho: "w-16", derecha: true },
];

function Rango({ clave, label, control }: { clave: ClaveColumna; label: string; control: ControlCorridaTabla }) {
  const r = control.filtros[clave] as FiltroRango;
  return (
    <div className="flex flex-col gap-0.5">
      <input
        className={miniCls} type="number" value={r.min} placeholder="mín"
        aria-label={`${label} mínimo`}
        onChange={(e) => control.setFiltro(clave, { ...r, min: e.target.value })}
      />
      <input
        className={miniCls} type="number" value={r.max} placeholder="máx"
        aria-label={`${label} máximo`}
        onChange={(e) => control.setFiltro(clave, { ...r, max: e.target.value })}
      />
    </div>
  );
}

export default function CabeceraFiltros({ control }: { control: ControlCorridaTabla }) {
  const flecha = (clave: ClaveColumna) =>
    control.orden?.clave === clave ? (control.orden.dir === "asc" ? "↑" : "↓") : "";

  return (
    <TableHeader>
      <TableRow>
        <TableHead className="w-6 px-1" />
        {COLS.map((c) => (
          <TableHead key={c.clave} className={`text-xs ${c.ancho} ${c.derecha ? "text-right" : ""}`}>
            <button
              type="button"
              aria-label={`Ordenar por ${c.label}`}
              onClick={() => control.alternarOrden(c.clave)}
              className="inline-flex items-center gap-1 hover:text-foreground select-none"
            >
              {c.label}
              <span className="text-[9px] w-2 text-muted-foreground">{flecha(c.clave)}</span>
            </button>
          </TableHead>
        ))}
      </TableRow>
      <TableRow className="hover:bg-transparent">
        <TableHead className="w-6 px-1" />
        {COLS.map((c) => (
          <TableHead key={c.clave} className={`${c.ancho} py-1 align-top`}>
            {c.tipo === "texto" && (
              <input
                className={inputCls} value={control.filtros[c.clave] as string}
                aria-label={`Filtrar ${c.label}`} placeholder="contiene…"
                onChange={(e) => control.setFiltro(c.clave, e.target.value)}
              />
            )}
            {c.tipo === "select" && (
              <select
                className={inputCls} value={control.filtros[c.clave] as string}
                aria-label={`Filtrar ${c.label}`}
                onChange={(e) => control.setFiltro(c.clave, e.target.value)}
              >
                <option value="">(todas)</option>
                {(c.clave === "unidad" ? control.opcionesUnidad : control.opcionesStatus).map((o) => (
                  <option key={o} value={o}>{o}</option>
                ))}
              </select>
            )}
            {c.tipo === "num" && <Rango clave={c.clave} label={c.label} control={control} />}
          </TableHead>
        ))}
      </TableRow>
    </TableHeader>
  );
}
