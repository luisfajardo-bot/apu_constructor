import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Lock } from "lucide-react";
import { toast } from "sonner";
import { supabase } from "@/lib/supabase";
import MarcoIngreso from "@/components/MarcoIngreso";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

// supabase-js detecta el token (invite/recovery) del hash de la URL y crea sesión temporal al cargar.
export default function DefinirClave() {
  const nav = useNavigate();
  const [password, setPassword] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [verClave, setVerClave] = useState(false);

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
    <MarcoIngreso>
      <div className="flex flex-col gap-0.5">
        <h1 className="text-[21px] font-semibold tracking-[-0.02em]">Definir contraseña</h1>
        <p className="text-[13px] text-muted-foreground">
          Elige una contraseña de al menos 8 caracteres.
        </p>
      </div>

      <form onSubmit={onSubmit} className="flex flex-col gap-3.5">
        <div className="flex flex-col gap-1.5">
          <label htmlFor="definir-password" className="text-[11.5px] font-medium">
            Nueva contraseña
          </label>
          <div className="relative flex items-center">
            <Lock
              aria-hidden
              className="pointer-events-none absolute left-2.5 size-3.5 text-muted-foreground"
            />
            <Input
              id="definir-password"
              type={verClave ? "text" : "password"}
              value={password}
              minLength={8}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoFocus
              autoComplete="new-password"
              className="h-9 pr-[62px] pl-8"
            />
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
          {enviando ? "Guardando…" : "Guardar"}
        </Button>
      </form>
    </MarcoIngreso>
  );
}
