import { createClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL as string;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string;

if (!url || !anonKey) {
  // Falla temprano y claro en dev/build si faltan las envs.
  console.error("Faltan VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY");
}

// La anon key es PÚBLICA por diseño (segura en el navegador). La service_role NUNCA va aquí.
export const supabase = createClient(url, anonKey, {
  auth: { persistSession: true, autoRefreshToken: true },
});
