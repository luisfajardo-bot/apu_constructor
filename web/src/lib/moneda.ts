export const cop = (n: number) =>
  "$" + Math.round(n ?? 0).toLocaleString("es-CO");
export const pct = (x: number) => ((x ?? 0) * 100).toFixed(1) + "%";
