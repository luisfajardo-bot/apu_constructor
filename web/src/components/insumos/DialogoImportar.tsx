import { useRef, useState } from "react";
import { toast } from "sonner";
import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { CambioPreview, ImportAmbiguo, ImportNoEncontrado } from "@/lib/tipos";
import { aplicarCambios, importarPreview, descargarPlantillaPrecios } from "@/api/insumos";
import { cop as fmtMoneda } from "@/lib/moneda";

interface DialogoImportarProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAplicado: () => void;
}

type EstadoDial =
  | { fase: "idle" }
  | { fase: "cargando" }
  | {
      fase: "preview";
      cambios: CambioPreview[];
      ambiguos: ImportAmbiguo[];
      no_encontrados: ImportNoEncontrado[];
    }
  | { fase: "aplicando" };

export function DialogoImportar({
  open,
  onOpenChange,
  onAplicado,
}: DialogoImportarProps) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [estado, setEstado] = useState<EstadoDial>({ fase: "idle" });
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  function resetear() {
    setEstado({ fase: "idle" });
    setErrorMsg(null);
    if (fileRef.current) fileRef.current.value = "";
  }

  function handleOpenChange(v: boolean) {
    if (!v) resetear();
    onOpenChange(v);
  }

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const archivo = e.target.files?.[0];
    if (!archivo) return;

    setErrorMsg(null);
    setEstado({ fase: "cargando" });

    try {
      const form = new FormData();
      form.append("archivo", archivo);
      const res = await importarPreview(form);

      setEstado({
        fase: "preview",
        cambios: res.cambios,
        ambiguos: res.ambiguos ?? [],
        no_encontrados: res.no_encontrados ?? [],
      });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Error al procesar el archivo";
      setErrorMsg(msg);
      setEstado({ fase: "idle" });
    }
  }

  async function aplicar() {
    if (estado.fase !== "preview") return;
    const { cambios } = estado;
    if (cambios.length === 0) return;

    setEstado({ fase: "aplicando" });
    try {
      const cambiosInput = cambios.map((c: CambioPreview) => ({
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
      // Restauramos a idle para evitar quedarnos en "aplicando" indefinidamente.
      setEstado({ fase: "idle" });
    }
  }

  async function bajarPlantilla() {
    try {
      await descargarPlantillaPrecios();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "No se pudo descargar la plantilla.");
    }
  }

  const fase = estado.fase;
  const enPreview = fase === "preview";
  const enAplicando = fase === "aplicando";
  const reconocidos = enPreview ? estado.cambios : [];
  const ambiguos = enPreview ? estado.ambiguos : [];
  const noEncontrados = enPreview ? estado.no_encontrados : [];

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle className="text-sm">
            Importar precios desde Excel / CSV
          </DialogTitle>
        </DialogHeader>

        {/* Zona de carga */}
        <div className="flex items-center gap-3">
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx,.xls,.csv"
            onChange={handleFileChange}
            disabled={fase === "cargando" || enAplicando}
            className="text-xs file:mr-2 file:rounded file:border file:border-border file:bg-muted file:px-2 file:py-0.5 file:text-xs file:font-medium file:cursor-pointer cursor-pointer disabled:opacity-50"
          />
          {fase === "cargando" && (
            <span className="text-xs text-muted-foreground animate-pulse">
              procesando…
            </span>
          )}
          <Button
            size="sm"
            variant="outline"
            type="button"
            onClick={bajarPlantilla}
            disabled={enAplicando}
            className="ml-auto"
          >
            <Download className="mr-1 h-3.5 w-3.5" />
            Descargar plantilla
          </Button>
        </div>

        {errorMsg && (
          <p className="text-xs text-destructive">{errorMsg}</p>
        )}

        {/* Vista previa tri-sección */}
        {enPreview && (
          <div className="space-y-3">
            {/* ── Sección 1: Reconocidos ── */}
            <div>
              <p className="text-xs font-semibold mb-1">
                Reconocidos{" "}
                <span className="font-normal text-muted-foreground">
                  ({reconocidos.length})
                </span>
              </p>
              <div className="overflow-auto max-h-52 border rounded">
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
                        Fuente nueva
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {reconocidos.map((c) => (
                      <tr
                        key={c.insumo_id}
                        className="hover:bg-muted/40 even:bg-muted/10"
                      >
                        <td className="px-2 py-0.5 font-mono">{c.codigo}</td>
                        <td
                          className="px-2 py-0.5 truncate max-w-xs"
                          title={c.nombre}
                        >
                          {c.nombre}
                        </td>
                        <td className="px-2 py-0.5 text-right text-muted-foreground">
                          {fmtMoneda(c.precio_actual)}
                        </td>
                        <td className="px-2 py-0.5 text-right font-medium text-amber-700 dark:text-amber-400">
                          {fmtMoneda(c.precio_nuevo)}
                        </td>
                        <td className="px-2 py-0.5">{c.fuente_nueva}</td>
                      </tr>
                    ))}
                    {reconocidos.length === 0 && (
                      <tr>
                        <td
                          colSpan={5}
                          className="px-3 py-4 text-center text-muted-foreground"
                        >
                          Sin reconocidos
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {/* ── Sección 2: Ambiguos ── */}
            <div>
              <p className="text-xs font-semibold mb-1">
                Ambiguos{" "}
                <span className="font-normal text-muted-foreground">
                  ({ambiguos.length})
                </span>
              </p>
              {ambiguos.length > 0 ? (
                <div className="overflow-auto max-h-36 border rounded">
                  <table className="w-full text-xs border-collapse">
                    <thead className="sticky top-0 bg-muted/80 backdrop-blur z-10">
                      <tr>
                        <th className="px-2 py-1 text-left font-medium text-muted-foreground border-b w-28">
                          Código
                        </th>
                        <th className="px-2 py-1 text-left font-medium text-muted-foreground border-b">
                          Candidatos
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {ambiguos.map((a) => (
                        <tr
                          key={a.codigo}
                          className="hover:bg-muted/40 even:bg-muted/10"
                        >
                          <td className="px-2 py-0.5 font-mono align-top">
                            {a.codigo}
                          </td>
                          <td className="px-2 py-0.5">
                            {a.candidatos.map((c) => c.nombre).join(" · ")}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">Ninguno</p>
              )}
            </div>

            {/* ── Sección 3: No encontrados ── */}
            <div>
              <p className="text-xs font-semibold mb-1">
                No encontrados{" "}
                <span className="font-normal text-muted-foreground">
                  ({noEncontrados.length})
                </span>
              </p>
              {noEncontrados.length > 0 ? (
                <div className="overflow-auto max-h-28 border rounded">
                  <table className="w-full text-xs border-collapse">
                    <thead className="sticky top-0 bg-muted/80 backdrop-blur z-10">
                      <tr>
                        <th className="px-2 py-1 text-left font-medium text-muted-foreground border-b w-28">
                          Código
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {noEncontrados.map((n) => (
                        <tr
                          key={n.codigo}
                          className="hover:bg-muted/40 even:bg-muted/10"
                        >
                          <td className="px-2 py-0.5 font-mono">{n.codigo}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">Ninguno</p>
              )}
            </div>
          </div>
        )}

        <DialogFooter>
          <Button
            size="sm"
            variant="outline"
            onClick={() => handleOpenChange(false)}
            disabled={enAplicando}
          >
            Cancelar
          </Button>
          <Button
            size="sm"
            onClick={aplicar}
            disabled={
              !enPreview ||
              reconocidos.length === 0 ||
              enAplicando
            }
          >
            {enAplicando
              ? "Aplicando…"
              : `Aplicar los ${enPreview ? reconocidos.length : 0} reconocidos`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
