import { useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { InsumoImportFila } from "@/lib/tipos";
import { previewImportarInsumos, aplicarImportarInsumos } from "@/api/autoria";
import { cop } from "@/lib/moneda";

interface DialogoImportarCrearInsumosProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAplicado: () => void;
}

type EstadoDial =
  | { fase: "idle" }
  | { fase: "cargando" }
  | {
      fase: "preview";
      crear: InsumoImportFila[];
      ya_existe: InsumoImportFila[];
      invalida: InsumoImportFila[];
    }
  | { fase: "aplicando" };

export function DialogoImportarCrearInsumos({
  open,
  onOpenChange,
  onAplicado,
}: DialogoImportarCrearInsumosProps) {
  const fileRef = useRef<HTMLInputElement>(null);
  // Conservamos el archivo elegido para re-enviarlo al aplicar.
  const archivoRef = useRef<File | null>(null);
  const [estado, setEstado] = useState<EstadoDial>({ fase: "idle" });
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  function resetear() {
    setEstado({ fase: "idle" });
    setErrorMsg(null);
    archivoRef.current = null;
    if (fileRef.current) fileRef.current.value = "";
  }

  function handleOpenChange(v: boolean) {
    if (!v) resetear();
    onOpenChange(v);
  }

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const archivo = e.target.files?.[0];
    if (!archivo) return;

    archivoRef.current = archivo;
    setErrorMsg(null);
    setEstado({ fase: "cargando" });

    try {
      const form = new FormData();
      form.append("archivo", archivo);
      const res = await previewImportarInsumos(form);
      setEstado({
        fase: "preview",
        crear: res.crear ?? [],
        ya_existe: res.ya_existe ?? [],
        invalida: res.invalida ?? [],
      });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Error al procesar el archivo";
      setErrorMsg(msg);
      setEstado({ fase: "idle" });
    }
  }

  async function aplicar() {
    if (estado.fase !== "preview") return;
    const archivo = archivoRef.current;
    if (!archivo || estado.crear.length === 0) return;

    setEstado({ fase: "aplicando" });
    try {
      const form = new FormData();
      form.append("archivo", archivo);
      const res = await aplicarImportarInsumos(form);
      const errCount = res.errores?.length ?? 0;
      if (errCount === 0) {
        toast.success(`${res.creados} insumo(s) creados`);
      } else {
        toast.warning(
          `${res.creados} creado(s), ${errCount} error(es): ` +
            res.errores.map((er) => `${er.codigo}: ${er.error}`).join("; "),
        );
      }
      handleOpenChange(false);
      onAplicado();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Error al aplicar";
      toast.error(`No se pudo aplicar: ${msg}`);
      setEstado({ fase: "idle" });
    }
  }

  const enPreview = estado.fase === "preview";
  const enAplicando = estado.fase === "aplicando";
  const crear = enPreview ? estado.crear : [];
  const yaExiste = enPreview ? estado.ya_existe : [];
  const invalida = enPreview ? estado.invalida : [];

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle className="text-sm">
            Importar insumos para crear (Excel / CSV)
          </DialogTitle>
        </DialogHeader>

        <div className="flex items-center gap-3">
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx,.xls,.csv"
            onChange={handleFileChange}
            disabled={estado.fase === "cargando" || enAplicando}
            className="text-xs file:mr-2 file:rounded file:border file:border-border file:bg-muted file:px-2 file:py-0.5 file:text-xs file:font-medium file:cursor-pointer cursor-pointer disabled:opacity-50"
          />
          {estado.fase === "cargando" && (
            <span className="text-xs text-muted-foreground animate-pulse">
              procesando…
            </span>
          )}
        </div>

        {errorMsg && <p className="text-xs text-destructive">{errorMsg}</p>}

        {enPreview && (
          <div className="space-y-3">
            <SeccionInsumos titulo="A crear" filas={crear} tono="ok" />
            <SeccionInsumos titulo="Ya existen" filas={yaExiste} tono="mut" />
            <SeccionInsumos titulo="Inválidas" filas={invalida} tono="err" />
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
            disabled={!enPreview || crear.length === 0 || enAplicando}
          >
            {enAplicando ? "Creando…" : `Crear los ${enPreview ? crear.length : 0}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function SeccionInsumos({
  titulo,
  filas,
  tono,
}: {
  titulo: string;
  filas: InsumoImportFila[];
  tono: "ok" | "mut" | "err";
}) {
  const precioCls =
    tono === "ok"
      ? "text-emerald-700 dark:text-emerald-400"
      : tono === "err"
        ? "text-destructive"
        : "text-muted-foreground";

  return (
    <div>
      <p className="text-xs font-semibold mb-1">
        {titulo}{" "}
        <span className="font-normal text-muted-foreground">({filas.length})</span>
      </p>
      {filas.length > 0 ? (
        <div className="overflow-auto max-h-44 border rounded">
          <table className="w-full text-xs border-collapse">
            <thead className="sticky top-0 bg-muted/80 backdrop-blur z-10">
              <tr>
                <th className="px-2 py-1 text-left font-medium text-muted-foreground border-b w-28">
                  Código
                </th>
                <th className="px-2 py-1 text-left font-medium text-muted-foreground border-b">
                  Nombre
                </th>
                <th className="px-2 py-1 text-left font-medium text-muted-foreground border-b w-14">
                  Und
                </th>
                <th className="px-2 py-1 text-left font-medium text-muted-foreground border-b w-28">
                  Grupo
                </th>
                <th className="px-2 py-1 text-right font-medium text-muted-foreground border-b w-24">
                  Precio
                </th>
                <th className="px-2 py-1 text-left font-medium text-muted-foreground border-b w-28">
                  Fuente
                </th>
              </tr>
            </thead>
            <tbody>
              {filas.map((f, i) => (
                <tr
                  key={`${f.codigo}-${i}`}
                  className="hover:bg-muted/40 even:bg-muted/10"
                >
                  <td className="px-2 py-0.5 font-mono">{f.codigo}</td>
                  <td className="px-2 py-0.5 truncate max-w-xs" title={f.nombre}>
                    {f.nombre}
                  </td>
                  <td className="px-2 py-0.5">{f.unidad}</td>
                  <td className="px-2 py-0.5 truncate max-w-[8rem]" title={f.grupo}>
                    {f.grupo}
                  </td>
                  <td className={`px-2 py-0.5 text-right font-mono ${precioCls}`}>
                    {cop(f.precio)}
                  </td>
                  <td className="px-2 py-0.5">{f.fuente}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">Ninguno</p>
      )}
    </div>
  );
}
