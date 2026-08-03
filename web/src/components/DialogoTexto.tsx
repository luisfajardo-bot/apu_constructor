import { useEffect, useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

type Props = {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  titulo: string;
  etiqueta?: string;
  valorInicial?: string;
  ayuda?: string;
  textoConfirmar?: string;
  onConfirmar: (valor: string) => void | Promise<void>;
};

/**
 * Pide un texto (un nombre) en un modal propio, en lugar de `window.prompt()`.
 *
 * El prompt nativo no se puede estilizar, no es accesible y bloquea el hilo principal de
 * la página (hallazgo 3 del smoke test de producción del 2026-08-03). Este componente no
 * conoce ningún dominio: el llamador pone el título, la ayuda y qué hacer al confirmar.
 */
export function DialogoTexto({
  open,
  onOpenChange,
  titulo,
  etiqueta = "Nombre",
  valorInicial = "",
  ayuda,
  textoConfirmar = "Guardar",
  onConfirmar,
}: Props) {
  const [valor, setValor] = useState(valorInicial);
  const [error, setError] = useState<string | null>(null);
  const [guardando, setGuardando] = useState(false);
  // Id único por instancia: Insumos.tsx monta dos DialogoTexto (crear/renombrar lista) y
  // un id fijo compartido entre ambos es una asociación label/input rota esperando pasar.
  const inputId = useId();
  const errorId = `${inputId}-error`;

  // Cada apertura arranca limpia y con el valor inicial: al renombrar, precargado con el
  // nombre actual, igual que hacía el segundo argumento de window.prompt().
  useEffect(() => {
    if (open) {
      setValor(valorInicial);
      setError(null);
    }
  }, [open, valorInicial]);

  async function confirmar(e: React.FormEvent) {
    e.preventDefault();
    const limpio = valor.trim();
    // El botón queda HABILITADO con el campo vacío y avisa acá. Es deliberado y rompe el
    // patrón de DialogoAgregarApu (`disabled={!valido}`): un botón bloqueado sin
    // explicación deja al usuario sin salida — es lo que se arregló en el commit 6fd5472.
    if (!limpio) {
      setError("Escribí un nombre");
      return;
    }
    setGuardando(true);
    try {
      await onConfirmar(limpio);
      onOpenChange(false);
    } catch {
      // El llamador ya mostró su toast con el mensaje del backend y re-lanzó. Dejamos el
      // diálogo abierto con lo escrito para poder corregir: el prompt nativo cerraba y
      // había que reescribir el nombre desde cero (p. ej. una lista duplicada -> 400).
    } finally {
      setGuardando(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="text-sm">{titulo}</DialogTitle>
        </DialogHeader>
        <form onSubmit={confirmar} className="space-y-2">
          <label className="text-xs block" htmlFor={inputId}>
            {etiqueta}
          </label>
          <Input
            id={inputId}
            autoFocus
            value={valor}
            onChange={(e) => {
              setValor(e.target.value);
              setError(null);
            }}
            // Replica la preselección que hacía window.prompt(msg, default): el texto
            // precargado queda seleccionado al enfocar, así que escribir lo REEMPLAZA en
            // vez de anteponerse (autoFocus solo hace .focus(), deja el caret al inicio).
            onFocus={(e) => e.currentTarget.select()}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? errorId : undefined}
          />
          {ayuda && <p className="text-xs text-muted-foreground">{ayuda}</p>}
          {error && (
            <p id={errorId} role="alert" className="text-xs text-red-600">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={guardando}
            >
              Cancelar
            </Button>
            <Button type="submit" size="sm" disabled={guardando}>
              {guardando ? "Guardando…" : textoConfirmar}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
