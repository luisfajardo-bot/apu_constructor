# Diseño — Plan 2a: Auth + RBAC (backend)

**Fecha:** 2026-07-01
**Rama:** `feat/auth-rbac` (desde `master`; Plan 1 ya fusionado)
**Estado:** aprobado en brainstorming; pendiente plan de implementación.
**Base:** Sección 5 del spec `2026-07-01-produccion-multiusuario-design.md` (aprobado).

## 1. Contexto y objetivo

Proteger la API del Armador de APUs con autenticación (Supabase Auth) y autorización por roles
(RBAC), manteniendo a **FastAPI como único gateway** a la base (con `service_role`), preservando la
**invariante #1** (la IA nunca ve dinero) y sin romper los **173 tests** actuales.

**Alcance de este plan (2a — backend):** verificación de JWT, tabla `perfiles` + RBAC, endpoints de
gestión de usuarios, RLS, protección de todos los endpoints, y pruebas (todas corren local sin BD
viva). **Fuera de alcance (2b — frontend):** login con supabase-js, UI según rol, pantalla de
gestión de usuarios.

**Decisiones tomadas:**
- Verificación de JWT: **asimétrica con JWKS** (Enfoque A).
- Primer Admin: **variable de entorno `APU_ADMIN_EMAILS`** (auto-asigna Admin en el primer login).
- Roles: **Admin / Editor / Consulta** en tabla `perfiles`, consultada por request.

**Entorno relevante:** proyecto Supabase "BASE APUS" (ref `hfjljzhgignngzooiwvl`, us-west-2, PG17)
con el esquema del Plan 1 ya aplicado. La máquina local **bloquea el egreso a puertos de BD**
(5432/6543), por lo que **todas las pruebas deben correr sin BD viva** (JWT con par de llaves de
prueba; RBAC/perfiles en SQLite; Admin API de Supabase tras una interfaz con *fake*).

## 2. Verificación del JWT

Módulo nuevo **`apu_tool/servicio/auth.py`**:

- **Cliente JWKS:** descarga las llaves públicas de
  `https://<ref>.supabase.co/auth/v1/.well-known/jwks.json`, las **cachea** y las refresca si aparece
  un `kid` desconocido (rotación). Se usa **PyJWT** (`PyJWKClient`) — dependencia liviana, respeta
  "sin dependencias pesadas". Nueva dependencia: `PyJWT[crypto]` en `requirements.txt`.
- **`verificar_jwt(token) -> dict`:** valida firma (ES256/RS256) + `exp` + `aud` (`authenticated`) +
  `iss` (`https://<ref>.supabase.co/auth/v1`). Fallo → excepción de auth.
- **`Usuario`** (dataclass en `auth.py`): `user_id`, `email`, `rol`, `estado`.
- **Dependencia `usuario_actual(request) -> Usuario`:** extrae `Authorization: Bearer`, verifica el
  JWT, resuelve el perfil (Sección 3) y devuelve `Usuario`. `401` si falta/está inválido el token;
  `403` si el usuario no tiene perfil o está inactivo (salvo bootstrap admins).
- **Config (env):** `SUPABASE_PROJECT_REF`/`SUPABASE_URL` (deriva la URL del JWKS), `APU_ADMIN_EMAILS`,
  `SUPABASE_SERVICE_ROLE_KEY` (Sección 4).
- **Sin bypass de auth en runtime** (no habrá flag `APU_AUTH_DISABLED`: riesgo de filtrarse a prod).

**Pruebas (sin red):** el test genera un par de llaves (RSA/EC), firma un token con la privada,
inyecta la pública como JWKS del verificador, y comprueba válido→OK; expirado/firma-mala/`aud`-malo→
`401`.

## 3. Perfiles + RBAC

**Tabla `perfiles`** (schema nuevo `seguridad` en Postgres; tabla equivalente en el backend SQLite
para dev/tests):
`user_id` UUID **PK** (= id de Supabase Auth), `email`, `rol` (`admin`/`editor`/`consulta` con CHECK),
`estado` (`activo`/`inactivo`), `nombre`, `creado_en`.

**Repositorio dual (patrón existente):** `RepositorioPerfiles` (Protocol) + `PerfilesPg` (Postgres) +
`PerfilesSqlite` (SQLite). `Almacen` gana `.perfiles`. El RBAC se prueba en SQLite localmente.

**`resolver_perfil(user_id, email)`** (lo llama `usuario_actual`):
- Perfil existe y `activo` → lo devuelve.
- Perfil existe e `inactivo` → `403`.
- No existe:
  - email ∈ `APU_ADMIN_EMAILS` → crea perfil `admin`/`activo` (bootstrap) y lo devuelve.
  - si no → `403` "usuario no autorizado" (los invitados ya tienen perfil, Sección 4).

**`requiere_rol(*roles)`:** fábrica de dependencia FastAPI (sobre `usuario_actual`) que exige
`rol ∈ roles` y `estado activo`; si no `403`. Un cambio de rol o desactivación surte efecto **al
instante** (perfil consultado por request).

**Matriz aplicada a `rutas.py`:**

| Grupo de endpoints | Rol mínimo |
|---|---|
| GET (ver insumos/APUs/precios/corridas/cuadros) | Consulta |
| Armar corrida / confirmar ítem / exportar cuadro / sample | Consulta |
| Crear/importar/editar insumos y APUs, cambiar precios, transformar | Editor |
| Gestión de usuarios (`/api/usuarios/*`) | Admin |

## 4. Gestión de usuarios (solo Admin)

**Endpoints `/api/usuarios/*`** con `requiere_rol("admin")`:
- `GET /api/usuarios` — lista perfiles (email, rol, estado, nombre).
- `POST /api/usuarios/invitar` `{email, rol, nombre}` — invita/crea el usuario en Supabase Auth (Admin
  API con `service_role`, vía `httpx` por HTTPS/443 — funciona pese al bloqueo de puertos de BD) y crea
  su fila en `perfiles` con el rol elegido.
- `PATCH /api/usuarios/{user_id}/rol` `{rol}` — cambia el rol.
- `PATCH /api/usuarios/{user_id}/estado` `{estado}` — activa/desactiva.

**Cliente Admin de Supabase** aislado en `apu_tool/servicio/supabase_admin.py` detrás de una interfaz,
para inyectar un **fake** en tests (no llama a Supabase real).

**Guardrails:**
- Un Admin **no puede desactivar ni degradar al último Admin activo**.
- Desactivar surte efecto de inmediato: como el perfil se consulta por request, `estado=inactivo`
  bloquea al usuario en su próxima petición aunque el JWT siga vigente (resuelve "borrar usuario no
  invalida el token" sin revocar sesiones).

**Auditoría:** invitar / cambiar rol / activar-desactivar son mutaciones sensibles; las funciones se
diseñan para que el **Plan 3 (auditoría)** las envuelva. En 2a quedan los ganchos.

## 5. RLS (defensa en profundidad)

- **Habilitar RLS sin policies** en todas las tablas de `precios`, `apus`, `corridas` y `seguridad`.
  Bloquea `anon`/`authenticated`; la `service_role` (FastAPI) hace **bypass**. Cierra el advisory del
  MCP.
- Migración **`supabase/migrations/0002_rls.sql`** (`ALTER TABLE … ENABLE ROW LEVEL SECURITY` por
  tabla).
- Doble cierre: schemas custom no expuestos por el Data API por defecto **+** RLS activado.
- RLS es solo de Postgres; no afecta al backend SQLite ni a los tests. Se verifica vía MCP que quede
  activado y que la `service_role` siga operando.

## 6. Pruebas (todas locales, sin BD viva)

- **JWT:** par de llaves de prueba → válido/expirado/firma-mala/`aud`-malo → `401`.
- **`resolver_perfil`:** bootstrap admin, invitado existente, inactivo→`403`, desconocido→`403` (SQLite).
- **`requiere_rol`:** matriz rol×endpoint → `200`/`403` con `TestClient` y `dependency_overrides`
  inyectando un verificador de token de prueba (sin Supabase real).
- **Gestión de usuarios:** invitar (cliente Admin fake), cambiar rol, desactivar, guardrail del último
  admin.
- **Contrato:** `PerfilesPg` parametrizado (param Postgres se omite local, como los demás).
- **No romper los 173:** al añadir `requiere_rol` a los endpoints, los tests de API actuales
  (`test_api_*`, `test_servicio_*`) que llaman sin token darían `401`. Se añade un **fixture compartido
  que sobreescribe `usuario_actual`** con un usuario de prueba (Admin) vía `dependency_overrides`
  (práctica estándar de FastAPI, solo-tests, no debilita el auth real). Los tests de dominio no se
  tocan.

## 7. Invariante #1 y no romper lo existente

- No se toca `dominio/privacy.py`, `ai_assist.py` ni las vistas `DePriced*`. Auth vive en `servicio/`
  y `datos/` (repo perfiles). Todo es aditivo.
- Los tests existentes son la red de no-regresión (más el override de auth para los de API).

## 8. Alcance, checklist y criterios de éxito

**Entregables 2a:** `auth.py` (JWT + `usuario_actual` + `requiere_rol` + `Usuario`), esquema `seguridad`
+ repo `perfiles` dual + `resolver_perfil`, endpoints `/api/usuarios/*` + `supabase_admin.py` (con
fake), migración RLS `0002`, protección de todos los endpoints en `rutas.py`, tests nuevos, y
actualización de los tests de API con el override.

**Checklist previo:** definir en el `.env` local (y en el env del PaaS) `SUPABASE_PROJECT_REF`,
`SUPABASE_SERVICE_ROLE_KEY`, `APU_ADMIN_EMAILS`. Crear el primer usuario Admin en el panel de Supabase
(Authentication > Add user) con un email incluido en `APU_ADMIN_EMAILS`.

**Criterios de éxito:**
- Endpoints sin token → `401`; con token pero rol insuficiente → `403`; con rol correcto → `200`.
- Bootstrap admin funciona; invitados obtienen su perfil; desactivar bloquea al instante.
- RLS activado en las tablas (verificado vía MCP); la `service_role` sigue operando.
- Los 173 tests siguen verdes (con el override de auth) + nuevos tests de JWT/RBAC/usuarios.
- Invariante #1 intacta.

**Diferido:** frontend (2b); auditoría transaccional de las mutaciones de usuario (Plan 3);
enforcement de MFA vía claim AAL (opcional, se evalúa en 2b/despliegue).
