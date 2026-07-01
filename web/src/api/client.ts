import { supabase } from "@/lib/supabase";

const BASE = "/api";

export async function authHeader(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function manejar(r: Response): Promise<Response> {
  if (r.status === 401) {
    await supabase.auth.signOut(); // sesión inválida -> redirección reactiva a /login
    throw new Error("Sesión expirada.");
  }
  if (!r.ok) throw new Error((await r.json().catch(() => ({})))?.detail || r.statusText);
  return r;
}

export async function apiGet<T>(path: string): Promise<T> {
  const r = await fetch(BASE + path, { headers: { ...(await authHeader()) } });
  return (await manejar(r)).json() as Promise<T>;
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const esForm = body instanceof FormData;
  const r = await fetch(BASE + path, {
    method: "POST",
    headers: {
      ...(await authHeader()),
      ...(esForm ? {} : { "Content-Type": "application/json" }),
    },
    body: esForm ? body : JSON.stringify(body ?? {}),
  });
  return (await manejar(r)).json() as Promise<T>;
}

export async function apiDelete(path: string): Promise<void> {
  const r = await fetch(BASE + path, { method: "DELETE", headers: { ...(await authHeader()) } });
  await manejar(r);
  const text = await r.text().catch(() => "");
  if (text) {
    try { JSON.parse(text); } catch { /* ignora cuerpo no-JSON */ }
  }
}
