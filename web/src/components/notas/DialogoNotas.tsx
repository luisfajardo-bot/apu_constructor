import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { borrarNota, crearNota, editarNota, listarMencionables, listarNotas } from "@/api/notas";
import type { DuenoNota, Mencionable, MencionNota, Nota } from "@/lib/tipos";
import { mencionesVigentes } from "@/lib/menciones";
import { agruparHilos } from "@/lib/hilos";
import { CajaConMenciones } from "./CajaConMenciones";
import { TextoConMenciones } from "./TextoConMenciones";
import { useAuth } from "@/lib/auth";
import { puede } from "@/components/rutas";

interface Props {
  dueno: DuenoNota | null;   // null = cerrado
  etiqueta: string;
  onClose: () => void;
  onCambio: () => void;      // hubo alta/edición/borrado: la tabla repinta el ícono
}

const fecha = (iso: string) => new Date(iso).toLocaleString("es-CO");
const msg = (e: unknown, respaldo: string) => (e instanceof Error ? e.message : respaldo);

export function DialogoNotas({ dueno, etiqueta, onClose, onCambio }: Props) {
  const { perfil } = useAuth();
  const escribe = puede(perfil?.rol, "editor");
  const [notas, setNotas] = useState<Nota[] | null>(null);
  const [nueva, setNueva] = useState("");
  const [editando, setEditando] = useState<{ id: number; texto: string; elegidos: MencionNota[] } | null>(null);
  const [respondiendo, setRespondiendo] = useState<{ raizId: number; texto: string; elegidos: MencionNota[] } | null>(null);
  const [mencionables, setMencionables] = useState<Mencionable[]>([]);
  const [elegidosNueva, setElegidosNueva] = useState<MencionNota[]>([]);
  const [ocupado, setOcupado] = useState(false);

  // Clave estable del dueño: un objeto nuevo con los mismos campos no recarga nada.
  const claveDueno = dueno ? [dueno.entidad, dueno.codigo, dueno.nombre, dueno.turno].join("|") : "";
  const duenoRef = useRef(dueno);
  duenoRef.current = dueno;
  // Dueño vigente: tras un await, si cambió (o se cerró), no se toca el estado.
  const claveVigente = useRef(claveDueno);
  claveVigente.current = claveDueno;

  useEffect(() => {
    const d = duenoRef.current;
    if (!d) return;
    let cancelado = false;
    setNotas(null);
    setNueva("");
    setEditando(null);
    setRespondiendo(null);
    setElegidosNueva([]);
    if (escribe) {
      listarMencionables()
        .then((u) => { if (!cancelado) setMencionables(u); })
        .catch(() => {});   // sin la lista igual se puede escribir
    }
    listarNotas(d)
      .then((r) => { if (!cancelado) setNotas(r); })
      .catch((e) => {
        if (cancelado) return;
        toast.error(msg(e, "No se pudieron cargar las notas"));
        setNotas([]);
      });
    return () => { cancelado = true; };
  }, [claveDueno, escribe]);

  async function agregar() {
    if (!dueno || !nueva.trim()) return;
    const clave = claveDueno;
    setOcupado(true);
    try {
      const n = await crearNota(dueno, nueva, mencionesVigentes(nueva, elegidosNueva));
      if (clave === claveVigente.current) {
        setNotas((prev) => [...(prev ?? []), n]);
        setNueva("");
        setElegidosNueva([]);
      }
      onCambio();
    } catch (e) {
      toast.error(msg(e, "No se pudo guardar la nota"));   // lo escrito se conserva
    } finally {
      setOcupado(false);
    }
  }

  async function guardarEdicion() {
    if (!editando || !editando.texto.trim()) return;
    const clave = claveDueno;
    setOcupado(true);
    try {
      const n = await editarNota(editando.id, editando.texto, mencionesVigentes(editando.texto, editando.elegidos));
      if (clave === claveVigente.current) {
        setNotas((prev) => (prev ?? []).map((x) => (x.id === n.id ? n : x)));
        setEditando(null);
      }
      onCambio();
    } catch (e) {
      toast.error(msg(e, "No se pudo editar la nota"));
    } finally {
      setOcupado(false);
    }
  }

  async function responder() {
    if (!dueno || !respondiendo || !respondiendo.texto.trim()) return;
    const clave = claveDueno;
    const r = respondiendo;
    setOcupado(true);
    try {
      const n = await crearNota(dueno, r.texto, mencionesVigentes(r.texto, r.elegidos), r.raizId);
      if (clave === claveVigente.current) {
        setNotas((prev) => [...(prev ?? []), n]);
        setRespondiendo(null);
      }
      onCambio();
    } catch (e) {
      toast.error(msg(e, "No se pudo guardar la respuesta"));   // lo escrito se conserva
    } finally {
      setOcupado(false);
    }
  }

  async function borrar(id: number) {
    if (!window.confirm("¿Borrar esta nota?")) return;
    const clave = claveDueno;
    setOcupado(true);
    try {
      await borrarNota(id);
      // Una raíz con respuestas pasa a marcador: lo decide el servidor, así que se recarga.
      const d = duenoRef.current;
      if (d && clave === claveVigente.current) {
        const r = await listarNotas(d);
        if (clave === claveVigente.current) setNotas(r);
      }
      onCambio();
    } catch (e) {
      toast.error(msg(e, "No se pudo borrar la nota"));
    } finally {
      setOcupado(false);
    }
  }

  // Una nota (raíz o respuesta). Un marcador de raíz borrada con respuestas no tiene acciones.
  function renderNota(n: Nota) {
    if (n.borrada) {
      return (
        <div key={n.id} className="text-xs">
          <p className="mt-1 italic text-muted-foreground">(nota borrada)</p>
        </div>
      );
    }
    return (
    <div key={n.id} className="text-xs">
      <div className="flex items-center gap-2 text-muted-foreground">
        <span>{n.autor_email}</span>
        <span>·</span>
        <span>{fecha(n.creada_en)}</span>
        {n.editada_en && <span>(editada)</span>}
        <span className="ml-auto flex gap-1">
          {n.puede_editar && editando?.id !== n.id && (
            <Button size="xs" variant="ghost" disabled={ocupado}
                    onClick={() => setEditando({ id: n.id, texto: n.texto, elegidos: n.menciones })}>
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
          <CajaConMenciones ariaLabel="Editar nota" valor={editando.texto}
                            onValor={(v) => setEditando((e) => (e ? { ...e, texto: v } : e))}
                            elegidos={editando.elegidos}
                            onElegidos={(el) => setEditando((e) => (e ? { ...e, elegidos: el } : e))}
                            mencionables={mencionables} abrirHacia="abajo" />
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
        <TextoConMenciones texto={n.texto} nombres={n.menciones.map((m) => m.nombre)} />
      )}
    </div>
    );
  }

  return (
    <Dialog open={dueno !== null} onOpenChange={(v) => { if (!v) onClose(); }}>
      <DialogContent className="max-w-lg" onEscapeKeyDown={(e) => {
        // Con la lista de menciones abierta, Escape solo la cierra (Radix escucha en el document).
        if ((document.activeElement as HTMLElement | null)?.dataset.sugerencias === "si") e.preventDefault();
      }}>
        <DialogHeader>
          <DialogTitle className="text-sm">Notas · {etiqueta}</DialogTitle>
        </DialogHeader>

        <div className="max-h-[50vh] space-y-2 overflow-y-auto">
          {notas === null && <p className="text-xs text-muted-foreground">Cargando…</p>}
          {notas?.length === 0 && (
            <p className="text-xs text-muted-foreground">Todavía no hay notas.</p>
          )}
          {notas && agruparHilos(notas).map(({ raiz, respuestas }) => (
            <div key={raiz.id} className="space-y-1 border-b border-border pb-2">
              {renderNota(raiz)}
              {respuestas.length > 0 && (
                <div data-respuesta="si" className="ml-4 space-y-1 border-l border-border pl-3">
                  {respuestas.map((r) => renderNota(r))}
                </div>
              )}
              {escribe && !raiz.borrada && (respondiendo?.raizId === raiz.id ? (
                <div className="ml-4 space-y-1">
                  <CajaConMenciones ariaLabel="Responder nota" valor={respondiendo.texto}
                                    onValor={(v) => setRespondiendo((x) => (x ? { ...x, texto: v } : x))}
                                    elegidos={respondiendo.elegidos}
                                    onElegidos={(el) => setRespondiendo((x) => (x ? { ...x, elegidos: el } : x))}
                                    mencionables={mencionables} abrirHacia="abajo" />
                  <div className="flex justify-end gap-1">
                    <Button size="xs" variant="outline" disabled={ocupado}
                            onClick={() => setRespondiendo(null)}>
                      Cancelar
                    </Button>
                    <Button size="xs" disabled={ocupado || !respondiendo.texto.trim()}
                            onClick={responder}>
                      Enviar respuesta
                    </Button>
                  </div>
                </div>
              ) : (
                <Button size="xs" variant="ghost" disabled={ocupado}
                        onClick={() => setRespondiendo({ raizId: raiz.id, texto: "", elegidos: [] })}>
                  Responder
                </Button>
              ))}
            </div>
          ))}
        </div>

        {escribe && (
          <div className="space-y-1">
            <CajaConMenciones ariaLabel="Nueva nota" valor={nueva} onValor={setNueva}
                              elegidos={elegidosNueva} onElegidos={setElegidosNueva}
                              mencionables={mencionables}
                              placeholder={"Ej.: Precio extraído de la cotización de… " +
                                           "(usa @ para avisarle a alguien)"} />
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
