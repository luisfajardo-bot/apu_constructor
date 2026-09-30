import { MessageSquare } from "lucide-react";

interface Props {
  tiene?: boolean;
  ultima?: string;
  onClick: () => void;
}

/** Ícono de notas de una fila: pintado si tiene notas, vacío si no. El clic no se
 *  propaga: en APUs la fila entera expande su composición. */
export function IconoNotas({ tiene = false, ultima = "", onClick }: Props) {
  return (
    <button
      type="button"
      aria-label="Notas"
      data-tiene={tiene ? "si" : "no"}
      title={tiene ? ultima : "Sin notas"}
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      className={
        "inline-flex h-5 w-5 items-center justify-center rounded hover:bg-muted " +
        (tiene ? "text-primary" : "text-muted-foreground/50")
      }
    >
      <MessageSquare className="h-3.5 w-3.5" fill={tiene ? "currentColor" : "none"} />
    </button>
  );
}
