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

      <p className="text-[11.5px] leading-relaxed text-muted-foreground">
        El acceso lo habilita un administrador. Si no puedes entrar, pídele que te invite o
        que reenvíe la invitación.
      </p>
    </MarcoIngreso>
  );
}
