import { useRef, useState } from "react";
import { toast } from "sonner";
import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import type { ImportInsumosUpsertPreview } from "@/lib/tipos";
import {
  previewImportarInsumos, aplicarImportarInsumos, descargarPlantillaInsumos,
} from "@/api/insumos";
import { cop } from "@/lib/moneda";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAplicado: () => void;
}

type Estado =
  | { fase: "idle" }
  | { fase: "cargando" }
  | { fase: "preview"; prev: ImportInsumosUpsertPreview }
  | { fase: "aplicando" };

export function DialogoImportarInsumos({ open, onOpenChange, onAplicado }: Props) {
  const fileRef = useRef<HTMLInputElement>(null);
  const archivoRef = useRef<File | null>(null);
  const [estado, setEstado] = useState<Estado>({ fase: "idle" });
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
      const prev = await previewImportarInsumos(form);
      setEstado({ fase: "preview", prev });
    } catch (e: unknown) {
      setErrorMsg(e instanceof Error ? e.message : "Error al procesar el archivo");
      setEstado({ fase: "idle" });
    }
  }

  async function bajarPlantilla() {
    try {
      await descargarPlantillaInsumos();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "No se pudo descargar la plantilla.");
    }
  }

  async function aplicar() {
    if (estado.fase !== "preview") return;
    const archivo = archivoRef.current;
    if (!archivo) return;
    setEstado({ fase: "aplicando" });
    try {
      const form = new FormData();
      form.append("archivo", archivo);
      const res = await aplicarImportarInsumos(form);
      const errCount = res.errores?.length ?? 0;
      const resumen = `${res.creados} creado(s), ${res.actualizados} actualizado(s)`;
      if (errCount === 0) toast.success(resumen);
      else toast.warning(`${resumen}, ${errCount} error(es): ` +
        res.errores.map((er) => `${er.codigo}: ${er.error}`).join("; "));
      handleOpenChange(false);
      onAplicado();
    } catch (e: unknown) {
      toast.error(`No se pudo aplicar: ${e instanceof Error ? e.message : "error"}`);
      setEstado({ fase: "idle" });
    }
  }

  const enPreview = estado.fase === "preview";
  const enAplicando = estado.fase === "aplicando";
  const prev = enPreview ? estado.prev : null;
  const nAcciones = prev ? prev.crear.length + prev.actualizar.length : 0;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="text-sm">Importar insumos (crear + actualizar precios)</DialogTitle>
        </DialogHeader>

        <p className="text-xs text-muted-foreground">
          Con nombre: crea el insumo o, si ya existe, actualiza su precio. Sin nombre: solo
          actualiza el precio por código.
        </p>

        <div className="flex flex-wrap items-center gap-3">
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx,.xls,.csv"
            onChange={handleFileChange}
            disabled={estado.fase === "cargando" || enAplicando}
            className="text-xs file:mr-2 file:rounded file:border file:border-border file:bg-muted file:px-2 file:py-0.5 file:text-xs file:font-medium file:cursor-pointer cursor-pointer disabled:opacity-50"
          />
          {estado.fase === "cargando" && (
            <span className="text-xs text-muted-foreground animate-pulse">procesando…</span>
          )}
          <Button size="sm" variant="outline" type="button" onClick={bajarPlantilla}
                  disabled={enAplicando} className="ml-auto">
            <Download className="mr-1 h-3.5 w-3.5" />
            Descargar plantilla
          </Button>
        </div>

        {errorMsg && <p className="text-xs text-destructive">{errorMsg}</p>}

        {prev && (
          <div className="space-y-3">
            <Seccion titulo="Crear">
              <Tabla cols={["Código", "Nombre", "Und", "Grupo", "Precio", "Fuente"]}
                     filas={prev.crear.map((f) => [f.codigo, f.nombre, f.unidad, f.grupo, cop(f.precio), f.fuente])} />
            </Seccion>
            <Seccion titulo="Actualizar precio">
              <Tabla cols={["Código", "Nombre", "Precio actual", "Precio nuevo", "Fuente nueva"]}
                     filas={prev.actualizar.map((c) => [c.codigo, c.nombre, cop(c.precio_actual), cop(c.precio_nuevo), c.fuente_nueva])} />
            </Seccion>
            <Seccion titulo="Ambiguas (código repetido, sin nombre)">
              <Tabla cols={["Código", "Candidatos"]}
                     filas={prev.ambigua.map((a) => [a.codigo, a.candidatos.map((c) => c.nombre).join(" · ")])} />
            </Seccion>
            <Seccion titulo="No encontradas (sin nombre, código inexistente)">
              <Tabla cols={["Código"]} filas={prev.no_encontrada.map((n) => [n.codigo])} />
            </Seccion>
            <Seccion titulo="Inválidas (sin código)">
              <Tabla cols={["Nombre"]} filas={prev.invalida.map((f) => [f.nombre])} />
            </Seccion>
          </div>
        )}

        <DialogFooter>
          <Button size="sm" variant="outline" onClick={() => handleOpenChange(false)} disabled={enAplicando}>
            Cancelar
          </Button>
          <Button size="sm" onClick={aplicar} disabled={!enPreview || nAcciones === 0 || enAplicando}>
            {enAplicando ? "Aplicando…" : `Aplicar (${nAcciones})`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Seccion({ titulo, children }: { titulo: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs font-semibold mb-1">{titulo}</p>
      {children}
    </div>
  );
}

function Tabla({ cols, filas }: { cols: string[]; filas: (string | number)[][] }) {
  if (filas.length === 0) return <p className="text-xs text-muted-foreground">Ninguno</p>;
  return (
    <div className="overflow-x-hidden overflow-y-auto max-h-52 border rounded">
      <table className="w-full text-xs border-collapse">
        <thead className="sticky top-0 bg-muted/80 backdrop-blur z-10">
          <tr>
            {cols.map((c) => (
              <th key={c} className="px-2 py-1 text-left font-medium text-muted-foreground border-b align-bottom">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {filas.map((fila, i) => (
            <tr key={i} className="hover:bg-muted/40 even:bg-muted/10">
              {fila.map((v, j) => (
                <td key={j} className="px-2 py-0.5 align-top break-words">{v}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
