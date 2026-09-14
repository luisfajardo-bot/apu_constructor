import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { cop } from "@/lib/moneda";
import type { PreviaPresupuesto } from "@/lib/tipos";

interface Props {
  previa: PreviaPresupuesto;
  cargando: boolean;
  onAprobar: () => void;
  onCancelar: () => void;
  onCambiarArchivo: () => void;
}

const n = (x: number) => x.toLocaleString("es-CO");

/** Lo que se detectó en el archivo, antes de crear nada.
 *
 *  No hay corrida todavía y no hay borrador en el servidor: el archivo sigue en el
 *  <input> del formulario y se reenvía al aprobar. Por eso "Cancelar" no tiene que
 *  limpiar nada — nunca hubo nada que limpiar. */
export default function PreviaIdu({ previa, cargando, onAprobar, onCancelar,
                                    onCambiarArchivo }: Props) {
  const [avisosEntendidos, setAvisosEntendidos] = useState(false);
  const nAvisos = previa.advertencias.length;
  // Una previa nueva (otro archivo) vuelve a exigir la confirmación de advertencias.
  useEffect(() => setAvisosEntendidos(false), [previa]);

  const bloqueado =
    !previa.puede_aprobar || (nAvisos > 0 && !avisosEntendidos) || cargando;
  const conciliacionOk = previa.conciliacion?.subtotales_ok !== false;

  return (
    <section className="mt-5 border-t pt-4" aria-labelledby="previa-titulo">
      <h3 id="previa-titulo" className="text-[13px] font-semibold">
        Estructura detectada
      </h3>

      <p className="mt-1 text-[11px] text-muted-foreground">
        Hoja «{previa.hoja}» · encabezado en la fila {previa.fila_encabezado} · parser{" "}
        {previa.parser_version}
      </p>
      <p className="mt-1 text-xs">
        Se detectaron {n(previa.capitulos.length)} capítulos y {n(previa.actividades)}{" "}
        actividades. Filas ignoradas: {n(previa.filas_ignoradas)}.
      </p>
      <p className="mt-1 text-xs">
        Contractual (con AIU) {cop(previa.totales.contractual)} · sin AIU{" "}
        {cop(previa.totales.contractual_sin_aiu)}
      </p>
      <p
        className={
          "mt-1 text-[11px] " +
          (conciliacionOk ? "text-muted-foreground" : "text-revisar")
        }
      >
        {conciliacionOk
          ? "Conciliación contra el Excel: cuadra."
          : `Conciliación contra el Excel: no cuadra (diferencia ${cop(
              previa.conciliacion.diferencia ?? 0,
            )}).`}
      </p>

      {previa.errores.length > 0 && (
        <div role="alert" className="mt-3 rounded-md border border-destructive/40 p-2">
          <p className="text-xs font-medium text-destructive">
            No se puede importar este archivo:
          </p>
          <ul className="mt-1 list-disc pl-4 text-[11px]">
            {previa.errores.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </div>
      )}

      {nAvisos > 0 && (
        <div className="mt-3 rounded-md border border-revisar/40 p-2">
          <p className="text-xs font-medium">
            {n(nAvisos)} advertencia{nAvisos === 1 ? "" : "s"}
          </p>
          <ul className="mt-1 max-h-40 list-disc overflow-y-auto pl-4 text-[11px]">
            {previa.advertencias.map((a, i) => (
              <li key={`${a.tipo}-${a.fila}-${i}`}>
                <span className="font-medium">{a.tipo}</span>
                {a.fila > 0 && <> (fila {n(a.fila)})</>}: {a.detalle}
              </li>
            ))}
          </ul>
          <label className="mt-2 flex items-center gap-1.5 text-[11px]">
            <input
              type="checkbox"
              checked={avisosEntendidos}
              onChange={(e) => setAvisosEntendidos(e.target.checked)}
            />
            Entiendo las {n(nAvisos)} advertencias y quiero continuar
          </label>
        </div>
      )}

      {previa.capitulos.length > 0 && (
        <div className="mt-3 max-h-72 overflow-auto">
          <table className="w-full border-collapse text-[11px]">
            <caption className="sr-only">
              Capítulos detectados con su total contractual
            </caption>
            <thead className="sticky top-0 bg-card">
              <tr>
                <th scope="col" className="p-1 text-left">Capítulo</th>
                <th scope="col" className="p-1 text-left">Nombre</th>
                <th scope="col" className="p-1 text-right">Actividades</th>
                <th scope="col" className="p-1 text-right">Contractual (c/AIU)</th>
                <th scope="col" className="p-1 text-right">Contractual (s/AIU)</th>
              </tr>
            </thead>
            <tbody>
              {previa.capitulos.map((c) => (
                <tr key={c.codigo || c.nombre} className="border-t">
                  <td className="p-1">{c.codigo}</td>
                  <td className="p-1">{c.nombre}</td>
                  <td className="p-1 text-right">{n(c.actividades)}</td>
                  <td className="p-1 text-right tabular-nums">{cop(c.contractual)}</td>
                  <td className="p-1 text-right tabular-nums">
                    {cop(c.contractual_sin_aiu)}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t font-medium">
                <td className="p-1" colSpan={2}>TOTAL</td>
                <td className="p-1 text-right">{n(previa.actividades)}</td>
                <td className="p-1 text-right tabular-nums">
                  {cop(previa.totales.contractual)}
                </td>
                <td className="p-1 text-right tabular-nums">
                  {cop(previa.totales.contractual_sin_aiu)}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        {/* Deshabilitado SOLO cuando hay una razón visible en pantalla (errores
            listados, o advertencias sin confirmar). Un botón muerto sin explicación
            deja al usuario sin salida: pasó en el smoke test del 2026-08-03. */}
        <Button type="button" disabled={bloqueado} onClick={onAprobar}>
          {cargando ? "Creando…" : "Aprobar y crear corrida"}
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={cargando}
          onClick={onCambiarArchivo}
        >
          Volver a seleccionar archivo
        </Button>
        <Button type="button" variant="outline" disabled={cargando} onClick={onCancelar}>
          Cancelar
        </Button>
      </div>
    </section>
  );
}
