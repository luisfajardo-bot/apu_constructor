import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { verTransporte, guardarTransporte } from "@/api/transporte";
import type { ParametrosTransporte, VistaTransporte } from "@/lib/tipos";
import { useAuth } from "@/lib/auth";
import { puede } from "@/components/rutas";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const NUM = new Intl.NumberFormat("es-CO", { maximumFractionDigits: 3 });

function num(v: string): number | null {
  const t = v.trim();
  if (!t) return null;
  const n = Number(t.replace(",", "."));
  return Number.isFinite(n) ? n : null;
}

function msg(e: unknown): string {
  return e instanceof Error ? e.message : "Error desconocido";
}

export default function DistanciasProyecto() {
  const carpetaId = Number(useParams().carpetaId);
  const { perfil } = useAuth();
  const puedeEditar = puede(perfil?.rol, "editor");
  const [vista, setVista] = useState<VistaTransporte | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [peaje, setPeaje] = useState(false);
  const [guardando, setGuardando] = useState(false);

  useEffect(() => {
    verTransporte(carpetaId)
      .then((v) => {
        setVista(v);
        setForm({
          km_botadero: v.parametros.km_botadero?.toString() ?? "",
          km_mezclas: v.parametros.km_mezclas?.toString() ?? "",
          km_granulares: v.parametros.km_granulares?.toString() ?? "",
          peaje_valor: v.parametros.peaje_valor?.toString() ?? "",
        });
        setPeaje(v.parametros.peaje_aplica === true);
      })
      .catch((e) => toast.error(msg(e)));
  }, [carpetaId]);

  async function guardar() {
    setGuardando(true);
    try {
      const payload: Partial<ParametrosTransporte> = {
        km_botadero: num(form.km_botadero ?? ""),
        km_mezclas: num(form.km_mezclas ?? ""),
        km_granulares: num(form.km_granulares ?? ""),
        peaje_aplica: peaje,
        peaje_valor: peaje ? num(form.peaje_valor ?? "") : null,
      };
      setVista(await guardarTransporte(carpetaId, payload));
      toast.success("Distancias del proyecto guardadas. Las corridas activas se recostean.");
    } catch (e) {
      toast.error(msg(e));
    } finally {
      setGuardando(false);
    }
  }

  if (!vista) return <div className="p-4 text-sm text-muted-foreground">Cargando…</div>;

  return (
    <div className="p-4 space-y-4">
      <div className="flex flex-wrap items-end gap-4">
        <Campo id="km_botadero" etiqueta="Botadero (km)" form={form} setForm={setForm}
               disabled={!puedeEditar} />
        <Campo id="km_mezclas" etiqueta="Mezclas (km)" form={form} setForm={setForm}
               disabled={!puedeEditar} />
        <Campo id="km_granulares" etiqueta="Granulares (km)" form={form} setForm={setForm}
               disabled={!puedeEditar} />
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={peaje} disabled={!puedeEditar}
                 onChange={(e) => setPeaje(e.target.checked)} />
          Peaje
        </label>
        {peaje && (
          <Campo id="peaje_valor" etiqueta="Valor del peaje" form={form} setForm={setForm}
                 disabled={!puedeEditar} />
        )}
        <Button onClick={guardar} disabled={guardando || !puedeEditar}>
          {guardando ? "Guardando…" : "Guardar"}
        </Button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b text-left text-muted-foreground">
              <th className="py-1 pr-3">APU</th>
              <th className="py-1 pr-3">Insumo</th>
              <th className="py-1 pr-3">Un.</th>
              <th className="py-1 pr-3 text-right">Rend. hoy</th>
              <th className="py-1 pr-3">Categoría</th>
              <th className="py-1 pr-3 text-right">Vol.</th>
              <th className="py-1 pr-3 text-right">Rend. nuevo</th>
            </tr>
          </thead>
          <tbody>
            {vista.impacto.map((f) => (
              <tr key={`${f.apu_codigo}|${f.shift}|${f.insumo_codigo}`} className="border-b">
                <td className="py-1 pr-3 font-mono">{f.apu_codigo}</td>
                <td className="py-1 pr-3">
                  <span className="font-mono text-muted-foreground">{f.insumo_codigo}</span>{" "}
                  {f.insumo_nombre}
                </td>
                <td className="py-1 pr-3">{f.unidad}</td>
                <td className="py-1 pr-3 text-right">{NUM.format(f.rendimiento_actual)}</td>
                <td className="py-1 pr-3">{f.categoria ?? "—"}</td>
                <td className="py-1 pr-3 text-right">
                  {f.volumen === null ? "—" : NUM.format(f.volumen)}
                </td>
                <td className="py-1 pr-3 text-right">
                  {f.quitado ? "quitado"
                    : f.sin_clasificar ? "⚠ sin clasificar"
                    : NUM.format(f.rendimiento_nuevo ?? f.rendimiento_actual)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="text-sm text-muted-foreground">
        {vista.impacto.length} componentes de acarreo ·{" "}
        {vista.sin_clasificar} componente{vista.sin_clasificar === 1 ? "" : "s"} sin
        clasificar{" "}
        <Link className="underline" to="/transporte/clasificacion">Clasificar</Link>
      </div>
    </div>
  );
}

function Campo({ id, etiqueta, form, setForm, disabled }: {
  id: string; etiqueta: string;
  form: Record<string, string>;
  setForm: (f: (p: Record<string, string>) => Record<string, string>) => void;
  disabled?: boolean;
}) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-muted-foreground">{etiqueta}</span>
      <Input id={id} aria-label={etiqueta} className="w-28" inputMode="decimal"
             disabled={disabled}
             value={form[id] ?? ""}
             onChange={(e) => setForm((p) => ({ ...p, [id]: e.target.value }))} />
    </label>
  );
}
