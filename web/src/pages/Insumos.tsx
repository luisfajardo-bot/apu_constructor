import { useEffect, useState, useCallback } from "react";
import { listarInsumos } from "@/api/insumos";
import type { Insumo } from "@/lib/tipos";
import { BarraFiltros, type FiltrosState } from "@/components/insumos/BarraFiltros";
import { TablaInsumos } from "@/components/insumos/TablaInsumos";

const LIMIT = 100;

export default function Insumos() {
  const [filtros, setFiltros] = useState<FiltrosState>({
    q: "",
    grupo: "",
    fuente: "",
    clasificacion: "",
    offset: 0,
  });
  const [insumos, setInsumos] = useState<Insumo[]>([]);
  const [total, setTotal] = useState(0);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const cargar = useCallback(async (f: FiltrosState) => {
    setCargando(true);
    setError(null);
    try {
      const params: Record<string, string | number> = {
        limit: LIMIT,
        offset: f.offset,
      };
      if (f.q) params.q = f.q;
      if (f.grupo) params.grupo = f.grupo;
      if (f.fuente) params.fuente = f.fuente;
      // clasificacion filter: handled via fuente or q if backend supports it
      // pass as extra param if present
      if (f.clasificacion) params.clasificacion = f.clasificacion;

      const res = await listarInsumos(params);
      setInsumos(res.items);
      setTotal(res.total);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Error desconocido";
      setError(msg);
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => {
    cargar(filtros);
  }, [filtros, cargar]);

  function cambiarFiltros(parcial: Partial<FiltrosState>) {
    setFiltros((prev) => ({ ...prev, ...parcial }));
  }

  function recargar() {
    cargar(filtros);
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-4 py-2 border-b">
        <h2 className="text-sm font-semibold">Insumos</h2>
        {cargando && (
          <span className="text-xs text-muted-foreground animate-pulse">cargando…</span>
        )}
      </div>

      <BarraFiltros
        filtros={filtros}
        total={total}
        limit={LIMIT}
        onChange={cambiarFiltros}
      />

      {error && (
        <div className="px-4 py-2 text-sm text-destructive border-b">
          Error: {error}
        </div>
      )}

      <TablaInsumos insumos={insumos} onReload={recargar} />
    </div>
  );
}
