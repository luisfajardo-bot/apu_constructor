# Diseño — Carpetas para organizar corridas en subproyectos

**Fecha:** 2026-07-09
**Estado:** aprobado (brainstorming)

## Objetivo

Permitir agrupar las corridas en **carpetas anidadas de hasta 2 niveles** para
separar subproyectos, p. ej. `Calle_13 > Lote_3 > (corridas)`. Hoy las corridas
son una lista plana (`MisCorridas.tsx`, tabla `corrida`); no existe agrupación.

## Requisitos (decisiones del brainstorming)

- Carpetas **genéricas anidadas**, profundidad **máx. 2 niveles** (no taxonomía fija).
- Carpetas **globales**: todo el equipo ve el mismo árbol y las mismas corridas.
- Toda corrida vive **dentro de una carpeta** (nivel 1 o 2), **nunca en la raíz**.
- **Crear** carpetas: cualquier usuario (`consulta`+), incluso **al vuelo** al crear la corrida.
- **Renombrar / mover / borrar** carpetas y **reubicar** corridas: `editor` / `admin`.
- **Borrar carpeta:** bloqueado si no está vacía (tiene subcarpetas o corridas).
- **Corridas existentes** (sin carpeta): migran automáticamente a una carpeta
  raíz **"Sin clasificar"** que luego un editor/admin reorganiza.

## 1. Modelo de datos

Nueva tabla `carpeta` (en `db/corridas.sql` SQLite y `db/pg/corridas.sql` Postgres):

| Campo | Tipo | Notas |
|---|---|---|
| `id` | PK autoincrement | |
| `nombre` | TEXT NOT NULL | |
| `parent_id` | FK→carpeta(id) NULL, `ON DELETE RESTRICT` | NULL = nivel 1; con valor = nivel 2 |
| `creada_en` | TEXT NOT NULL | |
| `creado_por` | TEXT | como `corrida.creado_por` en PG |

- **Unicidad de hermanas:** índice único sobre `(COALESCE(parent_id, 0), nombre)` —
  no dos carpetas con el mismo nombre bajo el mismo padre (incluida la raíz; los
  `NULL` se normalizan a 0 porque SQLite/PG tratan `NULL` como distintos en UNIQUE).
- **`corrida` gana `carpeta_id`** FK→carpeta(id) `ON DELETE RESTRICT`. A nivel DB
  queda **nullable** para simplificar la migración (SQLite no agrega `NOT NULL` a
  tablas con filas fácilmente); la **capa de servicio garantiza** que toda corrida
  nueva tenga carpeta.
- **Profundidad máx. 2:** se valida en servicio (una carpeta con `parent_id` no
  NULL no puede ser padre). No hay columna `nivel`: se deduce de `parent_id`.

## 2. Persistencia y servicio (backend)

**Repositorio** (respetando el aislamiento en `repositorio.py`):

- Nuevo `Protocol` `RepositorioCarpetas` en `repositorio.py`, implementado en
  `apu_tool/datos/carpetas_db.py` (SQLite) y `apu_tool/datos/pg/carpetas_pg.py`
  (Postgres), cableado en `Almacen` como `alm.carpetas`.
- Métodos: `crear`, `renombrar`, `mover`, `eliminar`, `listar_arbol`, `get`,
  `contar_hijas`, `contar_corridas`, `mover_corrida`.
- `CorridaMeta` y `listar_corridas` / `vista_corrida` incluyen `carpeta_id`.

**Servicio** `apu_tool/servicio/carpetas.py` (orquesta reglas + auditoría, como `corridas.py`):

- `crear_carpeta(nombre, parent_id)` — valida profundidad y unicidad de hermanas.
  Permitido a `consulta`+.
- `renombrar`, `mover_carpeta`, `eliminar_carpeta`, `mover_corrida` — **`editor` / `admin`**.
- `eliminar_carpeta` — bloquea si `contar_hijas > 0` o `contar_corridas > 0`
  (`RESTRICT` en DB es el respaldo).
- `mover_carpeta` — una carpeta de nivel 1 **con hijas** no puede volverse
  subcarpeta (rompería la profundidad); validación en servicio.
- Cada mutación llama `registrar_auditoria` (la app ya audita corridas/usuarios).

**Creación al vuelo:** el frontend hace dos llamadas — `POST /carpetas` (crea,
`consulta`+) y luego crea la corrida pasando `carpeta_id`. Así los endpoints de
corrida se mantienen delgados y no duplican lógica de carpetas.

## 3. API (endpoints)

Nuevos en `rutas.py` (delgados, delegan en `servicio/carpetas.py`):

| Método | Ruta | Rol | Acción |
|---|---|---|---|
| `GET` | `/carpetas` | `consulta` | árbol completo con conteos |
| `POST` | `/carpetas` | `consulta` | crear (body: `nombre`, `parent_id?`) |
| `PATCH` | `/carpetas/{id}` | `editor` | renombrar / mover (`nombre?`, `parent_id?`) |
| `DELETE` | `/carpetas/{id}` | `editor` | borrar (409 si no está vacía) |
| `POST` | `/corridas/{cid}/mover` | `editor` | reubicar corrida (`carpeta_id`) |

- `POST /corridas` y `/corridas/stream` ganan `carpeta_id` (Form) **obligatorio**;
  si falta o no existe → 400.
- `GET /corridas` sigue devolviendo lista plana, ahora con `carpeta_id` por fila
  (el frontend agrupa/navega).
- Errores coherentes con el patrón actual (`HTTPException`): 400 validación,
  403 rol, 404 no existe, 409 carpeta no vacía / nombre duplicado.
- **RLS Supabase** (`supabase/migrations/`): nueva migración para `carpetas.carpeta`
  — lectura global, escritura según rol, en línea con `0003_rls.sql`.

## 4. Frontend (React/TS)

**Navegación en `MisCorridas.tsx`** (2 niveles, estilo explorador):

- **Breadcrumb** arriba: `Todas › Calle_13 › Lote_3`. Al entrar a una carpeta se
  listan sus **subcarpetas** (como filas/tarjetas arriba) y sus **corridas** (la
  tabla actual, sin cambios en columnas/totales).
- Botón **"Nueva carpeta"** (`consulta`+) en el nivel actual. Acciones
  **renombrar / mover / borrar** por carpeta visibles solo a `editor` / `admin`.
- Estado de navegación por URL (`/corridas?carpeta=ID`) para que sea enlazable y
  sobreviva refresh.

**Nueva corrida** (`CorridasInicio.tsx` / flujo de creación):

- Selector de carpeta (árbol o dos `select` encadenados nivel1→nivel2) + opción
  **"crear carpeta nueva"** al vuelo (llama `POST /carpetas` y usa el `carpeta_id`
  resultante). Obligatorio elegir carpeta antes de armar.

**Reubicar corrida:** acción "Mover" en la fila (o en el detalle), `editor`+.

**Capas de apoyo:**

- `web/src/api/carpetas.ts` — CRUD del árbol + `moverCorrida`.
- `web/src/lib/tipos.ts` — tipo `Carpeta` (con conteos) y `carpeta_id` en `CorridaResumen`.

## 5. Migración y pruebas

- **Migración:** `init_schema` crea la carpeta **"Sin clasificar"** (raíz) si no
  existe y backfilea `carpeta_id` de las corridas con NULL. Idempotente, corre en
  cada boot (patrón actual de `ALTER … ADD COLUMN IF NOT EXISTS`).
- **Pruebas backend:** profundidad máx. 2, unicidad de hermanas, borrado bloqueado
  si no vacía, `mover_carpeta` inválido, backfill de migración, RBAC (`consulta`
  crea pero no renombra/mueve/borra), entradas de auditoría.
- **Pruebas frontend:** navegación por carpetas, crear carpeta, listado dentro de
  carpeta, crear corrida exige carpeta.

## Fuera de alcance (YAGNI)

- Más de 2 niveles de anidamiento.
- Carpetas privadas por usuario / permisos por carpeta.
- Arrastrar y soltar (drag & drop); mover es vía acción explícita.
- Borrado en cascada de carpetas.
