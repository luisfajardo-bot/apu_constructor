import { useEffect, useState, useCallback } from "react";
import { listarInsumos, getFuentes, type ListarInsumosParams } from "@/api/insumos";
import type { Insumo } from "@/lib/tipos";
import { BarraFiltros, type FiltrosState } from "@/components/insumos/BarraFiltros";
import { TablaInsumos } from "@/components/insumos/TablaInsumos";
import { Button } from "@/components/ui/button";
import { DialogoImportarInsumos } from "@/components/insumos/DialogoImportarInsumos";
import { DialogoAgregarInsumo } from "@/components/autoria/DialogoAgregarInsumo";
import { useAuth } from "@/lib/auth";
import { puede } from "@/components/rutas";

const LIMIT = 100;

export default function Insumos() {
  const { perfil } = useAuth();
  const puedeEditar = puede(perfil?.rol, "editor");
  const [filtros, setFiltros] = useState<FiltrosState>({
    q: "",
    grupo: "",
    fuente: "",
    clasificacion: "",
    offset: 0,
  });
  const [insumos, setInsumos] = useState<Insumo[]>([]);
  const [total, setTotal] = useState(0);
  const [fuentes, setFuentes] = useState<string[]>([]);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [importarOpen, setImportarOpen] = useState(false);
  const [agregarOpen, setAgregarOpen] = useState(false);

  const cargar = useCallback(async (f: FiltrosState) => {
    setCargando(true);
    setError(null);
    try {
      const params: ListarInsumosParams = {
        limit: LIMIT,
        offset: f.offset,
      };
      if (f.q) params.q = f.q;
      if (f.grupo) params.grupo = f.grupo;
      if (f.fuente) params.fuente = f.fuente;
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
    getFuentes().then(setFuentes).catch(() => {});
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
        {puedeEditar && (
          <div className="ml-auto flex gap-2">
            <Button
              size="xs"
              variant="outline"
              onClick={() => setAgregarOpen(true)}
            >
              Agregar insumo
            </Button>
            <Button
              size="xs"
              variant="outline"
              onClick={() => setImportarOpen(true)}
            >
              Importar
            </Button>
          </div>
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

      <TablaInsumos
        insumos={insumos}
        fuentes={fuentes}
        onReload={recargar}
        puedeEditar={puedeEditar}
      />

      {puedeEditar && (
        <>
          <DialogoImportarInsumos
            open={importarOpen}
            onOpenChange={setImportarOpen}
            onAplicado={recargar}
          />

          <DialogoAgregarInsumo
            open={agregarOpen}
            onOpenChange={setAgregarOpen}
            onCreado={recargar}
          />
        </>
      )}
    </div>
  );
}
