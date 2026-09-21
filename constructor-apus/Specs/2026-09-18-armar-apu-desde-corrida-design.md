> Espejo automático — no editar aquí. Fuente: `docs/superpowers/specs/2026-09-18-armar-apu-desde-corrida-design.md`

# Armar APU desde una fila de la corrida

Fecha: 2026-09-18
Estado: aprobado, sin implementar

## Problema

Parado en una fila de la corrida, el único camino para crear un APU es
**"Duplicar este APU y usarlo aquí"**, y ese botón exige que la fila **ya tenga un APU**
(`puedeDuplicar && detalle.apu_codigo`, en `TablaItems.tsx`). La condición viene así
desde el commit que creó la feature (`8d4b55b`) y nunca cambió.

O sea: justo cuando más falta hace armar un APU —la fila quedó sin ninguno— no hay botón.
Un botón de **crear** (no duplicar) en la fila de la corrida **nunca existió**: el único
modo que esa tabla le pasa a `DialogoAgregarApu` es `"duplicar"`.

Hoy hay que ir a la pestaña APUs, crearlo, y volver. La feature "Volver a buscar APU"
(2026-09-16) resolvió la vuelta —que la corrida encuentre lo que creaste— pero no la ida.

## Solución

Un solo botón **Armar APU** en el panel desplegado de la fila, **siempre visible** (rol
editor y corrida no congelada), que abre tres caminos hacia el mismo diálogo de alta:

1. **Duplicar el APU asignado** — solo si lo hay, y viene marcada. Es lo de hoy.
2. **Partir de otro APU** — con el buscador que ya usa "Cambiar APU" (`BuscadorApu`).
3. **Desde cero** — con los datos de la actividad ya cargados.

Al crear, el APU queda **asignado a la fila** y la fila `confirmed`, igual que hoy al
duplicar: lo armaste vos a propósito para ella.

**"Componer" (la mesa con IA) no se toca.** Son dos caminos distintos y ninguno reemplaza
al otro: uno lo armás a mano, el otro se lo pedís a la IA y después revisás.

## Decisiones

| Decisión | Valor | Por qué |
|---|---|---|
| Visibilidad | siempre (editor, no congelada) | El caso que faltaba es justamente la fila sin APU. |
| Fila sin APU | desde cero **o** partiendo de uno que busques | Arrancar de uno parecido es como se arma en la vida real; una hoja en blanco es peor punto de partida. |
| Fila con APU | las tres opciones, con "duplicar el asignado" marcada | Un solo comportamiento que aprender, y no obliga a desasignar para arrancar de otro lado cuando el APU asignado no sirve. |
| Precarga de "desde cero" | nombre, unidad, turno y **el código del presupuesto** | El `codigo_sugerido` es el que la fila debería llevar: es exactamente el dato que falta para saber qué APU crear. |
| Ubicación | el panel desplegado, donde está duplicar hoy | Se decide viendo la actividad completa y la composición. |
| Estado al crear | `confirmed`, asignado a la fila | Igual que duplicar hoy. Una persona armó ese APU para esa fila. |

## Arquitectura

### Lo que NO se toca: `DialogoAgregarApu.tsx`

Tiene **822 líneas** y lo usan tres pantallas (`TablaItems.tsx`, `pages/Apus.tsx`,
`pages/Composicion.tsx`). Meterle el paso de elección adentro lo haría crecer y pondría
en riesgo a los otros dos consumidores sin necesidad.

**Y no hace falta:** el modo `crear` **ya acepta un `inicial`** y lo precarga tal cual
—código sin derivar, nombre, unidad, turno, y una fila de composición vacía cuando
`inicial.composicion` viene vacía—. El comentario del propio archivo dice que es un camino
soportado que se quedó sin llamador cuando la mesa de composición dejó de usarlo. Esta
feature lo vuelve a usar; no lo inventa.

Los tres caminos salen de combinar lo que ya existe:

| Opción | `modo` | `inicial` |
|---|---|---|
| Duplicar el asignado | `"duplicar"` | el APU de la fila, leído con `getApuDetalle` |
| Partir de otro | `"duplicar"` | el APU que elegiste en el buscador, leído igual |
| Desde cero | `"crear"` | uno sintético armado con los datos de la fila |

El `inicial` sintético de "desde cero" es un `ApuDetalle` completo, para no aflojar el
tipo: `codigo: detalle.codigo_sugerido ?? ""`, `turno: detalle.apu_turno`,
`nombre: detalle.descripcion`, `unidad: detalle.unidad`, `grupo: ""` (lo elegís en el
diálogo), `costo_unitario: 0` y `composicion: []` — que es lo que hace que el alta abra con
una fila de composición vacía.

### Lo nuevo: `web/src/components/corrida/DialogoArmarApu.tsx`

Un archivo chico (~90 líneas) dueño de una sola cosa: **elegir el punto de partida y
entregar el `(modo, inicial)` correcto**. Renderiza su propia ventana compacta con las tres
opciones y, al elegir, cierra y abre `DialogoAgregarApu` ya cargado.

**El precio consciente:** son dos modales centrados uno tras otro, no una sola ventana que
cambia de contenido. En la práctica se siente como un paso. La alternativa —la ventana
única— exige tocar el archivo de 822 líneas, y no vale ese riesgo para esta diferencia.

### Backend: dos campos

`servicio/corridas.py::detalle_item` hoy no manda `codigo_sugerido` ni `unidad`. Se agregan
al dict que ya arma, y al tipo `DetalleItem` del frontend. Sin endpoint nuevo, sin
migración, sin tocar el modelo.

`codigo_sugerido` ya vive en `LicitacionItem` (`nucleo/models.py`) desde la ruta IDU: es el
"código IDU dado por el presupuesto". Solo no viajaba al frontend.

## Lo que NO hace

- No toca `DialogoAgregarApu.tsx` ni a sus otros dos consumidores.
- No toca "Componer" ni la mesa de composición.
- No agrega el botón a la columna Acciones: vive solo en el panel desplegado.
- No muestra el código del presupuesto como columna de la tabla. Eso es otra conversación
  (ver "Pendiente relacionado").

## Pendiente relacionado (fuera de alcance)

Cuando el presupuesto trae un código y ese APU **no existe** en la biblioteca, el matcher
lo ignora y asigna otro por nombre. Hoy no hay dónde ver que eso pasó: ni en la tabla ni
en el cuadro. Esta feature lo expone en el alta (precargando el código), pero **no** crea
la columna comparativa. Si hace falta, es un spec aparte.

## Pruebas

**vitest** (`DialogoArmarApu.test.tsx` y `TablaItems.test.tsx`)

- El botón aparece en una fila **con** APU y en una **sin** APU.
- No aparece sin rol editor, ni con la corrida congelada.
- "Duplicar el asignado" solo se ofrece cuando hay APU, y viene marcada.
- "Desde cero" precarga nombre, unidad, turno y el código del presupuesto.
- "Partir de otro" carga el APU que devolvió el buscador.
- Al crear, se llama al mismo camino que hoy usa duplicar, y la fila queda con ese APU.

**pytest** (`tests/test_servicio_corridas.py`)

- `detalle_item` devuelve `codigo_sugerido` y `unidad`.
- Una fila sin `codigo_sugerido` devuelve `""`, no rompe.
