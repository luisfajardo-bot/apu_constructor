import { useState } from "react";
import { Bell } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { listarMenciones, marcarMencionLeida, marcarMencionesLeidas } from "@/api/notas";
import type { DuenoNota, Mencion } from "@/lib/tipos";
import { DialogoNotas } from "./DialogoNotas";

interface Props {
  sinLeer: number | null;          // viene de la presencia (cada 45 s); null = no se sabe
  onSinLeer: (n: number) => void;  // corrige el número al leer, sin esperar el próximo latido
}

const fecha = (iso: string) => new Date(iso).toLocaleString("es-CO");

/** Campanita de menciones. El número lo trae la presencia; la lista se pide al abrir
 *  (una acción del usuario, no un sondeo). */
export function Campanita({ sinLeer, onSinLeer }: Props) {
  const [abierta, setAbierta] = useState(false);
  const [menciones, setMenciones] = useState<Mencion[] | null>(null);
  const [nota, setNota] = useState<{ dueno: DuenoNota; etiqueta: string } | null>(null);
  const n = sinLeer ?? 0;

  function abrir() {
    setAbierta(true);
    setMenciones(null);
    listarMenciones()
      .then(setMenciones)
      .catch((e) => {
        toast.error(e instanceof Error ? e.message : "No se pudieron cargar las menciones");
        setMenciones([]);
      });
  }

  const restantes = (lista: Mencion[]) => lista.filter((m) => !m.leida).length;

  async function ir(m: Mencion) {
    setAbierta(false);
    setNota({ dueno: m.dueno, etiqueta: m.etiqueta });
    if (m.leida) return;
    try {
      await marcarMencionLeida(m.nota_id);
      const lista = (menciones ?? []).map((x) => (x.nota_id === m.nota_id ? { ...x, leida: true } : x));
      setMenciones(lista);
      onSinLeer(restantes(lista));
    } catch {
      /* si no se pudo marcar, sigue sin leer: el próximo latido lo muestra igual */
    }
  }

  async function todas() {
    try {
      await marcarMencionesLeidas();
      setMenciones((prev) => (prev ?? []).map((x) => ({ ...x, leida: true })));
      onSinLeer(0);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "No se pudieron marcar las menciones");
    }
  }

  return (
    <>
      <button type="button" onClick={abrir}
              aria-label={n > 0 ? `Menciones (${n} sin leer)` : "Menciones"}
              className="relative inline-flex h-7 w-7 items-center justify-center rounded hover:bg-muted">
        <Bell className="h-4 w-4" aria-hidden />
        {n > 0 && (
          <span className="absolute -right-0.5 -top-0.5 min-w-4 rounded-full bg-primary px-1 text-[9px] font-semibold leading-4 text-primary-foreground">
            {n}
          </span>
        )}
      </button>

      <Dialog open={abierta} onOpenChange={setAbierta}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="text-sm">Menciones</DialogTitle>
          </DialogHeader>
          <div className="max-h-[60vh] space-y-1 overflow-y-auto">
            {menciones === null && <p className="text-xs text-muted-foreground">Cargando…</p>}
            {menciones?.length === 0 && (
              <p className="text-xs text-muted-foreground">Nadie te ha mencionado todavía.</p>
            )}
            {menciones?.map((m) => (
              <button key={m.nota_id} type="button" onClick={() => ir(m)}
                      className={"block w-full rounded px-2 py-1.5 text-left text-xs hover:bg-muted " +
                                 (m.leida ? "text-muted-foreground" : "font-medium")}>
                <span className="block">
                  {m.autor_email} · {m.etiqueta} · {fecha(m.creada_en)}
                </span>
                <span className="block truncate">{m.texto}</span>
              </button>
            ))}
          </div>
          {menciones && restantes(menciones) > 0 && (
            <div className="flex justify-end">
              <Button size="xs" variant="outline" onClick={todas}>Marcar todas como leídas</Button>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <DialogoNotas dueno={nota?.dueno ?? null} etiqueta={nota?.etiqueta ?? ""}
                    onClose={() => setNota(null)} onCambio={() => {}} />
    </>
  );
}
