import { useEffect, useState, useCallback } from "react";
import { listarInsumos, getFuentes, type ListarInsumosParams } from "@/api/insumos";
import { listarListas } from "@/api/listas";
import { LISTA_PRINCIPAL_ID, type Insumo, type ListaPrecios } from "@/lib/tipos";
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
    lista: LISTA_PRINCIPAL_ID,
    sinPrecio: false,
    offset: 0,
  });
  const [listas, setListas] = useState<ListaPrecios[]>([]);
  const [insumos, setInsumos] = useState<Insumo[]>([]);
  const [total, setTotal] = useState(0);
  const [fuentes, setFuentes] = useState<string[]>([]);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [importarOpen, setImportarOpen] = useState(false);
  const [agregarOpen, setAgregarOpen] = useState(false);
  // Cambios sin guardar en la TablaInsumos de la lista activa (ver hallazgo
  // CRITICAL: un precio editado en la lista A no debe poder guardarse en la B).
  const [dirtyCount, setDirtyCount] = useState(0);

  const cargar = useCallback(async (f: FiltrosState) => {
    setCargando(true);
    setError(null);
    try {
      const params: ListarInsumosParams = {
        limit: LIMIT,
        offset: f.offset,
        lista: f.lista,
      };
      if (f.q) params.q = f.q;
      if (f.grupo) params.grupo = f.grupo;
      if (f.fuente) params.fuente = f.fuente;
      if (f.clasificacion) params.clasificacion = f.clasificacion;
      if (f.sinPrecio) params.sin_precio = true;

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
    listarListas().then(setListas).catch(() => {});
  }, []);

  // Las fuentes son atributo de precio de la lista activa: recargar al cambiarla
  // (TablaInsumos las usa para el autocompletado del editor de fuente).
  useEffect(() => {
    getFuentes(filtros.lista).then(setFuentes).catch(() => {});
  }, [filtros.lista]);

  useEffect(() => {
    cargar(filtros);
  }, [filtros, cargar]);

  function cambiarFiltros(parcial: Partial<FiltrosState>) {
    // Cambiar de lista de precios descarta cualquier edición sin guardar de la
    // TablaInsumos actual (se remonta con key={filtros.lista}). Si hay cambios
    // pendientes, confirmamos con el usuario antes de perderlos; si cancela,
    // la lista NO cambia (tampoco el resto del filtro que venga en el mismo
    // parcial, p.ej. el reseteo de fuente/clasificación de BarraFiltros).
    if (
      parcial.lista !== undefined &&
      parcial.lista !== filtros.lista &&
      dirtyCount > 0
    ) {
      const plural = dirtyCount === 1 ? "cambio" : "cambios";
      const mensaje =
        `Tienes ${dirtyCount} ${plural} sin guardar en esta lista. ` +
        "Si cambias de lista se van a descartar. ¿Deseas continuar?";
      if (!window.confirm(mensaje)) return;
    }
    setFiltros((prev) => ({ ...prev, ...parcial }));
  }

  function recargar() {
    cargar(filtros);
  }

  const listaActivaNombre =
    listas.find((l) => l.id === filtros.lista)?.nombre ?? "Principal";

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

      {filtros.lista !== LISTA_PRINCIPAL_ID && (
        <div className="px-4 py-1.5 text-xs border-b bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200">
          Editando la lista <span className="font-semibold">{listaActivaNombre}</span>.
          Los precios que cambies aquí NO afectan la lista Principal.
        </div>
      )}

      <BarraFiltros
        filtros={filtros}
        listas={listas}
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
        key={filtros.lista}
        insumos={insumos}
        fuentes={fuentes}
        listaId={filtros.lista}
        onReload={recargar}
        puedeEditar={puedeEditar}
        onDirtyCountChange={setDirtyCount}
      />

      {puedeEditar && (
        <>
          <DialogoImportarInsumos
            open={importarOpen}
            onOpenChange={setImportarOpen}
            listaId={filtros.lista}
            listaNombre={listaActivaNombre}
            onAplicado={recargar}
          />

          <DialogoAgregarInsumo
            open={agregarOpen}
            onOpenChange={setAgregarOpen}
            listaId={filtros.lista}
            onCreado={recargar}
          />
        </>
      )}
    </div>
  );
}
