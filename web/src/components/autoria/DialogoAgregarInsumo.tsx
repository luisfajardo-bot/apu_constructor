import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { crearInsumo } from "@/api/autoria";
import { conflictoInsumo } from "@/api/insumos";
import type { ConflictoAlta } from "@/lib/tipos";

interface DialogoAgregarInsumoProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  listaId: number;
  onCreado: () => void;
}

interface Campos {
  codigo: string;
  nombre: string;
  unidad: string;
  grupo: string;
  precio: string;
  fuente: string;
}

const VACIO: Campos = {
  codigo: "",
  nombre: "",
  unidad: "",
  grupo: "",
  precio: "",
  fuente: "",
};

const inputCls =
  "h-8 w-full rounded border border-border bg-transparent px-2 py-1 text-xs outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40";

export function DialogoAgregarInsumo({
  open,
  onOpenChange,
  listaId,
  onCreado,
}: DialogoAgregarInsumoProps) {
  const [c, setC] = useState<Campos>(VACIO);
  const [guardando, setGuardando] = useState(false);
  const [conflicto, setConflicto] = useState<ConflictoAlta | null>(null);

  function set<K extends keyof Campos>(k: K, v: string) {
    setC((prev) => ({ ...prev, [k]: v }));
  }

  function handleOpenChange(v: boolean) {
    if (!v) {
      setC(VACIO);
      setGuardando(false);
      setConflicto(null);
    }
    onOpenChange(v);
  }

  // Aviso en vivo: mismo chequeo que hace el 400 al guardar (ver @/api/insumos),
  // con debounce para no consultar en cada tecla. Falla abierta: un error de red
  // limpia el aviso y no bloquea el formulario, el 400 del guardado es la red.
  useEffect(() => {
    const codigo = c.codigo.trim();
    const nombre = c.nombre.trim();
    if (!codigo || !nombre) {
      setConflicto(null);
      return;
    }
    let cancelado = false;
    const t = setTimeout(async () => {
      try {
        const res = await conflictoInsumo(codigo, nombre);
        if (!cancelado) setConflicto(res);
      } catch {
        if (!cancelado) setConflicto(null);
      }
    }, 400);
    return () => {
      cancelado = true;
      clearTimeout(t);
    };
  }, [c.codigo, c.nombre]);

  const precioNum = Number(c.precio);
  const precioValido = c.precio.trim() !== "" && Number.isFinite(precioNum) && precioNum >= 0;
  const valido =
    c.codigo.trim() !== "" &&
    c.nombre.trim() !== "" &&
    c.unidad.trim() !== "" &&
    c.grupo.trim() !== "" &&
    c.fuente.trim() !== "" &&
    precioValido &&
    conflicto?.motivo == null;

  async function guardar() {
    if (!valido) return;
    setGuardando(true);
    try {
      const ins = await crearInsumo({
        codigo: c.codigo.trim(),
        nombre: c.nombre.trim(),
        unidad: c.unidad.trim(),
        grupo: c.grupo.trim(),
        precio: precioNum,
        fuente: c.fuente.trim(),
        lista_id: listaId,
      });
      toast.success(`Insumo ${ins.codigo} creado`);
      handleOpenChange(false);
      onCreado();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Error al crear el insumo";
      toast.error(msg);
      setGuardando(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="text-sm">Agregar insumo</DialogTitle>
        </DialogHeader>

        <div className="grid grid-cols-2 gap-2">
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-muted-foreground">Código</span>
            <input
              className={inputCls}
              value={c.codigo}
              onChange={(e) => set("codigo", e.target.value)}
              autoFocus
            />
            {conflicto?.campo === "codigo" && (
              <span className="text-destructive">{conflicto.motivo}</span>
            )}
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-muted-foreground">Unidad</span>
            <input
              className={inputCls}
              value={c.unidad}
              onChange={(e) => set("unidad", e.target.value)}
            />
          </label>
          <label className="col-span-2 flex flex-col gap-1 text-xs">
            <span className="text-muted-foreground">Nombre</span>
            <input
              className={inputCls}
              value={c.nombre}
              onChange={(e) => set("nombre", e.target.value)}
            />
            {conflicto?.campo === "nombre" && (
              <span className="text-destructive">{conflicto.motivo}</span>
            )}
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-muted-foreground">Grupo</span>
            <input
              className={inputCls}
              value={c.grupo}
              onChange={(e) => set("grupo", e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-muted-foreground">Fuente</span>
            <input
              className={inputCls}
              value={c.fuente}
              onChange={(e) => set("fuente", e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-muted-foreground">Precio</span>
            <input
              className={inputCls}
              type="number"
              min="0"
              step="any"
              value={c.precio}
              onChange={(e) => set("precio", e.target.value)}
            />
          </label>
        </div>

        <DialogFooter>
          <Button
            size="sm"
            variant="outline"
            onClick={() => handleOpenChange(false)}
            disabled={guardando}
          >
            Cancelar
          </Button>
          <Button size="sm" onClick={guardar} disabled={!valido || guardando}>
            {guardando ? "Creando…" : "Crear insumo"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
