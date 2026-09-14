> Espejo automático — no editar aquí. Fuente: `docs/superpowers/specs/2026-09-14-descripciones-corrida-design.md`

# Ver completa la descripción de una actividad en la corrida

**Fecha:** 2026-09-14
**Estado:** aprobado

## Problema

La descripción de la actividad de la licitación es lo que dice qué debe llevar el APU:
es el dato que se lee al revisar una corrida. Hoy no se puede leer completa.

1. En la fila, la celda es `max-w-[240px] truncate`: corta con `…` a una línea.
2. Al desplegar la fila, la descripción **no aparece**. El panel muestra el APU, los
   candidatos y la composición, pero nunca la actividad que se está revisando.
   `DetalleItem.descripcion` ya viaja en la respuesta del API y se descarta en el render.
3. En pantalla angosta (teléfono) el panel desplegado es un `<td colSpan>` que abarca
   las ~14 columnas de la tabla: mide el ancho de la tabla (~1400px), no el de la
   pantalla. El texto envuelve fuera del área visible y toca scroll horizontal para
   leerlo.
4. Adentro del panel, los nombres de los candidatos (`max-w-[200px] truncate`), el
   motivo (`max-w-[160px]`), el nombre del APU (`max-w-xs`) y el nombre del insumo de
   la composición (`max-w-[200px]`) también se cortan.

## Alcance

Solo `web/src/components/corrida/TablaItems.tsx`. Sin cambios de backend, de API ni de
tipos: todo el texto ya llega al frontend.

## Diseño

### 1. Fila colapsada: descripción elástica que envuelve

La celda pasa de `max-w-[240px] truncate` a envolver en varias líneas, con el ancho
elástico entre 240px y 420px: en monitor ancho casi todo cabe en 1–2 líneas, en
teléfono baja a 240px y cabe en pantalla sin scroll horizontal. Una sola regla para
toda pantalla, sin breakpoints.

El `max-width` va en un `<div>` adentro de la celda, no en el `<td>`: en tablas de
layout automático el navegador trata el `max-width` de una celda como sugerencia y
puede ignorarlo.

Todas las celdas de la fila pasan a `align-top`. Con filas de 3–4 líneas, el centrado
vertical (`align-middle`, el default del primitivo) deja la plata flotando en la mitad
y se pierde el renglón al escanear.

Consecuencia aceptada: las filas quedan de alturas distintas y la tabla se alarga.
Es la decisión del usuario, tomada viendo el trade-off.

### 2. Panel desplegado: bloque "Actividad" con la descripción completa

Arriba del todo, antes del encabezado del APU: la descripción de la licitación
completa, sin cortar. Es lo primero que se lee al desplegar, porque es contra lo que
se juzga si el APU asignado sirve.

### 3. Panel desplegado: al ancho de la pantalla, no al de la tabla

El `<TableCell colSpan>` pasa a `p-0` y adentro va un
`<div className="sticky left-0 w-[100cqw] …">`. El `sticky left-0` clava el panel al
borde izquierdo del área visible aunque la tabla esté scrolleada a la derecha, y
`100cqw` le da el ancho visible del contenedor.

Para que `100cqw` mida lo correcto, el `<Table>` de la corrida se envuelve en un
`<div className="@container">`. **No se toca `ui/table.tsx`**: ese primitivo lo comparten
todas las tablas de la app y `container-type: inline-size` cambia el bloque contenedor
de los descendientes posicionados. El `@container` va solo donde hace falta.

### 4. Adentro del panel no se corta nada

Se van los `truncate` de: nombre del APU en el encabezado, nombre y motivo de cada
candidato, nombre del insumo en la composición costeada. Cada uno queda
`whitespace-normal break-words` con un piso de ancho (`min-w-*`) para que la columna no
se vuelva un hilo de una letra por línea.

## Verificación

**Test (vitest):** desplegar una fila muestra la descripción completa de la actividad.
Hoy ese bloque no existe, así que el test falla antes del cambio.

**Lo que NO se puede testear:** el corte con `…` es puro CSS y jsdom no calcula layout.
Ni el `truncate`, ni el `sticky`, ni `100cqw` son visibles desde un test. Esa parte se
verifica **en el navegador**, a 390px de ancho y a pantalla completa, antes de
cualquier push. Es la lección de `dialogo-texto-sin-prompt`: en cambios de UI el
navegador va antes del push.
