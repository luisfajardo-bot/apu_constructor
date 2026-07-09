import { useEffect, useState, useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { listarCorridas, eliminarCorrida, descargarPlantillaLicitacion } from "@/api/corridas";
import { listarCarpetas, crearCarpeta, renombrarCarpeta, borrarCarpeta, moverCorrida, moverCarpeta } from "@/api/carpetas";
import { useAuth } from "@/lib/auth";
import { fmtDuracion } from "@/lib/tiempo";
import { cop, pct } from "@/lib/moneda";
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
    if (!window.confirm(`¿Eliminar la corrida "${corrida.archivo}"?`)) return;
    try {
      await eliminarCorrida(corrida.id);
      toast.success(`Corrida "${corrida.archivo}" eliminada`);
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

  async function handleMoverCorrida(e: React.MouseEvent, corrida: CorridaResumen) {
    e.stopPropagation();
    const destinos = listaDestinos(arbol);
    if (destinos.length === 0) {
      toast.error("No hay carpetas de destino disponibles.");
      return;
    }
    const opciones = destinos.map((d, i) => `${i + 1}. ${d.etiqueta}`).join("\n");
    const resp = window.prompt(`Mover "${corrida.archivo}" a:\n${opciones}\n\nEscribe el número:`);
    if (!resp?.trim()) return;
    const idx = parseInt(resp.trim(), 10) - 1;
    if (isNaN(idx) || idx < 0 || idx >= destinos.length) return;
    try {
      await moverCorrida(corrida.id, destinos[idx].id);
      toast.success(`Corrida "${corrida.archivo}" movida a "${destinos[idx].etiqueta}"`);
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
    <div style={styles.container}>
      <div style={styles.header}>
        <h2 style={styles.titulo}>Mis corridas</h2>
        <div style={styles.acciones}>
          <button style={styles.btnPlantilla} onClick={bajarPlantilla}>
            Descargar plantilla
          </button>
          <button style={styles.btnNuevaCarpeta} onClick={handleNuevaCarpeta}>
            Nueva carpeta
          </button>
          <button style={styles.btnNueva} onClick={() => navigate("/corridas/nueva")}>
            Nueva corrida
          </button>
        </div>
      </div>

      {/* Breadcrumb */}
      <div style={styles.breadcrumb}>
        <span
          style={styles.breadcrumbLink}
          onClick={() => setSearchParams({})}
        >
          Todas
        </span>
        {migajas.map((m) => (
          <span key={m.id}>
            <span style={styles.breadcrumbSep}> › </span>
            <span
              style={styles.breadcrumbLink}
              onClick={() => setSearchParams({ carpeta: String(m.id) })}
            >
              {m.nombre}
            </span>
          </span>
        ))}
      </div>

      {cargando && <p style={styles.msg}>Cargando…</p>}
      {error && <p style={styles.msgError}>{error}</p>}

      {!cargando && !error && (
        <>
          {/* Filas de subcarpetas */}
          {subcarpetas.length > 0 && (
            <div style={styles.carpetasWrap}>
              {subcarpetas.map((carpeta) => (
                <div
                  key={carpeta.id}
                  style={styles.carpetaFila}
                  onClick={() => setSearchParams({ carpeta: String(carpeta.id) })}
                  onMouseEnter={(e) =>
                    ((e.currentTarget as HTMLDivElement).style.background = "#f0f4f8")
                  }
                  onMouseLeave={(e) =>
                    ((e.currentTarget as HTMLDivElement).style.background = "")
                  }
                >
                  <span style={styles.carpetaIcono}>📁</span>
                  <span style={styles.carpetaNombre}>{carpeta.nombre}</span>
                  <span style={styles.carpetaCount}>{carpeta.n_corridas} corrida{carpeta.n_corridas !== 1 ? "s" : ""}</span>
                  {puedeEditar && (
                    <div style={styles.carpetaAcciones}>
                      <button
                        style={styles.btnCarpetaAccion}
                        onClick={(e) => handleRenombrar(e, carpeta)}
                        title="Renombrar carpeta"
                      >
                        Renombrar
                      </button>
                      <button
                        style={styles.btnCarpetaAccion}
                        onClick={(e) => handleMoverCarpeta(e, carpeta)}
                        title="Mover carpeta"
                      >
                        Mover
                      </button>
                      <button
                        style={{ ...styles.btnCarpetaAccion, ...styles.btnCarpetaEliminar }}
                        onClick={(e) => handleEliminarCarpeta(e, carpeta)}
                        title="Eliminar carpeta"
                      >
                        Eliminar
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Tabla de corridas: solo dentro de una carpeta */}
          {carpetaActual != null && corridasFiltradas.length === 0 && (
            <p style={styles.msgVacio}>No hay corridas en esta carpeta.</p>
          )}

          {carpetaActual != null && corridasFiltradas.length > 0 && (
            <div style={styles.tableWrap}>
              <table style={styles.table}>
                <thead>
                  <tr>
                    <th style={styles.th}>Nombre</th>
                    <th style={{ ...styles.th, ...styles.thNum }}>Items</th>
                    <th style={{ ...styles.th, ...styles.thNum }}>Por revisar</th>
                    <th style={{ ...styles.th, ...styles.thNum }}>Contractual</th>
                    <th style={{ ...styles.th, ...styles.thNum }}>Costo</th>
                    <th style={{ ...styles.th, ...styles.thNum }}>Dif. $</th>
                    <th style={{ ...styles.th, ...styles.thNum }}>Margen %</th>
                    <th style={{ ...styles.th, ...styles.thNum }}>Tiempo</th>
                    <th style={styles.th}>Estado</th>
                    <th style={styles.th}>Modo</th>
                    <th style={styles.th}></th>
                  </tr>
                </thead>
                <tbody>
                  {corridasFiltradas.map((c) => (
                    <tr
                      key={c.id}
                      style={styles.tr}
                      onClick={() => navigate(`/corridas/${c.id}`)}
                      onMouseEnter={(e) =>
                        ((e.currentTarget as HTMLTableRowElement).style.background = "#f0f4f8")
                      }
                      onMouseLeave={(e) =>
                        ((e.currentTarget as HTMLTableRowElement).style.background = "")
                      }
                    >
                      <td style={styles.td}>
                        <span style={styles.nombre}>{c.archivo}</span>
                        <span style={styles.fecha}> — {fechaLegible(c.creada_en)}</span>
                      </td>
                      <td style={{ ...styles.td, ...styles.tdNum }}>{c.n_items}</td>
                      <td style={{ ...styles.td, ...styles.tdNum }}>{c.n_revision}</td>
                      <td style={{ ...styles.td, ...styles.tdNum }}>
                        {c.contractual === null ? "—" : cop(c.contractual)}
                      </td>
                      <td style={{ ...styles.td, ...styles.tdNum }}>
                        {c.costo === null ? "—" : cop(c.costo)}
                      </td>
                      <td style={{ ...styles.td, ...styles.tdNum, color: colorSigno(c.margen) }}>
                        {c.margen === null ? "—" : cop(c.margen)}
                      </td>
                      <td style={{ ...styles.td, ...styles.tdNum, color: colorSigno(c.margen) }}>
                        {c.margen_pct === null ? "—" : pct(c.margen_pct)}
                      </td>
                      <td style={{ ...styles.td, ...styles.tdNum }}>{fmtDuracion(c.duracion_ms)}</td>
                      <td style={styles.td}>
                        <span style={{ ...styles.badge, ...estadoBadgeStyle(c.estado) }}>
                          {c.estado}
                        </span>
                      </td>
                      <td style={styles.td}>
                        <span style={{ ...styles.badge, ...(c.modo === "congelada"
                          ? { background: "#bee3f8", color: "#2a4365" }
                          : { background: "#c6f6d5", color: "#276749" }) }}>
                          {c.modo === "congelada" ? "Congelada" : "Activa"}
                        </span>
                      </td>
                      <td style={{ ...styles.td, ...styles.tdAccion }}>
                        {puedeEditar && (
                          <button
                            style={styles.btnMover}
                            onClick={(e) => handleMoverCorrida(e, c)}
                            title="Mover corrida"
                          >
                            Mover
                          </button>
                        )}
                        <button
                          style={styles.btnEliminar}
                          onClick={(e) => handleEliminar(e, c)}
                          title="Eliminar corrida"
                        >
                          Eliminar
                        </button>
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

export function colorSigno(n: number | null): string | undefined {
  if (n === null || n === undefined) return undefined;
  return n >= 0 ? "#276749" : "#c53030";
}

function estadoBadgeStyle(estado: string): React.CSSProperties {
  switch (estado.toLowerCase()) {
    case "ok":
    case "listo":
      return { background: "#c6f6d5", color: "#276749" };
    case "armando":
      return { background: "#bee3f8", color: "#2a4365" };
    case "revision":
    case "en_revision":
    case "por_revisar":
      return { background: "#fefcbf", color: "#744210" };
    case "error":
      return { background: "#fed7d7", color: "#9b2c2c" };
    default:
      return { background: "#e2e8f0", color: "#4a5568" };
  }
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    padding: "20px 24px",
  },
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: "14px",
  },
  titulo: {
    margin: 0,
    fontSize: "15px",
    fontWeight: 600,
    color: "#1a1a2e",
  },
  acciones: {
    display: "flex",
    gap: "8px",
    alignItems: "center",
  },
  btnPlantilla: {
    padding: "5px 14px",
    fontSize: "12px",
    fontWeight: 600,
    background: "#fff",
    color: "#1a1a2e",
    border: "1px solid #cbd5e0",
    borderRadius: "4px",
    cursor: "pointer",
  },
  btnNuevaCarpeta: {
    padding: "5px 14px",
    fontSize: "12px",
    fontWeight: 600,
    background: "#fff",
    color: "#1a1a2e",
    border: "1px solid #cbd5e0",
    borderRadius: "4px",
    cursor: "pointer",
  },
  btnNueva: {
    padding: "5px 14px",
    fontSize: "12px",
    fontWeight: 600,
    background: "#1a1a2e",
    color: "#e2e8f0",
    border: "none",
    borderRadius: "4px",
    cursor: "pointer",
  },
  breadcrumb: {
    fontSize: "12px",
    color: "#718096",
    marginBottom: "12px",
  },
  breadcrumbLink: {
    cursor: "pointer",
    color: "#3182ce",
    textDecoration: "underline",
  },
  breadcrumbSep: {
    color: "#a0aec0",
  },
  msg: {
    fontSize: "12px",
    color: "#718096",
    margin: "8px 0",
  },
  msgError: {
    fontSize: "12px",
    color: "#c53030",
    margin: "8px 0",
  },
  msgVacio: {
    fontSize: "13px",
    color: "#718096",
    margin: "24px 0",
  },
  carpetasWrap: {
    marginBottom: "16px",
  },
  carpetaFila: {
    display: "flex",
    alignItems: "center",
    gap: "10px",
    padding: "8px 10px",
    borderBottom: "1px solid #edf2f7",
    cursor: "pointer",
    fontSize: "13px",
    borderRadius: "4px",
    transition: "background 0.1s",
  },
  carpetaIcono: {
    fontSize: "16px",
    lineHeight: 1,
  },
  carpetaNombre: {
    fontWeight: 500,
    color: "#2d3748",
    flex: 1,
  },
  carpetaCount: {
    fontSize: "11px",
    color: "#718096",
    marginRight: "8px",
  },
  carpetaAcciones: {
    display: "flex",
    gap: "6px",
  },
  btnCarpetaAccion: {
    padding: "2px 8px",
    fontSize: "11px",
    background: "transparent",
    color: "#4a5568",
    border: "1px solid #cbd5e0",
    borderRadius: "4px",
    cursor: "pointer",
  },
  btnCarpetaEliminar: {
    color: "#c53030",
    border: "1px solid #feb2b2",
  },
  tableWrap: {
    overflowX: "auto",
  },
  table: {
    width: "100%",
    borderCollapse: "collapse",
    fontSize: "12px",
  },
  th: {
    padding: "6px 10px",
    background: "#f7f7f8",
    borderBottom: "1px solid #e2e8f0",
    textAlign: "left" as const,
    fontWeight: 600,
    color: "#4a5568",
    whiteSpace: "nowrap" as const,
  },
  thNum: {
    textAlign: "right" as const,
  },
  tr: {
    cursor: "pointer",
    borderBottom: "1px solid #edf2f7",
    transition: "background 0.1s",
  },
  td: {
    padding: "6px 10px",
    color: "#2d3748",
    verticalAlign: "middle" as const,
  },
  tdNum: {
    textAlign: "right" as const,
    fontVariantNumeric: "tabular-nums",
  },
  tdAccion: {
    textAlign: "right" as const,
    width: "140px",
    whiteSpace: "nowrap" as const,
  },
  nombre: {
    fontWeight: 500,
  },
  fecha: {
    color: "#718096",
    fontSize: "11px",
  },
  badge: {
    display: "inline-block",
    padding: "1px 7px",
    borderRadius: "10px",
    fontSize: "11px",
    fontWeight: 500,
    whiteSpace: "nowrap" as const,
  },
  btnMover: {
    padding: "3px 10px",
    fontSize: "11px",
    color: "#2b6cb0",
    background: "transparent",
    border: "1px solid #bee3f8",
    borderRadius: "4px",
    cursor: "pointer",
    marginRight: "4px",
  },
  btnEliminar: {
    padding: "3px 10px",
    fontSize: "11px",
    color: "#c53030",
    background: "transparent",
    border: "1px solid #feb2b2",
    borderRadius: "4px",
    cursor: "pointer",
  },
};
