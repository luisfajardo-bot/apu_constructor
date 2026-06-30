import { useState } from "react";
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

interface DialogoAgregarInsumoProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
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
  onCreado,
}: DialogoAgregarInsumoProps) {
  const [c, setC] = useState<Campos>(VACIO);
  const [guardando, setGuardando] = useState(false);

  function set<K extends keyof Campos>(k: K, v: string) {
    setC((prev) => ({ ...prev, [k]: v }));
  }

  function handleOpenChange(v: boolean) {
    if (!v) {
      setC(VACIO);
      setGuardando(false);
    }
    onOpenChange(v);
  }

  const precioNum = Number(c.precio);
  const precioValido = c.precio.trim() !== "" && Number.isFinite(precioNum) && precioNum >= 0;
  const valido =
    c.codigo.trim() !== "" &&
    c.nombre.trim() !== "" &&
    c.unidad.trim() !== "" &&
    c.grupo.trim() !== "" &&
    c.fuente.trim() !== "" &&
    precioValido;

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
