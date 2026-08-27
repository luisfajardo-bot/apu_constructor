import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { listarComponentes, clasificar } from "@/api/transporte";
import type { CategoriaTransporte, FilaClasificacion } from "@/lib/tipos";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const NUM = new Intl.NumberFormat("es-CO", { maximumFractionDigits: 4 });
const clave = (f: FilaClasificacion) => `${f.apu_codigo}|${f.shift}|${f.insumo_codigo}`;

function msg(e: unknown): string {
  return e instanceof Error ? e.message : "Error desconocido";
}

export default function ClasificacionTransporte() {
  const [filas, setFilas] = useState<FilaClasificacion[]>([]);
  const [categorias, setCategorias] = useState<CategoriaTransporte[]>([]);
  const [guardando, setGuardando] = useState(false);

  useEffect(() => {
    listarComponentes()
      .then((l) => {
        setCategorias(l.categorias);
        setFilas(l.items.map((f) => ({
          ...f, categoria: f.categoria ?? f.categoria_sugerida })));
      })
      .catch((e) => toast.error(msg(e)));
  }, []);

  const atipicas = useMemo(
    () => filas.filter((f) => f.volumen < 0.5 || f.volumen > 2).length, [filas]);

  // Lo que realmente escribe "Guardar clasificación": mismo filtro que usa
  // guardar() de abajo, para que el botón nunca prometa un alcance distinto
  // del que va a aplicar.
  const aGuardar = useMemo(
    () => filas.filter((f) => f.categoria && f.volumen > 0), [filas]);
  const atipicasAGuardar = useMemo(
    () => aGuardar.filter((f) => f.volumen < 0.5 || f.volumen > 2).length, [aGuardar]);

  function editar(k: string, cambio: Partial<FilaClasificacion>) {
    setFilas((prev) => prev.map((f) => {
      if (clave(f) !== k) return f;
      const fusion = { ...f, ...cambio };
      // El volumen se deriva del km base: es la perilla de calibración. Un km
      // base <= 0 no reescala (evita Infinity/NaN); el volumen queda como estaba.
      if (cambio.km_base !== undefined && fusion.km_base > 0) {
        fusion.volumen = fusion.rendimiento / fusion.km_base;
      }
      fusion.km_implicito = fusion.volumen > 0
        ? Number((fusion.rendimiento / fusion.volumen).toFixed(2)) : null;
      return fusion;
    }));
  }

  async function guardar() {
    if (!aGuardar.length) { toast.error("No hay filas con categoría y volumen."); return; }
    setGuardando(true);
    try {
      const r = await clasificar(aGuardar.map((f) => ({
        apu_codigo: f.apu_codigo, shift: f.shift, insumo_codigo: f.insumo_codigo,
        insumo_nombre: f.insumo_nombre, categoria: f.categoria as CategoriaTransporte,
        volumen: f.volumen, km_base: f.km_base })));
      toast.success(`${r.aplicados} componentes clasificados.`);
    } catch (e) {
      toast.error(msg(e));
    } finally {
      setGuardando(false);
    }
  }

  return (
    <div className="p-4 space-y-3">
      <p className="text-sm text-muted-foreground">
        Clasificación de la biblioteca de APUs: se hace una sola vez y afecta a
        todos los proyectos, no solo al que estés viendo ahora.
      </p>
      <div className="flex items-center gap-3 text-sm">
        <span className="text-muted-foreground">
          {filas.length} componentes de acarreo · {atipicas} con volumen atípico
        </span>
        <Button onClick={guardar} disabled={guardando}>
          {guardando ? "Guardando…" : (
            `Guardar clasificación (${aGuardar.length} `
            + `${aGuardar.length === 1 ? "fila" : "filas"})`
            + (atipicasAGuardar > 0 ? ` · ${atipicasAGuardar} con volumen atípico` : "")
          )}
        </Button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b text-left text-muted-foreground">
              <th className="py-1 pr-3">APU</th>
              <th className="py-1 pr-3">Insumo</th>
              <th className="py-1 pr-3 text-right">Rend.</th>
              <th className="py-1 pr-3">Categoría</th>
              <th className="py-1 pr-3 text-right">km base</th>
              <th className="py-1 pr-3 text-right">Volumen</th>
              <th className="py-1 pr-3 text-right">km implícito</th>
            </tr>
          </thead>
          <tbody>
            {filas.map((f) => {
              const k = clave(f);
              const raro = f.volumen < 0.5 || f.volumen > 2;
              return (
                <tr key={k} className="border-b">
                  <td className="py-1 pr-3">
                    <span className="font-mono">{f.apu_codigo}</span>{" "}
                    <span className="text-muted-foreground">{f.apu_nombre}</span>
                  </td>
                  <td className="py-1 pr-3">
                    <span className="font-mono text-muted-foreground">{f.insumo_codigo}</span>{" "}
                    {f.insumo_nombre}
                  </td>
                  <td className="py-1 pr-3 text-right">{NUM.format(f.rendimiento)}</td>
                  <td className="py-1 pr-3">
                    <select className="border rounded px-1 py-0.5 bg-background"
                            aria-label={`Categoría de ${k}`}
                            value={f.categoria ?? ""}
                            onChange={(e) => editar(k, {
                              categoria: (e.target.value || null) as CategoriaTransporte })}>
                      <option value="">—</option>
                      {categorias.map((c) => <option key={c} value={c}>{c}</option>)}
                    </select>
                  </td>
                  <td className="py-1 pr-3 text-right">
                    <Input className="w-20 text-right" inputMode="decimal"
                           aria-label={`km base de ${k}`}
                           value={String(f.km_base)}
                           onChange={(e) => editar(k, {
                             km_base: Number(e.target.value.replace(",", ".")) || 0 })} />
                  </td>
                  <td className={`py-1 pr-3 text-right ${raro ? "text-amber-600" : ""}`}>
                    <span>{NUM.format(f.volumen)}</span>{raro ? " ⚠" : ""}
                  </td>
                  <td className="py-1 pr-3 text-right">
                    {f.km_implicito === null ? "—" : NUM.format(f.km_implicito)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
