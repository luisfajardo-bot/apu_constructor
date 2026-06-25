import { useState, useCallback } from "react";

export interface FilaBase {
  id: number;
  precio: number;
  fuente: string;
}

export interface CambiosDirty {
  [insumo_id: number]: {
    precio?: number;
    fuente?: string;
  };
}

export interface CambioOutput {
  insumo_id: number;
  precio: number;
  fuente: string;
}

export function useDirtyRows(filas: FilaBase[]) {
  const [dirty, setDirty] = useState<CambiosDirty>({});

  const setCampo = useCallback(
    (id: number, campo: "precio" | "fuente", valor: number | string) => {
      setDirty((prev) => ({
        ...prev,
        [id]: {
          ...prev[id],
          [campo]: valor,
        },
      }));
    },
    []
  );

  const descartar = useCallback(() => {
    setDirty({});
  }, []);

  const cambios = useCallback((): CambioOutput[] => {
    return Object.entries(dirty).map(([idStr, edits]) => {
      const id = Number(idStr);
      const fila = filas.find((f) => f.id === id);
      return {
        insumo_id: id,
        precio: edits.precio !== undefined ? edits.precio : (fila?.precio ?? 0),
        fuente: edits.fuente !== undefined ? edits.fuente : (fila?.fuente ?? ""),
      };
    });
  }, [dirty, filas]);

  const count = Object.keys(dirty).length;

  return { setCampo, descartar, cambios, count, dirty };
}
