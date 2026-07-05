import { useEffect, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { listarCorridas, eliminarCorrida, descargarPlantillaLicitacion } from "@/api/corridas";
import { fmtDuracion } from "@/lib/tiempo";
import type { CorridaResumen } from "@/lib/tipos";

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

export default function MisCorridas() {
  const navigate = useNavigate();
  const [corridas, setCorridas] = useState<CorridaResumen[]>([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const cargar = useCallback(() => {
    setCargando(true);
    setError(null);
    listarCorridas()
      .then(setCorridas)
      .catch((e) => setError(e instanceof Error ? e.message : "Error al cargar corridas"))
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

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <h2 style={styles.titulo}>Mis corridas</h2>
        <div style={styles.acciones}>
          <button style={styles.btnPlantilla} onClick={bajarPlantilla}>
            Descargar plantilla
          </button>
          <button style={styles.btnNueva} onClick={() => navigate("/corridas/nueva")}>
            Nueva corrida
          </button>
        </div>
      </div>

      {cargando && <p style={styles.msg}>Cargando…</p>}
      {error && <p style={styles.msgError}>{error}</p>}

      {!cargando && !error && corridas.length === 0 && (
        <p style={styles.msgVacio}>No hay corridas; crea una nueva.</p>
      )}

      {!cargando && !error && corridas.length > 0 && (
        <div style={styles.tableWrap}>
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>Nombre</th>
                <th style={{ ...styles.th, ...styles.thNum }}>Items</th>
                <th style={{ ...styles.th, ...styles.thNum }}>Por revisar</th>
                <th style={{ ...styles.th, ...styles.thNum }}>Tiempo</th>
                <th style={styles.th}>Estado</th>
                <th style={styles.th}>Modo</th>
                <th style={styles.th}></th>
              </tr>
            </thead>
            <tbody>
              {corridas.map((c) => (
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
    </div>
  );
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
    width: "90px",
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
