import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import type { Session } from "@supabase/supabase-js";
import { supabase } from "@/lib/supabase";
import { getYo, type Yo } from "@/api/usuarios";

type AuthCtx = {
  sesion: Session | null;
  perfil: Yo | null;
  cargando: boolean;
  noAutorizado: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [sesion, setSesion] = useState<Session | null>(null);
  const [perfil, setPerfil] = useState<Yo | null>(null);
  const [cargando, setCargando] = useState(true);
  const [noAutorizado, setNoAutorizado] = useState(false);

  useEffect(() => {
    const { data } = supabase.auth.onAuthStateChange(async (_evento, nuevaSesion) => {
      setSesion(nuevaSesion);
      setNoAutorizado(false);
      if (nuevaSesion) {
        try {
          setPerfil(await getYo());
        } catch {
          // Autenticado en Supabase pero sin perfil / inactivo -> 403
          setPerfil(null);
          setNoAutorizado(true);
          await supabase.auth.signOut();
        }
      } else {
        setPerfil(null);
      }
      setCargando(false);
    });
    return () => data.subscription.unsubscribe();
  }, []);

  const login = async (email: string, password: string) => {
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) throw new Error(error.message);
  };
  const logout = async () => { await supabase.auth.signOut(); };

  return (
    <Ctx.Provider value={{ sesion, perfil, cargando, noAutorizado, login, logout }}>
      {children}
    </Ctx.Provider>
  );
}

export function useAuth(): AuthCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth debe usarse dentro de <AuthProvider>");
  return c;
}
