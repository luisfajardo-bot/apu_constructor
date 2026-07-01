# Plan 2b — Auth + RBAC (frontend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Para las tareas de UI (Login, DefinirClave, Usuarios, menú del Layout) el implementador DEBE usar la skill **frontend-design** para el acabado visual, manteniendo la preferencia densa/table-first.

**Goal:** Hacer la app usable end-to-end con login: sesión Supabase en el frontend, Bearer en cada request, gateo de UI por rol, página de contraseña (fijar/restablecer) y pantalla de gestión de usuarios (Admin).

**Architecture:** Enfoque A — un `AuthProvider` (context React) inicializa el cliente Supabase, mantiene `{sesion, perfil, cargando}` (perfil = `{email, rol, nombre}` desde `GET /api/yo`), y expone `login`/`logout`. `client.ts` adjunta `Authorization: Bearer` (token de `supabase.auth.getSession()`) en cada request y en los streams SSE; ante `401` hace `signOut` (redirección reactiva a `/login`). Rutas y acciones se gatean por rol con `<RutaProtegida>`/`<RequiereRol>`.

**Tech Stack:** React 19, react-router-dom 7, @supabase/supabase-js (nuevo), radix-ui, sonner, tailwind, vitest (jsdom, globals). Backend: FastAPI (única adición `GET /api/yo`).

## Global Constraints

- **Invariante #1:** el frontend nunca ve dinero de la IA; no toca `dominio/privacy.py`/`ai_assist.py`. (No aplica directo, pero no introducir llamadas que la violen.)
- **Español** en nombres de dominio, UI y comentarios.
- **La anon key es pública por diseño** (segura en el navegador); la `service_role` **jamás** va al frontend.
- **No romper:** los 202 tests backend + los vitest existentes (`corridas.sse`, `tiempo`, `useDirtyRows`, `validacionApu`) siguen verdes. Backend solo gana `GET /api/yo`.
- **Gateo de UI = solo UX**; la barrera real es `requiere_rol` en el backend.
- **Pruebas vitest SIN red:** mock de `@supabase/supabase-js` y de `fetch`. Comando frontend (dentro de `web/`): `npm test` (vitest run) y `npm run build`. Backend: `python -m pytest`.
- **Jerarquía de roles:** `consulta<editor<admin` (igual que el backend).
- **Config (no código):** Supabase debe tener `<app>/definir-clave` en el allowlist de redirect URLs (para invitación/reset). Anotarlo, no es tarea de código.
- **Disciplina de commit:** `git add` SOLO los archivos de cada tarea (NUNCA `-A`/`.`/`-u`); hay cruft ignorado (node_modules raíz, `.env`, `ejemplos/*.xlsx`). Verificar `git status` antes de commitear.
- TDD, commits frecuentes. Rama: `feat/auth-frontend`.

---

### Task 1: Backend — endpoint `GET /api/yo`

**Files:**
- Modify: `apu_tool/servicio/rutas.py`
- Test: `tests/test_api_yo.py`

**Interfaces:**
- Consumes: `usuario_actual`/`requiere_rol` (Plan 2a, `apu_tool/servicio/auth.py`), `tests.conftest.cliente`.
- Produces: `GET /api/yo` → `{"email": str, "rol": str, "nombre": str}` del usuario autenticado (cualquier rol).

- [ ] **Step 1: Escribir el test (falla)**

Create `tests/test_api_yo.py`:
```python
from apu_tool.datos.almacen import Almacen
from apu_tool.servicio.app import create_app
from apu_tool.servicio.auth import usuario_actual
from apu_tool.nucleo.models import Perfil
from fastapi.testclient import TestClient


def _app(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return create_app(almacen=alm)


def test_yo_devuelve_perfil_del_usuario(tmp_path):
    app = _app(tmp_path)
    app.dependency_overrides[usuario_actual] = lambda: Perfil(
        user_id="u1", email="ana@obra.co", rol="editor", estado="activo", nombre="Ana")
    cli = TestClient(app)
    r = cli.get("/api/yo")
    assert r.status_code == 200
    assert r.json() == {"email": "ana@obra.co", "rol": "editor", "nombre": "Ana"}


def test_yo_sin_token_da_401(tmp_path):
    cli = TestClient(_app(tmp_path))
    assert cli.get("/api/yo").status_code == 401
```

- [ ] **Step 2: Verificar que falla**

Run: `python -m pytest tests/test_api_yo.py -v`
Expected: FAIL (404/ruta inexistente).

- [ ] **Step 3: Implementar la ruta**

En `apu_tool/servicio/rutas.py`, añadir (junto a los otros endpoints; `requiere_rol` y `Perfil` ya se importan/está disponible — si `Perfil` no está importado, usar el tipo devuelto por la dependencia sin anotarlo):
```python
@router.get("/yo")
def yo(usuario=Depends(requiere_rol("consulta"))):
    return {"email": usuario.email, "rol": usuario.rol, "nombre": usuario.nombre}
```

- [ ] **Step 4: Verificar que pasa + no-regresión**

Run: `python -m pytest tests/test_api_yo.py -v`
Expected: PASS (2 tests).
Run: `python -m pytest tests/ -q`
Expected: 204+ passed (202 + 2), 4 skipped.

- [ ] **Step 5: Commit**
```bash
git add apu_tool/servicio/rutas.py tests/test_api_yo.py
git commit -m "feat(api): endpoint GET /api/yo (perfil del usuario actual)"
```

---

### Task 2: Dependencia supabase-js + cliente + envs

**Files:**
- Modify: `web/package.json` (dependencia)
- Create: `web/src/lib/supabase.ts`
- Create: `web/.env.example`
- Test: `web/src/lib/supabase.test.ts`

**Interfaces:**
- Produces: `supabase` (cliente `SupabaseClient`) exportado desde `web/src/lib/supabase.ts`.

- [ ] **Step 1: Añadir la dependencia**

En `web/`, instalar (con versión fijada y lockfile):
Run (dentro de `web/`): `npm install @supabase/supabase-js@^2`
Expected: añade `@supabase/supabase-js` a `web/package.json` dependencies y a `web/package-lock.json`.

- [ ] **Step 2: Escribir el test (falla)**

Create `web/src/lib/supabase.test.ts`:
```ts
import { beforeAll, expect, test, vi } from "vitest";

beforeAll(() => {
  vi.stubEnv("VITE_SUPABASE_URL", "https://proj.supabase.co");
  vi.stubEnv("VITE_SUPABASE_ANON_KEY", "anon-key-test");
});

test("exporta un cliente supabase con auth", async () => {
  const { supabase } = await import("./supabase");
  expect(supabase).toBeDefined();
  expect(typeof supabase.auth.getSession).toBe("function");
});
```

- [ ] **Step 3: Verificar que falla**

Run (dentro de `web/`): `npx vitest run src/lib/supabase.test.ts`
Expected: FAIL (`./supabase` no existe).

- [ ] **Step 4: Implementar `web/src/lib/supabase.ts`**

```ts
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
```

- [ ] **Step 5: Crear `web/.env.example`**

```
# Copia a web/.env (ignorado por git) y rellena con tu proyecto Supabase.
# La anon key es PÚBLICA por diseño (segura en el navegador).
VITE_SUPABASE_URL=https://TU-REF.supabase.co
VITE_SUPABASE_ANON_KEY=tu-anon-o-publishable-key
```

- [ ] **Step 6: Verificar que pasa**

Run (dentro de `web/`): `npx vitest run src/lib/supabase.test.ts`
Expected: PASS.

- [ ] **Step 7: Commit**
```bash
git add web/package.json web/package-lock.json web/src/lib/supabase.ts web/.env.example web/src/lib/supabase.test.ts
git commit -m "feat(web): dependencia supabase-js + cliente + .env.example"
```

---

### Task 3: `client.ts` con Bearer + 401 + streams SSE

**Files:**
- Modify: `web/src/api/client.ts`
- Modify: `web/src/api/corridas.ts` (streams SSE)
- Test: `web/src/api/client.test.ts`

**Interfaces:**
- Consumes: `supabase` (Task 2).
- Produces:
  - `authHeader(): Promise<Record<string, string>>` — `{ Authorization: "Bearer <token>" }` o `{}` si no hay sesión.
  - `apiGet`/`apiPost`/`apiDelete` inalterados en firma, pero ahora envían el Bearer y, ante `401`, llaman `supabase.auth.signOut()` y lanzan error.

- [ ] **Step 1: Escribir el test (falla)**

Create `web/src/api/client.test.ts`:
```ts
import { afterEach, expect, test, vi } from "vitest";

vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: vi.fn(async () => ({ data: { session: { access_token: "TOK" } } })),
      signOut: vi.fn(async () => ({})),
    },
  },
}));

afterEach(() => vi.restoreAllMocks());

test("apiGet adjunta el Bearer del token de sesión", async () => {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify({ ok: 1 }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  const { apiGet } = await import("./client");
  await apiGet("/status");
  const [, init] = fetchMock.mock.calls[0];
  expect((init.headers as Record<string, string>).Authorization).toBe("Bearer TOK");
});

test("401 dispara signOut y lanza", async () => {
  const { supabase } = await import("@/lib/supabase");
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 401 })));
  const { apiGet } = await import("./client");
  await expect(apiGet("/status")).rejects.toThrow();
  expect(supabase.auth.signOut).toHaveBeenCalled();
});
```

- [ ] **Step 2: Verificar que falla**

Run (dentro de `web/`): `npx vitest run src/api/client.test.ts`
Expected: FAIL (Authorization no presente / signOut no llamado).

- [ ] **Step 3: Reescribir `web/src/api/client.ts`**

```ts
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
```

- [ ] **Step 4: Añadir el Bearer a los streams SSE en `corridas.ts`**

En `web/src/api/corridas.ts`, importar `authHeader` y usarlo en `streamCorrida`. Cambiar la firma de `streamCorrida` para inyectar el header en `init`:
```ts
import { apiGet, apiPost, apiDelete, authHeader } from "@/api/client";
```
Y dentro de `streamCorrida`, antes del `fetch`, fusionar el header de auth y manejar el 401:
```ts
async function streamCorrida(
  path: string,
  init: RequestInit,
  onProgress: (p: Progreso) => void,
  onStarted?: (c: CorridaIniciada) => void,
): Promise<CorridaCreada> {
  const r = await fetch("/api" + path, {
    ...init,
    headers: { ...(init.headers || {}), ...(await authHeader()) },
  });
  if (r.status === 401) {
    const { supabase } = await import("@/lib/supabase");
    await supabase.auth.signOut();
    throw new Error("Sesión expirada.");
  }
  if (!r.ok || !r.body) {
    const err = await r.json().catch(() => ({}) as { detail?: string });
    throw new Error(err.detail || r.statusText);
  }
  // ... resto del cuerpo SIN CAMBIOS (reader/decoder/bucle de eventos) ...
```
(El resto de `streamCorrida` y las funciones `crearCorridaStream`/`crearSampleStream` no cambian.)

- [ ] **Step 5: Verificar que pasa + no-regresión**

Run (dentro de `web/`): `npx vitest run src/api/client.test.ts`
Expected: PASS (2 tests).
Run (dentro de `web/`): `npm test`
Expected: todos verdes (los vitest existentes + los nuevos).

- [ ] **Step 6: Commit**
```bash
git add web/src/api/client.ts web/src/api/corridas.ts web/src/api/client.test.ts
git commit -m "feat(web): Bearer en client.ts y streams SSE + signOut ante 401"
```

---

### Task 4: `api/usuarios.ts` + `AuthProvider`

**Files:**
- Create: `web/src/api/usuarios.ts`
- Create: `web/src/lib/auth.tsx`
- Test: `web/src/lib/auth.test.tsx`

**Interfaces:**
- Consumes: `apiGet`/`apiPost` (Task 3), `supabase` (Task 2).
- Produces:
  - Tipos `Yo = { email: string; rol: Rol; nombre: string }`, `Rol = "admin" | "editor" | "consulta"`, `Usuario = { user_id: string; email: string; rol: Rol; estado: "activo" | "inactivo"; nombre: string }`.
  - `getYo()`, `listarUsuarios()`, `invitarUsuario(email, rol, nombre)`, `cambiarRol(userId, rol)`, `cambiarEstado(userId, estado)`.
  - `AuthProvider` (componente) + `useAuth() -> { sesion, perfil: Yo|null, cargando, noAutorizado: boolean, login(email,pw), logout() }`.

- [ ] **Step 1: Escribir `web/src/api/usuarios.ts`**

```ts
import { apiGet, apiPost } from "@/api/client";

export type Rol = "admin" | "editor" | "consulta";
export type Yo = { email: string; rol: Rol; nombre: string };
export type Usuario = {
  user_id: string; email: string; rol: Rol; estado: "activo" | "inactivo"; nombre: string;
};

export const getYo = () => apiGet<Yo>("/yo");
export const listarUsuarios = () => apiGet<Usuario[]>("/usuarios");
export const invitarUsuario = (email: string, rol: Rol, nombre: string) =>
  apiPost<{ user_id: string }>("/usuarios/invitar", { email, rol, nombre });
export const cambiarRol = (userId: string, rol: Rol) =>
  apiPost(`/usuarios/${userId}/rol`, { rol }); // ver nota
export const cambiarEstado = (userId: string, estado: "activo" | "inactivo") =>
  apiPost(`/usuarios/${userId}/estado`, { estado }); // ver nota
```
NOTA: los endpoints de cambiar rol/estado son `PATCH` en el backend. `client.ts` no tiene `apiPatch`. En este mismo paso, AÑADIR a `web/src/api/client.ts` una función `apiPatch<T>(path, body)` idéntica a `apiPost` pero con `method: "PATCH"`, y usarla aquí (`import { apiGet, apiPatch, apiPost }`). Reemplazar los dos `apiPost(\`/usuarios/...\`)` por `apiPatch(...)`.

- [ ] **Step 2: Escribir el test del AuthProvider (falla)**

Create `web/src/lib/auth.test.tsx`:
```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

const authMocks = {
  onAuthStateChange: vi.fn((cb: (e: string, s: unknown) => void) => {
    cb("SIGNED_IN", { access_token: "TOK", user: { email: "ana@obra.co" } });
    return { data: { subscription: { unsubscribe: vi.fn() } } };
  }),
  getSession: vi.fn(async () => ({ data: { session: { access_token: "TOK" } } })),
  signOut: vi.fn(async () => ({})),
};
vi.mock("@/lib/supabase", () => ({ supabase: { auth: authMocks } }));
vi.mock("@/api/usuarios", () => ({
  getYo: vi.fn(async () => ({ email: "ana@obra.co", rol: "editor", nombre: "Ana" })),
}));

afterEach(() => vi.clearAllMocks());

function Sonda() {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const { useAuth } = require("./auth");
  const { perfil, cargando } = useAuth();
  return <div>{cargando ? "cargando" : perfil ? `rol:${perfil.rol}` : "anon"}</div>;
}

test("carga el perfil desde /api/yo tras SIGNED_IN", async () => {
  const { AuthProvider } = await import("./auth");
  render(<AuthProvider><Sonda /></AuthProvider>);
  await waitFor(() => expect(screen.getByText("rol:editor")).toBeInTheDocument());
});
```
(Si `require` en el componente Sonda da problemas con TS/ESM, importar `useAuth` normal al tope del test junto a `AuthProvider`.)

- [ ] **Step 3: Verificar que falla**

Run (dentro de `web/`): `npx vitest run src/lib/auth.test.tsx`
Expected: FAIL (`./auth` no existe).

- [ ] **Step 4: Implementar `web/src/lib/auth.tsx`**

```tsx
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
```

- [ ] **Step 5: Verificar que pasa**

Run (dentro de `web/`): `npx vitest run src/lib/auth.test.tsx src/api/client.test.ts`
Expected: PASS.

- [ ] **Step 6: Commit**
```bash
git add web/src/api/usuarios.ts web/src/api/client.ts web/src/lib/auth.tsx web/src/lib/auth.test.tsx
git commit -m "feat(web): api/usuarios + AuthProvider (sesión + perfil desde /api/yo)"
```

---

### Task 5: Rutas protegidas por rol (`RutaProtegida`, `RequiereRol`)

**Files:**
- Create: `web/src/components/rutas.tsx`
- Test: `web/src/components/rutas.test.tsx`

**Interfaces:**
- Consumes: `useAuth` (Task 4), react-router `Navigate`/`Outlet`.
- Produces: `<RutaProtegida>` (envuelve rutas privadas), `<RequiereRol minimo>` (gatea por rol), y `RANGO = { consulta:1, editor:2, admin:3 }`, y `puede(rol, minimo): boolean`.

- [ ] **Step 1: Escribir el test (falla)**

Create `web/src/components/rutas.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { expect, test, vi } from "vitest";

let mockAuth: { sesion: unknown; perfil: unknown; cargando: boolean; noAutorizado: boolean };
vi.mock("@/lib/auth", () => ({ useAuth: () => mockAuth }));

function montar(inicial = "/priv") {
  return render(
    <MemoryRouter initialEntries={[inicial]}>
      <Routes>
        <Route path="/login" element={<div>LOGIN</div>} />
        {/* @ts-expect-error import dinámico en test */}
        <Route element={require("./rutas").RutaProtegida()}>
          <Route path="/priv" element={<div>PRIVADO</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

test("sin sesión redirige a /login", async () => {
  const { RutaProtegida } = await import("./rutas");
  mockAuth = { sesion: null, perfil: null, cargando: false, noAutorizado: false };
  render(
    <MemoryRouter initialEntries={["/priv"]}>
      <Routes>
        <Route path="/login" element={<div>LOGIN</div>} />
        <Route element={<RutaProtegida />}>
          <Route path="/priv" element={<div>PRIVADO</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
  expect(screen.getByText("LOGIN")).toBeInTheDocument();
});

test("con perfil muestra el contenido privado", async () => {
  const { RutaProtegida } = await import("./rutas");
  mockAuth = { sesion: {}, perfil: { rol: "consulta" }, cargando: false, noAutorizado: false };
  render(
    <MemoryRouter initialEntries={["/priv"]}>
      <Routes>
        <Route element={<RutaProtegida />}>
          <Route path="/priv" element={<div>PRIVADO</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
  expect(screen.getByText("PRIVADO")).toBeInTheDocument();
});

test("puede() respeta la jerarquía", async () => {
  const { puede } = await import("./rutas");
  expect(puede("admin", "editor")).toBe(true);
  expect(puede("consulta", "editor")).toBe(false);
});
```
(Quitar el helper `montar`/bloque `@ts-expect-error` si no se usa; los tests reales usan `<RutaProtegida />` directo como arriba.)

- [ ] **Step 2: Verificar que falla**

Run (dentro de `web/`): `npx vitest run src/components/rutas.test.tsx`
Expected: FAIL (`./rutas` no existe).

- [ ] **Step 3: Implementar `web/src/components/rutas.tsx`**

```tsx
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
```

- [ ] **Step 4: Verificar que pasa**

Run (dentro de `web/`): `npx vitest run src/components/rutas.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**
```bash
git add web/src/components/rutas.tsx web/src/components/rutas.test.tsx
git commit -m "feat(web): RutaProtegida + RequiereRol (gateo por rol)"
```

---

### Task 6: Login + DefinirClave + wiring de rutas públicas

**Files:**
- Create: `web/src/pages/Login.tsx`
- Create: `web/src/pages/DefinirClave.tsx`
- Modify: `web/src/main.tsx` (envolver en `AuthProvider`)
- Modify: `web/src/App.tsx` (rutas públicas + RutaProtegida)
- Test: `web/src/pages/Login.test.tsx`

**Interfaces:**
- Consumes: `useAuth` (Task 4), `supabase` (Task 2), `RutaProtegida` (Task 5).

**UI: usar la skill frontend-design para el acabado de Login y DefinirClave (formularios centrados, pulidos, densos, coherentes con la marca).**

- [ ] **Step 1: Escribir el test de Login (falla)**

Create `web/src/pages/Login.test.tsx`:
```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test, vi } from "vitest";

const login = vi.fn(async () => {});
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ login, perfil: null, sesion: null }) }));
vi.mock("@/lib/supabase", () => ({ supabase: { auth: { resetPasswordForEmail: vi.fn() } } }));

test("envía email+password a login()", async () => {
  const { default: Login } = await import("./Login");
  render(<MemoryRouter><Login /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText(/correo/i), { target: { value: "ana@obra.co" } });
  fireEvent.change(screen.getByLabelText(/contraseña/i), { target: { value: "secreta" } });
  fireEvent.click(screen.getByRole("button", { name: /ingresar/i }));
  await waitFor(() => expect(login).toHaveBeenCalledWith("ana@obra.co", "secreta"));
});
```

- [ ] **Step 2: Verificar que falla**

Run (dentro de `web/`): `npx vitest run src/pages/Login.test.tsx`
Expected: FAIL (`./Login` no existe).

- [ ] **Step 3: Implementar `web/src/pages/Login.tsx`**

```tsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useAuth } from "@/lib/auth";
import { supabase } from "@/lib/supabase";

export default function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [enviando, setEnviando] = useState(false);

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
    <form onSubmit={onSubmit} style={{ maxWidth: 320, margin: "10vh auto", display: "grid", gap: 10 }}>
      <h1 style={{ fontSize: 18 }}>Armador de APUs</h1>
      <label>Correo<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
      <label>Contraseña<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
      <button type="submit" disabled={enviando}>{enviando ? "Ingresando…" : "Ingresar"}</button>
      <button type="button" onClick={olvide} style={{ background: "none", border: "none", color: "#4a90d9", cursor: "pointer" }}>
        ¿Olvidaste tu contraseña?
      </button>
    </form>
  );
}
```

- [ ] **Step 4: Implementar `web/src/pages/DefinirClave.tsx`**

```tsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { supabase } from "@/lib/supabase";

// supabase-js detecta el token (invite/recovery) del hash de la URL y crea sesión temporal al cargar.
export default function DefinirClave() {
  const nav = useNavigate();
  const [password, setPassword] = useState("");
  const [enviando, setEnviando] = useState(false);

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
    <form onSubmit={onSubmit} style={{ maxWidth: 320, margin: "10vh auto", display: "grid", gap: 10 }}>
      <h1 style={{ fontSize: 18 }}>Definir contraseña</h1>
      <label>Nueva contraseña
        <input type="password" value={password} minLength={8}
               onChange={(e) => setPassword(e.target.value)} required />
      </label>
      <button type="submit" disabled={enviando}>{enviando ? "Guardando…" : "Guardar"}</button>
    </form>
  );
}
```

- [ ] **Step 5: Envolver en `AuthProvider` (`main.tsx`)**

Reescribir `web/src/main.tsx`:
```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { AuthProvider } from "@/lib/auth";
import "./index.css";
import App from "./App.tsx";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
```

- [ ] **Step 6: Rutas públicas + protección en `App.tsx`**

Reescribir `web/src/App.tsx`:
```tsx
import { Routes, Route, Navigate } from "react-router-dom";
import Layout from "@/components/Layout";
import { RutaProtegida, RequiereRol } from "@/components/rutas";
import Login from "@/pages/Login";
import DefinirClave from "@/pages/DefinirClave";
import MisCorridas from "@/pages/MisCorridas";
import CorridasInicio from "@/pages/CorridasInicio";
import Corrida from "@/pages/Corrida";
import Insumos from "@/pages/Insumos";
import Apus from "@/pages/Apus";
import Usuarios from "@/pages/Usuarios";
import { ArmadoVivoProvider } from "@/lib/armado";

export default function App() {
  return (
    <ArmadoVivoProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/definir-clave" element={<DefinirClave />} />
        <Route element={<RutaProtegida />}>
          <Route element={<Layout />}>
            <Route index element={<Navigate to="/corridas" replace />} />
            <Route path="corridas" element={<MisCorridas />} />
            <Route path="corridas/nueva" element={<CorridasInicio />} />
            <Route path="corridas/:id" element={<Corrida />} />
            <Route path="insumos" element={<Insumos />} />
            <Route path="apus" element={<Apus />} />
            <Route element={<RequiereRol minimo="admin" />}>
              <Route path="usuarios" element={<Usuarios />} />
            </Route>
          </Route>
        </Route>
      </Routes>
    </ArmadoVivoProvider>
  );
}
```
NOTA: `Usuarios` se crea en Task 8. Para que `App.tsx` compile en esta tarea, crear un stub temporal `web/src/pages/Usuarios.tsx` con `export default function Usuarios(){ return null; }` — Task 8 lo reemplaza por la pantalla real. (Alternativa: hacer Task 8 antes de cablear su ruta; pero mantener el orden y usar el stub es más simple.)

- [ ] **Step 7: Verificar que pasa + build**

Run (dentro de `web/`): `npx vitest run src/pages/Login.test.tsx`
Expected: PASS.
Run (dentro de `web/`): `npm test` y luego `npm run build`
Expected: vitest verde; build OK (TS compila con las nuevas rutas y el stub de Usuarios).

- [ ] **Step 8: Commit**
```bash
git add web/src/pages/Login.tsx web/src/pages/DefinirClave.tsx web/src/pages/Usuarios.tsx web/src/main.tsx web/src/App.tsx web/src/pages/Login.test.tsx
git commit -m "feat(web): login + definir/restablecer contraseña + rutas protegidas"
```

---

### Task 7: Layout (menú usuario + nav Admin) + gateo de acciones en Insumos/APUs

**Files:**
- Modify: `web/src/components/Layout.tsx`
- Modify: `web/src/pages/Insumos.tsx`
- Modify: `web/src/pages/Apus.tsx`
- Test: `web/src/components/Layout.test.tsx`

**Interfaces:**
- Consumes: `useAuth` (Task 4), `puede` (Task 5).

**UI: usar frontend-design para el menú de usuario en la topbar (email, rol, logout) coherente con el estilo actual.**

- [ ] **Step 1: Escribir el test del Layout (falla)**

Create `web/src/components/Layout.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test, vi } from "vitest";

vi.mock("@/api/corridas", () => ({ getStatus: vi.fn(async () => ({ insumos: 0, apus: 0, ia: false })) }));
let rol = "consulta";
vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ perfil: { email: "a@obra.co", rol }, logout: vi.fn() }),
}));

test("el link Usuarios solo aparece para Admin", async () => {
  const { default: Layout } = await import("./Layout");
  rol = "editor";
  const { unmount } = render(<MemoryRouter><Layout /></MemoryRouter>);
  expect(screen.queryByText("Usuarios")).toBeNull();
  unmount();
  rol = "admin";
  render(<MemoryRouter><Layout /></MemoryRouter>);
  expect(screen.getByText("Usuarios")).toBeInTheDocument();
});
```

- [ ] **Step 2: Verificar que falla**

Run (dentro de `web/`): `npx vitest run src/components/Layout.test.tsx`
Expected: FAIL (no hay lógica de rol en Layout todavía).

- [ ] **Step 3: Modificar `Layout.tsx`**

En `web/src/components/Layout.tsx`: importar `useAuth` y `puede`; leer `const { perfil, logout } = useAuth();`. En `NAV_LINKS`, dejar los fijos (Corridas/Insumos/APUs) y añadir "Usuarios" **condicionalmente** solo si `puede(perfil?.rol, "admin")`:
```tsx
import { useAuth } from "@/lib/auth";
import { puede } from "@/components/rutas";
// ...dentro del componente:
const { perfil, logout } = useAuth();
const links = [
  { to: "/corridas", label: "Corridas", end: false },
  { to: "/insumos", label: "Insumos", end: true },
  { to: "/apus", label: "APUs", end: true },
  ...(puede(perfil?.rol, "admin") ? [{ to: "/usuarios", label: "Usuarios", end: true }] : []),
];
```
Usar `links` en vez de `NAV_LINKS` en el `.map`. En la topbar (junto al chip), añadir el email + rol + un botón "Cerrar sesión" que llama `logout()`:
```tsx
<span style={styles.chip}>{perfil ? `${perfil.email} · ${perfil.rol}` : ""}</span>
<button onClick={() => logout()} style={{ marginLeft: 8, ...(styles.chip as object) }}>Cerrar sesión</button>
```
(Ajustar estilos con frontend-design; mantener denso.)

- [ ] **Step 4: Gatear acciones de edición en Insumos/APUs**

En `web/src/pages/Insumos.tsx` y `web/src/pages/Apus.tsx`: importar `useAuth` + `puede`; obtener `const { perfil } = useAuth();` y `const puedeEditar = puede(perfil?.rol, "editor");`. Envolver los controles de EDICIÓN (botones/diálogos de crear, importar, transformar, y la edición inline/guardar) para que solo se rendericen/activen si `puedeEditar`. Las vistas de solo-lectura (tabla, filtros, búsqueda) quedan siempre visibles. Leer cada archivo primero e identificar los puntos de mutación (botones que llaman a `aplicarCambios`/`crear`/`importar`/`transformar`); condicionarlos con `{puedeEditar && ( ... )}` o `disabled={!puedeEditar}`.

- [ ] **Step 5: Verificar que pasa + build**

Run (dentro de `web/`): `npx vitest run src/components/Layout.test.tsx`
Expected: PASS.
Run (dentro de `web/`): `npm test` y `npm run build`
Expected: vitest verde; build OK.

- [ ] **Step 6: Commit**
```bash
git add web/src/components/Layout.tsx web/src/pages/Insumos.tsx web/src/pages/Apus.tsx web/src/components/Layout.test.tsx
git commit -m "feat(web): menú de usuario + nav Usuarios (Admin) + gateo de edición por rol"
```

---

### Task 8: Pantalla de usuarios (Admin)

**Files:**
- Modify: `web/src/pages/Usuarios.tsx` (reemplaza el stub de Task 6)
- Test: `web/src/pages/Usuarios.test.tsx`

**Interfaces:**
- Consumes: `listarUsuarios`/`invitarUsuario`/`cambiarRol`/`cambiarEstado` (Task 4).

**UI: usar frontend-design para la tabla densa + diálogo de invitación (radix), coherente con la preferencia table-first.**

- [ ] **Step 1: Escribir el test (falla)**

Create `web/src/pages/Usuarios.test.tsx`:
```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";

vi.mock("@/api/usuarios", () => ({
  listarUsuarios: vi.fn(async () => [
    { user_id: "u1", email: "a@obra.co", rol: "editor", estado: "activo", nombre: "Ana" },
  ]),
  invitarUsuario: vi.fn(async () => ({ user_id: "u2" })),
  cambiarRol: vi.fn(async () => ({})),
  cambiarEstado: vi.fn(async () => ({})),
}));

test("lista los usuarios existentes", async () => {
  const { default: Usuarios } = await import("./Usuarios");
  render(<Usuarios />);
  await waitFor(() => expect(screen.getByText("a@obra.co")).toBeInTheDocument());
  expect(screen.getByText("editor")).toBeInTheDocument();
});
```

- [ ] **Step 2: Verificar que falla**

Run (dentro de `web/`): `npx vitest run src/pages/Usuarios.test.tsx`
Expected: FAIL (el stub no lista nada).

- [ ] **Step 3: Implementar `web/src/pages/Usuarios.tsx`**

Reemplazar el stub con la pantalla real: tabla densa de usuarios + acción invitar + acciones por fila. Estructura funcional mínima (frontend-design pule el estilo/diálogo radix):
```tsx
import { useEffect, useState } from "react";
import { toast } from "sonner";
import {
  listarUsuarios, invitarUsuario, cambiarRol, cambiarEstado,
  type Usuario, type Rol,
} from "@/api/usuarios";

const ROLES: Rol[] = ["consulta", "editor", "admin"];

export default function Usuarios() {
  const [usuarios, setUsuarios] = useState<Usuario[]>([]);
  const [email, setEmail] = useState("");
  const [rol, setRol] = useState<Rol>("consulta");
  const [nombre, setNombre] = useState("");

  const cargar = () => listarUsuarios().then(setUsuarios).catch((e) => toast.error(e.message));
  useEffect(() => { cargar(); }, []);

  async function invitar(e: React.FormEvent) {
    e.preventDefault();
    try {
      await invitarUsuario(email, rol, nombre);
      toast.success("Invitación enviada.");
      setEmail(""); setNombre(""); setRol("consulta");
      cargar();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "No se pudo invitar.");
    }
  }

  async function setRolDe(u: Usuario, nuevo: Rol) {
    try { await cambiarRol(u.user_id, nuevo); cargar(); }
    catch (err) { toast.error(err instanceof Error ? err.message : "Error."); }
  }
  async function setEstadoDe(u: Usuario, estado: "activo" | "inactivo") {
    try { await cambiarEstado(u.user_id, estado); cargar(); }
    catch (err) { toast.error(err instanceof Error ? err.message : "Error."); }
  }

  return (
    <div style={{ padding: 16 }}>
      <h1 style={{ fontSize: 16 }}>Usuarios</h1>
      <form onSubmit={invitar} style={{ display: "flex", gap: 8, margin: "8px 0", flexWrap: "wrap" }}>
        <input placeholder="correo" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <input placeholder="nombre" value={nombre} onChange={(e) => setNombre(e.target.value)} />
        <select value={rol} onChange={(e) => setRol(e.target.value as Rol)}>
          {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <button type="submit">Invitar</button>
      </form>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead><tr><th>Correo</th><th>Nombre</th><th>Rol</th><th>Estado</th><th></th></tr></thead>
        <tbody>
          {usuarios.map((u) => (
            <tr key={u.user_id}>
              <td>{u.email}</td>
              <td>{u.nombre}</td>
              <td>
                <select value={u.rol} onChange={(e) => setRolDe(u, e.target.value as Rol)}>
                  {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              </td>
              <td>{u.estado}</td>
              <td>
                <button onClick={() => setEstadoDe(u, u.estado === "activo" ? "inactivo" : "activo")}>
                  {u.estado === "activo" ? "Desactivar" : "Activar"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 4: Verificar que pasa + build + suite completa**

Run (dentro de `web/`): `npx vitest run src/pages/Usuarios.test.tsx`
Expected: PASS.
Run (dentro de `web/`): `npm test` y `npm run build`
Expected: TODO vitest verde; build OK.
Run (raíz): `python -m pytest tests/ -q`
Expected: 204 passed, 4 skipped (backend intacto salvo /api/yo de Task 1).

- [ ] **Step 5: Commit**
```bash
git add web/src/pages/Usuarios.tsx web/src/pages/Usuarios.test.tsx
git commit -m "feat(web): pantalla de gestión de usuarios (Admin)"
```

---

## Self-Review

**Cobertura del spec:**
- Cliente Supabase + AuthProvider + /api/yo (spec §2) → Tasks 1,2,4. ✅
- Cliente HTTP con Bearer + 401 (spec §3) → Task 3 (incluye streams SSE, no cubierto explícito en el spec pero necesario). ✅
- Login/logout + página de contraseña (spec §4) → Task 6 (+ logout en Layout, Task 7). ✅
- Gateo por rol (spec §5) → Tasks 5 (componentes), 6 (App wiring), 7 (Layout + acciones). ✅
- Pantalla de usuarios (spec §6) → Task 8 (+ api/usuarios en Task 4). ✅
- Envs + pruebas (spec §7) → Task 2 (.env.example), tests en cada task. ✅

**Placeholder scan:** sin TODO/TBD; el único stub deliberado es `Usuarios.tsx` en Task 6 (para que `App.tsx` compile), reemplazado por la pantalla real en Task 8 — explicado. Indirecciones necesarias: Task 7 Step 4 pide leer Insumos/Apus para ubicar los puntos de mutación a gatear (no se puede transcribir sin ver esos archivos, que son grandes); se dan reglas concretas (`puedeEditar` + condicionar botones de crear/importar/transformar/guardar).

**Consistencia de tipos:** `Rol`/`Yo`/`Usuario` definidos en `api/usuarios.ts` y usados en auth.tsx, rutas.tsx, Layout, Usuarios. `authHeader()`/`apiGet/apiPost/apiPatch/apiDelete` consistentes. `useAuth()` devuelve `{sesion, perfil, cargando, noAutorizado, login, logout}` — mismo shape en todos los consumidores. `puede(rol, minimo)` y `RANGO` en rutas.tsx.

**Riesgos abiertos conocidos:** (1) `apiPatch` debe añadirse en Task 4 Step 1 (los endpoints de rol/estado son PATCH). (2) Task 7 Step 4 requiere leer Insumos.tsx/Apus.tsx para gatear con precisión. (3) Los tests con `require()` dinámico deben ajustarse a import ESM si el toolchain (vitest/TS) se queja — nota incluida. (4) El build necesita `web/.env` con las VITE_ para `npm run build`; si no existen, el build igual compila (supabase.ts solo hace `console.error` en runtime), pero para probar la app de verdad hacen falta. La suite es la red de seguridad.
