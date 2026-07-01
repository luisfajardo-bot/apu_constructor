# Diseño — Plan 4: Endurecimiento + despliegue

**Fecha:** 2026-07-01
**Rama:** `feat/endurecimiento-despliegue` (desde `master`; Planes 1, 2a, 2b, 3 ya fusionados)
**Estado:** aprobado en brainstorming; pendiente plan de implementación.

## 1. Contexto y objetivo

Última etapa de la ruta a producción multiusuario. Los Planes 1/2a/2b/3 dejaron: backend Postgres
dual (SQLite dev/tests, Postgres prod), auth JWT/RBAC, y auditoría transaccional. Falta **exponer la
app en internet de forma segura** para el equipo de la empresa y **endurecer** la API. Construye sobre
las Secciones 7 (endurecimiento), 8 (migración) y 9 (despliegue) del spec maestro
(`docs/superpowers/specs/2026-07-01-produccion-multiusuario-design.md`).

**Decisiones (brainstorming):**
- **PaaS: Render** — contenedor Docker, HTTPS automático, env vars, health-check, auto-deploy desde GitHub.
- **Acceso: solo login Supabase** — URL pública, pero solo entran cuentas invitadas por el Admin (sin
  registro abierto). El RBAC + auditoría protegen los datos. (Gate de red se difiere.)
- **CI: incluido** — GitHub Actions corre backend + frontend en cada push/PR a `master`.
- **Gate psycopg:** los contratos Postgres corren en CI contra un **Postgres efímero** (service container
  `postgres:17`), no contra Supabase — aislado, gratis, y ejercita los repos `*Pg` contra Postgres real
  por primera vez. La **migración del catálogo** (`migrate-pg`) es un paso de ops único contra
  "BASE APUS", verificado por conteos.

**Restricciones:**
- **Invariante #1 intacta:** el endurecimiento vive en `apu_tool/servicio/` (middleware, manejadores);
  NO se toca `apu_tool/dominio/privacy.py`, `ai_assist.py`, ni las vistas `DePriced*`.
- **Cero regresiones:** 236 tests backend + 19 vitest siguen verdes. El rate-limit debe poder
  desactivarse/relajarse por env en tests para no volver la suite flaky.
- **Un solo origen / sin CORS.** **Contenedor stateless** (Postgres/Auth en Supabase; cuadros Excel a
  disco efímero, descargados al vuelo).
- **Español** en dominio, comentarios y mensajes de usuario.

## 2. Topología y Dockerfile

Un contenedor sirve todo (mismo origen). `Dockerfile` multi-stage:
- **Etapa 1 (Node):** `npm ci` + `npm run build` en `web/` con `VITE_SUPABASE_URL` y
  `VITE_SUPABASE_ANON_KEY` como `ARG`/build-args (se bakean en `web/dist`; la anon key es pública por diseño).
- **Etapa 2 (Python slim):** `pip install -r requirements.txt`; copia `apu_tool/`, `db/`, y el `web/dist`
  de la etapa 1; expone el puerto; arranca gunicorn (ver §5).
- **`.dockerignore`:** excluye `web/node_modules`, `node_modules`, `data/`, `salidas/`, `ejemplos/*.xlsx`,
  `.env*` (excepto `.env.example`), `.git`, `tests/`, `.superpowers/`, `**/__pycache__`.
- FastAPI (`apu_tool/servicio/app.py`) ya monta `/api` y sirve la SPA de `web/dist` — sin cambios de
  topología. Postgres/Auth externos → contenedor stateless; los cuadros Excel (`salidas/`) son efímeros
  (se descargan por `GET /api/corridas/{id}/cuadro`), no requieren volumen persistente.

## 3. Endurecimiento — tráfico (rate limiting + límites de subida)

**Nueva dependencia:** `slowapi` (en `requirements.txt`).

- **Rate limiting** (`apu_tool/servicio/limites.py`, nuevo): `Limiter` de slowapi keyeado por IP remota.
  Límite global por defecto (p.ej. `200/minute`) + límites estrictos por endpoint sensible:
  subida/armado de corridas (`/api/corridas`, `/api/corridas/stream`, `/api/sample*`), importaciones
  (`/api/insumos/importar*`, `/api/apus/importar*`), e invitación (`/api/usuarios/invitar`). Exceso → `429`
  con cuerpo JSON `{detail}`. El `Limiter` se registra en `app.state` y su handler de `RateLimitExceeded`.
  - **IP real detrás del proxy:** Render termina TLS en un proxy; gunicorn corre con `--forwarded-allow-ips="*"`
    y uvicorn `proxy_headers=True` para que `request.client.host` (que slowapi usa) sea la IP real, no el proxy.
  - **Config por env:** `APU_RATELIMIT_ENABLED` (default `true`); en tests se pone `false` (o límites muy
    altos) para no volver la suite flaky. Un test dedicado activa el límite y verifica `429`.

- **Límite de subida** (`apu_tool/servicio/limites.py`): middleware que, en requests con cuerpo, si
  `Content-Length` supera `APU_MAX_UPLOAD_MB` (default 15) responde `413` **antes** de leer el cuerpo.
  Complementa la validación de extensión/`content-type` ya existente en los servicios de importación;
  openpyxl ya se abre en `read_only` (mitiga zip-bomb). Sin `Content-Length` (chunked), se aplica un tope
  al acumular en `await archivo.read()` — se documenta el límite efectivo.

## 4. Endurecimiento — errores (sin fugas)

- **Manejador global de excepciones** (`app.py`): `@app.exception_handler(Exception)` → log server-side
  con traceback (logger `apu_tool`) + respuesta `500` con cuerpo genérico `{"detail": "Error interno."}`.
  Los `HTTPException` conservan su status/detalle (son intencionales). Un `@app.exception_handler(ValueError)`
  → `400` genérico.
- **Excel corrupto:** capturar `zipfile.BadZipFile` e `openpyxl.utils.exceptions.InvalidFileException`
  (además de `ValueError`) en los servicios de importación/lectura de licitación → `HTTPException(400)`
  con mensaje limpio (corrige el `500` actual). Se añade el manejo donde se hace `openpyxl.load_workbook`.
- **SSE:** el `event: error` de `_event_stream` (en `rutas.py`) pasa a un mensaje genérico al cliente;
  el detalle va al log. No se filtran trazas por el stream.

## 5. Cabeceras, transporte y servidor

- **Middleware de cabeceras** (`apu_tool/servicio/seguridad_headers.py`, nuevo): añade a cada respuesta
  `Strict-Transport-Security` (HSTS), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer`, y **CSP**.
  - **CSP (riesgo real, mitigado):** `default-src 'self'; base-uri 'self'; frame-ancestors 'none';
    img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self';
    connect-src 'self' https://<SUPABASE_HOST> wss://<SUPABASE_HOST>`. El `connect-src` DEBE incluir el
    host de Supabase (supabase-js hace fetch + realtime/websocket), derivado de `SUPABASE_URL`/`PROJECT_REF`
    en runtime. `style-src 'unsafe-inline'` porque los estilos inline de la SPA/Tailwind lo requieren.
    **El plan incluye un paso de validación manual**: build + servir + abrir la app y confirmar (consola sin
    violaciones de CSP; login y navegación funcionan). Si Vite inyecta scripts inline, se ajusta con hash/nonce.
- **HTTPS:** lo fuerza Render (TLS + redirección HTTP→HTTPS). No se implementa en la app.
- **Sin CORS:** SPA y API en el mismo origen; no se añade `CORSMiddleware` (evita comodines).
- **Servidor de producción** (`requirements.txt` + entrypoint): `gunicorn` con
  `-k uvicorn.workers.UvicornWorker`, `--workers` configurable (env `WEB_CONCURRENCY`, default 2),
  `--forwarded-allow-ips="*"`, `--timeout` y bind a `0.0.0.0:$PORT` (Render inyecta `$PORT`). `run_web.py`
  sigue siendo el arranque local (uvicorn, un worker, abre navegador); el contenedor usa gunicorn.

## 6. Config, secretos y quickstart local

- **`.env.example` (backend, versionado)** — documenta TODAS las envs con placeholders y comentarios:
  `DATABASE_URL` (pooler Supabase, modo transacción), `SUPABASE_PROJECT_REF`, `SUPABASE_SERVICE_ROLE_KEY`,
  `APU_ADMIN_EMAILS`, `ANTHROPIC_API_KEY` (opcional), `APU_MAX_UPLOAD_MB`, `APU_RATELIMIT_ENABLED`,
  `WEB_CONCURRENCY`. **`web/.env.example`** ya existe (VITE_*) — se revisa que esté completo.
- **Secretos en Render:** por el dashboard (o `render.yaml` con `sync: false`), nunca en el repo. `.env` en
  `.gitignore` (ya está).
- **Quickstart local (README):** pasos para correr en local con SQLite —
  1) `web/.env` con `VITE_SUPABASE_URL` + `VITE_SUPABASE_ANON_KEY`;
  2) env backend con `SUPABASE_PROJECT_REF` (o `SUPABASE_URL`) + `APU_ADMIN_EMAILS=<tu-email>`;
  3) `python run_cli.py seed`; 4) `python run_web.py` + (en `web/`) `npm run dev`;
  5) crear el usuario en Supabase Auth y entrar. **Esto resuelve el "no corre local"** (supabase-js
  revienta al importar sin las `VITE_*`).

## 7. Migración del catálogo + gate psycopg

- **Gate psycopg (en CI, contra Postgres real efímero):** el job de CI levanta un service container
  `postgres:17`, exporta `TEST_DATABASE_URL=postgresql://...@localhost:5432/...`, y corre `pytest -q`. Los
  tests de contrato dual (hoy 4 skipped por falta de `TEST_DATABASE_URL`) se ejecutan por primera vez
  contra Postgres real → valida los repos `*Pg` end-to-end. Aislado, gratis, sin tocar Supabase.
- **Migración del catálogo (ops, una vez, contra "BASE APUS"):** documentada en el README de despliegue.
  Con `DATABASE_URL` de Supabase: 1) aplicar `db/pg/*.sql` (esquema; ya aplicado precios/apus/corridas/
  seguridad + auditoría vía MCP); 2) `python run_cli.py migrate-pg` (insumos + historial de precios +
  APUs + componentes; `creado_por='migración'`); 3) **verificar conteos** SQLite vs Postgres + spot-check
  de un par de APUs (vía MCP de Supabase). No es un test automatizado (requiere acceso a la BD real).

## 8. Despliegue en Render

- **`render.yaml`** (IaC, versionado): un servicio web tipo Docker; `healthCheckPath: /api/status`;
  `envVars` (las secretas con `sync: false` → se llenan en el dashboard; las `VITE_*` como build-args del
  Docker); `autoDeploy` desde `master`.
- **Post-deploy (ops, documentado en README):** en Supabase añadir `https://<app-url>/definir-clave` al
  allowlist de redirect URLs (invitación/reset); crear el **primer Admin** (usuario en Supabase Auth con un
  email de `APU_ADMIN_EMAILS` → `resolver_perfil` lo bootstrapea a admin al primer login).

## 9. CI (GitHub Actions)

`.github/workflows/ci.yml`, en `push`/`pull_request` a `master`:
- **Job backend:** Python 3, `pip install -r requirements.txt`, `pytest -q`. Variante con service container
  `postgres:17` + `TEST_DATABASE_URL` para los contratos Postgres (§7).
- **Job frontend:** Node, `cd web && npm ci && npx vitest run && npm run build && npx oxlint`.
- Merge a `master` bloqueado si algún job falla (branch protection — nota de ops; el workflow es el
  deliverable versionado).

## 10. Pruebas y no romper

**Nuevos tests de endurecimiento** (`tests/test_endurecimiento.py`, TestClient sobre `create_app`):
- Subida > `APU_MAX_UPLOAD_MB` → `413` (con `Content-Length` alto).
- Excel corrupto (bytes basura con nombre `.xlsx`) a `/api/insumos/importar/preview` → `400` (no `500`).
- Con rate-limit activado (env) y límite bajo, N+1 requests al endpoint limitado → `429`.
- El manejador global: una ruta que fuerza una excepción interna → `500` con cuerpo genérico (sin traza).
- Cabeceras: una respuesta cualquiera incluye HSTS/nosniff/CSP/X-Frame-Options.

**No romper:**
- 236 backend + 19 vitest verdes. El rate-limit se desactiva por defecto en el entorno de test
  (`APU_RATELIMIT_ENABLED=false`) para no volver flaky la suite; los tests de `429` lo activan localmente.
- El middleware de cabeceras/límite se añade a `create_app` sin cambiar el contrato de los endpoints.
- **Invariante #1 intacta**: no se toca `dominio/privacy.py`, `ai_assist.py`, ni `DePriced*`; el
  endurecimiento es solo `servicio/` (middleware/handlers/limits) + infra (Docker/CI/Render).

## 11. Estructura de archivos (nuevos / modificados)

- Nuevos: `Dockerfile`, `.dockerignore`, `render.yaml`, `.github/workflows/ci.yml`,
  `apu_tool/servicio/limites.py` (rate limit + upload middleware), `apu_tool/servicio/seguridad_headers.py`
  (cabeceras), `.env.example`, `tests/test_endurecimiento.py`, y una sección de despliegue en `README.md`.
- Modificados: `apu_tool/servicio/app.py` (registrar middlewares + manejadores globales + limiter),
  `apu_tool/servicio/rutas.py` (SSE genérico; captura de errores de openpyxl → 400; `Depends`/decoradores de
  rate limit en endpoints sensibles), servicios de importación/licitación (capturar `BadZipFile`/
  `InvalidFileException`), `requirements.txt` (`slowapi`, `gunicorn`).

## 12. Criterios de éxito

- La app queda desplegada en Render sobre HTTPS, sirviendo SPA + `/api` desde un contenedor; health-check
  verde en `/api/status`.
- Solo entran cuentas invitadas (login Supabase); nadie sin cuenta pasa del login.
- Endurecimiento activo: subida sobre el límite → `413`; Excel corrupto → `400`; exceso → `429`; errores
  internos → `500` genérico sin fugas; cabeceras de seguridad + CSP presentes.
- CI verde en push/PR; los contratos Postgres corren contra Postgres real (efímero) en CI.
- Catálogo migrado y verificado en "BASE APUS" (conteos + spot-check).
- 236 tests backend + 19 vitest verdes + nuevos tests de endurecimiento. Invariante #1 intacta.

**Diferido:** gate de red (Cloudflare Access); observabilidad avanzada (APM/tracing); autoscaling;
formalizar el historial de migraciones Supabase (`supabase db push`).
