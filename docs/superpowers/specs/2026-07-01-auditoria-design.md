# Diseño — Plan 3: Auditoría transaccional de mutaciones sensibles

**Fecha:** 2026-07-01
**Rama:** `feat/auditoria` (desde `master`; Planes 1, 2a, 2b ya fusionados)
**Estado:** aprobado en brainstorming; pendiente plan de implementación.

## 1. Contexto y objetivo

Los Planes 1/2a/2b dejaron: backend Postgres dual (SQLite dev/tests, Postgres prod), auth
JWT/RBAC (`consulta<editor<admin`), y la app usable end-to-end con login. Falta la
**trazabilidad**: quién cambió qué y cuándo sobre datos sensibles (precios de costo, catálogo,
usuarios). Este plan añade un **registro de auditoría append-only**, escrito **en la misma
transacción** que la mutación que audita (sin best-effort), más un endpoint y un visor solo-Admin.

Construye sobre la Sección 6 del spec maestro
(`docs/superpowers/specs/2026-07-01-produccion-multiusuario-design.md`).

**Decisiones aprobadas en brainstorming:**
- **Atomicidad (seam mínimo):** los métodos de escritura auditados ganan un parámetro `conn`
  opcional; la capa de servicio envuelve mutación + auditoría en una unidad de trabajo. Aditivo,
  preserva el comportamiento actual cuando `conn=None`.
- **Granularidad (por-entidad + `lote_id`):** una fila de auditoría por entidad afectada (no
  resumen-por-lote), con un `lote_id` en `contexto` que agrupa las filas de una misma operación por
  lote. Preserva el *partial-success* del código actual y da traza total; el visor colapsa lotes.
- **Visor frontend incluido** en este plan (página Admin `/auditoria`).

**Restricciones:**
- **Invariante #1 intacta:** auditoría vive solo en `servicio/` y `datos/`; NO se toca
  `nucleo/privacy.py`, `ai_assist.py`, ni las vistas `DePriced*`. La IA jamás ve auditoría.
- **Cero regresiones:** 204 tests backend + 18 vitest deben seguir verdes. `conn=None` conserva el
  camino actual de cada repo.
- **Repos duales:** contrato SQLite obligatorio; el parámetro Postgres de los contratos se omite sin
  `TEST_DATABASE_URL` (la máquina local bloquea el egreso a la BD; se valida vía MCP o desde el PaaS).
- **Español** en dominio, comentarios y mensajes.

## 2. El problema central: atomicidad a través de la asimetría de backends

Hoy cada escritura de repo es su **propia** transacción (`with connect()/connection(): ...; commit`).
Para confirmar mutación + auditoría **juntas o ninguna** hacen falta ambas en **una** conexión.

- **Postgres (prod):** todos los repos comparten una `Conexion` (un pool, una BD con schemas
  `precios/apus/corridas/seguridad`). Una conexión ya ve todas las tablas → atomicidad natural.
  `auditoria` vive en el schema `seguridad`.
- **SQLite (dev/tests):** cada dominio es un archivo distinto (`precios.db`, `apus.db`,
  `corridas.db`, `seguridad.db`). Una transacción SQLite no cruza archivos… salvo con
  **`ATTACH DATABASE`** + *master journal*, que sí da commit atómico multi-archivo en modo
  *rollback journal* (el default actual — nunca usamos WAL).

**Mecanismo del seam:** `auditoria` vive junto a `perfiles` (SQLite `seguridad.db`; Postgres schema
`seguridad`). La unidad de trabajo abre **una** conexión sobre el archivo del dominio mutado y, si ese
archivo no es `seguridad.db`, hace `ATTACH DATABASE '<ruta seguridad.db>' AS seg`. Como la tabla
`auditoria` existe **solo** en `seguridad.db`, un `INSERT INTO auditoria` **sin calificar** resuelve
sola por las reglas de resolución de nombres de SQLite (main → temp → attached en orden). Ninguna
tabla de dominio se llama `auditoria`, así que no hay ambigüedad. → **cero prefijos** en el SQL de los
repos; el mismo SQL funciona cuando la base es `seguridad.db` (mutación de usuario, sin attach) y
cuando es otro archivo (attach de `seguridad`).

**Restricción documentada:** no cambiar el `journal_mode` de SQLite a WAL — rompería la atomicidad de
commit multi-archivo vía attach. (Postgres no tiene esta limitación.)

## 3. Unidad de trabajo + parámetro `conn` opcional (seam mínimo)

- **SQLite:** cada repo ya tiene `connect()` (abre archivo, commit al salir, close). Se añade a cada
  repo auditado un context manager `transaccion()` que abre una conexión sobre su archivo, hace
  `ATTACH` de `seguridad.db` si su archivo ≠ `seguridad.db`, cede la conexión, y hace **un solo**
  commit al final (rollback en excepción, `DETACH`/close en `finally`).
- **Postgres:** `Conexion.transaccion()` ya existe (Plan 1) y cede una conexión del pool; todos los
  repos Pg comparten esa `Conexion`, así que una conexión ve todos los schemas.
- **`conn` opcional:** los métodos de escritura auditados aceptan `conn=None`. Si viene, ejecutan
  sobre esa conexión y **no** commitean/cierran (lo hace la UdT). Si es `None`, abren su propia
  conexión como hoy (camino intacto → tests verdes).
- **Métodos tocados (SQLite y Pg):**
  - `PreciosDB/PreciosPg.set_precio_por_id(insumo_id, precio, fuente, fecha=None, conn=None, creado_por=None)`
  - `PreciosDB/PreciosPg.crear_insumo(insumo, conn=None, creado_por=None) -> int`
  - `ApusDB/ApusPg.crear_apu(apu, comps, conn=None) -> None`
  - `CorridasDB/CorridasPg.eliminar_corrida(corrida_id, conn=None) -> bool`
  - `PerfilesDB/PerfilesPg.set_rol(user_id, rol, conn=None)`, `set_estado(user_id, estado, conn=None)`,
    `upsert(perfil, conn=None)`

**Contrato de conexión compartida:** cuando `conn` viene dado, el método usa un helper interno que
ejecuta el SQL sobre `conn` sin `commit`. Se factoriza el cuerpo de cada método para aceptar la
conexión (patrón: `def _op(self, conn, ...)` privado, y el método público decide abrir o reutilizar).

## 4. `insumo_precios.creado_por` — libro mayor de precios (reutilización)

`insumo_precios` ya versiona cada precio (precio, fuente, clasificación, fecha, vigente). Se le añade
la columna **`creado_por TEXT`** (user_id, nullable). Cada nueva fila de precio (vía
`_insertar_precio_vigente`) guarda quién la creó. Así **cada** cambio de precio queda atribuido a
nivel entidad en su ledger natural, independientemente de lo que registre `auditoria`.

- **Migración aditiva:** `ALTER TABLE insumo_precios ADD COLUMN creado_por TEXT` (nullable) en
  `db/precios.sql` (SQLite) y en el esquema Postgres (`db/pg/precios.sql` +
  `supabase/migrations`). Sin tocar filas históricas (quedan `NULL` = origen desconocido/previo).
- `set_precio_por_id`, `crear_insumo`, `set_precio` propagan `creado_por` a
  `_insertar_precio_vigente`. `insert_insumos` (seed) deja `creado_por=NULL` (origen histórico).

## 5. Tabla `auditoria` + `registrar_auditoria(...)`

**Esquema** (`db/seguridad.sql` SQLite; `db/pg/seguridad.sql` + `supabase/migrations` Postgres). JSON
como `TEXT` en SQLite y `jsonb` en Postgres (serialización resuelta en el repo dual):

| Columna | Tipo (SQLite / Pg) | Nota |
|---|---|---|
| `id` | INTEGER PK / BIGSERIAL PK | |
| `ts` | TEXT ISO / timestamptz default now() | |
| `user_id` | TEXT NULL | actor; NULL = sistema (CLI/seed) |
| `user_email` | TEXT NULL | snapshot denormalizado (perfiles puede cambiar) |
| `rol` | TEXT | rol del actor; `"sistema"` si `user_id` NULL |
| `accion` | TEXT | taxonomía `objeto.verbo` (ver §6) |
| `entidad_tipo` | TEXT | `insumo` \| `apu` \| `corrida` \| `usuario` |
| `entidad_id` | TEXT | id/código/user_id de la entidad |
| `antes` | TEXT JSON / jsonb NULL | estado previo (NULL en altas) |
| `despues` | TEXT JSON / jsonb NULL | estado nuevo (NULL en borrados) |
| `contexto` | TEXT JSON / jsonb NULL | `{origen, lote_id, archivo, ...}` |

Append-only por convención (sin endpoints de update/delete). Índices: `(ts)`, `(entidad_tipo, entidad_id)`,
`(user_id)`.

**Repo dual `AuditoriaDB` / `AuditoriaPg`** (implementan un `RepositorioAuditoria` Protocol en
`repository.py`):
- `registrar(conn, evento: EventoAuditoria) -> None` — `INSERT` sobre la conexión de la UdT (nunca
  abre la suya: siempre transaccional con la mutación).
- `listar(filtros) -> tuple[list[dict], int]` — lectura paginada con filtros (abre su propia conexión).
- `init_schema()` / `reset()` — como los demás repos.

`Almacen` gana `self.auditoria` (rama SQLite → `AuditoriaDB` sobre `seguridad.db`; rama Postgres →
`AuditoriaPg` sobre la `Conexion` compartida). `init_schema`/`reset` lo incluyen.

**Helper de servicio** `apu_tool/servicio/auditoria.py`:
```
registrar_auditoria(alm, conn, actor, accion, entidad_tipo, entidad_id,
                    antes=None, despues=None, contexto=None) -> None
```
Construye el `EventoAuditoria` (deriva `user_id/user_email/rol` de `actor: Perfil | None`; `None` →
`rol="sistema"`) y llama `alm.auditoria.registrar(conn, evento)`. Si falla, la excepción propaga y la
UdT revierte **todo** (sin best-effort).

**Modelo** `EventoAuditoria` (dataclass en `nucleo/models.py`, sin dinero → no afecta invariante #1).

## 6. Instrumentación por acción

Cada función de servicio auditada gana `actor: Perfil | None = None` (kwarg final → retrocompatible;
`rutas.py` pasa `actor=usuario_actual`; CLI/seed no pasan nada → `None`). Para operaciones por lote se
genera un `lote_id` (uuid4) que va en `contexto` de cada fila del lote, junto a `contexto.origen`.

| Acción (`accion`) | entidad_tipo | antes → después | contexto |
|---|---|---|---|
| `precio.editar` | insumo | `{precio,fuente}` viejo → nuevo | `{origen: "edicion", lote_id}` |
| `insumo.crear` | insumo | `null` → insumo | `{origen: individual\|import, lote_id?}` |
| `apu.crear` | apu | `null` → `{..., n_componentes}` | `{origen: individual\|import, lote_id?}` |
| `corrida.eliminar` | corrida | resumen corrida → `null` | — |
| `usuario.invitar` | usuario | `null` → `{email,rol,estado}` | — |
| `usuario.cambiar_rol` | usuario | `{rol}` → `{rol}` | — |
| `usuario.cambiar_estado` | usuario | `{estado}` → `{estado}` | — |

**Servicios tocados:**
- `insumos.aplicar_cambios(alm, cambios, actor=None)` — el bucle envuelve **cada** ítem en
  `alm.precios.transaccion()`: lee estado previo (`get_insumo_por_id`), aplica
  `set_precio_por_id(..., conn=conn, creado_por=(actor.user_id if actor else None))`, registra
  `precio.editar` con `conn`. Un ítem fallido revierte **solo ese ítem** (partial-success intacto).
  `lote_id` compartido por la operación; `origen="edicion"` fijo — los tres flujos de precio
  (edición interactiva, import por código, transformación) caen todos en `POST /insumos/cambios` y el
  backend no los distingue. Distinguir sub-orígenes se difiere (requeriría un hint del frontend); la
  procedencia granular de cada precio ya vive en `insumo_precios.creado_por`.
- `autoria.crear_insumo` / `crear_apu` — una transacción: crear + `registrar_auditoria`.
- `autoria.aplicar_importar_insumos` / `aplicar_importar_apus` — bucle con transacción por ítem
  (partial-success intacto), `lote_id` compartido, `contexto.origen="import"`, `archivo` en contexto.
- `corridas.eliminar_corrida(alm, corrida_id, actor=None)` — lee resumen de la corrida, borra +
  registra en una transacción.
- `usuarios.cambiar_rol` / `cambiar_estado` / `invitar` — ya reciben `actor`; envuelven mutación +
  auditoría en `alm.perfiles.transaccion()`. `invitar`: la creación en Supabase (HTTP) ocurre **antes**
  de abrir la transacción; solo el `upsert` local + auditoría son transaccionales (el efecto externo no
  es reversible, se documenta).

## 7. `GET /api/auditoria` (solo-Admin)

En `rutas.py`, `Depends(requiere_rol("admin"))`. Query params: `user_id`, `accion`, `entidad_tipo`,
`desde`, `hasta`, `lote_id`, `limit` (default 100), `offset` (default 0). Devuelve
`{items: [...], total, limit, offset}` ordenado por `ts` desc. Delegado a un servicio
`auditoria.listar(alm, filtros)` que llama `alm.auditoria.listar(...)` y serializa (parsea los JSON de
`antes/despues/contexto` a objetos en la respuesta).

## 8. Visor de auditoría (frontend)

- **`web/src/api/auditoria.ts`** (nuevo): tipos `EventoAuditoria`/`AuditoriaFiltros` + `listar()` vía
  `client.ts` (Bearer).
- **`web/src/pages/Auditoria.tsx`** (nuevo, ruta `/auditoria`, `RequiereRol minimo="admin"`): tabla
  densa (table-first, sin cards): fecha · usuario (email·rol) · acción · entidad · antes→después.
  Filtros arriba (usuario, acción, tipo de entidad, rango de fechas). Filas de un mismo `lote_id`
  colapsables ("importación de N insumos ▸"). Paginado.
- **`Layout.tsx`**: link "Auditoría" en el sidebar **solo si Admin** (junto a "Usuarios").
- **`App.tsx`**: ruta `/auditoria` bajo `<RequiereRol minimo="admin">`.
- Acabado con la skill **frontend-design**, coherente con Usuarios/Insumos.

## 9. Pruebas y no-romper

**Backend (pytest, SQLite):**
- **Atomicidad (clave):** forzar que el `INSERT` de auditoría falle dentro de la UdT (monkeypatch de
  `registrar`) → aserción: la mutación **tampoco** persiste; y el caso inverso (mutación falla →
  auditoría no queda). Valida ATTACH + rollback real multi-archivo.
- Cada acción auditada escribe la fila correcta (accion/entidad/antes/después/actor/lote_id).
- `registrar_auditoria` con `actor=None` → `user_id=NULL`, `rol="sistema"`.
- Partial-success preservado: `aplicar_cambios` con un ítem inválido → los válidos se aplican y se
  auditan, el inválido no.
- `GET /api/auditoria`: filtros; solo-Admin (403 para editor/consulta, 200 para admin) vía el override
  del `conftest`.
- `insumo_precios.creado_por` se guarda en cambios de precio.
- Contrato del repo dual de auditoría (SQLite ejecuta; el caso Postgres se marca skip sin
  `TEST_DATABASE_URL`).

**Frontend (vitest, sin red):** `Auditoria.tsx` lista, filtra y colapsa lotes; ruta solo-Admin. Los 18
vitest existentes siguen verdes.

**No romper:** `conn=None` conserva el camino de cada repo (204 tests intactos). Migración
`creado_por` aditiva nullable. Invariante #1 intacta (auditoría solo en servicio/datos; no toca
`privacy`/`ai_assist`/`DePriced*`). Disciplina de commit: `git add` **solo** los archivos de cada
tarea (nunca `-A`/`.`/`-u`; hay cruft ignorado y `ejemplos/*.xlsx` modificado fuera de alcance).

## 10. Criterios de éxito

- Un cambio de precio, alta/edición de insumo o APU, borrado de corrida, e invitación/cambio de
  rol/estado de usuario dejan **una fila de auditoría** con actor, antes→después y timestamp, en la
  **misma transacción** que la mutación.
- Si la auditoría no se puede escribir, la mutación **no** ocurre (y viceversa) — verificado con test
  en SQLite.
- `GET /api/auditoria` responde solo a Admin, con filtros; el visor `/auditoria` muestra y filtra el
  historial y colapsa lotes.
- `insumo_precios.creado_por` atribuye cada precio.
- 204 tests backend + 18 vitest verdes + build OK; invariante #1 intacta.

**Diferido:** retención/archivado de auditoría (append-only sin poda por ahora); exportar auditoría a
Excel; auditar lecturas (solo se auditan mutaciones); reversión externa de Supabase en `invitar`.
