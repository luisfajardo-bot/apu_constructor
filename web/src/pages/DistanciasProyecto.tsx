import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { verTransporte, guardarTransporte, listarAjustes, borrarAjuste } from "@/api/transporte";
import type { AjusteProyecto, ParametrosTransporte, VistaTransporte } from "@/lib/tipos";
import { useAuth } from "@/lib/auth";
import { puede } from "@/components/rutas";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const NUM = new Intl.NumberFormat("es-CO", { maximumFractionDigits: 3 });

const ETIQUETA_ACCION: Record<AjusteProyecto["accion"], string> = {
  rendimiento: "Rendimiento",
  agregar: "Agregar insumo",
  quitar: "Quitar insumo",
  reemplazar: "Reemplazar insumo",
};

function fechaLegible(iso?: string): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("es-CO", {
      year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

// Etiquetas visibles de cada campo, compartidas entre el formulario y el
// mensaje de error de guardar() (para no repetir el texto en dos lugares).
const ETIQUETAS: Record<string, string> = {
  km_botadero: "Botadero (km)",
  km_mezclas: "Mezclas (km)",
  km_granulares: "Granulares (km)",
  peaje_valor: "Valor del peaje",
};

// null = el campo esta vacio a proposito ("esta distancia no aplica").
// undefined = hay texto que no es un numero: es un error del usuario, no un "no aplica".
function num(v: string): number | null | undefined {
  const t = v.trim();
  if (!t) return null;
  const n = Number(t.replace(",", "."));
  return Number.isFinite(n) ? n : undefined;
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
  const [ajustes, setAjustes] = useState<AjusteProyecto[]>([]);

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

  useEffect(() => {
    listarAjustes(carpetaId).then(setAjustes).catch((e) => toast.error(msg(e)));
  }, [carpetaId]);

  async function eliminarAjuste(a: AjusteProyecto) {
    if (a.id == null) return;
    if (!window.confirm(
      `¿Borrar este ajuste? Afecta a todas las corridas del proyecto.`)) return;
    try {
      await borrarAjuste(carpetaId, a.id);
      toast.success("Ajuste borrado.");
      // El costo del proyecto cambió: se refresca el impacto (verTransporte)
      // y la lista de ajustes, igual que hace guardar() con la respuesta del PUT.
      await Promise.all([
        verTransporte(carpetaId).then(setVista),
        listarAjustes(carpetaId).then(setAjustes),
      ]);
    } catch (e) {
      toast.error(msg(e));
    }
  }

  async function guardar() {
    const km_botadero = num(form.km_botadero ?? "");
    const km_mezclas = num(form.km_mezclas ?? "");
    const km_granulares = num(form.km_granulares ?? "");
    const peaje_valor = peaje ? num(form.peaje_valor ?? "") : null;

    // Basura (texto que no es número) bloquea el guardado; vacío ("no aplica")
    // sigue viajando como null. Ver `num()`.
    const invalido = ([
      ["km_botadero", km_botadero],
      ["km_mezclas", km_mezclas],
      ["km_granulares", km_granulares],
      ["peaje_valor", peaje_valor],
    ] as const).find(([, v]) => v === undefined);
    if (invalido) {
      const [campo] = invalido;
      toast.error(`${ETIQUETAS[campo]}: "${form[campo] ?? ""}" no es un número.`);
      return;
    }

    setGuardando(true);
    try {
      const payload: Partial<ParametrosTransporte> = {
        km_botadero: km_botadero ?? null,
        km_mezclas: km_mezclas ?? null,
        km_granulares: km_granulares ?? null,
        peaje_aplica: peaje,
        peaje_valor: peaje_valor ?? null,
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
        <Campo id="km_botadero" etiqueta={ETIQUETAS.km_botadero} form={form} setForm={setForm}
               disabled={!puedeEditar} />
        <Campo id="km_mezclas" etiqueta={ETIQUETAS.km_mezclas} form={form} setForm={setForm}
               disabled={!puedeEditar} />
        <Campo id="km_granulares" etiqueta={ETIQUETAS.km_granulares} form={form} setForm={setForm}
               disabled={!puedeEditar} />
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={peaje} disabled={!puedeEditar}
                 onChange={(e) => setPeaje(e.target.checked)} />
          Peaje
        </label>
        {peaje && (
          <Campo id="peaje_valor" etiqueta={ETIQUETAS.peaje_valor} form={form} setForm={setForm}
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

      <div className="space-y-2">
        <h2 className="text-sm font-medium">Ajustes del proyecto</h2>
        <div className="text-sm text-muted-foreground">
          Ajustes puntuales de composición que valen solo para este proyecto: no tocan
          la biblioteca de APUs.
        </div>
        {ajustes.length === 0 ? (
          <div className="text-sm text-muted-foreground">
            Este proyecto no tiene ajustes de composición.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm border-collapse">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="py-1 pr-3">APU</th>
                  <th className="py-1 pr-3">Acción</th>
                  <th className="py-1 pr-3">Insumo</th>
                  <th className="py-1 pr-3 text-right">Rendimiento</th>
                  <th className="py-1 pr-3">Nota</th>
                  <th className="py-1 pr-3">Creado</th>
                  {puedeEditar && <th className="py-1 pr-3" />}
                </tr>
              </thead>
              <tbody>
                {ajustes.map((a) => (
                  <tr key={a.id} className="border-b align-top">
                    <td className="py-1 pr-3 font-mono">{a.apu_codigo} · {a.shift}</td>
                    <td className="py-1 pr-3">{ETIQUETA_ACCION[a.accion]}</td>
                    <td className="py-1 pr-3">
                      <span className="font-mono text-muted-foreground">{a.insumo_codigo}</span>{" "}
                      {a.insumo_nombre}
                      {a.accion === "reemplazar" && a.insumo_nuevo_codigo && (
                        <>
                          {" → "}
                          <span className="font-mono text-muted-foreground">
                            {a.insumo_nuevo_codigo}
                          </span>{" "}
                          {a.insumo_nuevo_nombre}
                        </>
                      )}
                    </td>
                    <td className="py-1 pr-3 text-right">
                      {a.rendimiento != null ? NUM.format(a.rendimiento) : "—"}
                    </td>
                    <td className="py-1 pr-3">{a.nota || "—"}</td>
                    <td className="py-1 pr-3 text-muted-foreground">
                      {a.creado_por ?? "—"}
                      <br />
                      {fechaLegible(a.creado_en)}
                    </td>
                    {puedeEditar && (
                      <td className="py-1 pr-3">
                        <Button variant="destructive" size="xs" title="Borrar este ajuste"
                                onClick={() => eliminarAjuste(a)}>
                          Borrar
                        </Button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
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
