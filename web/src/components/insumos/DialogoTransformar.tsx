import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { CambioPreview, TransformarPreviewResponse } from "@/lib/tipos";
import { aplicarCambios, transformarPreview } from "@/api/insumos";
import { cop as fmtMoneda } from "@/lib/moneda";

export interface FiltroTransformar {
  q?: string;
  grupo?: string;
  fuente?: string;
  clasificacion?: string;
}

type TipoOperacion = "fuente" | "precio_factor" | "precio_pct" | "precio_set";

interface Operacion {
  tipo: TipoOperacion;
  valor: string | number;
}

interface DialogoTransformarProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  filtro: FiltroTransformar;
  onAplicado: () => void;
}

const LABELS: Record<TipoOperacion, string> = {
  fuente: "Cambiar fuente",
  precio_factor: "Precio × factor",
  precio_pct: "Precio ± %",
  precio_set: "Precio = valor fijo",
};

export function DialogoTransformar({
  open,
  onOpenChange,
  filtro,
  onAplicado,
}: DialogoTransformarProps) {
  const [tipo, setTipo] = useState<TipoOperacion>("precio_pct");
  const [valor, setValor] = useState<string>("");
  const [preview, setPreview] = useState<TransformarPreviewResponse | null>(null);
  const [previsualizando, setPrevisualizando] = useState(false);
  const [aplicando, setAplicando] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  function resetear() {
    setTipo("precio_pct");
    setValor("");
    setPreview(null);
    setErrorMsg(null);
    setPrevisualizando(false);
    setAplicando(false);
  }

  function handleOpenChange(v: boolean) {
    if (!v) resetear();
    onOpenChange(v);
  }

  function buildOperacion(): Operacion {
    if (tipo === "fuente") {
      return { tipo, valor: valor.trim() };
    }
    return { tipo, valor: parseFloat(valor) };
  }

  async function previsualizar() {
    setErrorMsg(null);
    const raw = valor.trim();
    if (!raw) {
      setErrorMsg("Ingresa un valor para la operación.");
      return;
    }
    if (tipo !== "fuente") {
      const n = parseFloat(raw);
      if (Number.isNaN(n)) {
        setErrorMsg("El valor debe ser un número.");
        return;
      }
    }
    setPrevisualizando(true);
    try {
      const res = await transformarPreview({
        filtro,
        operacion: buildOperacion(),
      });
      setPreview(res);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Error al previsualizar";
      setErrorMsg(msg);
    } finally {
      setPrevisualizando(false);
    }
  }

  async function aplicar() {
    if (!preview) return;
    setAplicando(true);
    try {
      const cambiosInput = preview.cambios.map((c: CambioPreview) => ({
        insumo_id: c.insumo_id,
        precio: c.precio_nuevo,
        fuente: c.fuente_nueva,
      }));
      const res = await aplicarCambios(cambiosInput);
      const errCount = res.errores?.length ?? 0;
      if (errCount === 0) {
        toast.success(`${res.aplicados} insumo(s) actualizados correctamente`);
      } else {
        toast.warning(
          `${res.aplicados} aplicado(s), ${errCount} error(es): ` +
            res.errores.map((e) => `#${e.insumo_id}: ${e.error}`).join("; ")
        );
      }
      handleOpenChange(false);
      onAplicado();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Error al aplicar";
      toast.error(`No se pudo aplicar: ${msg}`);
    } finally {
      setAplicando(false);
    }
  }

  const placeholderValor: Record<TipoOperacion, string> = {
    fuente: "ej. PRECIO IDU",
    precio_factor: "ej. 1.1",
    precio_pct: "ej. 10 (= +10%)",
    precio_set: "ej. 50000",
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle className="text-sm">
            Transformar insumos por filtro
          </DialogTitle>
        </DialogHeader>

        {/* Resumen del filtro activo */}
        <div className="text-xs text-muted-foreground border rounded px-2 py-1 bg-muted/30">
          <span className="font-medium">Filtro activo: </span>
          {[
            filtro.q && `buscar="${filtro.q}"`,
            filtro.grupo && `grupo="${filtro.grupo}"`,
            filtro.fuente && `fuente="${filtro.fuente}"`,
            filtro.clasificacion && `clasificacion="${filtro.clasificacion}"`,
          ]
            .filter(Boolean)
            .join(" · ") || "Sin filtros (todos los insumos)"}
        </div>

        {/* Selector de operación + valor */}
        <div className="flex gap-2 items-center">
          <Select value={tipo} onValueChange={(v) => { setTipo(v as TipoOperacion); setPreview(null); setErrorMsg(null); }}>
            <SelectTrigger size="sm" className="w-44 text-xs">
              <SelectValue placeholder="Operación" />
            </SelectTrigger>
            <SelectContent>
              {(Object.keys(LABELS) as TipoOperacion[]).map((k) => (
                <SelectItem key={k} value={k} className="text-xs">
                  {LABELS[k]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Input
            className="h-7 w-40 text-xs"
            type={tipo === "fuente" ? "text" : "number"}
            step={tipo === "precio_factor" ? "0.01" : "any"}
            placeholder={placeholderValor[tipo]}
            value={valor}
            onChange={(e) => { setValor(e.target.value); setPreview(null); setErrorMsg(null); }}
            onKeyDown={(e) => { if (e.key === "Enter") previsualizar(); }}
          />

          <Button
            size="sm"
            variant="outline"
            onClick={previsualizar}
            disabled={previsualizando || aplicando}
          >
            {previsualizando ? "…" : "Previsualizar"}
          </Button>
        </div>

        {errorMsg && (
          <p className="text-xs text-destructive">{errorMsg}</p>
        )}

        {/* Resultado del preview */}
        {preview && (
          <div className="space-y-1">
            <p className="text-xs text-muted-foreground">
              <span className="font-medium text-foreground">{preview.afectados}</span>{" "}
              insumo(s) afectados
            </p>
            <div className="overflow-auto max-h-72 border rounded">
              <table className="w-full text-xs border-collapse">
                <thead className="sticky top-0 bg-muted/80 backdrop-blur z-10">
                  <tr>
                    <th className="px-2 py-1 text-left font-medium text-muted-foreground border-b w-28">
                      Código
                    </th>
                    <th className="px-2 py-1 text-left font-medium text-muted-foreground border-b">
                      Nombre
                    </th>
                    <th className="px-2 py-1 text-right font-medium text-muted-foreground border-b w-28">
                      Precio actual
                    </th>
                    <th className="px-2 py-1 text-right font-medium text-muted-foreground border-b w-28">
                      Precio nuevo
                    </th>
                    <th className="px-2 py-1 text-left font-medium text-muted-foreground border-b w-32">
                      Fuente actual
                    </th>
                    <th className="px-2 py-1 text-left font-medium text-muted-foreground border-b w-32">
                      Fuente nueva
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {preview.cambios.map((c) => {
                    const precioChanged = c.precio_nuevo !== c.precio_actual;
                    const fuenteChanged = c.fuente_nueva !== c.fuente_actual;
                    return (
                      <tr key={c.insumo_id} className="hover:bg-muted/40 even:bg-muted/10">
                        <td className="px-2 py-0.5 font-mono">{c.codigo}</td>
                        <td className="px-2 py-0.5 truncate max-w-xs" title={c.nombre}>
                          {c.nombre}
                        </td>
                        <td className="px-2 py-0.5 text-right text-muted-foreground">
                          {fmtMoneda(c.precio_actual)}
                        </td>
                        <td className={`px-2 py-0.5 text-right font-medium ${precioChanged ? "text-amber-700 dark:text-amber-400" : ""}`}>
                          {fmtMoneda(c.precio_nuevo)}
                        </td>
                        <td className="px-2 py-0.5 text-muted-foreground">{c.fuente_actual}</td>
                        <td className={`px-2 py-0.5 ${fuenteChanged ? "font-medium text-amber-700 dark:text-amber-400" : "text-muted-foreground"}`}>
                          {c.fuente_nueva}
                        </td>
                      </tr>
                    );
                  })}
                  {preview.cambios.length === 0 && (
                    <tr>
                      <td colSpan={6} className="px-3 py-6 text-center text-muted-foreground">
                        Ningún insumo será modificado
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        <DialogFooter>
          <Button
            size="sm"
            variant="outline"
            onClick={() => handleOpenChange(false)}
            disabled={aplicando}
          >
            Cancelar
          </Button>
          <Button
            size="sm"
            onClick={aplicar}
            disabled={!preview || preview.cambios.length === 0 || aplicando}
          >
            {aplicando ? "Aplicando…" : `Aplicar${preview ? ` (${preview.afectados})` : ""}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
