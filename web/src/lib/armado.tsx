import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";
import { crearCorridaStream, crearSampleStream } from "@/api/corridas";
import type { CorridaIniciada, ItemCuadro, Progreso } from "@/lib/tipos";

// Estado del armado en curso, compartido entre la pantalla de "Nueva corrida" y la
// página de la corrida, para navegar a /corridas/:id y ver la tabla llenarse en vivo
// sin perder el stream al cambiar de página. El stream lo posee el provider (montado
// arriba de las rutas), no la pantalla que lo inició.

type EstadoVivo = "armando" | "listo" | "error" | null;

interface ArmadoState {
  corridaId: number | null;
  total: number;
  filas: ItemCuadro[];
  estado: EstadoVivo;
  error: string | null;
}

interface ArmadoCtx extends ArmadoState {
  armarArchivo: (form: FormData, onStarted: (id: number) => void) => Promise<void>;
  armarEjemplo: (onStarted: (id: number) => void) => Promise<void>;
}

const VACIO: ArmadoState = {
  corridaId: null,
  total: 0,
  filas: [],
  estado: null,
  error: null,
};

const Ctx = createContext<ArmadoCtx | null>(null);

export function useArmadoVivo(): ArmadoCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useArmadoVivo debe usarse dentro de <ArmadoVivoProvider>");
  return c;
}

export function ArmadoVivoProvider({ children }: { children: ReactNode }) {
  const [estado, setEstado] = useState<ArmadoState>(VACIO);

  const correr = useCallback(
    async (
      run: (cbs: {
        onProgress: (p: Progreso) => void;
        onStarted: (c: CorridaIniciada) => void;
      }) => Promise<unknown>,
      onStarted: (id: number) => void,
    ) => {
      setEstado({ ...VACIO, estado: "armando" });
      try {
        await run({
          onStarted: (c) => {
            setEstado((s) => ({ ...s, corridaId: c.id, total: c.total, estado: "armando" }));
            onStarted(c.id);
          },
          onProgress: (p) => {
            if (p.fila) {
              const fila = p.fila;
              setEstado((s) => ({ ...s, filas: [...s.filas, fila] }));
            }
          },
        });
        setEstado((s) => ({ ...s, estado: "listo" }));
      } catch (e) {
        const msg = e instanceof Error ? e.message : "Error al armar";
        setEstado((s) => ({ ...s, estado: "error", error: msg }));
        throw e;
      }
    },
    [],
  );

  const armarArchivo = useCallback(
    (form: FormData, onStarted: (id: number) => void) =>
      correr((cbs) => crearCorridaStream(form, cbs.onProgress, cbs.onStarted), onStarted),
    [correr],
  );

  const armarEjemplo = useCallback(
    (onStarted: (id: number) => void) =>
      correr((cbs) => crearSampleStream(cbs.onProgress, cbs.onStarted), onStarted),
    [correr],
  );

  return (
    <Ctx.Provider value={{ ...estado, armarArchivo, armarEjemplo }}>
      {children}
    </Ctx.Provider>
  );
}
