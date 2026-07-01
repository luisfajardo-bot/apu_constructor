import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { supabase } from "@/lib/supabase";

// supabase-js detecta el token (invite/recovery) del hash de la URL y crea sesión temporal al cargar.
export default function DefinirClave() {
  const nav = useNavigate();
  const [password, setPassword] = useState("");
  const [enviando, setEnviando] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setEnviando(true);
    const { error } = await supabase.auth.updateUser({ password });
    setEnviando(false);
    if (error) return toast.error(error.message);
    toast.success("Contraseña definida. Ya puedes usar la app.");
    nav("/corridas", { replace: true });
  }

  return (
    <div style={styles.pantalla}>
      <header style={styles.topbar}>
        <span style={styles.brand}>Armador de APUs</span>
      </header>
      <div style={styles.centro}>
        <form onSubmit={onSubmit} style={styles.panel}>
          <h1 style={styles.titulo}>Definir contraseña</h1>
          <p style={styles.subtitulo}>Elige una contraseña de al menos 8 caracteres.</p>

          <div style={styles.campo}>
            <label style={styles.label} htmlFor="definir-password">Nueva contraseña</label>
            <input
              id="definir-password"
              type="password"
              value={password}
              minLength={8}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoFocus
              autoComplete="new-password"
              style={styles.input}
            />
          </div>

          <button type="submit" style={styles.btnPrimario} disabled={enviando}>
            {enviando ? "Guardando…" : "Guardar"}
          </button>
        </form>
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  pantalla: {
    display: "flex",
    flexDirection: "column",
    height: "100vh",
    fontFamily: "system-ui, sans-serif",
    background: "#f7f7f8",
  },
  topbar: {
    display: "flex",
    alignItems: "center",
    padding: "0 12px",
    height: "36px",
    background: "#1a1a2e",
    color: "#e2e8f0",
    flexShrink: 0,
  },
  brand: {
    fontWeight: 600,
    fontSize: "13px",
    letterSpacing: "0.02em",
  },
  centro: {
    flex: 1,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "24px",
  },
  panel: {
    width: "100%",
    maxWidth: "320px",
    display: "flex",
    flexDirection: "column",
    gap: "12px",
    background: "#ffffff",
    border: "1px solid #e2e8f0",
    borderRadius: "6px",
    padding: "28px 24px",
  },
  titulo: {
    margin: 0,
    fontSize: "16px",
    fontWeight: 600,
    color: "#1a1a2e",
  },
  subtitulo: {
    margin: "-8px 0 4px",
    fontSize: "12px",
    color: "#a0aec0",
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
  input: {
    padding: "6px 8px",
    fontSize: "13px",
    border: "1px solid #cbd5e0",
    borderRadius: "4px",
    outline: "none",
    color: "#1a1a2e",
    background: "#fff",
  },
  btnPrimario: {
    marginTop: "4px",
    padding: "7px 16px",
    fontSize: "13px",
    fontWeight: 600,
    background: "#1a1a2e",
    color: "#e2e8f0",
    border: "none",
    borderRadius: "4px",
    cursor: "pointer",
  },
};
