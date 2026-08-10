import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Lock, Mail } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/lib/auth";
import { supabase } from "@/lib/supabase";
import MarcoIngreso from "@/components/MarcoIngreso";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export default function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [verClave, setVerClave] = useState(false);

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

  async function conGoogle() {
    // El backend no cambia: el JWT de Supabase es el mismo venga de contraseña o de
    // Google, y el acceso lo sigue habilitando la invitación de un Admin.
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: `${window.location.origin}/corridas` },
    });
    if (error) toast.error(error.message);
  }

  return (
    <MarcoIngreso>
      <div className="flex flex-col gap-0.5">
        <h1 className="text-[21px] font-semibold tracking-[-0.02em]">Ingresar</h1>
        <p className="text-[13px] text-muted-foreground">Usa tu correo de la empresa.</p>
      </div>

      <form onSubmit={onSubmit} className="flex flex-col gap-3.5">
        <div className="flex flex-col gap-1.5">
          <label htmlFor="login-email" className="text-[11.5px] font-medium">
            Correo
          </label>
          <div className="relative flex items-center">
            <Mail
              aria-hidden
              className="pointer-events-none absolute left-2.5 size-3.5 text-muted-foreground"
            />
            <Input
              id="login-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
              autoComplete="username"
              placeholder="tu.nombre@indugravas.com"
              className="h-9 pl-8"
            />
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          <div className="flex items-baseline justify-between gap-2.5">
            <label htmlFor="login-password" className="text-[11.5px] font-medium">
              Contraseña
            </label>
            <button
              type="button"
              onClick={olvide}
              className="rounded-sm text-[11.5px] text-ring underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            >
              ¿Olvidaste tu contraseña?
            </button>
          </div>
          <div className="relative flex items-center">
            <Lock
              aria-hidden
              className="pointer-events-none absolute left-2.5 size-3.5 text-muted-foreground"
            />
            <Input
              id="login-password"
              type={verClave ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
              className="h-9 pr-[62px] pl-8"
            />
            {/* Sin aria-label a propósito: el nombre accesible es la etiqueta visible.
                Con `aria-label="Mostrar contraseña"` este botón chocaría con el
                getByLabelText(/contraseña/i) del test que ya existía. */}
            <Button
              type="button"
              variant="ghost"
              size="xs"
              aria-pressed={verClave}
              onClick={() => setVerClave((v) => !v)}
              className="absolute right-1 text-[11px] font-normal text-muted-foreground"
            >
              {verClave ? "Ocultar" : "Mostrar"}
            </Button>
          </div>
        </div>

        <Button type="submit" size="lg" disabled={enviando} className="mt-0.5 w-full">
          {enviando ? "Ingresando…" : "Ingresar"}
        </Button>
      </form>

      <div className="flex items-center gap-2.5">
        <span className="h-px flex-1 bg-border" />
        <span className="text-[11px] text-muted-foreground">o</span>
        <span className="h-px flex-1 bg-border" />
      </div>

      <Button type="button" variant="outline" size="lg" className="w-full"
              onClick={conGoogle} disabled={enviando}>
        <IconoGoogle />
        Continuar con Google
      </Button>

      <p className="text-[11.5px] leading-relaxed text-muted-foreground">
        El acceso lo habilita un administrador. Si no puedes entrar, pídele que te invite o
        que reenvíe la invitación.
      </p>
    </MarcoIngreso>
  );
}

function IconoGoogle() {
  return (
    <svg aria-hidden viewBox="0 0 24 24" className="size-4">
      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.76h3.57c2.08-1.92 3.27-4.74 3.27-8.09Z" />
      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.76c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23Z" />
      <path fill="#FBBC05" d="M5.84 14.11a6.6 6.6 0 0 1 0-4.22V7.05H2.18a11 11 0 0 0 0 9.9l3.66-2.84Z" />
      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.05l3.66 2.84C6.71 7.31 9.14 5.38 12 5.38Z" />
    </svg>
  );
}
