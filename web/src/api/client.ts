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

export async function apiPatch<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(BASE + path, {
    method: "PATCH",
    headers: { ...(await authHeader()), "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
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

/** Descarga un archivo protegido con el token Bearer (una navegación normal no lleva el header). */
export async function descargarArchivo(path: string, filename: string): Promise<void> {
  const r = await fetch(BASE + path, { headers: { ...(await authHeader()) } });
  if (r.status === 401) {
    await supabase.auth.signOut();
    throw new Error("Sesión expirada.");
  }
  if (!r.ok) {
    const err = await r.json().catch(() => ({}) as { detail?: string });
    throw new Error(err.detail || r.statusText);
  }
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
