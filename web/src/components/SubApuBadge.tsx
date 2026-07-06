import { cn } from "@/lib/utils";

/** Chip para marcar una línea/fila que es un sub-APU. Sigue el estilo de EstadoBadge. */
export default function SubApuBadge({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-semibold",
        "leading-none uppercase tracking-wide bg-indigo-100 text-indigo-800 border-indigo-200",
        className,
      )}
    >
      APU
    </span>
  );
}
