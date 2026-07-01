import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "@/lib/auth";
import type { Rol } from "@/api/usuarios";

export const RANGO: Record<Rol, number> = { consulta: 1, editor: 2, admin: 3 };
export const puede = (rol: Rol | undefined, minimo: Rol): boolean =>
  (rol ? RANGO[rol] : 0) >= RANGO[minimo];

export function RutaProtegida() {
  const { sesion, perfil, cargando, noAutorizado } = useAuth();
  if (cargando) return <div style={{ padding: 24 }}>Cargando…</div>;
  if (noAutorizado)
    return (
      <div style={{ padding: 24 }}>
        Tu cuenta no está autorizada. Contacta al administrador.
      </div>
    );
  if (!sesion || !perfil) return <Navigate to="/login" replace />;
  return <Outlet />;
}

export function RequiereRol({ minimo }: { minimo: Rol }) {
  const { perfil } = useAuth();
  if (!puede(perfil?.rol, minimo))
    return <div style={{ padding: 24 }}>No tienes permiso para ver esta sección.</div>;
  return <Outlet />;
}
