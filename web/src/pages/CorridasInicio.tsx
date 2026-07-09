import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useArmadoVivo } from "@/lib/armado";
import { listarCarpetas, crearCarpeta } from "@/api/carpetas";
import type { CarpetaNodo } from "@/lib/tipos";

export default function CorridasInicio() {
  const navigate = useNavigate();
  const { armarArchivo, armarEjemplo } = useArmadoVivo();
  const fileRef = useRef<HTMLInputElement>(null);
  const [usarIA, setUsarIA] = useState(true);
  const [cargando, setCargando] = useState(false);

  // Carpetas
  const [carpetas, setCarpetas] = useState<CarpetaNodo[]>([]);
  const [nivel1Id, setNivel1Id] = useState<number | null>(null);
  const [nivel2Id, setNivel2Id] = useState<number | null>(null);

  const carpetaDestino: number | null =
    nivel2Id !== null ? nivel2Id : nivel1Id !== null ? nivel1Id : null;

  async function cargarCarpetas(): Promise<CarpetaNodo[]> {
    const arbol = await listarCarpetas();
    setCarpetas(arbol);
    return arbol;
  }

  useEffect(() => {
    cargarCarpetas().catch(() => {
      toast.error("No se pudieron cargar las carpetas");
    });
  }, []);

  const hijas: CarpetaNodo[] =
    nivel1Id !== null
      ? (carpetas.find((c) => c.id === nivel1Id)?.hijas ?? [])
      : [];

  function handleNivel1Change(e: React.ChangeEvent<HTMLSelectElement>) {
    const val = e.target.value;
    setNivel1Id(val ? Number(val) : null);
    setNivel2Id(null);
  }

  function handleNivel2Change(e: React.ChangeEvent<HTMLSelectElement>) {
    const val = e.target.value;
    setNivel2Id(val ? Number(val) : null);
  }

  async function handleCrearCarpeta() {
    const nombre = window.prompt(
      nivel1Id !== null
        ? "Nombre de la nueva subcarpeta"
        : "Nombre de la nueva carpeta"
    );
    if (!nombre || !nombre.trim()) return;
    try {
      const nueva = await crearCarpeta(nombre.trim(), nivel1Id);
      const arbol = await cargarCarpetas();
      // Auto-select the new folder as destination
      if (nivel1Id !== null) {
        // Created a subfolder under the current level-1
        setNivel2Id(nueva.id);
      } else {
        // Created a new level-1 folder; select it
        const nodo = arbol.find((c) => c.id === nueva.id);
        if (nodo) {
          setNivel1Id(nueva.id);
          setNivel2Id(null);
        }
      }
    } catch {
      toast.error("No se pudo crear la carpeta");
    }
  }

  async function handleArmar(e: React.FormEvent) {
    e.preventDefault();
    if (carpetaDestino == null) {
      toast.error("Elige una carpeta");
      return;
    }
    const archivo = fileRef.current?.files?.[0];
    if (!archivo) {
      toast.error("Selecciona un archivo .xlsx o .csv");
      return;
    }
    const form = new FormData();
    form.append("archivo", archivo);
    form.append("use_ai", String(usarIA));
    form.append("carpeta_id", String(carpetaDestino));
    setCargando(true);
    try {
      await armarArchivo(form, (id) => navigate(`/corridas/${id}`));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Error al crear la corrida");
    } finally {
      setCargando(false);
    }
  }

  async function handleEjemplo() {
    setCargando(true);
    try {
      await armarEjemplo((id) => navigate(`/corridas/${id}`));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Error al crear corrida de ejemplo");
    } finally {
      setCargando(false);
    }
  }

  return (
    <div style={styles.container}>
        <h2 style={styles.titulo}>Nueva corrida</h2>
        <form onSubmit={handleArmar} style={styles.form}>
          {/* Archivo */}
          <div style={styles.campo}>
            <label style={styles.label} htmlFor="archivo">
              Archivo de licitación
            </label>
            <input
              id="archivo"
              ref={fileRef}
              type="file"
              accept=".xlsx,.csv"
              style={styles.inputFile}
              disabled={cargando}
            />
          </div>

          {/* Usar IA */}
          <div style={styles.campoInline}>
            <input
              id="usar-ia"
              type="checkbox"
              checked={usarIA}
              onChange={(e) => setUsarIA(e.target.checked)}
              disabled={cargando}
              style={styles.checkbox}
            />
            <label htmlFor="usar-ia" style={styles.labelInline}>
              Usar IA
            </label>
          </div>

          {/* Carpeta */}
          <div style={styles.campo}>
            <label style={styles.label} htmlFor="carpeta-nivel1">
              Carpeta
            </label>
            <div style={styles.selectFila}>
              <select
                id="carpeta-nivel1"
                value={nivel1Id ?? ""}
                onChange={handleNivel1Change}
                disabled={cargando}
                style={styles.select}
              >
                <option value="">— Elegir carpeta —</option>
                {carpetas.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.nombre}
                  </option>
                ))}
              </select>
              {hijas.length > 0 && (
                <select
                  id="carpeta-nivel2"
                  value={nivel2Id ?? ""}
                  onChange={handleNivel2Change}
                  disabled={cargando}
                  style={styles.select}
                >
                  <option value="">— (ninguna) —</option>
                  {hijas.map((h) => (
                    <option key={h.id} value={h.id}>
                      {h.nombre}
                    </option>
                  ))}
                </select>
              )}
              <button
                type="button"
                style={styles.btnCrearCarpeta}
                disabled={cargando}
                onClick={handleCrearCarpeta}
              >
                + Carpeta
              </button>
            </div>
          </div>

          {/* Botones */}
          <div style={styles.botones}>
            <button
              type="submit"
              style={styles.btnPrimario}
              disabled={cargando || carpetaDestino == null}
            >
              {cargando ? "Armando…" : "Armar"}
            </button>
            <button
              type="button"
              style={styles.btnSecundario}
              disabled={cargando}
              onClick={handleEjemplo}
            >
              Usar ejemplo
            </button>
          </div>
        </form>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    padding: "24px 28px",
    maxWidth: "400px",
  },
  titulo: {
    margin: "0 0 16px",
    fontSize: "15px",
    fontWeight: 600,
    color: "#1a1a2e",
  },
  form: {
    display: "flex",
    flexDirection: "column",
    gap: "12px",
  },
  campo: {
    display: "flex",
    flexDirection: "column",
    gap: "4px",
  },
  label: {
    fontSize: "12px",
    fontWeight: 500,
    color: "#4a5568",
  },
  inputFile: {
    fontSize: "12px",
    color: "#2d3748",
  },
  campoInline: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
  },
  checkbox: {
    cursor: "pointer",
  },
  labelInline: {
    fontSize: "12px",
    fontWeight: 500,
    color: "#4a5568",
    cursor: "pointer",
  },
  selectFila: {
    display: "flex",
    gap: "6px",
    alignItems: "center",
    flexWrap: "wrap",
  },
  select: {
    fontSize: "12px",
    color: "#2d3748",
    padding: "4px 6px",
    borderRadius: "4px",
    border: "1px solid #cbd5e0",
    background: "#fff",
  },
  botones: {
    display: "flex",
    gap: "8px",
    marginTop: "4px",
  },
  btnPrimario: {
    padding: "6px 16px",
    fontSize: "12px",
    fontWeight: 600,
    background: "#1a1a2e",
    color: "#e2e8f0",
    border: "none",
    borderRadius: "4px",
    cursor: "pointer",
  },
  btnSecundario: {
    padding: "6px 14px",
    fontSize: "12px",
    fontWeight: 500,
    background: "#fff",
    color: "#4a5568",
    border: "1px solid #cbd5e0",
    borderRadius: "4px",
    cursor: "pointer",
  },
  btnCrearCarpeta: {
    padding: "4px 10px",
    fontSize: "11px",
    fontWeight: 500,
    background: "#fff",
    color: "#4a5568",
    border: "1px solid #cbd5e0",
    borderRadius: "4px",
    cursor: "pointer",
    whiteSpace: "nowrap",
  },
  progresoLinea: {
    margin: "8px 0 0",
    fontSize: "11px",
    color: "#4a5568",
  },
};
