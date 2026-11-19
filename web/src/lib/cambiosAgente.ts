import type { CambioAgente, ComponentePropuesto } from "./tipos";

export interface ResultadoCambios {
  componentes: ComponentePropuesto[];
  /** Lo que no se pudo aplicar porque la tabla cambió desde que el agente propuso.
   *  Se muestra: un cambio que no entró nunca se pierde callado. */
  conflictos: string[];
}

/** Aplica los cambios del agente sobre la tabla de la mesa. Pura: no muta la
 *  entrada. Lo que choca (agregar algo que ya está; quitar o modificar algo que ya no
 *  está) se salta y se reporta, y el resto se aplica. */
export function aplicarCambios(
  actuales: ComponentePropuesto[],
  cambios: CambioAgente[],
): ResultadoCambios {
  let out = [...actuales];
  const conflictos: string[] = [];
  for (const c of cambios) {
    const i = out.findIndex((x) => x.codigo === c.codigo);
    if (c.op === "agregar") {
      if (i >= 0) {
        conflictos.push(`${c.codigo} ya estaba en la tabla: no se agregó otra vez.`);
      } else if (c.componente) {
        out = [...out, { ...c.componente, codigo: c.codigo }];
      }
    } else if (c.op === "quitar") {
      if (i < 0) {
        conflictos.push(`${c.codigo} ya no estaba en la tabla: no había nada que quitar.`);
      } else {
        out = out.filter((_, j) => j !== i);
      }
    } else {
      const nuevo = c.componente;
      if (i < 0) {
        conflictos.push(`${c.codigo} ya no estaba en la tabla: no se modificó.`);
      } else if (nuevo) {
        out = out.map((x, j) => (j === i ? { ...nuevo, codigo: c.codigo } : x));
      }
    }
  }
  return { componentes: out, conflictos };
}
