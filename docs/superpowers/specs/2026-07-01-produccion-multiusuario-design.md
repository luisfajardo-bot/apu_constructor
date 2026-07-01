# Diseño — Ruta a producción multiusuario del Armador de APUs

**Fecha:** 2026-07-01
**Rama:** `feat/produccion-multiusuario` (a partir de `master`; `master` queda intacto como respaldo)
**Estado:** aprobado en brainstorming; pendiente escribir el plan de implementación.

## 1. Contexto y objetivo

El Armador de APUs hoy es una app **local-first de un solo usuario** (SQLite + FastAPI ligado a
`127.0.0.1`, sin autenticación). El objetivo es llevarlo a **producción multiusuario, expuesto a
internet con login**, alojando la base de datos y la autenticación en **Supabase**, sin romper la
lógica existente y **preservando la invariante #1** (la IA nunca ve dinero).

Una auditoría previa confirmó que el núcleo es sólido (161 tests verdes, arquitectura limpia por
capas, invariante #1 realmente enforced) y que lo que falta para multiusuario son **cimientos**:
autenticación, autorización, trazabilidad, migración a Postgres y endurecimiento de la API.

**Fuera de alcance (explícitamente diferido a después del lanzamiento):** nuevas visualizaciones y
pruebas extra más allá de las que cubren este trabajo. No se gatilla el lanzamiento seguro por
cosméticos.

## 2. Decisiones tomadas

| Tema | Decisión |
|---|---|
| Roles | **3 niveles**: Admin, Editor, Consulta. Gestión de usuarios dentro de la app (Admin). |
| Exposición | **Internet abierto con login** → endurecimiento completo (rate limiting, límites de subida, cabeceras). |
| Migración de datos | **Migrar el catálogo** (insumos, APUs, historial de precios con sus ediciones); **corridas desde cero**. |
| Auditoría | **Mutaciones sensibles** (con `antes→después` en precios). No se registran lecturas. |
| Hosting | **PaaS gestionado** (Render/Railway/Fly), contenedor Docker. Supabase solo BD + Auth. |
| Persistencia | **Enfoque A**: repos Postgres nativos que implementan los `Protocol` existentes (psycopg v3). SQLite se conserva para dev/tests. |

## 3. Arquitectura y frontera de seguridad

El navegador **nunca** habla directo con Supabase. FastAPI es el **único gateway** a la base, y
ahí conviven dos fronteras: la de **privacidad** (invariante #1, ya existente) y la nueva de
**autorización**.

```
Navegador (SPA)
  │  1. Login → Supabase Auth devuelve un JWT
  │  2. Cada request lleva Authorization: Bearer <JWT>
  ▼
FastAPI (único que habla con la BD)
  │  3. Dependencia verifica el JWT contra Supabase (JWKS, exp, aud, iss)
  │  4. Resuelve usuario + rol → autoriza (Admin/Editor/Consulta)
  │  5. Servicios de dominio (SIN CAMBIOS)
  │        └─ IA acotada: privacy.safe_json (invariante #1, intacta)
  │  6. Auditoría de mutaciones sensibles (misma transacción que la mutación)
  ▼
Supabase Postgres  ← pool de conexiones, con service-role/pooler key (solo server-side)
```

**Principios:**

- Supabase da **solo identidad y almacenamiento**. No se usa el patrón navegador→PostgREST ni RLS
  como control de acceso de la app: la autorización se decide en FastAPI. Esto mantiene la
  invariante #1 en la capa de dominio y evita exponer datos al cliente.
- **RBAC solo sobre escritura + identidad.** Los tres roles ven los precios (incluidos internos);
  los roles controlan *quién puede modificar* y *dejan rastro de quién hizo qué*.
- **La capa de dominio no se toca** (`matching`, `assemble`, `pricing`, `privacy`, `ai_assist`,
  `report`). Todo el cambio se concentra en `datos/` (backend Postgres), `servicio/` (auth +
  auditoría + endurecimiento) y despliegue. Extender por adición, no reescribir.

## 4. Persistencia Postgres (Enfoque A)

- **Nuevo backend, mismos contratos.** `PreciosPg`, `ApusPg`, `CorridasPg` en `apu_tool/datos/pg/`
  implementan `RepositorioPrecios/Apus/Corridas` (definidos en `apu_tool/datos/repositorio.py`) con
  **psycopg v3**. Nada por encima de `Almacen` cambia.
- **Selección de backend por config.** `config.py` elige según entorno: `sqlite` en local/dev/tests,
  `postgres` cuando hay `DATABASE_URL`. `Almacen` instancia una familia u otra. SQLite **no se
  elimina**.
- **Una sola base, tres áreas lógicas.** Las tres SQLite se unifican en un Postgres, separadas por
  *schema* (`precios`, `apus`, `corridas`), con un **pool de conexiones único** creado en el lifespan
  de FastAPI y compartido (nada de abrir/cerrar por operación como en SQLite).
- **Pooler de Supabase** en modo transacción (Supavisor); con psycopg implica desactivar
  *prepared statements* server-side (`prepare_threshold=None`).
- **Traducción de SQL:** `INSERT OR IGNORE`→`ON CONFLICT DO NOTHING`; `INSERT OR REPLACE`→
  `ON CONFLICT … DO UPDATE`; `lastrowid`→`RETURNING id`; `INTEGER PRIMARY KEY`/`AUTOINCREMENT`→
  `GENERATED ALWAYS AS IDENTITY`; placeholders `?`→`%s`. Parametrización preservada (cero
  concatenación → cero inyección). Atomicidad por operación conservada (mismo patrón commit/rollback
  sobre el pool).
- **Esquema como migraciones Supabase** (`supabase/migrations/`, fuente de verdad, aplicadas con el
  plugin/MCP). El FK `insumo_precios→insumos` gana `ON DELETE CASCADE` (hoy le falta). Los problemas
  de "database is locked / WAL / timeout" de SQLite **desaparecen** (Postgres maneja concurrencia).
- **Red de seguridad:** `tests/test_repositorios_contrato.py` se parametriza para correr contra
  **ambos** backends (Postgres cuando haya BD de test). Garantía de no-regresión del contrato.

## 5. Auth + RBAC

### Verificación del JWT
- Dependencia `usuario_actual` valida `Authorization: Bearer <JWT>` en cada request: firma contra el
  **JWKS** de Supabase (claves asimétricas), `exp`, `aud`, `iss`. Sin token válido → `401`.
- El frontend usa `supabase-js` para login y manejo/refresh de sesión; solo adjunta el bearer a `/api`.

### Roles (tabla `perfiles` en Postgres)
- Clave = `user_id` (UUID de Supabase). Columnas: `rol` (`admin`/`editor`/`consulta`), `estado`
  (`activo`/`inactivo`), `nombre`, `email`, `creado_en`.
- El rol se **consulta en cada request** (barato, sobre el pool). Un cambio de rol o desactivación
  surte efecto **al instante**. (Custom claims en el JWT = optimización futura.)
- Dependencia `requiere_rol(*roles)` protege cada endpoint server-side. La UI esconde botones según
  rol, pero **la barrera real es el backend**.

### Matriz de permisos
| Acción | Consulta | Editor | Admin |
|---|:--:|:--:|:--:|
| Ver insumos, APUs, precios, corridas, cuadros | ✅ | ✅ | ✅ |
| Armar corridas / confirmar ítems / exportar cuadro | ✅ | ✅ | ✅ |
| Crear/importar/editar insumos y APUs, cambiar precios | ❌ | ✅ | ✅ |
| Gestionar usuarios (invitar, cambiar rol, desactivar) | ❌ | ❌ | ✅ |

### Gestión de usuarios (solo Admin)
- Endpoints `/api/usuarios`: listar, **invitar** (Admin API de Supabase con service-role key,
  server-side), cambiar rol, activar/desactivar.
- **Registro público desactivado** en Supabase: solo entra quien el Admin invita.

### Altos estándares (palancas de Supabase que activamos)
- Invitación-solo (sin signup público).
- **MFA (TOTP)** al menos para Admin y Editor.
- Protección de contraseñas filtradas (HaveIBeenPwned) + política de contraseña fuerte.
- Verificación con claves asimétricas (JWKS), tokens de vida corta con rotación de refresh.
- **Service-role key solo en el servidor**, jamás en el frontend.

### Trazabilidad de corridas
- Las corridas guardan `creado_por` (user_id). Por defecto: **todos los roles ven todas las
  corridas** (equipo pequeño y colaborativo), registrando quién la creó y quién la borró. (Si se
  quisiera aislar por usuario, se añade sin reescribir.)

## 6. Auditoría (mutaciones sensibles)

### Qué se registra
| Acción | Detalle capturado |
|---|---|
| Cambio de precio | insumo, **precio antes → después**, fuente |
| Alta/edición de insumo | valores nuevos (y anteriores si es edición) |
| Alta/edición/importación de APU | código, turno, resumen |
| Importación masiva (insumos/APUs) | resumen (creados/actualizados) + nombre de archivo |
| Borrado de corrida | id de corrida, quién la creó |
| Usuarios/roles | invitar, cambiar rol, activar/desactivar (antes→después) |

No se registran lecturas.

### Esquema — tabla `auditoria`
`id`, `ts`, `user_id` + `rol`, `accion`, `entidad_tipo`, `entidad_id`, `antes` (jsonb),
`despues` (jsonb), `contexto` (jsonb: ip, user-agent, archivo…). **Append-only**: la app nunca
actualiza ni borra filas.

### Instrumentación (correctitud)
- Helper `registrar_auditoria(...)` llamado desde la capa de **servicio** (no en `datos/`).
- **La escritura de auditoría comparte la transacción con la mutación**: o se confirman ambas o
  ninguna. El log nunca diverge de la realidad. Los repos Postgres se diseñan desde el inicio para
  aceptar una transacción compartida (unidad de trabajo en el servicio). Sin "best-effort".

### Reutilización
- `insumo_precios` ya versiona precios (fecha, fuente). Se le **añade `creado_por`** (user_id): quién
  cambió el precio queda en el historial y en la auditoría.

### Consulta
- Endpoint `/api/auditoria` (**solo Admin**, lectura) con filtros por usuario, acción, entidad y
  rango de fechas. Retención **indefinida** (append-only, liviana); archivado/purga por antigüedad
  se añade después si hace falta.

## 7. Endurecimiento (internet abierto)

**Tráfico**
- **Rate limiting** (`slowapi`): global por IP + más estricto en subida de Excel, armado de corridas,
  login e invitación de usuarios. Exceso → `429`.
- **Límites de subida**: tamaño máximo configurable (~15 MB), rechazo temprano (sin cargar todo a
  memoria sin tope); validación de extensión/`content-type`; tope de filas/tamaño descomprimido
  (anti *zip-bomb*; openpyxl en modo `read_only`).

**Errores (sin fugas)**
- Capturar errores de openpyxl (`BadZipFile`, `InvalidFileException`) + `ValueError` → **`400` limpio**
  (corrige el 500 por Excel corrupto).
- **Manejador global de excepciones**: mensaje genérico al cliente; traceback completo solo al log
  server-side. El `event: error` del SSE también se vuelve genérico.

**Cabeceras y transporte**
- Middleware: `HSTS`, `X-Content-Type-Options: nosniff`, `X-Frame-Options`/`frame-ancestors`,
  `Content-Security-Policy` restringida al mismo origen, `Referrer-Policy`.
- **HTTPS** forzado por el PaaS (TLS, redirección HTTP→HTTPS).
- **Same-origin**: SPA y API en el mismo origen → sin CORS (sin comodines).

**Observabilidad y secretos**
- **Logging estructurado** (stdlib `logging`) en `servicio/` y `datos/`: request (método, ruta,
  status, latencia, user_id) y errores (traza server-side). Complementa la auditoría. No registrar
  secretos/tokens. La invariante #1 no se afecta (logs server-side; la IA sigue viendo solo lo que
  pasa por `privacy.safe_json`).
- **Secretos por variables de entorno** en el PaaS: `DATABASE_URL`, service-role key, JWKS/JWT de
  Supabase, `ANTHROPIC_API_KEY`. `.env` en `.gitignore`, nunca en el repo.

**Config de servidor**
- uvicorn/gunicorn con varios workers, `reload=False`, `proxy_headers`, timeouts de request y límite
  de concurrencia.

**Calidad de datos**
- La lectura de la lista de licitación deja de convertir en silencio celdas basura a `0.0`: **reporta
  cuántas celdas no se pudieron leer**. Se valida `turno`/`limit`/`offset` en las rutas.

## 8. Migración de datos (SQLite → Supabase)

- **Alcance:** catálogo completo con ediciones; corridas no se migran.
- **Script único** (`run_cli.py migrate-pg` o herramienta aparte): lee las SQLite locales
  (`precios.db`, `apus.db`) y escribe en Supabase.
- **Qué se traslada:** insumos, **historial completo de precios** (`insumo_precios` con `vigente`,
  `fecha`, `fuente`), APUs y composiciones. El historial se lee directo de las tablas (el `Protocol`
  solo expone el precio vigente); a las filas migradas se les pone `creado_por = 'migración'`.
- **Orden:** 1) aplicar esquema en Supabase, 2) migrar datos, 3) verificar.
- **Verificación:** comparar conteos (insumos/precios/APUs/componentes) SQLite vs Postgres +
  spot-check de composición y precio vigente de un par de APUs (vía MCP de Supabase).
- **Idempotencia:** pensado para correr una vez contra esquema limpio; seguro de re-correr (upserts).
  Tras esto, el Excel deja de ser dependencia de runtime.

## 9. Despliegue + Pruebas

**Despliegue**
- **Dockerfile multi-stage**: etapa Node compila `web/dist` → etapa Python sirve FastAPI (`/api`) +
  SPA estático. Un contenedor, un solo origen.
- **PaaS** (Render/Railway/Fly): deploy del contenedor, secretos por env vars, HTTPS automático,
  workers configurables, health-check en `/api/status`.
- **Supabase**: esquema por migraciones (fuente de verdad); conexión por el *pooler*.
- **CI (GitHub Actions)** una vez montado el repo: en cada PR corre `pytest` + tests del frontend +
  lint; **merge bloqueado si algo está en rojo**.

**Pruebas (red de seguridad contra regresiones)**
- Los **161 tests actuales siguen verdes** (innegociable).
- **Contrato** parametrizado sobre ambos backends (SQLite siempre; Postgres cuando hay BD de test).
- **Auth**: JWT válido/expirado/firma mala → `401`; matriz rol×endpoint → `403` donde corresponde.
- **Auditoría**: cada mutación genera su fila con `antes→después`; rollback → sin registro
  (atomicidad).
- **Endurecimiento**: subida sobre el límite → `400/413`; Excel corrupto → `400` (no `500`); rate
  limit → `429`; el manejador no filtra detalles internos.
- **Migración**: correr contra bases temporales y verificar conteos + spot-checks.
- **Invariante #1**: los tests de privacidad actuales se mantienen; **opcional** (defensa en
  profundidad): escaneo de *valores* de texto (no solo de claves) buscando patrones monetarios —
  marcado opcional por riesgo de falsos positivos.

## 10. Invariante #1 y no romper la lógica existente

- La invariante #1 **no se modifica**: `privacy.py`, `ai_assist.py` y las vistas `DePriced*` quedan
  igual; la IA sigue recibiendo solo payloads que pasan por `privacy.safe_json`.
- Todo el cambio es **por adición**: nuevo backend de datos (SQLite intacto para dev/tests), nuevas
  capas de auth/auditoría/endurecimiento en `servicio/`, despliegue. Los tests existentes son el
  contrato de no-regresión.

## 11. Checklist previo a la implementación

- [ ] Trabajar en la rama `feat/produccion-multiusuario` (`master` intacto como respaldo). **Hecho.**
- [ ] **Purgar del historial de git el Excel histórico confidencial**
      (`OBRA-Calle 13-…v2.xlsx`) antes del primer push (nunca se ha subido; historial 100% local).
      Quitarlo del seguimiento, añadirlo a `.gitignore`, y purgar con `git filter-repo`.
- [ ] Añadir `.env` (y variantes) a `.gitignore`.
- [ ] Crear el repo en **GitHub privado** y hacer el primer push **solo tras confirmación explícita**
      del nombre/visibilidad (acción de salida).

## 12. Criterios de éxito

- Login funcional con Supabase; los 3 roles enforced server-side (401/403 correctos).
- Catálogo migrado y verificado en Supabase; corridas nuevas persisten y se costean igual que hoy.
- Toda mutación sensible deja rastro atómico en `auditoria`, consultable por el Admin.
- Endurecimiento activo (rate limit, límites de subida, sin fugas de error, cabeceras, HTTPS).
- **161 tests actuales verdes** + nuevos tests de auth/auditoría/endurecimiento/contrato/migración.
- Invariante #1 intacta.
- Desplegado en PaaS detrás de HTTPS, con secretos solo en variables de entorno.
