import { cn } from "@/lib/utils";

type Estado = "AUTO" | "REVIEW" | "NEW" | "CONFIRMED" | string;

const CONFIG: Record<string, { label: string; cls: string }> = {
  AUTO: {
    label: "AUTO",
    cls: "bg-green-100 text-green-800 border-green-200",
  },
  REVIEW: {
    label: "REVISAR",
    cls: "bg-amber-100 text-amber-800 border-amber-200",
  },
  NEW: {
    label: "NUEVO",
    cls: "bg-gray-100 text-gray-600 border-gray-200",
  },
  CONFIRMED: {
    label: "CONFIRM",
    cls: "bg-blue-100 text-blue-800 border-blue-200",
  },
  // No es un `status` de la base: la fila sigue guardada como `confirmed`. Es la misma
  // confirmación, pero resuelta igualando el costo al precio contractual, y se distingue
  // porque el número no lo calculó el motor. Violeta a propósito: el azul del CONFIRM
  // normal significa "costeado desde su composición", que acá no pasó.
  CONTRACTUAL: {
    label: "CONTRACTUAL",
    cls: "bg-violet-100 text-violet-800 border-violet-200",
  },
};

export function etiquetaEstado(status: string): string {
  return CONFIG[status.toUpperCase()]?.label ?? status.toUpperCase();
}

interface EstadoBadgeProps {
  status: Estado;
  /** La fila se resolvió igualando el costo al contractual, no costeándola. */
  costoManual?: boolean;
}

export default function EstadoBadge({ status, costoManual }: EstadoBadgeProps) {
  const upper = costoManual ? "CONTRACTUAL" : status.toUpperCase();
  const cfg = CONFIG[upper] ?? {
    label: upper,
    cls: "bg-gray-100 text-gray-600 border-gray-200",
  };
  return (
    <span
      title={costoManual
        ? "Confirmada con el costo igualado al precio contractual"
        : undefined}
      className={cn(
        "inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-semibold leading-none uppercase tracking-wide",
        cfg.cls,
      )}
    >
      {cfg.label}
    </span>
  );
}
