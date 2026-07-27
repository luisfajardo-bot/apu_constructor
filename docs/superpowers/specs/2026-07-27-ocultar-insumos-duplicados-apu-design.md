# Diseño — Ocultar del catálogo de insumos los códigos que son APU

> Fecha: 2026-07-27
> Estado: propuesto (aprobado en brainstorming; pendiente de revisión del spec escrito)
> Rama de trabajo sugerida: `feat/ocultar-insumos-duplicados-apu`

## Objetivo

Tras activar `marcar-subapus` en producción (128 componentes marcados, ver sesión del
2026-07-27), se confirmó que **1152** códigos del catálogo de insumos también son
código de un APU. De esos, **1123** (97%) no tienen ya ningún componente que los use
como insumo real — son "ecos" del precio aplanado de un APU que quedaron en el catálogo
histórico del Excel y que ahora ya no cumplen ninguna función (el costeo pasa por la
composición recursiva del sub-APU, no por el precio del insumo). Solo **29** códigos son
colisiones reales (el mismo número quedó asignado por casualidad a un APU y a un insumo
genuinamente distinto). Este proyecto oculta esos ~1123 códigos del catálogo que ve el
usuario (y de la búsqueda de candidatos de la IA), sin borrar nada, para que dejen de
generar confusión — el borrado real, si se decide, es una conversación aparte y
posterior, una vez se verifique que todo sigue funcionando bien.

## Decisiones tomadas (brainstorming)

- **Ocultar, no borrar (por ahora).** Un flag reversible en la base; nada se elimina.
  El borrado se evalúa más adelante, por separado.
- **Alcance de esta corrección:** solo los códigos existentes de hoy. La prevención
  hacia adelante (avisar al crear un insumo que choca con un código de APU) queda para
  una conversación aparte.
- **Sin vista especial de "ocultos" todavía.** No se agrega ningún toggle/filtro en la
  UI para verlos — cuando llegue el momento de revisar/decidir el borrado, se consulta
  directo en la base o se agrega esa vista en ese momento.
- **El costeo nunca debe depender de si algo está oculto.** `get_candidatos`/
  `get_candidatos_bulk` (los que usa `pricing.py`) no se tocan — siguen encontrando
  cualquier insumo por código exista o no esté oculto.
- **Mismo patrón operativo que `marcar-subapus`:** migración idempotente, auditada,
  corrida primero en local y después en producción con backup + verificación manual
  (no automatizada dentro de este código).

## Qué se oculta (regla exacta)

Una fila de `insumos` (identificada por su `id`) se marca `oculto=true` si **todas**
estas condiciones se cumplen:

1. Su `codigo` es también el código de un APU en la biblioteca.
2. Su `nombre` (normalizado con `apu_tool.nucleo.texto.normalizar`) coincide con el
   nombre (normalizado) de ese APU. Si el código coincide pero el nombre es distinto,
   es una colisión real (código reciclado para dos cosas distintas) y **nunca** se
   oculta.
3. Ningún componente de APU (`apu_componentes`) tiene hoy `tipo='insumo'` con ese mismo
   `insumo_codigo` + `insumo_nombre` (normalizado) — es decir, nada lo sigue consumiendo
   como insumo real. (Los que sí lo consumían y coincidían en nombre ya deberían estar
   marcados `tipo='apu'` por `marcar-subapus`; si por algún motivo alguno no lo está
   todavía, esta migración lo detecta y **no** lo oculta, para no ocultar algo que
   sigue en uso activo como insumo.)

## Esquema — columna `oculto`

Aditivo, dual-backend, mismo patrón que `modo`/`snapshot_json` en `corridas`.

**`db/precios.sql`** (SQLite) — agregar a la tabla `insumos`:
```sql
oculto      INTEGER NOT NULL DEFAULT 0   -- 1 = eco de un APU sin uso real; no se borra, solo se filtra
```

**`apu_tool/datos/precios_db.py::init_schema()`** — agregar el chequeo idempotente
(mismo estilo que la migración existente de `creado_por`):
```python
if "oculto" not in cols:
    conn.execute("ALTER TABLE insumos ADD COLUMN oculto INTEGER NOT NULL DEFAULT 0")
```
(`cols` pasa a leerse también de `PRAGMA table_info(insumos)`, además del
`PRAGMA table_info(insumo_precios)` ya existente.)

**`db/pg/precios.sql`** (Postgres) — agregar a `precios.insumos` en el `CREATE TABLE`:
```sql
oculto      BOOLEAN NOT NULL DEFAULT FALSE
```
y una línea de migración idempotente después (mismo patrón que `corridas.sql`):
```sql
ALTER TABLE precios.insumos ADD COLUMN IF NOT EXISTS oculto BOOLEAN NOT NULL DEFAULT FALSE;
```

## Filtrado por `oculto`

**No se toca** (deben seguir encontrando cualquier código exista o no esté oculto):
`get_candidatos`, `get_candidatos_bulk`, `get_insumo_por_id`, `price_history`.

**Se filtran** (excluyen `oculto` por defecto, en ambos backends — SQLite `i.oculto = 0`,
Postgres `i.oculto = FALSE`):

- `list_insumos`: agregar `where.append("i.oculto = 0")` (SQLite) incondicional al
  armar la cláusula `WHERE` (no depende de ningún parámetro nuevo del método).
- `search_insumos`: cambiar el `WHERE` de
  `"WHERE nombre_norm LIKE ? OR UPPER(codigo) LIKE ?"` a
  `"WHERE (nombre_norm LIKE ? OR UPPER(codigo) LIKE ?) AND oculto = 0"`.
- `search_insumos_por_palabras`: cambiar
  `f"WHERE {clauses}"` a `f"WHERE ({clauses}) AND oculto = 0"`.
- `grupos()`: agregar `AND oculto = 0` al `WHERE` existente (para que el dropdown de
  grupos no ofrezca un valor que solo exista entre insumos ocultos).
- `fuentes()`: esta consulta ya es sobre `insumo_precios`, no sobre `insumos`
  directamente — agregar un `JOIN insumos i ON i.id = p.insumo_id AND i.oculto = 0`.

Postgres (`precios_pg.py`): mismos cinco cambios, con `%s`/`FALSE` y las tablas
calificadas por esquema (`precios.insumos`, `precios.insumo_precios`).

**No se agrega ningún parámetro `incluir_ocultos` todavía** — decidido explícitamente
en brainstorming (sin vista especial por ahora).

## Migración: `ocultar_apus_duplicados`

Nuevo archivo `apu_tool/servicio/insumos_ocultos.py` (mismo nivel/patrón que
`servicio/subapus.py`):

```python
def ocultar_apus_duplicados(alm: Almacen, actor: Optional[Perfil] = None) -> dict:
    """Oculta (no borra) los insumos cuyo código+nombre coincide con un APU y que ya
    no tiene ningún componente usándolo como insumo real (ver regla en el spec)."""
```

- `alm.apus.apu_index()` (ya existe) → `codigos_apu`, `nombres_por_codigo_apu`.
- Nuevo `alm.precios.todos_no_ocultos() -> list[tuple[int, str, str]]` (id, codigo,
  nombre) — trae **todos** los insumos con `oculto = 0`, sin filtrar por código en SQL
  (la tabla es chica, ~8000 filas); el cruce contra `codigos_apu` se hace en Python,
  igual que `mapa_codigos_apu` en `subapus.py` ya hace con los APUs. Evita chunking de
  placeholders para un set potencialmente grande de códigos.
- Nuevo `alm.apus.usos_insumo_codigo_nombre() -> set[tuple[str, str]]` — `SELECT DISTINCT
  insumo_codigo, insumo_nombre FROM apu_componentes WHERE tipo='insumo'`, normalizado en
  Python a `(codigo, nombre_normalizado)`.
- Cruce en Python (igual criterio que la sección anterior): nombre debe coincidir con
  el del APU de ese código, y `(codigo, nombre_normalizado)` no debe estar en los usos
  restantes.
- Escritura: `alm.transaccion("precios")` (mismo patrón que `alm.transaccion("apus")`
  en `marcar_subapus`), un `alm.precios.set_oculto(insumo_id, True, conn=conn)` por
  fila, más un solo evento de auditoría `insumo.ocultar_duplicado_apu` con la lista de
  ids ocultados en `despues`.
- Devuelve `{"insumos_ocultados": N}`.
- Idempotente: correrlo de nuevo con nada nuevo que ocultar devuelve
  `{"insumos_ocultados": 0}` y no re-audita (mismo criterio que `marcar_subapus`).

Nuevo método en `precios_db.py`/`precios_pg.py`:
```python
def set_oculto(self, insumo_id: int, oculto: bool, conn=None) -> None:
    """UPDATE insumos SET oculto=? WHERE id=?"""
```

## CLI

Nuevo subcomando `ocultar-duplicados` en `apu_tool/interfaz/cli.py`, mismo estilo que
`cmd_marcar_subapus`:
```python
def cmd_ocultar_duplicados(args) -> int:
    from apu_tool.servicio.insumos_ocultos import ocultar_apus_duplicados
    alm = get_almacen()
    res = ocultar_apus_duplicados(alm)
    print(f"Insumos ocultados: {res['insumos_ocultados']}.")
    return 0
```
Registrado en `build_parser()` igual que `marcar-subapus` (subparser sin argumentos).

## Pruebas

- `tests/test_ocultar_duplicados.py` (mismo estilo que `test_subapus_migracion.py`,
  `Almacen` SQLite con `tmp_path`):
  - Oculta un insumo cuyo código+nombre coincide con un APU y no tiene componentes
    usándolo → `oculto=1`, auditoría registrada.
  - **No** oculta un insumo cuyo código coincide con un APU pero el nombre es distinto
    (colisión real).
  - **No** oculta un insumo cuyo código+nombre coincide con un APU pero todavía hay un
    componente `tipo='insumo'` usándolo (no debería pasar tras `marcar-subapus`, pero la
    migración debe ser segura igual).
  - Idempotente: correrlo dos veces no vuelve a ocultar ni re-audita.
- `tests/test_precios_db.py` (y el equivalente Postgres si existe suite paralela):
  - `list_insumos`, `search_insumos`, `search_insumos_por_palabras` excluyen un insumo
    con `oculto=1`.
  - `get_candidatos`, `get_candidatos_bulk`, `get_insumo_por_id` **sí** encuentran un
    insumo oculto (verificación explícita de la propiedad de seguridad del costeo).
  - `grupos()`/`fuentes()` no ofrecen un valor que solo exista entre ocultos.
- Se corre `pytest` completo como parte de verificar la feature.

## Operación en producción

Mismo procedimiento ya usado para `marcar-subapus` (fuera del código, manual):
1. Correr primero en local (SQLite) para confirmar comportamiento y conteos.
2. Backup de `precios.insumos` en producción (`precios.zbak_YYYYMMDD_ocultar_duplicados`),
   mismo criterio que `apus.zbak_20260727_marcar_subapus`.
3. Correr `python run_cli.py ocultar-duplicados` contra producción (`DATABASE_URL`).
4. Verificar: conteo de ocultados, que los 29 casos de colisión real siguen visibles,
   y que `list_insumos`/búsqueda de la página Insumos ya no los muestra.

## Fuera de alcance (YAGNI)

- Borrar físicamente los insumos ocultos — conversación aparte, posterior, una vez
  verificado que todo funciona bien con el ocultamiento.
- Prevención hacia adelante (avisar al crear un insumo con código de APU existente) —
  decidido explícitamente que no, en este diseño.
- Un toggle/filtro "mostrar ocultos" en la UI — decidido explícitamente que no, por
  ahora.
- Tocar `grupos()`/`fuentes()` de forma distinta a un simple filtro adicional (no se
  rediseña esa lógica).
- Cambiar el modelo `Insumo` (`nucleo/models.py`) para exponer `oculto` — el flag vive
  solo como criterio de filtro en SQL, no se serializa a la API ni al frontend.
