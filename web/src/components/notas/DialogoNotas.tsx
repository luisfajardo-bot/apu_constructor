import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { borrarNota, crearNota, editarNota, listarNotas } from "@/api/notas";
import type { DuenoNota, Nota } from "@/lib/tipos";
import { useAuth } from "@/lib/auth";
import { puede } from "@/components/rutas";

interface Props {
  dueno: DuenoNota | null;   // null = cerrado
  etiqueta: string;
  onClose: () => void;
  onCambio: () => void;      // hubo alta/edición/borrado: la tabla repinta el ícono
}

const areaCls =
  "w-full rounded border border-border bg-transparent px-2 py-1 text-xs outline-none " +
  "focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40";

const fecha = (iso: string) => new Date(iso).toLocaleString("es-CO");
const msg = (e: unknown, respaldo: string) => (e instanceof Error ? e.message : respaldo);

export function DialogoNotas({ dueno, etiqueta, onClose, onCambio }: Props) {
  const { perfil } = useAuth();
  const escribe = puede(perfil?.rol, "editor");
  const [notas, setNotas] = useState<Nota[] | null>(null);
  const [nueva, setNueva] = useState("");
  const [editando, setEditando] = useState<{ id: number; texto: string } | null>(null);
  const [ocupado, setOcupado] = useState(false);

  useEffect(() => {
    if (!dueno) return;
    setNotas(null);
    setNueva("");
    setEditando(null);
    listarNotas(dueno)
      .then(setNotas)
      .catch((e) => {
        toast.error(msg(e, "No se pudieron cargar las notas"));
        setNotas([]);
      });
  }, [dueno]);

  async function agregar() {
    if (!dueno || !nueva.trim()) return;
    setOcupado(true);
    try {
      const n = await crearNota(dueno, nueva);
      setNotas((prev) => [...(prev ?? []), n]);
      setNueva("");
      onCambio();
    } catch (e) {
      toast.error(msg(e, "No se pudo guardar la nota"));   // lo escrito se conserva
    } finally {
      setOcupado(false);
    }
  }

  async function guardarEdicion() {
    if (!editando || !editando.texto.trim()) return;
    setOcupado(true);
    try {
      const n = await editarNota(editando.id, editando.texto);
      setNotas((prev) => (prev ?? []).map((x) => (x.id === n.id ? n : x)));
      setEditando(null);
      onCambio();
    } catch (e) {
      toast.error(msg(e, "No se pudo editar la nota"));
    } finally {
      setOcupado(false);
    }
  }

  async function borrar(id: number) {
    if (!window.confirm("¿Borrar esta nota?")) return;
    setOcupado(true);
    try {
      await borrarNota(id);
      setNotas((prev) => (prev ?? []).filter((x) => x.id !== id));
      onCambio();
    } catch (e) {
      toast.error(msg(e, "No se pudo borrar la nota"));
    } finally {
      setOcupado(false);
    }
  }

  return (
    <Dialog open={dueno !== null} onOpenChange={(v) => { if (!v) onClose(); }}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="text-sm">Notas · {etiqueta}</DialogTitle>
        </DialogHeader>

        <div className="max-h-[50vh] space-y-2 overflow-y-auto">
          {notas === null && <p className="text-xs text-muted-foreground">Cargando…</p>}
          {notas?.length === 0 && (
            <p className="text-xs text-muted-foreground">Todavía no hay notas.</p>
          )}
          {notas?.map((n) => (
            <div key={n.id} className="border-b border-border pb-2 text-xs">
              <div className="flex items-center gap-2 text-muted-foreground">
                <span>{n.autor_email}</span>
                <span>·</span>
                <span>{fecha(n.creada_en)}</span>
                {n.editada_en && <span>(editada)</span>}
                <span className="ml-auto flex gap-1">
                  {n.puede_editar && editando?.id !== n.id && (
                    <Button size="xs" variant="ghost" disabled={ocupado}
                            onClick={() => setEditando({ id: n.id, texto: n.texto })}>
                      Editar
                    </Button>
                  )}
                  {n.puede_borrar && (
                    <Button size="xs" variant="ghost" disabled={ocupado}
                            onClick={() => borrar(n.id)}>
                      Borrar
                    </Button>
                  )}
                </span>
              </div>
              {editando?.id === n.id ? (
                <div className="mt-1 space-y-1">
                  <textarea aria-label="Editar nota" rows={3} className={areaCls}
                            value={editando.texto} maxLength={4000}
                            onChange={(e) => setEditando({ id: n.id, texto: e.target.value })} />
                  <div className="flex justify-end gap-1">
                    <Button size="xs" variant="outline" disabled={ocupado}
                            onClick={() => setEditando(null)}>
                      Cancelar
                    </Button>
                    <Button size="xs" disabled={ocupado || !editando.texto.trim()}
                            onClick={guardarEdicion}>
                      Guardar
                    </Button>
                  </div>
                </div>
              ) : (
                <p className="mt-1 whitespace-pre-wrap">{n.texto}</p>
              )}
            </div>
          ))}
        </div>

        {escribe && (
          <div className="space-y-1">
            <textarea aria-label="Nueva nota" rows={3} className={areaCls} value={nueva}
                      maxLength={4000} placeholder="Ej.: Precio extraído de la cotización de…"
                      onChange={(e) => setNueva(e.target.value)} />
            <div className="flex justify-end">
              <Button size="sm" disabled={ocupado || !nueva.trim()} onClick={agregar}>
                Agregar nota
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
