import { cop, pct } from "@/lib/moneda";
import type { CapituloCorrida } from "@/lib/tipos";

const n = (x: number) => x.toLocaleString("es-CO");

/** Contractual, costo y cobertura por capítulo, después del armado.
 *
 *  NO calcula nada: el backend manda las filas ya sumadas
 *  (`dominio/report_categorizado.resumen_por_capitulo`), que es la misma función que
 *  escribe la hoja de Excel. Sumar acá sería el segundo lugar donde el mismo número
 *  puede salir distinto. */
export default function ResumenCapitulos({ capitulos }: { capitulos: CapituloCorrida[] }) {
  if (!capitulos.length) return null;
  const total = (f: (c: CapituloCorrida) => number) =>
    capitulos.reduce((a, c) => a + f(c), 0);
  const contractual = total((c) => c.contractual);
  const costo = total((c) => c.costo);
  const incompletos = capitulos.filter((c) => !c.completo).length;

  return (
    <details open className="mb-3 rounded-md border">
      <summary className="cursor-pointer px-2 py-1.5 text-xs font-medium">
        Resumen por capítulo ({n(capitulos.length)})
        {incompletos > 0 && (
          <span className="ml-2 font-normal text-revisar">
            · {n(incompletos)} sin costear del todo
          </span>
        )}
      </summary>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-[11px]">
          <caption className="sr-only">
            Contractual y costo interno por capítulo de la corrida
          </caption>
          <thead>
            <tr className="border-t">
              <th scope="col" className="p-1 text-left">Capítulo</th>
              <th scope="col" className="p-1 text-left">Nombre</th>
              <th scope="col" className="p-1 text-right">Activid.</th>
              <th scope="col" className="p-1 text-right">Con APU</th>
              <th scope="col" className="p-1 text-right">Sin APU</th>
              <th scope="col" className="p-1 text-right">Contractual</th>
              <th scope="col" className="p-1 text-right">Costo interno</th>
              <th scope="col" className="p-1 text-right">Diferencia</th>
              <th scope="col" className="p-1 text-right">Margen</th>
              <th scope="col" className="p-1 text-right">Cobertura</th>
              <th scope="col" className="p-1 text-right">Cobertura $</th>
              <th scope="col" className="p-1 text-left">Estado</th>
            </tr>
          </thead>
          <tbody>
            {capitulos.map((c) => (
              <tr key={c.codigo || c.nombre} className="border-t">
                <td className="p-1">{c.codigo}</td>
                <td className="p-1">{c.nombre}</td>
                <td className="p-1 text-right">{n(c.actividades)}</td>
                <td className="p-1 text-right">{n(c.con_apu)}</td>
                <td className={"p-1 text-right " + (c.sin_apu ? "text-revisar" : "")}>
                  {n(c.sin_apu)}
                </td>
                <td className="p-1 text-right tabular-nums">{cop(c.contractual)}</td>
                <td className="p-1 text-right tabular-nums">{cop(c.costo)}</td>
                <td className="p-1 text-right tabular-nums">{cop(c.diferencia)}</td>
                {/* Con actividades sin costear el margen NO es definitivo: se dice, en
                    vez de mostrar un porcentaje que parece final y no lo es. */}
                <td className="p-1 text-right tabular-nums">
                  {pct(c.margen_pct)}
                  {!c.completo && <span className="text-revisar"> parcial</span>}
                </td>
                <td className="p-1 text-right">{pct(c.cobertura)}</td>
                <td className="p-1 text-right">{pct(c.cobertura_valor)}</td>
                <td className={"p-1 " + (c.completo ? "" : "text-revisar")}>
                  {c.completo ? "Completo" : "Incompleto"}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t font-medium">
              <td className="p-1" colSpan={2}>TOTAL</td>
              <td className="p-1 text-right">{n(total((c) => c.actividades))}</td>
              <td className="p-1 text-right">{n(total((c) => c.con_apu))}</td>
              <td className="p-1 text-right">{n(total((c) => c.sin_apu))}</td>
              <td className="p-1 text-right tabular-nums">{cop(contractual)}</td>
              <td className="p-1 text-right tabular-nums">{cop(costo)}</td>
              <td className="p-1 text-right tabular-nums">{cop(contractual - costo)}</td>
              <td className="p-1 text-right tabular-nums">
                {pct(contractual ? (contractual - costo) / contractual : 0)}
              </td>
              <td className="p-1" colSpan={3} />
            </tr>
          </tfoot>
        </table>
      </div>
    </details>
  );
}
