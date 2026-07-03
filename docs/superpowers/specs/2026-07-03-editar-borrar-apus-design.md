# Diseño — Editar y borrar APUs (biblioteca)

> Fecha: 2026-07-03
> Estado: propuesto (pendiente de revisión del usuario)
> Antecede: `2026-07-02-alta-de-apus-design.md`, que dejó fuera de alcance la edición
> y el borrado de APUs. La **alta** (crear + importar) ya está construida en
> `servicio/autoria.py`; este spec cierra el CRUD con **editar** y **borrar**.
> Rama de trabajo: `feat/editar-borrar-apus` (parte del código ya en producción;
> se coordina el redeploy con el usuario).

## Objetivo

Hoy la biblioteca de APUs (`apus.db` / schema `apus` en Postgres) se puebla con `seed`
(carga masiva) y con la **alta** ya construida: crear un APU individual, crear un insumo
al vuelo e importar APUs desde Excel en modo agregar (`servicio/autoria.py`). **Falta la
otra mitad del CRUD**: no hay forma de **editar** un APU existente (cabecera y composición)
ni de **borrarlo** salvo tocando la base a mano.

Este proyecto agrega **editar** y **borrar** APUs, end-to-end, respetando la realidad
actual del proyecto que el spec anterior (pensado local/SQLite/sin login) no contemplaba:

- **Doble backend**: SQLite (`apus_db.py`) **y** Postgres (`apus_pg.py`); producción corre
  en Postgres/Supabase.
- **Auth/RBAC + auditoría**: toda mutación pasa por rol y deja rastro (`registrar_auditoria`).
- **Corridas ya existentes**: editar o borrar un APU **no** rompe corridas ya armadas,
  porque cada ítem recostea desde su **foto guardada** (`corrida_item.componentes`), no
  desde la biblioteca.

La UI sigue la estética ya establecida: **práctica, densa, orientada a tabla, sin cards**,
y reutiliza la pantalla `web/src/pages/Apus.tsx` que ya existe.

## Decisiones de alcance

| Decisión | Elección |
|----------|----------|
| Qué es editable | **Cabecera** (nombre, unidad, grupo) **+ composición completa** (agregar/quitar insumos, cambiar rendimiento). |
| Identidad | `codigo` + `turno` son la identidad y **no se editan** (para cambiarlos: borrar + crear). |
| Composición al editar | Se **reemplaza entera** (borra las filas de ese `(codigo, shift)` y reinserta con `seq` 0..n), misma mecánica que `crear_apu`. |
| Borrado | **Hard delete** (borra componentes + cabecera). Las corridas ya armadas conservan su foto y no se ven afectadas. |
| Aviso al borrar | El diálogo informa **cuántas corridas** referencian el APU (señal, no bloqueo) vía `contar_items_por_apu`. |
| Permisos | **Editar** = rol `editor` (igual que crear). **Borrar** = rol `admin` (un escalón más, por ser destructivo). |
| Backends | Se implementa en **SQLite y Postgres** y se declara en el `Protocol` de `repositorio.py`. |
| Esquema/migración | **Ninguna**: editar/borrar usan las tablas existentes (`apus`, `apu_componentes`) tal cual. |
| Enfoque de código | **Extender `autoria.py`** (junto a `crear_apu`) + métodos nuevos en la capa de datos. |
| Despliegue | Producción (Render + Supabase). `npm run build` + redeploy; sin migración de datos. |

**Fuera de alcance:** cambiar `codigo`/`turno` de un APU existente (= borrar + crear);
mejoras al import (política "reemplazar", leer hojas de insumos); versionado/historial de
composición más allá de la auditoría existente; **editar o reasignar APUs desde la corrida**
(spec prioritario aparte: "Reasignar/editar APU desde la corrida"); estados de corrida
activa/congelada (Spec 2).

## Arquitectura y estructura de archivos

El dominio (matching, pricing, assemble, ai_assist) **no se toca**. Editar/borrar es edición
pura de la biblioteca y **no roza la IA** (invariante #1 intacto). Se extiende el módulo de
autoría que ya concentra crear/importar, apoyado en dos métodos nuevos en la capa de datos.

```
apu_tool/datos/apus_db.py         + editar_apu, borrar_apu           [SQLite]
apu_tool/datos/pg/apus_pg.py      + editar_apu, borrar_apu           [Postgres, port 1:1]
apu_tool/datos/corridas_db.py     + contar_items_por_apu             [SQLite]
apu_tool/datos/pg/corridas_pg.py  + contar_items_por_apu             [Postgres]
apu_tool/datos/repositorio.py     + editar_apu, borrar_apu en RepositorioApus;
                                    + contar_items_por_apu en RepositorioCorridas
apu_tool/servicio/autoria.py      + editar_apu, borrar_apu (servicio, auditado)
apu_tool/servicio/rutas.py        + PUT /api/apus/{codigo}/{turno}, DELETE /api/apus/{codigo}/{turno}
apu_tool/servicio/esquemas.py     + ApuEditIn (reusa ComponenteIn de ApuNuevoIn)

web/src/api/autoria.ts            + editarApu, borrarApu (junto a listarApus/getApuDetalle/crearApu)
web/src/pages/Apus.tsx            + acciones Editar (editor) y Borrar (admin) por fila
web/src/components/autoria/DialogoAgregarApu.tsx  + modo edición (precarga, codigo/turno fijos)
web/src/components/autoria/DialogoBorrarApu.tsx   [nuevo] confirmación de borrado con n_corridas
web/src/lib/tipos.ts              + tipo del payload de edición (reusa ApuResumen/ApuDetalle)
```

> Nota de verificación (2026-07-03): el cliente web de APUs vive en `web/src/api/autoria.ts`
> (no en un `apus.ts`), y el formulario de alta es `DialogoAgregarApu.tsx` en
> `web/src/components/autoria/`. El spec apunta a esos archivos reales para no duplicar.

## Capa de datos

### `ApusDB` (`apus_db.py`) y `ApusPg` (`apus_pg.py`)
Dos métodos nuevos, simétricos a `crear_apu` (que ya existe en ambos backends). El esquema
(`db/apus.sql`, `db/pg/apus.sql`) **no cambia**.

- **`editar_apu(apu: Apu, componentes: list[ApuComponent], conn=None) -> None`**
  - `ValueError` si `(codigo, shift)` **no** existe (el servicio lo traduce a 404).
  - `UPDATE apus SET nombre, unidad, grupo` para ese `(codigo, shift)` (no toca `codigo`/`shift`).
  - **Borra** las filas de `apu_componentes` de ese `(codigo, shift)` y **reinserta** la lista
    con `seq` 0..n (mismo patrón que `_crear_apu`).
  - Atómico: si se pasa `conn`, opera sobre esa conexión (transaccional con la auditoría);
    si no, abre la suya.
- **`borrar_apu(codigo: str, shift: str, conn=None) -> bool`**
  - Borra primero `apu_componentes` de ese `(codigo, shift)`, luego la fila de `apus`
    (orden explícito; no depende de `ON DELETE CASCADE`).
  - Devuelve `False` si el APU no existía (nada que borrar).

No se agrega `exists_apu`: `get_apu()` ya devuelve `None` y sirve de chequeo de existencia.

### `CorridasDB` (`corridas_db.py`) y `CorridasPg` (`corridas_pg.py`)
- **`contar_items_por_apu(apu_codigo: str) -> int`** — `SELECT COUNT(*) FROM corrida_item
  WHERE apu_codigo = ?`. Lectura pura (sin DDL); alimenta el aviso del borrado.

### `repositorio.py` (Protocols)
- `RepositorioApus` += `editar_apu`, `borrar_apu`.
- `RepositorioCorridas` += `contar_items_por_apu`.

## Servicio — `apu_tool/servicio/autoria.py`

Se extiende el módulo que ya tiene `crear_apu` (mismo patrón: validar → `alm.transaccion(...)`
→ mutación + `registrar_auditoria`). Reusa `_componentes_de` (resuelve nombre/unidad desde el
catálogo y valida `rendimiento > 0`).

Convención de errores (alineada al patrón existente): **no encontrado → el servicio
devuelve `None`** (el endpoint responde 404); **error de validación → `ValueError`**
(el endpoint responde 400, igual que `crear_apu`). Así el endpoint distingue 404 de 400
sin ambigüedad.

- **`editar_apu(alm, codigo, shift, datos, actor=None) -> dict | None`**
  - Normaliza `codigo`/`shift`; valida `nombre` obligatorio; `turno` inmutable (se toma del path).
  - Si el APU no existe (`get_apu` → `None`) → **devuelve `None`** (endpoint 404); no muta nada.
  - Lee el estado previo (`get_apu` + `get_components`) para el `antes=` de auditoría.
  - Construye `comps = _componentes_de(alm, datos["componentes"], shift)` — errores de
    validación (nombre vacío, `rendimiento ≤ 0`) suben como `ValueError` (endpoint 400).
  - Dentro de `alm.transaccion("apus")`: `alm.apus.editar_apu(apu, comps, conn=conn)` +
    `registrar_auditoria(alm, conn, actor, "apu.editar", "apu", codigo, antes=…, despues=…)`.
  - Devuelve `{codigo, shift, nombre, unidad, grupo, n_componentes}`.
- **`borrar_apu(alm, codigo, shift, actor=None) -> dict | None`**
  - Si el APU no existe (`get_apu` → `None`) → **devuelve `None`** (endpoint 404).
  - Toma la foto previa (cabecera + `n_componentes`) y `n_corridas = alm.corridas.contar_items_por_apu(codigo)`.
  - Dentro de `alm.transaccion("apus")`: `alm.apus.borrar_apu(codigo, shift, conn=conn)` +
    `registrar_auditoria(alm, conn, actor, "apu.borrar", "apu", codigo, antes=foto, despues=None,
    contexto={"n_corridas": n_corridas})`.
  - Devuelve `{borrado: True, n_corridas}`.

Nota sobre la capa de datos: `apus.editar_apu` conserva el `raise ValueError` si el
`(codigo, shift)` no existe (defensa en profundidad), pero el servicio ya evita llegar ahí
al chequear con `get_apu` primero y devolver `None`.

## API — `apu_tool/servicio/rutas.py`

Simétrica a lo que ya existe (`GET /apus`, `GET /apus/{codigo}/{turno}`, `POST /apus/crear`).

| Método + ruta | Rol | Hace |
|---|---|---|
| `PUT /api/apus/{codigo}/{turno}` | `editor` | editar cabecera + reemplazar composición; `404` si no existe; `400` en validación |
| `DELETE /api/apus/{codigo}/{turno}` | `admin` | borrar; `404` si no existe; devuelve `{borrado, n_corridas}` |

`GET /api/apus/{codigo}/{turno}` (detalle, ya existe, rol `consulta`) precarga el formulario
de edición. El gating usa el helper existente `requiere_rol(...)` que devuelve el `actor`.

**Mapeo de errores en el endpoint** (patrón ya usado por `crear_apu`/`detalle_apu`): envuelve
la llamada al servicio en `try/except ValueError → 400`; si el servicio devuelve `None`,
responde `404`; si no, devuelve el `dict`. Ejemplo para `PUT`:

```python
try:
    r = autoria.editar_apu(alm, codigo, turno, body.model_dump(), actor=actor)
except ValueError as e:
    raise HTTPException(status_code=400, detail=str(e))
if r is None:
    raise HTTPException(status_code=404, detail="APU no encontrado.")
return r
```

### DTO — `apu_tool/servicio/esquemas.py`
`ApuEditIn { nombre: str, unidad: str, grupo: str, componentes: list[ComponenteIn] }` — igual
a `ApuNuevoIn` pero **sin** `codigo`/`turno` (vienen del path). Reusa el `ComponenteIn`
existente. Validación: `nombre` no vacío; cada componente con `insumo_codigo` no vacío y
`rendimiento > 0` (lo aplica `_componentes_de`).

## Frontend — pantalla "APUs"

Reutiliza `web/src/pages/Apus.tsx` (que ya usa `listarApus`/`getApuDetalle` de
`@/api/autoria`, los tipos `ApuResumen`/`ApuDetalle` de `@/lib/tipos`, `DialogoAgregarApu`/
`DialogoImportarApus` de `@/components/autoria/`, y el gating `puede` de `@/components/rutas`
con `useAuth` de `@/lib/auth`). Nada nuevo de estética.

- **`web/src/api/autoria.ts`** — agregar `editarApu(codigo, turno, datos)` → `PUT`;
  `borrarApu(codigo, turno)` → `DELETE`. `listarApus`/`getApuDetalle`/`crearApu` ya existen ahí.
- **Acciones por fila en `Apus.tsx`:**
  - **Editar** (visible con rol `editor`+): reutiliza **`DialogoAgregarApu`** en **modo edición**,
    precargado vía `getApuDetalle(codigo, turno)`, con `codigo` y `turno` **deshabilitados**. El
    editor de composición (agregar/quitar filas, buscador de insumo, rendimiento) es el que ya
    usa "Nuevo APU". Guardar → `editarApu` (`PUT`) → toast + refresco de la lista.
  - **Borrar** (visible **solo** con rol `admin`): nuevo **`DialogoBorrarApu`** de confirmación
    que muestra `n_corridas` ("Este APU está referenciado en N corridas; las ya armadas conservan
    su composición y no se verán afectadas") → `borrarApu` (`DELETE`) → toast + refresco.
- **Gating**: reutiliza `puede(rol, …)` de `@/components/rutas` (el mismo que ya usa `Apus.tsx`
  para "Nuevo APU"/"Importar" con `"editor"`); el botón borrar chequea `"admin"`. El backend
  responde `403` si el rol no alcanza; la UI solo oculta los botones para no ofrecer acciones
  que fallarían.

## Errores, privacidad y pruebas

**Privacidad (Invariante #1):** editar/borrar no abren ningún camino hacia la IA; la IA sigue
viendo solo `DePriced*` dentro del dominio. El test que verifica que `apu_tool/servicio/` no
contiene `"ai_assist"` cubre también estos cambios.

**Errores/validación:**
- `nombre` obligatorio; `rendimiento > 0`; `turno` inmutable.
- Editar/borrar un `(codigo, turno)` inexistente → `404` con mensaje claro.
- `editor` intentando `DELETE` → `403`; `consulta` intentando `PUT`/`DELETE` → `403`.
- Componente cuyo `insumo_codigo` no resuelve en el catálogo → **permitido** (enlace blando),
  igual que en `crear_apu` (queda como cruce huérfano al costear).

**Pruebas (pytest + TestClient), en los dos backends donde aplica:**
- **Datos** (`ApusDB` y `ApusPg`): `editar_apu` actualiza cabecera + reemplaza composición sin
  duplicar `seq` y da `ValueError` si el APU no existe; `borrar_apu` elimina componentes +
  cabecera y devuelve `False` si no existía; `contar_items_por_apu` cuenta correcto.
- **Servicio** (`autoria`): `editar_apu`/`borrar_apu` auditan con `antes`/`despues` correctos;
  editar/borrar inexistente → señal de error; validaciones (rendimiento > 0, nombre, turno inmutable).
- **API** (TestClient): `PUT` (editor) y `DELETE` (admin) funcionan; gating (`editor`→`DELETE`
  = `403`; `consulta`→`PUT`/`DELETE` = `403`); `404` en inexistente; `400` en validación.
- **Frontend:** Vitest ligero del formulario en modo edición (precarga, `codigo`/`turno`
  deshabilitados) y del diálogo de borrado; smoke manual.
- `python -m pytest tests/ -q` debe seguir **verde** completo (incluye seed, privacidad y backend previo).

**Build/serve:** al terminar la web, `npm run build` regenera `web/dist`; luego redeploy en
Render. **No hay migración de datos.** Se coordina el reinicio del servidor con el usuario.

## Criterios de aceptación

1. Editar un APU desde la web (cambiar nombre/grupo y rendimientos, agregar/quitar insumos) y
   verlo reflejado en el detalle y disponible para próximas corridas.
2. Borrar un APU (solo admin), con confirmación que informa cuántas corridas lo referencian;
   las corridas ya armadas no cambian.
3. Un `editor` no puede borrar (botón oculto + `403` del backend); `consulta` no edita.
4. La auditoría registra `apu.editar` y `apu.borrar` con `antes`/`despues` correctos.
5. `pytest` pasa completo en ambos backends (SQLite y Postgres).
6. La IA nunca recibe dinero (invariante intacto); editar/borrar no tocan la IA.
