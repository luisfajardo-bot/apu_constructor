// web/src/lib/tiempo.ts
export function fmtDuracion(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 60000) return (ms / 1000).toFixed(1) + " s";
  const totalSeg = Math.round(ms / 1000);
  const m = Math.floor(totalSeg / 60);
  const s = totalSeg % 60;
  return `${m} m ${String(s).padStart(2, "0")} s`;
}
