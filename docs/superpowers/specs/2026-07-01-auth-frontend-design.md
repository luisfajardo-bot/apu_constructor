# Diseño — Plan 2b: Auth + RBAC (frontend)

**Fecha:** 2026-07-01
**Rama:** `feat/auth-frontend` (desde `master`; Plan 2a backend ya fusionado)
**Estado:** aprobado en brainstorming; pendiente plan de implementación.

## 1. Contexto y objetivo

El Plan 2a dejó la API protegida: exige `Authorization: Bearer <JWT de Supabase>` en todo endpoint,
con RBAC jerárquico (`consulta<editor<admin`) y `/api/usuarios/*` solo-Admin. Hoy el frontend no tiene
login, así que la app responde `401` desde el navegador. **Objetivo de 2b: hacer la app usable
end-to-end con login**, gateo de UI por rol, y pantalla de gestión de usuarios.

**Enfoque (aprobado):** Context `AuthProvider` + rutas protegidas (Enfoque A). Estado de auth en un
contexto React; `client.ts` adjunta el Bearer por request; rutas/acciones gateadas por rol leído del
backend.

**Alcance (aprobado):** completo — login + sesión + Bearer + UI según rol + página de contraseña
(fijar/restablecer) + pantalla de gestión de usuarios (Admin) + endpoint backend `GET /api/yo`.
**Diferido:** UI de enrolamiento MFA (opcional).

**Stack (web/package.json):** React 19, react-router-dom 7, radix-ui, sonner, tailwind, vitest.
Nueva dependencia: `@supabase/supabase-js`.

**Restricciones:** no romper los 202 tests backend (única adición backend: `GET /api/yo`); los tests
vitest existentes siguen verdes; invariante #1 no aplica al frontend (nunca ve dinero de la IA; habla
con FastAPI y Supabase Auth). UI **densa/table-first, pulida (skill frontend-design)**.

## 2. Cliente Supabase + AuthProvider (+ `GET /api/yo`)

- **`web/src/lib/supabase.ts`** (nuevo): cliente Supabase desde `import.meta.env.VITE_SUPABASE_URL` +
  `VITE_SUPABASE_ANON_KEY` (anon/publishable key: **pública por diseño**, segura en el navegador —
  su alcance lo acotan RLS + schemas no expuestos; la `service_role` jamás va al front). Config SPA:
  `persistSession: true`, `autoRefreshToken: true`.
- **Backend `GET /api/yo`** (adición en `rutas.py`, `requiere_rol("consulta")`): devuelve
  `{email, rol, nombre}` del `usuario_actual`. Es la fuente del rol para gatear la UI (rol del backend,
  no del JWT crudo).
- **`web/src/lib/auth.tsx`** (nuevo, `AuthProvider` + hook `useAuth`): se suscribe a
  `supabase.auth.onAuthStateChange`; con sesión, hace `GET /api/yo` y guarda el perfil. Expone
  `{ sesion, perfil, cargando, login(email,pw), logout() }`.
  - **Caso "autenticado pero no autorizado":** sesión válida en Supabase pero sin perfil/inactivo →
    `/api/yo` responde `403` → la UI muestra "cuenta no autorizada, contacta al Admin" + `logout()`.
- **`main.tsx`**: envuelve `App` con `<AuthProvider>` dentro del `BrowserRouter`.

## 3. Cliente HTTP con Bearer

- **`web/src/api/client.ts`** (modificar): antes de cada request obtiene el token con
  `supabase.auth.getSession()` (lectura local rápida de localStorage; supabase-js auto-refresca en
  background) y adjunta `Authorization: Bearer <token>` en `apiGet`/`apiPost`/`apiDelete` (incluye el
  caso `FormData`, conservando su manejo de headers).
- **`401`** → `supabase.auth.signOut()`; eso dispara `onAuthStateChange` → `AuthProvider` sin sesión →
  las rutas protegidas redirigen a `/login` de forma reactiva (sin navegación manual desde `client.ts`).
- Se conserva la extracción del `detail` del error para los toasts.
- **Nota de seguridad:** el token vive en `localStorage` (estándar SPA). Riesgo = XSS (no CSRF).
  Mitigación: React auto-escapa, evitar `dangerouslySetInnerHTML`, CSP estricta (Plan 4), tokens de
  vida corta + rotación de refresh, HTTPS (Plan 4).

## 4. Login/logout + página de contraseña

- **`web/src/pages/Login.tsx`** (ruta pública `/login`): email+contraseña → `useAuth().login()` →
  `supabase.auth.signInWithPassword`. Éxito → carga perfil → redirige a `/corridas`. Error → toast.
  Enlace **"¿olvidaste tu contraseña?"** → `supabase.auth.resetPasswordForEmail(email, { redirectTo:
  <app>/definir-clave })`.
- **`web/src/pages/DefinirClave.tsx`** (ruta pública `/definir-clave`): maneja **invitación y
  recuperación** — supabase-js detecta el token de la URL y crea sesión temporal; formulario "nueva
  contraseña" → `supabase.auth.updateUser({ password })` → redirige. Una sola página cubre "fijar clave
  por primera vez" (invitado) y "restablecer".
- **Logout**: en la topbar del `Layout`, menú de usuario (email + rol) + "Cerrar sesión" →
  `useAuth().logout()`.
- Rutas públicas (`/login`, `/definir-clave`) fuera del `Layout` protegido.

## 5. Gateo por rol

- **`<RutaProtegida>`**: `cargando` → spinner; sin sesión → `<Navigate to="/login">`; sin
  perfil/no autorizado → mensaje + logout; con perfil → `Outlet`.
- **`<RequiereRol minimo="...">`**: `perfil.rol < minimo` (jerarquía del backend) → página "sin permiso".
- **Gateo de acciones**: las páginas leen `useAuth().perfil.rol` y ocultan/deshabilitan los botones de
  edición para menos-que-Editor (crear/importar/transformar en Insumos y APUs). Consulta = solo-lectura.
- **`Layout`**: topbar con email/rol/logout; sidebar muestra "Usuarios" **solo si Admin**.
- **`App.tsx`**: públicas fuera del `Layout`; el resto en `<RutaProtegida><Layout/></RutaProtegida>`;
  `/usuarios` en `<RequiereRol minimo="admin">`.
- **Defensa:** el gateo de UI es solo UX; la barrera real es `requiere_rol` en el backend (un Consulta
  que llame directo a una mutación igual recibe `403`).

## 6. Pantalla de usuarios (Admin)

- **`web/src/api/usuarios.ts`** (nuevo): funciones tipadas para `/api/yo` y `/api/usuarios/*` (vía
  `client.ts` con Bearer).
- **`web/src/pages/Usuarios.tsx`** (nuevo, `/usuarios`, solo Admin):
  - Tabla densa (table-first, sin cards): email, nombre, rol, estado, acciones.
  - **"Invitar usuario"** (diálogo radix): email + rol + nombre → `POST /api/usuarios/invitar` → toast →
    refresca.
  - Por fila: cambiar rol (select) + activar/desactivar (toggle) → `PATCH` → refresca. El **guardrail
    del último admin** (backend `400`) se muestra en toast.
- radix-ui (diálogo/select) + `sonner`. Acabado con la skill **frontend-design**.

## 7. Envs, pruebas y no romper

**Envs (frontend):** `web/.env` (ignorado): `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` (pública).
`web/.env.example` versionado documentándolas. En prod, el build del PaaS necesita esas `VITE_` (se
baken en build; se ata al Plan 4).

**Pruebas (vitest, frontend):**
- `AuthProvider`: mock supabase-js + fetch `/api/yo` → login carga perfil; sin sesión → no autenticado;
  `/api/yo` 403 → "no autorizado".
- `client.ts`: adjunta Bearer desde `getSession`; `401` → `signOut`.
- Gateo: `RutaProtegida` redirige sin sesión; `RequiereRol` bloquea bajo el mínimo; botones ocultos para
  Consulta.
- `Usuarios.tsx`: lista, invitar llama a la API, guardrail → toast.
- Los tests vitest existentes (`corridas.sse`, `tiempo`, `useDirtyRows`, `validacionApu`) siguen verdes.

**Backend:** `GET /api/yo` probado con el override del `conftest`. Los 202 tests siguen verdes + 1.

**No romper:** las páginas existentes solo ganan gateo de acciones; su comportamiento no cambia. Única
adición backend: `GET /api/yo`.

## 8. Criterios de éxito

- Sin sesión → la app redirige a `/login`; login válido → entra a `/corridas`.
- Invitado: recibe email → `/definir-clave` fija su clave → entra. "Olvidé mi contraseña" funciona.
- Consulta no ve acciones de edición (y si las forzara, el backend responde `403`); Editor edita
  catálogo; Admin ve y usa `/usuarios`.
- Admin invita/cambia rol/activa-desactiva desde la app; el guardrail del último admin se respeta.
- Usuario autenticado sin perfil → mensaje "no autorizado" + logout.
- `web` build OK; vitest verde; 202 tests backend + `GET /api/yo` verdes.

**Diferido:** MFA (enrolamiento y enforcement por claim AAL); i18n (solo español).
