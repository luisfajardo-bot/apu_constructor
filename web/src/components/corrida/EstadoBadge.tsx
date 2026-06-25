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
};

interface EstadoBadgeProps {
  status: Estado;
}

export default function EstadoBadge({ status }: EstadoBadgeProps) {
  const upper = status.toUpperCase();
  const cfg = CONFIG[upper] ?? {
    label: upper,
    cls: "bg-gray-100 text-gray-600 border-gray-200",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-semibold leading-none uppercase tracking-wide",
        cfg.cls,
      )}
    >
      {cfg.label}
    </span>
  );
}
