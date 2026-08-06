import { authHeader } from "./client";
import type { PresenciaResponse } from "@/lib/tipos";

/** Quién está usando la app ahora. Pedirla también te marca presente (el latido es
 *  este mismo poll, ver apu_tool/servicio/presencia.py).
 *
 *  A propósito NO usa `apiGet`: ese helper hace `signOut()` ante CUALQUIER 401 (ver
 *  client.ts), y este es el único poll siempre-activo de la app — cada 45 s, sin
 *  ninguna acción del usuario. `auth.py` convierte en 401 cualquier excepción al
 *  resolver la llave del JWKS, incluida una falla de red transitoria Render→Supabase;
 *  con `apiGet` un 401 de ese tipo desloguearía a alguien que solo estaba leyendo una
 *  pantalla. Si el pedido falla, "no sabemos quién hay": se lanza un error simple que
 *  el `.catch()` de quien llama (Layout.tsx) ya absorbe en silencio, sin tocar la sesión.
 */
export async function getPresencia(): Promise<PresenciaResponse> {
  const r = await fetch("/api/presencia", { headers: { ...(await authHeader()) } });
  if (!r.ok) throw new Error("No se pudo leer presencia.");
  return r.json() as Promise<PresenciaResponse>;
}
