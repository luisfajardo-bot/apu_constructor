import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useAuth } from "@/lib/auth";
import { supabase } from "@/lib/supabase";

export default function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [enviando, setEnviando] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setEnviando(true);
    try {
      await login(email, password);
      nav("/corridas", { replace: true });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "No se pudo ingresar.");
    } finally {
      setEnviando(false);
    }
  }

  async function olvide() {
    if (!email) return toast.error("Escribe tu correo primero.");
    const redirectTo = `${window.location.origin}/definir-clave`;
    const { error } = await supabase.auth.resetPasswordForEmail(email, { redirectTo });
    if (error) toast.error(error.message);
    else toast.success("Te enviamos un correo para restablecer la contraseña.");
  }

  return (
    <div style={styles.pantalla}>
      <header style={styles.topbar}>
        <span style={styles.brand}>Armador de APUs</span>
      </header>
      <div style={styles.centro}>
        <form onSubmit={onSubmit} style={styles.panel}>
          <h1 style={styles.titulo}>Ingresar</h1>
          <p style={styles.subtitulo}>Usa tu correo de la empresa.</p>

          <div style={styles.campo}>
            <label style={styles.label} htmlFor="login-email">Correo</label>
            <input
              id="login-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
              autoComplete="username"
              style={styles.input}
            />
          </div>

          <div style={styles.campo}>
            <label style={styles.label} htmlFor="login-password">Contraseña</label>
            <input
              id="login-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
              style={styles.input}
            />
          </div>

          <button type="submit" style={styles.btnPrimario} disabled={enviando}>
            {enviando ? "Ingresando…" : "Ingresar"}
          </button>
          <button type="button" onClick={olvide} style={styles.btnEnlace}>
            ¿Olvidaste tu contraseña?
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
  btnEnlace: {
    background: "none",
    border: "none",
    color: "#4a90d9",
    fontSize: "12px",
    cursor: "pointer",
    padding: "2px 0",
    textAlign: "center",
  },
};
