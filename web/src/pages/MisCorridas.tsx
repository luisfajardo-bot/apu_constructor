import { useEffect, useState, useCallback } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Folder } from "lucide-react";
import { toast } from "sonner";
import { listarCorridas, eliminarCorrida, renombrarCorrida, descargarPlantillaLicitacion } from "@/api/corridas";
import { listarCarpetas, crearCarpeta, renombrarCarpeta, borrarCarpeta, moverCorrida, moverCarpeta } from "@/api/carpetas";
import { useAuth } from "@/lib/auth";
import { fmtDuracion } from "@/lib/tiempo";
import { cop, pct } from "@/lib/moneda";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { CorridaResumen, CarpetaNodo } from "@/lib/tipos";

function fechaLegible(iso: string): string {
  try {
    return new Date(iso).toLocaleString("es-CO", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

// Aplana el árbol de carpetas en un mapa id → nodo
function aplanarArbol(nodos: CarpetaNodo[]): Map<number, CarpetaNodo> {
  const mapa = new Map<number, CarpetaNodo>();
  function recorrer(lista: CarpetaNodo[]) {
    for (const n of lista) {
      mapa.set(n.id, n);
      if (n.hijas.length > 0) recorrer(n.hijas);
    }
  }
  recorrer(nodos);
  return mapa;
}

// Construye la cadena de ancestros para el breadcrumb: [raíz..., nodoActual]
function ancestros(id: number, mapa: Map<number, CarpetaNodo>): CarpetaNodo[] {
  const cadena: CarpetaNodo[] = [];
  let actual = mapa.get(id);
  while (actual) {
    cadena.unshift(actual);
    actual = actual.parent_id != null ? mapa.get(actual.parent_id) : undefined;
  }
  return cadena;
}

// Devuelve lista plana de carpetas en orden depth-first con etiqueta de ruta
function listaDestinos(nodos: CarpetaNodo[]): { id: number; etiqueta: string }[] {
  const resultado: { id: number; etiqueta: string }[] = [];
  function recorrer(lista: CarpetaNodo[], prefijo: string) {
    for (const n of lista) {
      const etiqueta = prefijo ? `${prefijo} › ${n.nombre}` : n.nombre;
      resultado.push({ id: n.id, etiqueta });
      if (n.hijas.length > 0) recorrer(n.hijas, etiqueta);
    }
  }
  recorrer(nodos, "");
  return resultado;
}

export default function MisCorridas() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { perfil } = useAuth();

  const [corridas, setCorridas] = useState<CorridaResumen[]>([]);
  const [arbol, setArbol] = useState<CarpetaNodo[]>([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const puedeEditar = perfil?.rol === "admin" || perfil?.rol === "editor";

  // carpetaActual es null en la raíz o el id de la carpeta activa
  const carpetaParam = searchParams.get("carpeta");
  const carpetaActual: number | null = carpetaParam ? Number(carpetaParam) : null;

  const cargar = useCallback(() => {
    setCargando(true);
    setError(null);
    Promise.all([listarCorridas(), listarCarpetas()])
      .then(([c, a]) => {
        setCorridas(c);
        setArbol(a);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Error al cargar"))
      .finally(() => setCargando(false));
  }, []);

  useEffect(() => {
    cargar();
  }, [cargar]);

  async function bajarPlantilla() {
    try {
      await descargarPlantillaLicitacion();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "No se pudo descargar la plantilla.");
    }
  }

  async function handleEliminar(e: React.MouseEvent, corrida: CorridaResumen) {
    e.stopPropagation();
    if (!window.confirm(`¿Eliminar la corrida "${corrida.nombre}"?`)) return;
    try {
      await eliminarCorrida(corrida.id);
      toast.success(`Corrida "${corrida.nombre}" eliminada`);
      cargar();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Error al eliminar");
    }
  }

  async function handleNuevaCarpeta() {
    const nombre = window.prompt("Nombre de la carpeta");
    if (!nombre?.trim()) return;
    try {
      await crearCarpeta(nombre.trim(), carpetaActual);
      cargar();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Error al crear carpeta");
    }
  }

  async function handleRenombrar(e: React.MouseEvent, carpeta: CarpetaNodo) {
    e.stopPropagation();
    const nuevo = window.prompt("Nuevo nombre", carpeta.nombre);
    if (!nuevo?.trim() || nuevo.trim() === carpeta.nombre) return;
    try {
      await renombrarCarpeta(carpeta.id, nuevo.trim());
      cargar();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Error al renombrar");
    }
  }

  async function handleEliminarCarpeta(e: React.MouseEvent, carpeta: CarpetaNodo) {
    e.stopPropagation();
    if (!window.confirm(`¿Eliminar la carpeta "${carpeta.nombre}"?`)) return;
    try {
      await borrarCarpeta(carpeta.id);
      cargar();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Error al eliminar carpeta");
    }
  }

  async function handleRenombrarCorrida(e: React.MouseEvent, corrida: CorridaResumen) {
    e.stopPropagation();
    const nuevo = window.prompt("Nuevo nombre", corrida.nombre);
    if (!nuevo?.trim() || nuevo.trim() === corrida.nombre) return;
    try {
      await renombrarCorrida(corrida.id, nuevo.trim());
      toast.success(`Corrida renombrada a "${nuevo.trim()}"`);
      cargar();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Error al renombrar");
    }
  }

  async function handleMoverCorrida(e: React.MouseEvent, corrida: CorridaResumen) {
    e.stopPropagation();
    const destinos = listaDestinos(arbol);
    if (destinos.length === 0) {
      toast.error("No hay carpetas de destino disponibles.");
      return;
    }
    const opciones = destinos.map((d, i) => `${i + 1}. ${d.etiqueta}`).join("\n");
    const resp = window.prompt(`Mover "${corrida.nombre}" a:\n${opciones}\n\nEscribe el número:`);
    if (!resp?.trim()) return;
    const idx = parseInt(resp.trim(), 10) - 1;
    if (isNaN(idx) || idx < 0 || idx >= destinos.length) return;
    try {
      await moverCorrida(corrida.id, destinos[idx].id);
      toast.success(`Corrida "${corrida.nombre}" movida a "${destinos[idx].etiqueta}"`);
      cargar();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Error al mover corrida");
    }
  }

  async function handleMoverCarpeta(e: React.MouseEvent, carpeta: CarpetaNodo) {
    e.stopPropagation();
    // Excluir la carpeta misma y sus descendientes (hijas directas; max depth 2)
    const idsExcluidos = new Set<number>([carpeta.id, ...carpeta.hijas.map((h) => h.id)]);
    const todasLasCarpetas = listaDestinos(arbol).filter((d) => !idsExcluidos.has(d.id));
    // Opción raíz más las demás carpetas
    const destinos: { id: number | null; etiqueta: string }[] = [
      { id: null, etiqueta: "(raíz)" },
      ...todasLasCarpetas,
    ];
    const opciones = destinos.map((d, i) => `${i + 1}. ${d.etiqueta}`).join("\n");
    const resp = window.prompt(`Mover carpeta "${carpeta.nombre}" a:\n${opciones}\n\nEscribe el número:`);
    if (!resp?.trim()) return;
    const idx = parseInt(resp.trim(), 10) - 1;
    if (isNaN(idx) || idx < 0 || idx >= destinos.length) return;
    const parentId = destinos[idx].id;
    try {
      await moverCarpeta(carpeta.id, parentId);
      toast.success(`Carpeta "${carpeta.nombre}" movida a "${destinos[idx].etiqueta}"`);
      cargar();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Error al mover carpeta");
    }
  }

  // Construir información de la carpeta actual a partir del árbol
  const mapa = aplanarArbol(arbol);
  const nodoActual = carpetaActual != null ? mapa.get(carpetaActual) : null;

  // Subcarpetas a mostrar: si estamos en raíz, los nodos raíz; si estamos en una carpeta, sus hijas
  const subcarpetas: CarpetaNodo[] = carpetaActual == null
    ? arbol
    : (nodoActual?.hijas ?? []);

  // Breadcrumb: ["Todas", ...ancestros]
  const migajas: CarpetaNodo[] = carpetaActual != null ? ancestros(carpetaActual, mapa) : [];

  // Corridas filtradas (solo visibles dentro de una carpeta)
  const corridasFiltradas = carpetaActual != null
    ? corridas.filter((c) => c.carpeta_id === carpetaActual)
    : [];

  return (
    <div className="px-6 py-5">
      <div className="mb-3.5 flex items-center justify-between">
        <h2 className="text-[15px] font-semibold tracking-[-0.01em]">Mis corridas</h2>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={bajarPlantilla}>
            Descargar plantilla
          </Button>
          <Button variant="outline" size="sm" onClick={handleNuevaCarpeta}>
            Nueva carpeta
          </Button>
          <Button size="sm" onClick={() => navigate("/corridas/nueva")}>
            Nueva corrida
          </Button>
        </div>
      </div>

      {/* Estando DENTRO de un proyecto (carpeta de nivel 1) hay que poder llegar a sus
          distancias: el enlace de la lista de subcarpetas solo se ve un nivel arriba, y
          aca es donde el usuario esta trabajando con las corridas de ese proyecto. */}
      {nodoActual != null && nodoActual.parent_id === null && (
        <div className="mb-3 flex items-center gap-2 text-xs">
          <span className="text-muted-foreground">Proyecto {nodoActual.nombre}:</span>
          <Link to={`/proyecto/${nodoActual.id}/distancias`} className="underline">
            Distancias y ajustes
          </Link>
        </div>
      )}

      {/* Breadcrumb. Eran <span onClick>, o sea inalcanzables con teclado; pasan a
          <button>, que es lo que son. Mismo onClick, misma navegación. */}
      <nav aria-label="Ruta de carpetas" className="mb-3 text-xs text-muted-foreground">
        <button type="button" className={CLASE_MIGAJA} onClick={() => setSearchParams({})}>
          Todas
        </button>
        {migajas.map((m) => (
          <span key={m.id}>
            <span aria-hidden className="text-muted-foreground/70"> › </span>
            <button
              type="button"
              className={CLASE_MIGAJA}
              onClick={() => setSearchParams({ carpeta: String(m.id) })}
            >
              {m.nombre}
            </button>
          </span>
        ))}
      </nav>

      {cargando && <p className="my-2 text-xs text-muted-foreground">Cargando…</p>}
      {error && <p className="my-2 text-xs text-destructive">{error}</p>}

      {!cargando && !error && (
        <>
          {/* Filas de subcarpetas */}
          {subcarpetas.length > 0 && (
            <div className="mb-4">
              {subcarpetas.map((carpeta) => (
                // ponytail: la fila sigue siendo un <div onClick>, no alcanzable con
                // teclado. No se arregla acá porque un <button> no puede contener los
                // botones de acción que ya tiene dentro; necesita su propio rediseño,
                // igual que el <tr onClick> de la tabla de abajo.
                <div
                  key={carpeta.id}
                  className="flex cursor-pointer items-center gap-2.5 rounded-md border-b border-hairline px-2.5 py-2 text-[13px] transition-colors hover:bg-muted"
                  onClick={() => setSearchParams({ carpeta: String(carpeta.id) })}
                >
                  {/* Era el emoji 📁. La guía no-emoji-icons lo prohíbe: depende de la
                      fuente del sistema y no se puede teñir con un token. */}
                  <Folder aria-hidden className="size-4 shrink-0 text-muted-foreground" />
                  <span className="flex-1 font-medium">{carpeta.nombre}</span>
                  <span className="mr-2 text-[11px] text-muted-foreground">
                    {carpeta.n_corridas} corrida{carpeta.n_corridas !== 1 ? "s" : ""}
                  </span>
                  {carpeta.parent_id === null && (
                    <Link
                      to={`/proyecto/${carpeta.id}/distancias`}
                      className="mr-1.5 text-xs underline"
                      onClick={(e) => e.stopPropagation()}
                    >
                      Distancias
                    </Link>
                  )}
                  {puedeEditar && (
                    <div className="flex gap-1.5">
                      <Button
                        variant="outline"
                        size="xs"
                        onClick={(e) => handleRenombrar(e, carpeta)}
                        title="Renombrar carpeta"
                      >
                        Renombrar
                      </Button>
                      <Button
                        variant="outline"
                        size="xs"
                        onClick={(e) => handleMoverCarpeta(e, carpeta)}
                        title="Mover carpeta"
                      >
                        Mover
                      </Button>
                      <Button
                        variant="destructive"
                        size="xs"
                        onClick={(e) => handleEliminarCarpeta(e, carpeta)}
                        title="Eliminar carpeta"
                      >
                        Eliminar
                      </Button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Tabla de corridas: solo dentro de una carpeta */}
          {carpetaActual != null && corridasFiltradas.length === 0 && (
            <p className="my-6 text-[13px] text-muted-foreground">
              No hay corridas en esta carpeta.
            </p>
          )}

          {carpetaActual != null && corridasFiltradas.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-xs">
                <thead>
                  <tr>
                    <th className={CLASE_TH}>Nombre</th>
                    <th className={CLASE_TH}>Lista</th>
                    <th className={cn(CLASE_TH, "text-right")}>Items</th>
                    <th className={cn(CLASE_TH, "text-right")}>Por revisar</th>
                    <th className={cn(CLASE_TH, "text-right")}>Contractual</th>
                    <th className={cn(CLASE_TH, "text-right")}>Costo</th>
                    <th className={cn(CLASE_TH, "text-right")}>Dif. $</th>
                    <th className={cn(CLASE_TH, "text-right")}>Margen %</th>
                    <th className={cn(CLASE_TH, "text-right")}>Tiempo</th>
                    <th className={CLASE_TH}>Estado</th>
                    <th className={CLASE_TH}>Modo</th>
                    <th className={CLASE_TH}></th>
                  </tr>
                </thead>
                <tbody>
                  {corridasFiltradas.map((c) => (
                    <tr
                      key={c.id}
                      className="cursor-pointer border-b border-hairline transition-colors hover:bg-muted"
                      onClick={() => navigate(`/corridas/${c.id}`)}
                    >
                      <td className={CLASE_TD}>
                        <span className="font-medium" title={c.archivo}>{c.nombre}</span>
                        <span className="text-[11px] text-muted-foreground">
                          {" "}— {fechaLegible(c.creada_en)}
                        </span>
                      </td>
                      <td className={CLASE_TD}>
                        {c.lista_precios_id === null
                          ? <span className="text-muted-foreground">Principal</span>
                          : <span className="font-medium text-revisar">{c.lista_nombre}</span>}
                      </td>
                      <td className={cn(CLASE_TD, CLASE_NUM)}>{c.n_items}</td>
                      <td className={cn(CLASE_TD, CLASE_NUM)}>{c.n_revision}</td>
                      <td className={cn(CLASE_TD, CLASE_NUM)}>
                        {c.contractual === null ? "—" : cop(c.contractual)}
                      </td>
                      <td className={cn(CLASE_TD, CLASE_NUM)}>
                        {c.costo === null ? "—" : cop(c.costo)}
                      </td>
                      <td className={cn(CLASE_TD, CLASE_NUM, claseSigno(c.margen))}>
                        {c.margen === null ? "—" : cop(c.margen)}
                      </td>
                      <td className={cn(CLASE_TD, CLASE_NUM, claseSigno(c.margen))}>
                        {c.margen_pct === null ? "—" : pct(c.margen_pct)}
                      </td>
                      <td className={cn(CLASE_TD, CLASE_NUM)}>{fmtDuracion(c.duracion_ms)}</td>
                      <td className={CLASE_TD}>
                        <span className={cn(CLASE_BADGE, claseEstado(c.estado))}>{c.estado}</span>
                      </td>
                      <td className={CLASE_TD}>
                        <span
                          className={cn(
                            CLASE_BADGE,
                            c.modo === "congelada"
                              ? "bg-info-surface text-info"
                              : "bg-margen-pos-surface text-margen-pos",
                          )}
                        >
                          {c.modo === "congelada" ? "Congelada" : "Activa"}
                        </span>
                      </td>
                      <td className={cn(CLASE_TD, "w-[140px] space-x-1 text-right whitespace-nowrap")}>
                        {puedeEditar && (
                          <Button
                            variant="outline"
                            size="xs"
                            onClick={(e) => handleRenombrarCorrida(e, c)}
                            title="Renombrar corrida"
                          >
                            Renombrar
                          </Button>
                        )}
                        {puedeEditar && (
                          <Button
                            variant="outline"
                            size="xs"
                            onClick={(e) => handleMoverCorrida(e, c)}
                            title="Mover corrida"
                          >
                            Mover
                          </Button>
                        )}
                        <Button
                          variant="destructive"
                          size="xs"
                          onClick={(e) => handleEliminar(e, c)}
                          title="Eliminar corrida"
                        >
                          Eliminar
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** Clase del signo de una cifra: positivo en `--margen-pos`, negativo en `--margen-neg`.
 *
 *  Antes se llamaba `colorSigno` y devolvía los hex `#276749` / `#c53030` para meterlos
 *  en un `style={{color}}`. Devolver una clase es lo que permite que el color viva en
 *  index.css y no acá. El contrato lógico es el mismo: >= 0 positivo, < 0 negativo,
 *  `null` sin clase. */
export function claseSigno(n: number | null): string | undefined {
  if (n === null || n === undefined) return undefined;
  return n >= 0 ? "text-margen-pos" : "text-margen-neg";
}

/** Clase del badge de estado de una corrida. Los cinco casos son los mismos de antes;
 *  lo que cambia es que salen de tokens y no de hex sueltos. */
function claseEstado(estado: string): string {
  switch (estado.toLowerCase()) {
    case "ok":
    case "listo":
      return "bg-margen-pos-surface text-margen-pos";
    case "armando":
      return "bg-info-surface text-info";
    case "revision":
    case "en_revision":
    case "por_revisar":
      return "bg-revisar-surface text-revisar";
    case "error":
      return "bg-destructive-surface text-destructive";
    default:
      return "bg-muted text-muted-foreground";
  }
}

const CLASE_MIGAJA =
  "cursor-pointer rounded-sm text-ring underline underline-offset-2 " +
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring";
const CLASE_TH =
  "border-b border-border bg-muted px-2.5 py-1.5 text-left font-semibold " +
  "whitespace-nowrap text-muted-foreground";
const CLASE_TD = "px-2.5 py-1.5 align-middle";
const CLASE_NUM = "text-right font-mono tabular-nums";
const CLASE_BADGE =
  "inline-block rounded-md px-1.5 py-px text-[11px] font-medium whitespace-nowrap";
