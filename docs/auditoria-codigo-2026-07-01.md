# Auditoría de código — Armador de APUs (2026-07-01)

Auditoría adversarial de solo-lectura sobre `master` (`c5b7214`), tras completar los Planes 1–4
(Postgres dual, auth/RBAC, auditoría transaccional, endurecimiento + despliegue). Seis auditores
independientes, una dimensión cada uno. Severidad = impacto real, no estilo.

## Veredicto

- **Limpio en lo crítico de seguridad:** Invariante #1 (la IA nunca ve dinero) **se sostiene**; **sin SQL
  injection**; **sin XSS**; verificación JWT sólida; atomicidad de auditoría correcta en las 7 acciones
  instrumentadas; CSP no rompe la SPA; los errores no filtran internos.
- **Pero hay 3 fallos Critical y 8 Important reales** — la mayoría son *asunciones de SQLite que se
  colaron al backend Postgres* y features que el trabajo de auth/UI dejó a medias en el mundo real.

---

## CRITICAL (rompen el backend Postgres = producción)

### C1 — `run_cli.py status` crashea en Postgres
`apu_tool/interfaz/cli.py:65-66` imprime `alm.precios.path` / `alm.apus.path`. Los repos Postgres
(`PreciosPg`/`ApusPg`) **no tienen** `.path` (solo los SQLite). Con `DATABASE_URL`/`APU_DB_BACKEND=postgres`
→ `AttributeError`. `status` es un comando básico documentado en CLAUDE.md.
**Fix:** exponer una identidad de backend por el Protocol (p.ej. `descripcion()` en cada repo) en vez de `.path`.

### C2 — `run_cli.py db check` crashea en Postgres
`apu_tool/dominio/integridad.py:20-24` llama `almacen.apus.connect()` (los repos Pg no exponen `.connect()`)
y usa SQL con la tabla sin calificar (`apu_componentes` en vez de `apus.apu_componentes`). El comando de
chequeo de integridad no corre en ningún despliegue Postgres.
**Fix:** añadir un método de lectura al Protocol `RepositorioApus` (p.ej. `componentes_para_integridad()`)
implementado en ambos backends, y llamar eso en `integridad.py` en vez de SQL crudo.

### C3 — `seguridad.perfiles` no la crea ninguna migración numerada
`supabase/migrations/0002_rls.sql:11` hace `ALTER TABLE seguridad.perfiles ...`, pero **ninguna** migración
la crea: `0001` = precios/apus/corridas; `0003` = `seguridad.auditoria` solamente; `db/pg/seguridad.sql`
(que sí define `perfiles`) no es una migración numerada; y `migrate-pg` solo aplica precios/apus/corridas.
En un proyecto Supabase nuevo provisto vía `supabase/migrations/`, `0002` falla y el auth/RBAC no arranca.
README.md afirma "El esquema Postgres (db/pg/*.sql + auditoría) ya está aplicado" — **falso** por este camino.
*(En "BASE APUS" `perfiles` existe porque se creó ad-hoc por MCP en el Plan 2a; producción actual no está
rota, pero la reproducibilidad/DR sí, y el README miente.)*
**Fix:** crear `supabase/migrations/0002_seguridad_perfiles.sql` (renumerar RLS a 0004 o mover perfiles antes),
y que `migrate-pg`/`init_schema` apliquen `seguridad.sql`.

---

## IMPORTANT

### I1 — TOCTOU en `_proteger_ultimo_admin` → posible lockout total
`apu_tool/servicio/usuarios.py:45-49`: el conteo `contar_admins_activos()` se lee en una conexión aparte,
**fuera** de la transacción del `UPDATE` (READ COMMITTED, sin `FOR UPDATE`). Dos desactivaciones/degradaciones
concurrentes de los 2 únicos admins leen ambas "2" y proceden → **cero admins activos** → sistema bloqueado
(todas las rutas `/usuarios/*` exigen admin; recuperación solo por ops).
**Fix:** conteo dentro de la misma tx con `SELECT ... FOR UPDATE`, o `UPDATE ... WHERE` condicional atómico + verificar `rowcount`.

### I2 — El bootstrap de admin no deja rastro de auditoría
`apu_tool/servicio/auth.py:82-84`: `resolver_perfil` auto-crea un **admin completo** (primer login de un email
en `APU_ADMIN_EMAILS`) con `perfiles.upsert(...)` **sin transacción y sin `registrar_auditoria`**. Es la
mutación más sensible del sistema (auto-otorgar admin) y es justo la única que no queda registrada.
**Fix:** envolver en `alm.transaccion("seguridad")` + `registrar_auditoria(accion="usuario.bootstrap_admin", actor=None)`.

### I3 — "Descargar cuadro" da 401 en producción
`web/src/pages/Corrida.tsx:119` hace `window.open(descargarCuadroUrl(id))` — navegación del navegador **sin
header `Authorization`**. El backend (`rutas.py:223`) exige `requiere_rol("consulta")` y el token es
header-only (sin cookie). Con auth real (producción) **toda descarga de Excel falla con 401**. La acción
principal "dame el cuadro" está muerta.
**Fix:** descargar vía `fetch` con Bearer → `Blob` → enlace temporal; o un token de descarga de un solo uso en query.

### I4 — El visor de Auditoría oculta/orfana filas de un lote
`web/src/pages/Auditoria.tsx:57-70,150-183`: el colapso por `lote_id` asume que las filas del lote son
**contiguas**. El backend ordena por `ts DESC` y cada fila de un import lleva su propio `datetime.now()`;
en un log multiusuario (limit=200, sin aislar por usuario) se intercalan otros eventos → filas del lote no
contiguas → colapsadas desaparecen, expandidas quedan huérfanas lejos de su cabecera.
**Fix:** agrupar por `lote_id` en un `Map` (no por orden del array) antes de renderizar.

### I5 — Divergencia `LIKE` (SQLite) vs `ILIKE` (Postgres) con acentos
Búsquedas (`list_insumos`/`search_*`/`list_apus`) usan `LIKE` en SQLite (case-insensitive solo ASCII) e
`ILIKE` en Postgres (case-insensitive con acentos). Misma búsqueda → **resultados distintos** entre los tests
(SQLite) y producción (Postgres). Ej.: `%hormigón%` no matchea `HORMIGÓN` en SQLite pero sí en Pg.
**Fix:** normalizar el término (ya existe `nucleo/texto.normalizar`) o usar `LOWER()` en ambos lados con la misma semántica.

### I6 — `migrate-pg` no es idempotente (contradice su docstring)
`apu_tool/datos/migracion_pg.py` hace `INSERT` plano (sin `ON CONFLICT`) para insumos/precios/apus/componentes;
`cmd_migrate_pg` aplica el esquema con `CREATE TABLE IF NOT EXISTS` (no limpia). Re-correrlo (tras `seed --force`
o un reintento) choca `UNIQUE`/PK y aborta. No hay camino soportado para re-empujar el catálogo sin dropear
schemas a mano. (No corrompe: la tx entera hace rollback.)
**Fix:** `ON CONFLICT DO UPDATE`/`DO NOTHING`, o dropear+recrear los schemas precios/apus al inicio de migrate-pg.

### I7 — Bypass del límite de subida (chunked / sin Content-Length) → OOM
`apu_tool/servicio/limites.py::LimiteSubida` solo mira `Content-Length`. Un POST con `Transfer-Encoding: chunked`
(o sin CL) lo salta y `await archivo.read()` bufferiza todo el cuerpo en memoria → OOM/crash de worker
(agravado con 2 workers en plan starter).
**Fix:** rechazar chunked/sin-CL, o leer por trozos abortando al superar `max_bytes`.

### I8 — Spoofing de `X-Forwarded-For` evade el rate limit
`Dockerfile` usa `--forwarded-allow-ips="*"` → uvicorn confía el XFF de **cualquier** peer y toma la entrada
más a la izquierda (controlable por el cliente); `get_remote_address` la usa como clave. En cualquier host
donde el contenedor sea alcanzable directo, `X-Forwarded-For: <ip-rotativa>` → clave falsificable → evasión
total del rate-limit y envenenamiento de la IP en auditoría. Seguro HOY solo porque el edge de Render es el
único ingreso (asunción no documentada).
**Fix:** allowlist del CIDR del proxy de Render en `--forwarded-allow-ips` en vez de `"*"`; documentar la dependencia de topología.

---

## MINOR

- **M1** — `/docs`,`/redoc`,`/openapi.json` públicos sin auth (`app.py`): un anónimo lee todo el contrato de la API. Fix: `docs_url=None, redoc_url=None, openapi_url=None` en prod.
- **M2** — rate limiter con storage in-memory por proceso + `WEB_CONCURRENCY=2` → límite efectivo ×2 (invitar "3/minute" rinde ~6/min). Fix: storage compartido (Redis) o dividir por workers.
- **M3** — `web/src/lib/auth.tsx:23-42`: al rechazar (403 de `/api/yo`) el `signOut()` re-dispara el listener y pisa `noAutorizado=false` → muestra `/login` en vez de "cuenta no autorizada" (falla cerrado, solo UX).
- **M4** — código muerto: `apu_tool/dominio/models.py` (copia obsoleta sin usar; el vivo es `nucleo/models.py`) y `_ALLOWED_NUMERIC_KEYS` en `privacy.py` (definido, nunca usado).
- **M5** — drift de esquema: `db/pg/precios.sql` tiene `ON DELETE CASCADE` en `insumo_precios.insumo_id` que `db/precios.sql` (SQLite) no. Dormido (nadie borra insumos hoy); reconciliar antes de añadir borrado.
- **M6** — footgun: `INSERT INTO auditoria` sin calificar (SQLite) resuelve correcto hoy, pero si algún día una tabla de dominio se llamara `auditoria` escribiría en la BD equivocada sin error.
- **M7** — `usuarios.invitar`: si el `upsert`+auditoría local falla tras crear el usuario en Supabase, queda un usuario Auth sin perfil ni rastro (idempotente al re-invitar; diferido por diseño).

## Notas estructurales (por diseño, no bugs)

- `assert_no_money` es una **blocklist por nombre de clave**, no un escáner de valores: un número monetario bajo
  una clave inocua (o texto libre) no lo detectaría. Se sostiene porque los *builders* del payload nunca meten
  dinero; es un backstop, no una garantía de tipo. (Ver CLAUDE.md.)
- Un 500 que escapa por `ServerErrorMiddleware` de Starlette sale sin cabeceras de seguridad — límite
  estructural, documentado en `app.py`, no corregible a nivel app.

## Dimensiones limpias (verificadas)

Invariante #1 (sin fugas de dinero a la IA) · SQL injection (ninguna; toda data por parámetros) ·
XSS (React autoescapa; sin `dangerouslySetInnerHTML`) · JWT (alg explícito, exp/aud/iss obligatorios,
firma verificada por JWKS; `user_metadata` nunca usado para authz) · atomicidad de auditoría (misma
conexión mutación+fila; partial-success por ítem; sin WAL) · CSP (no rompe la SPA; connect-src cubre Supabase) ·
manejo de errores (sin fugas de traza/internos).

## Recomendación de orden de arreglo

1. **C1, C2, C3** (Postgres roto / auth no reproducible) — antes de cualquier despliegue Postgres real.
2. **I3, I4** (features rotas de cara al usuario: descarga y visor de auditoría).
3. **I1, I2** (integridad de admin: lockout y bootstrap sin auditar).
4. **I7, I8, I5, I6** (DoS/subida, evasión de rate-limit, divergencia de búsqueda, idempotencia de migración).
5. Minors según convenga (M1 y M2 son baratos y valiosos en prod).
