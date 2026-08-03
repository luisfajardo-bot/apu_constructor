# Listas de precios y APUs de No Previstos (NP)

## Qué resuelve

Cobrar actividades que no estaban en el presupuesto original (un "No Previsto" — NP),
con la tarifa que se acordó para esa obra en particular, sin tocar ni contaminar el
catálogo de precios contractual (`Principal`).

Una **lista de precios** es una tarifa completa: qué insumos tienen precio y a cuánto.
`Principal` (id 1) es la del catálogo de siempre — la que ya existía antes de esta
feature — y cada obra de NP puede tener la suya.

## Cómo se usa

1. **Crear la lista.** Página **Insumos** → selector de lista (arriba a la izquierda) →
   botón **+ Nueva** (rol editor). Pide el nombre con un diálogo del navegador —
   nómbrala con la obra, p. ej. `NP Calle 13`. Al crearla, la página te deja parado en
   ella (para que el siguiente precio que cargues no vaya a la Principal por error).
   Un nombre mal escrito se corrige con el botón **Renombrar** (no hay borrado: una
   lista vive mientras exista alguna corrida que la use).

2. **Cargarla.** Con el selector puesto en esa lista:
   - **Importar** un Excel/CSV con columnas `codigo`, `nombre`, `unidad`, `grupo`,
     `precio`, `fuente`. Una fila con nombre crea el insumo si no existe en el catálogo
     (identidad código+nombre) o actualiza su precio en **esta** lista si ya existe; una
     fila sin nombre solo actualiza el precio por código.
   - O editar precios a mano en la tabla, insumo por insumo.

3. **Completarla.** El botón **Sin precio** filtra los insumos que en esta lista
   todavía no tienen tarifa cargada. Mientras un insumo quede así, cualquier APU que lo
   use costea ese componente en **$0 con alerta** (`sin_precio_lista` /
   "Sin tarifa en la lista") — a propósito: en una lista que no es Principal el precio
   histórico embebido en la composición **no** sirve de respaldo silencioso, porque ese
   histórico es una tarifa contractual, y usarlo aquí sería cobrar el no previsto con el
   precio equivocado sin que nadie se entere. La franja ámbar que aparece arriba de la
   tabla mientras editas una lista que no es Principal es el mismo recordatorio.
   (Distinto es que el catálogo Principal tenga un insumo sin precio propio: eso se
   costea igual con el histórico, pero con la alerta `sin_precio_catalogo` — antes de
   esta feature ese caso costeaba en silencio.)

4. **Armar la corrida.** En **Nueva corrida**, el selector **Lista de precios** (por
   defecto Principal). Una vez creada la corrida, la lista queda fija — no se puede
   cambiar después, ni desde la API ni desde la UI. Los APUs de NP son APUs normales de
   la misma biblioteca; que uses un prefijo de código propio (p. ej. `NP-xxxx`) para
   distinguirlos a simple vista es una convención tuya, no algo que el sistema exija.
   La corrida y el listado de "Mis corridas" muestran qué lista usan (`Principal` o el
   nombre de la lista NP).

5. **Emitir.** El cuadro (ambos formatos, plano y por capítulos) trae la fila
   `Lista de precios` en la hoja `INFO`, con el nombre de la lista con la que se costeó.

## Reglas

- La lista `Principal` (id 1) no se renombra ni se borra: es el ancla de "sin lista
  elegida = comportamiento de siempre".
- Ninguna lista se borra — no hay endpoint para eso. Borrar dejaría huérfanas las
  corridas que la usan (`corrida.lista_precios_id` no tiene FK: la corrida vive en otra
  base que la lista).
- Un insumo sin tarifa en la lista activa **no** hereda el precio de Principal ni el
  histórico embebido: queda en $0 con la alerta *"sin precio en la lista"*. Un $0 real
  puesto a propósito (p. ej. material que pone el cliente) sí se ve como `$0`; lo que
  nunca se ve como `$0` sin más es la ausencia de tarifa — en la tabla de Insumos se
  muestra como `—`.
- Congelar una corrida fija sus números: editar la lista después de congelar no los
  mueve (la corrida congelada es un snapshot inmutable).
- **`seed --force` (re-semillar) borra las listas de precios** junto con el resto del
  catálogo — y, a diferencia de insumos/APUs, las listas NP no están en ningún Excel
  del que recuperarlas. No re-siembres en un ambiente con listas NP cargadas sin
  respaldarlas antes (exportar las tablas o, si aplica, restaurar desde un backup de
  base de datos).

## Despliegue

La migración es aditiva: `ADD COLUMN ... DEFAULT 1` sobre `insumo_precios.lista_id` y
la tabla nueva `lista_precios`, sin backfill (todo insumo existente queda en Principal
por el default). Aun así, en Postgres el `ALTER TABLE ... ADD COLUMN ... REFERENCES`
toma un lock breve sobre `precios.insumo_precios`, que en producción ya tiene ~8000
insumos y su historial — valídala contra el Postgres real antes de desplegar, como se
hizo con nombre/alias de corridas.

Esa validación está automatizada en `tests/test_migracion_lista_pg.py`: levanta el
esquema ANTERIOR a las listas, lo llena con ~8200 insumos y 24 600 filas de precio, y
recién entonces aplica `db/pg/precios.sql` (el resto de los tests de Postgres hace
`DROP SCHEMA` primero, así que el `ALTER TABLE` les queda como no-op y no prueban este
camino). Corre con `TEST_DATABASE_URL` apuntando a un Postgres **desechable** — esos
tests hacen `DROP SCHEMA ... CASCADE`, nunca a producción. Medido en PG 17: **57 ms**.

**Estado (2026-07-31):** el paso 3 de abajo (RLS) ya se aplicó en producción y
`relrowsecurity` da `true`. Falta el paso 4, el smoke test en el navegador; el
procedimiento detallado, pensado para que lo ejecute alguien que no conoce el proyecto,
está en **`docs/smoke-test-listas-np.md`**.

**El paso manual del RLS, para la próxima tabla nueva:**
`supabase/migrations/0005_lista_precios_rls.sql` habilita RLS
en `precios.lista_precios`, y nada lo aplica automáticamente (el boot solo aplica
`db/pg/*.sql`). Hay que correrlo a mano en el SQL editor de Supabase **después** del
primer arranque con el código nuevo, que es el que crea la tabla. Sin ese paso la tabla
queda sin RLS: la defensa en profundidad se pierde (la API sigue aplicando su RBAC con
la `service_role`, que hace bypass de RLS igual).

Antes de dar por buena la migración en producción:
1. Confirmar que la lista `Principal` quedó sembrada con id 1.
2. `SELECT count(*) FROM precios.insumo_precios WHERE lista_id <> 1` debe devolver 0
   (nada quedó fuera de Principal antes de que exista ninguna lista NP).
3. Aplicar `0005_lista_precios_rls.sql` (ver arriba) y verificar con
   `SELECT relrowsecurity FROM pg_class WHERE oid = 'precios.lista_precios'::regclass`.
4. Smoke test en el navegador — **pendiente**. Resumen: crear una lista, importar 2-3
   precios, armar una corrida contra ella, comprobar la alerta "Sin tarifa en la lista"
   en un insumo sin precio, y descargar el cuadro para ver la fila `Lista de precios` en
   `INFO`. El paso a paso completo, con qué esperar en cada pantalla y qué severidad tiene
   cada fallo, está en `docs/smoke-test-listas-np.md`.
