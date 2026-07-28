import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { listarInsumos, getFuentes, type ListarInsumosParams } from "@/api/insumos";
import { listarListas, crearLista, renombrarLista } from "@/api/listas";
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

  const cargarListas = useCallback(() => {
    return listarListas().then(setListas).catch(() => {});
  }, []);

  useEffect(() => {
    cargarListas();
  }, [cargarListas]);

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

  // Crear una lista deja al usuario seleccionado en ella (el flujo real es
  // "creo la lista de esta obra y la lleno"): si no, el siguiente precio que
  // edite iría a la Principal por error. Como eso cambia `filtros.lista`, pasa
  // por `cambiarFiltros` para respetar el guard de cambios sin guardar — si el
  // usuario cancela la confirmación, la lista queda creada pero no se entra en
  // ella (no se pierde ninguna edición en curso).
  async function crearListaNueva() {
    const nombre = window.prompt(
      "Nombre de la nueva lista de precios (p. ej. una obra No Prevista)"
    );
    if (!nombre || !nombre.trim()) return;
    try {
      const nueva = await crearLista(nombre.trim());
      await cargarListas();
      cambiarFiltros({ lista: nueva.id, fuente: "", clasificacion: "", sinPrecio: false, offset: 0 });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "No se pudo crear la lista de precios";
      toast.error(msg);
    }
  }

  // Renombrar no cambia la lista activa (mismo id), así que no toca el guard
  // de cambios sin guardar de la TablaInsumos.
  async function renombrarListaActual() {
    if (filtros.lista === LISTA_PRINCIPAL_ID) return; // la Principal no se renombra
    const actual = listas.find((l) => l.id === filtros.lista);
    const nombre = window.prompt("Nuevo nombre para la lista", actual?.nombre ?? "");
    if (!nombre || !nombre.trim()) return;
    try {
      await renombrarLista(filtros.lista, nombre.trim());
      await cargarListas();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "No se pudo renombrar la lista de precios";
      toast.error(msg);
    }
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
        puedeEditar={puedeEditar}
        onCrearLista={crearListaNueva}
        onRenombrarLista={renombrarListaActual}
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
