import { normalizarNombre } from "@/lib/duplicarApu";
import type { OpcionInsumo } from "@/lib/tipos";

/** Índice de la opción que coincide con `valor` (mismo criterio que el backend:
 *  `nucleo/texto.normalizar`), o -1 si ninguna. */
function indiceDe(opciones: OpcionInsumo[], valor: string): number {
  const v = normalizarNombre(valor);
  return opciones.findIndex((o) => normalizarNombre(o.nombre) === v);
}

/** ¿El nombre de la fila no coincide con ninguna opción? (= falta escoger). */
export function sinResolver(opciones: OpcionInsumo[], valor: string): boolean {
  return indiceDe(opciones, valor) < 0;
}

interface Props {
  codigo: string;
  opciones: OpcionInsumo[];
  /** El nombre que tiene hoy la fila ("" = sin elegir). */
  valor: string;
  onElegir: (o: OpcionInsumo) => void;
  deshabilitado?: boolean;
}

/** Un código del catálogo que es de varios insumos: el ingeniero escoge cuál.
 *  Se usa en el diálogo de APU (tras un 422) y en la mesa de composición. */
export default function SelectorCompartido({
  codigo, opciones, valor, onElegir, deshabilitado = false,
}: Props) {
  const i = indiceDe(opciones, valor);
  return (
    <select
      aria-label={`Insumo del código ${codigo}`}
      className={"h-7 w-full max-w-[22rem] rounded border bg-transparent px-1 text-xs "
        + (i < 0 ? "border-destructive" : "border-border")}
      value={i < 0 ? "" : String(i)}
      disabled={deshabilitado}
      onChange={(e) => {
        const o = opciones[Number(e.target.value)];
        if (o) onElegir(o);
      }}
    >
      <option value="" disabled>
        {`¿Cuál de los ${opciones.length}? El código ${codigo} es de varios insumos`}
      </option>
      {opciones.map((o, j) => (
        <option key={j} value={String(j)}>
          {`${o.nombre} · ${o.unidad}${o.oculto ? " (oculto)" : ""}`}
        </option>
      ))}
    </select>
  );
}
