> Espejo automático — no editar aquí. Fuente: `docs/superpowers/specs/2026-11-25-chat-consulta-design.md`

# Chat de consulta: preguntas de precios y totales sin que la IA vea dinero

**Fecha:** 2026-11-25 · **Rama:** `feat/chat-consulta` · **Estado:** diseño aprobado, sin plan

## Qué es

Un chat con el agente disponible desde cualquier pantalla de la app. Responde preguntas
como estas:

- «¿Cuánto cuesta la actividad de mezcla asfáltica?»
- «¿Cuánto vale el insumo de tubería?»
- «¿Cuál es el total contractual y el costo de la licitación del proyecto La Cali?»
- «¿Cuál es el total de redes húmedas de la Calle 13?»

Es hermano del chat de la mesa de composición (`dominio/composicion_chat.py`). Usa el
mismo bucle de tool use, el mismo tope y el mismo detector de dinero. La diferencia es
que este chat **responde con cifras**.

## El problema de fondo: el invariante #1

Las cuatro preguntas son de dinero, y la IA nunca ve dinero. El chat no rompe esa regla.

**La IA entiende la pregunta; el servidor pone las cifras.**

1. La IA busca con herramientas que devuelven solo nombres, códigos y **referencias**,
   sin un solo monto. Todo resultado pasa por `privacy.assert_no_money`.
2. La IA redacta la respuesta con **marcadores** donde va cada cifra, por ejemplo
   `{{costo:apu:4859|DIURNO}}`.
3. Cuando el modelo terminó, el servidor reemplaza cada marcador por el valor que
   calculan las funciones de siempre (`PricingEngine`, `vista_corrida`,
   `resumen_por_capitulo`). Ninguna cifra viaja hacia el modelo, ni antes ni después.

Lo que se pierde, a propósito: la IA no puede comparar ni opinar sobre montos
(«¿cuál es el más caro?», «¿está caro?»). Si eso hace falta, se agrega como herramienta
determinística que ordene en el servidor y devuelva referencias, no cifras.

## Alcance v1

**Entra:**

| Pregunta | Herramienta | Marcadores | Fuente de la cifra |
|---|---|---|---|
| Precio de un insumo | `buscar_insumos` | `precio:insumo:<id>` | precio vigente en la lista **Principal** |
| Costo de un APU de la biblioteca | `buscar_apus` | `costo:apu:<codigo>\|<TURNO>` | `PricingEngine(alm).cost_apu(...)`, lista Principal, sin contexto de proyecto |
| Totales de una corrida | `buscar_proyectos` | `contractual`, `costo`, `diferencia`, `margen` `:corrida:<id>` | `vista_corrida(...)["totales"]` |
| Totales de un capítulo | `capitulos` | `contractual`, `costo`, `diferencia`, `margen` `:capitulo:<corrida_id>:<codigo>` | `vista_corrida(...)["capitulos"]` (o sea, `resumen_por_capitulo`) |

**No entra (v1):**

- **Listas de No Previstos.** Todo precio de insumo y de APU es contra Principal, y la
  respuesta lo dice («lista Principal»).
- **Actividades sueltas de una corrida** («¿cuánto quedó la fila 120 de la Calle 13?»).
- **Rankings y comparaciones** de montos.
- **Sumar corridas de un mismo proyecto.** Un proyecto (carpeta de nivel 1) puede tener
  varias corridas, y casi siempre son versiones de la misma licitación: sumarlas da un
  total que no existe. Se responde **una línea por corrida**.
- **Persistir el chat.** El historial vive en el navegador, como el de la mesa.

## Marcadores

Gramática: `{{<campo>:<tipo>:<id>}}`. Es una lista cerrada:

| tipo | id | campos válidos |
|---|---|---|
| `insumo` | id del catálogo (`Insumo.id`) | `precio` |
| `apu` | `<codigo>\|<TURNO>` | `costo` |
| `corrida` | id de la corrida | `contractual`, `costo`, `diferencia`, `margen` |
| `capitulo` | `<corrida_id>:<codigo_capitulo>` | `contractual`, `costo`, `diferencia`, `margen` |

- El insumo va por **id** y no por código, porque 652 códigos del catálogo son de dos
  insumos. El id cambia con `seed --force`. Se acepta: el historial del chat es corto, y
  un id que ya no existe sale como «[cifra no disponible]», no como otra cifra.
- `margen` se muestra como porcentaje; las demás cifras como pesos, con el formato de la
  web. Ojo con los nombres: en `vista_corrida(...)["totales"]` la diferencia en pesos se
  llama `margen` y el porcentaje `margen_pct`. El marcador `diferencia` lee
  `totales["margen"]` y el marcador `margen` lee `totales["margen_pct"]`. En los
  capítulos son `diferencia` y `margen_pct`.
- Cada herramienta le dice al modelo qué marcadores puede usar en cada resultado: va
  como `ref` en el resultado, por ejemplo `"ref": "apu:4859|DIURNO"`. El prompt explica
  la gramática y prohíbe escribir cifras.

### Reglas del reemplazo (`servicio/consulta.py`)

1. **Marcador inválido** (tipo o campo fuera de la lista, id que no existe, capítulo que
   la corrida no tiene): se reemplaza por **«[cifra no disponible]»**. Nunca se adivina
   ni se acerca a otro.
2. **Cifra parcial.** Una corrida con el armado a medias (`armado` no es `None`) o un
   capítulo con `completo: false` lleva la etiqueta **«(parcial: X de Y actividades
   costeadas)»** pegada a la cifra. Un total de 290 de 1939 líneas que se ve entero es la
   misma mentira que `_exigir_armado_completo` evita en el cuadro.
3. **Un `vista_corrida` por corrida y por respuesta.** Varios marcadores de la misma
   corrida comparten la vista (memo dentro de la respuesta). `vista_corrida` cuesta lo
   mismo que abrir la corrida en la web.
4. **Una corrida congelada** responde con su foto. `vista_corrida` ya lo hace.
5. **Precio de insumo sin tarifa** (`sin_precio`) o en $0: se muestra «sin precio en la
   lista Principal». La regla "nada en $0": un $0 nunca se presenta como precio.
6. **APU con componentes sin precio:** si algún componente de `cost_apu` sale con una
   `calidad_cruce` de alerta (sin precio, sin cruce), la cifra va con «(incompleto: N
   componentes sin precio)». No se repite el texto de la alerta, que también lleva
   montos (ver «No hacer» en CLAUDE.md).

### Candado contra cifras inventadas

El texto crudo del modelo (antes del reemplazo y **sin** los marcadores) pasa por
`privacy.texto_con_dinero`. Si trae una cifra, el modelo la inventó: no tenía de dónde
sacarla. Ese párrafo se reemplaza por «[se omitió una cifra que no vino del sistema]».
Toda cifra que ve la persona sale del servidor.

## Historial

El cliente guarda **dos versiones** de cada respuesta del agente:

- `crudo`: con marcadores. Es lo que se reenvía como historial.
- `texto`: con cifras. Es solo lo que se muestra.

Igual que en la mesa, el servidor no confía en el historial:

- Un mensaje **del usuario** con dinero (`texto_con_dinero`) responde `bloqueado` sin
  llamar a la IA.
- Uno **del agente** con cifras se reemplaza por `[mensaje omitido]`. No se bloquea,
  porque eso envenenaría el chat.

Si un cliente viejo o con error manda la versión con cifras, el agente pierde ese
mensaje y la cifra no viaja.

## Herramientas (solo lectura, sin dinero)

Tope compartido: `MAX_HERRAMIENTAS = 4` búsquedas por mensaje. Al llegar al tope, las
herramientas se apagan con `tool_choice: {"type": "none"}` sin sacarlas de `tools`: los
modelos nuevos rechazan el `tool_choice` forzado con 400.

- **`buscar_insumos(texto)`** — reusa `alm.precios.list_insumos` (la búsqueda del
  buscador de la mesa, **no** `search_insumos_por_palabras`). Devuelve código, nombre,
  unidad, grupo y `ref`. Sin rendimientos observados: no ayudan a responder un precio.
- **`buscar_apus(texto)`** — el `Matcher` del chat de la mesa. Devuelve los **dos
  turnos** si existen, cada uno con su `ref`. No usa el turno de una fila: aquí no hay
  fila.
- **`buscar_proyectos(texto)`** — busca por nombre en carpetas de nivel 1 y en corridas.
  Para cada carpeta que coincide devuelve sus corridas, incluidas las de subcarpetas.
  Cada corrida va con nombre, carpeta, estado, modo, si tiene capítulos, número de
  líneas y `ref`.
- **`capitulos(corrida_id)`** — código, nombre y número de actividades de cada
  capítulo, con su `ref`. Los nombres salen de `vista_corrida(...)["capitulos"]`, copiados
  **clave por clave** sin los montos, por el mismo motivo que `insumo_encontrado_to_dict`:
  el borde hacia la IA no vuelca objetos.

Con varias coincidencias (cinco «tubería»), la IA lista las opciones, cada una con su
marcador. Con demasiadas, pide precisar.

## Piezas

| Archivo | Qué hace |
|---|---|
| `apu_tool/dominio/consulta_chat.py` (nuevo) | herramientas sin dinero, prompt, bucle de tool use con tope. Reusa `_acotar` y el armado de mensajes de `composicion_chat.py` importándolos, no copiándolos. |
| `apu_tool/servicio/consulta.py` (nuevo) | reemplazo de marcadores: el único punto de este chat que toca dinero. Lee `vista_corrida`, `PricingEngine` y el catálogo. |
| `apu_tool/dominio/privacy.py` | helpers `*_to_dict` para los resultados nuevos (corrida y capítulo sin montos). |
| `apu_tool/servicio/rutas.py` | `POST /api/consulta/chat`, SSE, rol `consulta`, rate limit igual que el chat de la mesa. 503 sin `ANTHROPIC_API_KEY`. |
| `web/src/components/consulta/ChatConsulta.tsx` (nuevo) | botón flotante con `AvatarIngeniero` y panel lateral. Reusa el render de mensajes de `PanelAgente` extrayendo lo común, no duplicándolo. |
| `web/src/components/Layout.tsx` | monta `ChatConsulta`. El estado vive en el layout, así que el panel **sigue abierto al cambiar de página**; además se guarda en `sessionStorage` (envuelto en try/catch) para sobrevivir a un recargo. |
| `CLAUDE.md` | sección del chat de consulta, `servicio/consulta.py` en la lista de quienes tocan dinero, y la regla del reemplazo en «No hacer». |

Sin API key, el botón sale deshabilitado con el mismo aviso que la revisión. No hay
fallback determinístico: un buscador sin lenguaje natural es otra feature.

### Por qué `servicio/` y no `dominio/` para el reemplazo

`vista_corrida` vive en `servicio/corridas.py`, y es la que ya resuelve los casos
difíciles (corrida congelada, contexto de transporte del proyecto, lista de la corrida,
armado a medias). Reusarla es la única forma de que el chat diga **el mismo número** que
la pantalla de la corrida. Recalcular en `dominio` sería la tercera suma que
`resumen_por_capitulo` existe para evitar.

## Errores

- **El modelo falla o se pasa del tope de vueltas:** el mensaje «No pude responder,
  vuelve a intentar.» (`MSG_REINTENTAR`), como en la mesa.
- **`vista_corrida` devuelve `None`** (corrida borrada entre la búsqueda y el
  reemplazo): «[cifra no disponible]».
- **Una excepción al reemplazar un marcador** no tumba la respuesta: ese marcador sale
  como no disponible y el error se registra en el log.

## Pruebas

**Backend (pytest, sin API real: advisor falso como en `test_composicion_chat_*`):**

- Ningún payload hacia el modelo lleva dinero. `assert_no_money` sobre cada resultado de
  herramienta, y el historial con cifras sale omitido.
- Reemplazo: cada tipo × campo da la misma cifra que `vista_corrida` y que `cost_apu`.
- Marcador inválido (tipo, campo, id inexistente, capítulo ajeno) → «[cifra no
  disponible]».
- Corrida a medio armar y capítulo incompleto → etiqueta de parcial.
- Insumo sin precio → «sin precio en la lista Principal», nunca "$ 0".
- Una cifra escrita por el modelo se omite; los marcadores no disparan ese candado.
- Mensaje del usuario con dinero → `bloqueado` sin llamar al advisor.
- `buscar_proyectos` trae las corridas de subcarpetas y no suma entre corridas.
- Endpoint: rol `consulta` alcanza; sin clave → 503.

**Frontend (vitest):** el historial que se manda es el `crudo`; el panel sobrevive a
navegar; sin IA el botón queda deshabilitado.

**Smoke real con API key** antes del merge, con las cuatro preguntas de arriba contra la
base real, y en el navegador antes del push.

## Riesgos conocidos

- **Falso positivo del detector:** «¿cuánto cuesta el apu 4859?» se bloquea («cuesta»
  y un número a menos de 3 palabras). Medido: las cuatro preguntas de ejemplo, «precio
  del tubo pvc de 6 pulgadas» y «costo del concreto de 3000 psi» pasan. El detector es
  compartido y **no se afloja** para este chat; el motivo del bloqueo le dice a la
  persona cómo reescribir. Un test fija este comportamiento para que un cambio se note.
- **Respuestas ambiguas por nombre de proyecto:** «Calle 13» puede casar con varias
  carpetas o corridas. La IA lista y pregunta; no escoge por su cuenta cuando hay más de
  una.
- **Costo de la IA:** cada pregunta son hasta 6 llamadas. Mismo modelo que el resto
  (`config.AI_MODEL`). Medir en el smoke y decidir después si conviene Haiku.
