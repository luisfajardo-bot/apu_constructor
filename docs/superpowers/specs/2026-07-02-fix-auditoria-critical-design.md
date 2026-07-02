# Diseño — Plan A: arreglar los 3 Critical de la auditoría

**Fecha:** 2026-07-02
**Rama:** `fix/auditoria-critical` (desde `master`; Planes 1–4 ya fusionados, `c5b7214`)
**Estado:** aprobado en brainstorming; pendiente plan de implementación.
**Origen:** auditoría de código `docs/auditoria-codigo-2026-07-01.md` (hallazgos C1, C2, C3).

## 1. Contexto y principio

La auditoría post-Plan 4 encontró 3 fallos **Critical**, todos por **asunciones de SQLite que se
colaron por encima de la frontera del `Protocol`** (los repos Postgres no tienen `.path`/`.connect()`;
la carpeta de migraciones Supabase quedó inconsistente). En el backend Postgres (producción) los
comandos `status` y `db check` crashean, y la ruta de provisión por `supabase db push` está rota.

**Principio del fix:** extender `apu_tool/datos/repositorio.py` con métodos **backend-agnósticos** e
implementarlos en ambos backends. **Nunca** parchear con `isinstance`/`hasattr`. TDD por bug: el test
que reproduce el fallo es el **contrato dual** (corre en SQLite; el caso Postgres se ejercita en CI con
el contenedor `postgres:17`, ya montado en el Plan 4).

**Alcance:** SOLO los 3 Critical (C1, C2, C3). Los 8 Important + 7 Minor (incluido I8, ya decidido:
documentar la dependencia de topología de `--forwarded-allow-ips`) van en el **Plan B**, su propio
ciclo spec→plan→ejecución, tras fusionar este.

**Restricciones:** Invariante #1 intacta (NO tocar `apu_tool/dominio/privacy.py`, `ai_assist.py`, vistas
`DePriced*`); CERO regresiones (249 tests backend + 19 vitest verdes) + AÑADIR tests que cubran cada
bug; español; ejecución con subagentes; disciplina de commit estricta.

## 2. C1 — `status` backend-agnóstico

**Bug:** `apu_tool/interfaz/cli.py:65-66` (`cmd_status`) imprime `alm.precios.path` / `alm.apus.path`;
`PreciosPg`/`ApusPg` no tienen `.path` → `AttributeError` en Postgres.

**Fix:**
- Añadir `descripcion() -> str` al Protocol `RepositorioPrecios` y `RepositorioApus`
  (`apu_tool/datos/repositorio.py`).
- Implementar en los 4 repos:
  - `PreciosDB.descripcion()` → `f"SQLite: {self.path}"`; `ApusDB.descripcion()` → igual con su `path`.
  - `PreciosPg.descripcion()` → `"Postgres (schema precios)"`; `ApusPg.descripcion()` → `"Postgres (schema apus)"`.
- `cmd_status` usa `alm.precios.descripcion()` / `alm.apus.descripcion()` en vez de `.path`.

**Tests:** contrato dual (`descripcion()` devuelve un `str` no vacío en ambos backends; Pg skip sin
`TEST_DATABASE_URL`); smoke de `cmd_status` sobre un `Almacen` SQLite (retorna 0, sin `AttributeError`).

## 3. C2 — integridad por el Protocol

**Bug:** `apu_tool/dominio/integridad.py:20-24` (`revisar`) hace `with almacen.apus.connect() as ca`
+ SQL crudo sobre `apu_componentes` (sin calificar). `ApusPg` no tiene `.connect()`; la tabla en
Postgres es `apus.apu_componentes` → crash + tabla inexistente en el `search_path`.

**Fix:**
- Añadir `componentes_para_integridad() -> list[tuple[str, str]]` al Protocol `RepositorioApus`:
  devuelve `(insumo_codigo, insumo_nombre)` de cada componente con `insumo_codigo` no nulo/no vacío.
- Implementar en `ApusDB` (SQL actual, tabla `apu_componentes`) y `ApusPg` (`apus.apu_componentes`,
  `%s`), ambos devolviendo `list[tuple[str, str]]` (mismo orden/forma).
- `integridad.revisar` itera sobre `almacen.apus.componentes_para_integridad()` en vez de abrir
  conexión y hacer SQL crudo. El resto de `revisar` (que usa `almacen.precios.get_candidatos` +
  `cruce.resolver`, ya del Protocol) no cambia.

**Tests:** contrato dual del nuevo método (SQLite devuelve las tuplas esperadas de una base sembrada;
Pg skip/CI); `integridad.revisar` corre sobre un `Almacen` con datos y devuelve el dict esperado sin
`AttributeError`.

## 4. C3 — reconciliar migraciones + migrate-pg + README

**Bug:** `supabase/migrations/0002_rls.sql` hace `ALTER TABLE seguridad.perfiles ENABLE RLS`, pero
ninguna migración numerada crea `seguridad.perfiles` (0001 = precios/apus/corridas; 0003 = solo
`seguridad.auditoria`). `db/pg/seguridad.sql` (que sí define `perfiles`) no es una migración, y
`cmd_migrate_pg` (`cli.py:191`) solo aplica `precios.sql`/`apus.sql`/`corridas.sql`. La app sí
autoprovisiona el esquema al arrancar (`create_app`→`init_schema`→`perfiles.init_schema`), pero la
ruta `supabase db push` está rota y el README afirma en falso que "el esquema ya está aplicado".

**Fix (reconciliación completa; historial de migraciones vacío → renombrar es seguro; DDL idempotente
→ seguro re-aplicar contra "BASE APUS"):**
- Reorganizar `supabase/migrations/` a un set ordenado y consistente que refleje `db/pg/*.sql`:
  - `0001_esquema_inicial.sql` — precios + apus + corridas (**sin cambios**).
  - `0002_seguridad.sql` (**nuevo**) — `CREATE SCHEMA IF NOT EXISTS seguridad` + tabla `perfiles`
    (con su `CHECK` de rol/estado) + tabla `auditoria` (11 columnas + 3 índices), **antes** del RLS.
    Contenido idéntico a `db/pg/seguridad.sql`.
  - `0003_rls.sql` (**renombrado** de `0002_rls.sql`, extendido) — `ENABLE ROW LEVEL SECURITY` en las
    **11** tablas: precios (insumos, insumo_precios, meta), apus (apus, apu_componentes, meta),
    corridas (corrida, corrida_item), seguridad (perfiles, auditoria).
  - **Eliminar** `0003_auditoria.sql` (su tabla se movió a `0002_seguridad.sql`; su `ENABLE RLS` de
    auditoria se absorbe en `0003_rls.sql`).
- `cmd_migrate_pg` (`cli.py:189-192`): añadir `"seguridad.sql"` al bucle de esquemas aplicados
  (`("precios.sql", "apus.sql", "corridas.sql", "seguridad.sql")`), para que la ruta de migración
  cree perfiles+auditoría. Extraer esa tupla a una constante de módulo para poder aserirla en test.
- **README.md**: corregir la sección de despliegue — el esquema Postgres lo provisiona el arranque de
  la app (`init_schema`) y/o `migrate-pg`; `supabase/migrations/` es la fuente para `supabase db push`
  y ahora es internamente consistente (perfiles antes del RLS).

**Tests:**
- `cmd_migrate_pg` referencia una constante `ESQUEMAS_PG` que **incluye `"seguridad.sql"`** (aserción
  directa sobre la constante — no requiere Postgres).
- Consistencia de `supabase/migrations/`: un test lee los `.sql` en orden y verifica que
  `seguridad.perfiles` se **crea** (aparece un `CREATE TABLE ... perfiles`) en un archivo **anterior**
  al que hace `ALTER TABLE seguridad.perfiles ... ROW LEVEL SECURITY` (evita la regresión de orden).
- El job Postgres del CI (Plan 4) ejercita `migrate-pg` completo contra `postgres:17` (validación real
  de que perfiles+auditoría se crean por esa ruta).

## 5. No romper + criterios de éxito

**No romper:** los nuevos métodos son adiciones al Protocol (no cambian firmas existentes); `cmd_status`
e `integridad.revisar` mantienen su salida/contrato observable en SQLite. Reorganizar `supabase/migrations/`
no afecta el runtime de la app (que usa `db/pg/*.sql` vía `init_schema`, no la carpeta de migraciones).
249 tests backend + 19 vitest siguen verdes. Invariante #1 intacta.

**Éxito:**
- `python run_cli.py status` y `python run_cli.py db check` corren sin crash con backend Postgres
  (verificado en CI; localmente el contrato dual cubre los métodos nuevos en SQLite).
- `supabase/migrations/` es consistente: `perfiles` se crea antes de que el RLS la referencie; la
  carpeta refleja `db/pg/*.sql`.
- `migrate-pg` aplica `seguridad.sql` (perfiles+auditoría) además de precios/apus/corridas.
- README veraz sobre la provisión del esquema.
- Suite verde; invariante #1 intacta.

**Diferido al Plan B:** los 8 Important (I1 TOCTOU último-admin, I2 bootstrap sin auditar, I3 descarga
401, I4 visor agrupa mal, I5 LIKE/ILIKE, I6 migrate-pg no idempotente, I7 bypass subida, I8 XFF —
documentar) + los 7 Minor.
