import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { crearCorrida, crearSample } from "@/api/corridas";

type Turno = "DIURNO" | "NOCTURNO";

export default function CorridasInicio() {
  const navigate = useNavigate();
  const fileRef = useRef<HTMLInputElement>(null);
  const [turno, setTurno] = useState<Turno>("DIURNO");
  const [usarIA, setUsarIA] = useState(true);
  const [cargando, setCargando] = useState(false);

  async function handleArmar(e: React.FormEvent) {
    e.preventDefault();
    const archivo = fileRef.current?.files?.[0];
    if (!archivo) {
      toast.error("Selecciona un archivo .xlsx o .csv");
      return;
    }
    const form = new FormData();
    form.append("archivo", archivo);
    form.append("turno", turno);
    form.append("use_ai", String(usarIA));
    setCargando(true);
    try {
      const { id } = await crearCorrida(form);
      navigate(`/corridas/${id}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Error al crear la corrida");
    } finally {
      setCargando(false);
    }
  }

  async function handleEjemplo() {
    setCargando(true);
    try {
      const { id } = await crearSample();
      navigate(`/corridas/${id}`);
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

          {/* Turno */}
          <div style={styles.campo}>
            <label style={styles.label} htmlFor="turno">
              Turno
            </label>
            <select
              id="turno"
              value={turno}
              onChange={(e) => setTurno(e.target.value as Turno)}
              style={styles.select}
              disabled={cargando}
            >
              <option value="DIURNO">DIURNO</option>
              <option value="NOCTURNO">NOCTURNO</option>
            </select>
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

          {/* Botones */}
          <div style={styles.botones}>
            <button type="submit" style={styles.btnPrimario} disabled={cargando}>
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
  select: {
    fontSize: "12px",
    padding: "4px 8px",
    border: "1px solid #cbd5e0",
    borderRadius: "4px",
    background: "#fff",
    color: "#2d3748",
    width: "160px",
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
};
