import { TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SIN_APU, etiquetaVeredicto } from "@/lib/corridaTabla";
import type { ClaveColumna, ControlCorridaTabla, FiltroRango } from "@/lib/corridaTabla";
import { etiquetaEstado } from "@/components/corrida/EstadoBadge";

const inputCls =
  "h-6 w-full rounded border border-border bg-transparent px-1 text-[11px] outline-none focus-visible:border-ring";
const miniCls =
  "h-5 w-full rounded border border-border bg-transparent px-1 text-[10px] outline-none focus-visible:border-ring";

type Tipo = "texto" | "select" | "num";
interface Col { clave: ClaveColumna; label: string; tipo: Tipo; ancho: string; derecha?: boolean }

// Cada `clave` está emparejada con su `tipo` correcto, así que los casts
// `as string`/`as FiltroRango` al leer `control.filtros[clave]` son seguros.
const COLS: Col[] = [
  { clave: "descripcion", label: "Descripción", tipo: "texto", ancho: "" },
  { clave: "unidad", label: "Und", tipo: "select", ancho: "w-12" },
  { clave: "cantidad", label: "Cantidad", tipo: "num", ancho: "w-20", derecha: true },
  { clave: "item", label: "Ítem", tipo: "texto", ancho: "w-24" },
  { clave: "capitulo", label: "Capítulo", tipo: "texto", ancho: "w-32" },
  { clave: "apu", label: "APU", tipo: "texto", ancho: "w-28" },
  { clave: "status", label: "Estado", tipo: "select", ancho: "w-20" },
  { clave: "veredicto", label: "Veredicto", tipo: "select", ancho: "w-28" },
  { clave: "precio_contractual", label: "Unit. Contractual", tipo: "num", ancho: "w-28", derecha: true },
  { clave: "costo_unitario", label: "Unit. Costo", tipo: "num", ancho: "w-28", derecha: true },
  { clave: "contractual_total", label: "Total Contractual", tipo: "num", ancho: "w-28", derecha: true },
  { clave: "costo_total", label: "Total Costo", tipo: "num", ancho: "w-28", derecha: true },
  { clave: "margen_total", label: "Margen", tipo: "num", ancho: "w-28", derecha: true },
  { clave: "margen_pct", label: "%", tipo: "num", ancho: "w-16", derecha: true },
];

const esCentinela = (clave: ClaveColumna, control: ControlCorridaTabla) =>
  clave === "apu" && control.filtros.apu === SIN_APU;

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

export default function CabeceraFiltros({
  control,
  conSeleccion = false,
  conVeredicto = true,
  conCapitulo = false,
  conAcciones = false,
}: {
  control: ControlCorridaTabla;
  /** Layout: reserva la celda de la columna de checkboxes cuando la selección está activa. */
  conSeleccion?: boolean;
  /** false = la corrida no tiene ni un veredicto: la columna no se dibuja (14
   *  columnas no caben en un portátil, y esta estaría entera vacía). */
  conVeredicto?: boolean;
  /** false = la corrida no vino de un presupuesto por capítulos: la columna no se
   *  dibuja, igual que Veredicto. Una corrida plana queda EXACTAMENTE como estaba. */
  conCapitulo?: boolean;
  /** true = alguna fila ofrece Componer: se reserva la celda de esa columna. No
   *  se filtra ni se ordena por ella (no es un dato de la línea, es un botón). */
  conAcciones?: boolean;
}) {
  const cols = COLS.filter((c) => (c.clave !== "veredicto" || conVeredicto)
                                   && (c.clave !== "capitulo" || conCapitulo));
  const flecha = (clave: ClaveColumna) =>
    control.orden?.clave === clave ? (control.orden.dir === "asc" ? "↑" : "↓") : "";

  return (
    <TableHeader>
      <TableRow>
        {conSeleccion && <TableHead className="w-8 px-1" />}
        <TableHead className="w-6 px-1" />
        {cols.map((c) => (
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
        {conAcciones && <TableHead className="text-xs w-24">Acciones</TableHead>}
      </TableRow>
      <TableRow className="hover:bg-transparent">
        {conSeleccion && <TableHead className="w-8 px-1" />}
        <TableHead className="w-6 px-1" />
        {cols.map((c) => {
          // El filtro de APU puede llevar el centinela de "sin APU" (lo pone el
          // contador rojo de la corrida). El centinela se muestra como *placeholder*,
          // no como value: así no hay texto que editar parcialmente y cualquier tecla
          // arranca de vacío, como en un filtro normal.
          const sinApuActivo = esCentinela(c.clave, control);
          const opciones = c.clave === "unidad" ? control.opcionesUnidad
            : c.clave === "status" ? control.opcionesStatus
            : control.opcionesVeredicto;
          const etiqueta = (o: string) => c.clave === "status" ? etiquetaEstado(o)
            : c.clave === "veredicto" ? etiquetaVeredicto(o)
            : o;
          return (
            <TableHead key={c.clave} className={`${c.ancho} py-1 align-top`}>
              {c.tipo === "texto" && (
                <input
                  className={`${inputCls}${sinApuActivo ? " border-red-400 placeholder:text-red-700" : ""}`}
                  value={sinApuActivo ? "" : (control.filtros[c.clave] as string)}
                  placeholder={sinApuActivo ? "(sin APU)" : "contiene…"}
                  aria-label={`Filtrar ${c.label}`}
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
                  {opciones.map((o) => (
                    <option key={o} value={o}>{etiqueta(o)}</option>
                  ))}
                </select>
              )}
              {c.tipo === "num" && <Rango clave={c.clave} label={c.label} control={control} />}
            </TableHead>
          );
        })}
        {conAcciones && <TableHead className="w-24 py-1" />}
      </TableRow>
    </TableHeader>
  );
}
