import { supabase } from "@/lib/supabase";

const BASE = "/api";

export async function authHeader(): Promise<Record<string, string>> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** Texto de error de la API. `detail` es normalmente un string, pero algunos
 *  endpoints devuelven un objeto con datos que la interfaz necesita (p. ej. los
 *  `seqs` de las filas sin APU); de ahí sale el `mensaje`. */
export function mensajeDeError(cuerpo: unknown, respaldo: string): string {
  const d = (cuerpo as { detail?: unknown } | null)?.detail;
  if (typeof d === "string" && d) return d;
  // 422 de FastAPI: detail es un array de errores de validación de Pydantic
  // (`[{loc, msg, type}, ...]`). Antes caía al respaldo y mostraba "Unprocessable
  // Content" en vez del motivo real.
  if (Array.isArray(d)) {
    const msgs = d.map((x) => (x as { msg?: string })?.msg).filter(Boolean);
    if (msgs.length) return msgs.join("; ");
  }
  if (d && typeof d === "object") {
    const m = (d as { mensaje?: unknown }).mensaje;
    if (typeof m === "string" && m) return m;
  }
  return respaldo;
}

/** Error de la API que además conserva el `detail` crudo y el status.
 *
 *  `message` es el de siempre, así que quien solo hace `e instanceof Error ? e.message`
 *  no cambia. Lo que se gana es el `detail` estructurado: los endpoints que devuelven
 *  un objeto (el 409 de las filas sin APU con sus `seqs`, el del armado duplicado con
 *  su `corrida_id`) traen ahí datos que la interfaz necesita para ACTUAR — navegar a la
 *  corrida que ya existe— y que el mensaje solo tiene en prosa. Sacarlos de la prosa a
 *  punta de regex sería peor. */
export class ErrorApi extends Error {
  status: number;
  detail: unknown;
  constructor(mensaje: string, status: number, detail: unknown) {
    super(mensaje);
    this.name = "ErrorApi";
    this.status = status;
    this.detail = detail;
  }
}

async function manejar(r: Response): Promise<Response> {
  if (r.status === 401) {
    await supabase.auth.signOut(); // sesión inválida -> redirección reactiva a /login
    throw new Error("Sesión expirada.");
  }
  if (!r.ok) {
    const cuerpo = await r.json().catch(() => null);
    throw new ErrorApi(
      mensajeDeError(cuerpo, r.statusText),
      r.status,
      (cuerpo as { detail?: unknown } | null)?.detail,
    );
  }
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

export async function apiPut<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(BASE + path, {
    method: "PUT",
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
  if (!r.ok) throw new Error(mensajeDeError(await r.json().catch(() => null), r.statusText));
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
