# Chat con el agente en la mesa de composición — diseño

> Fecha: 2026-11-18. Rama: `feat/chat-agente-composicion`.
> Extiende el agente de composición asistida
> (`docs/superpowers/specs/2026-09-10-agente-composicion-design.md`).

## Problema

Hoy la composición es de un solo disparo: "Componer" genera una propuesta completa y
la mesa (`/corridas/:id/componer/:seq`) la deja editar a mano. Si la propuesta no
sirve, las opciones son editarla uno mismo o **regenerarla entera**. No hay forma de
decirle a la IA "cambia solo esto", "incluye tal insumo" o "busca una mano de obra que
tenga X".

## Objetivo

Un panel de chat en la mesa, con un agente visible (un avatar animado según lo que
está haciendo), al que se le pide en lenguaje natural que ajuste la composición. El
agente busca en el catálogo y **propone** cambios; la persona los aplica o los
descarta.

## Decisiones tomadas

| Tema | Decisión |
|---|---|
| Alcance | Solo la mesa de composición (filas sin APU). |
| Control | El agente propone y la persona aplica. La tabla solo cambia con un clic. |
| Dinero en el texto | Se bloquea y se avisa. El mensaje no sale, y se valida en el servidor. |
| Historial | Efímero, en la pestaña. Queda rastro de cada cambio aplicado como versión del expediente. |
| Arquitectura | Agente con herramientas de búsqueda de solo lectura (bucle de tool use, tope de 4). |
| Avatar | Una persona con casco (cabeza y hombros), SVG inline animado con CSS. |

## 1. Backend

### Endpoint

`POST /api/corridas/{cid}/composicion/{seq}/chat`: SSE, rol `editor`, con los mismos
candados que la generación (corrida activa y la fila de esta línea).

Request:

```json
{
  "mensajes": [{"rol": "usuario|agente", "texto": "..."}],
  "componentes": [ /* la tabla tal como está en pantalla, sin guardar incluido */ ]
}
```

### Antes de llamar a la IA

1. `privacy.texto_con_dinero(texto) -> Optional[str]` revisa **todos** los mensajes
   del usuario del historial, no solo el último: el historial lo manda el cliente y el
   cliente puede mentir. Si encuentra dinero → evento `bloqueado` y el SDK **no se
   llama**.
2. Se topa el historial a los últimos 20 mensajes de 1000 caracteres cada uno (lo que
   sobra se recorta en el servidor, no se rechaza).
3. `assert_no_money` sobre el payload completo, serializado con `privacy.safe_json`.

**Detector de dinero.** Bloquea si hay `$`, `COP` o `pesos`, o si aparece una palabra
de dinero (`precio`, `costo`, `valor`, `cotiz-`, `tarifa`, `vale`, `cuesta`) a pocas
palabras de un número. Deja pasar las cantidades físicas ("8 horas", "0,125 HH/m3",
"1,05 m3"). Los falsos positivos se aceptan a propósito: la regla del repo es
*preferimos fallar a filtrar*. Vive en `dominio/privacy.py`, que es la frontera, y no
tiene espejo en el frontend: la autoridad es el servidor.

### Orquestador: `dominio/composicion_chat.py`

Hermano de `composicion_agente.py`. Un generador de eventos, como `componer`.

Herramientas, todas de solo lectura y des-monetizadas:

| Herramienta | Devuelve |
|---|---|
| `buscar_insumos(texto, grupo?)` | hasta 15: código, nombre, unidad, grupo y rendimientos observados (`rendimientos_observados`). Sin ocultos. |
| `buscar_apus(texto)` | hasta 5 APUs de referencia con su composición (`DePricedApu`). |

- Cada resultado se convierte a tipos sin precio y pasa por `assert_no_money` antes de
  volver al modelo.
- Tope: **4 llamadas a herramientas por mensaje**. Al llegar al tope, el siguiente
  turno va sin herramientas, para obligar a una respuesta final. No se usa
  `tool_choice` forzado: el modelo por defecto puede rechazarlo.
- `effort="low"`: una instrucción puntual no necesita el razonamiento de una
  composición completa.
- El `usage` de cada mensaje se escribe en el log del servidor, para medir el costo
  real.

Respuesta final estructurada:

```json
{
  "texto": "respuesta para la persona",
  "cambios": [
    {"op": "agregar|quitar|modificar", "componente": { /* contrato de 10 campos */ }}
  ]
}
```

- El `componente` usa **el mismo contrato** de la composición
  (`dominio/composicion.py`), con el esquema igual de acotado (`tipo` solo `insumo`,
  sin `sub_apu` en `funcion`). Se parsea con `propuesta_desde_json` para que pase por
  el mismo acotado que una respuesta de "Componer".
- El servidor descarta los cambios con códigos que no existen en el catálogo o están
  ocultos **antes** de emitirlos, y lo dice en un campo `descartados`.
- Para `quitar` basta el código.

### Eventos SSE

| Evento | Datos | Avatar |
|---|---|---|
| `pensando` | `{}` | pensando |
| `buscando` | `{herramienta, consulta}` | buscando |
| `respuesta` | `{texto, cambios, descartados, modelo, prompt_version}` | lista |
| `bloqueado` | `{motivo}` | error |
| `error` | `{detail}` | error |

### Aplicar: el `PUT` de siempre

El navegador aplica los cambios a la tabla y guarda con el `PUT` existente
(`servicio/composicion.py::guardar_edicion`), que ya revalida sin IA y amplía la lista
blanca con lo que se agregó (la lista blanca solo crece). Tres campos opcionales
nuevos en el body:

- `instruccion` → se guarda como `motivo = "chat: <instrucción>"`.
- `modelo`, `prompt_version` (`"chat/v1"`) → se guardan en sus columnas.

Sin columnas nuevas. La versión queda `editada`, y `prompt_version="chat/v1"` la
distingue de una edición a mano para el futuro reporte de correcciones. Sin esos
campos, el `PUT` se comporta **exactamente** igual que hoy.

El texto de `instruccion` ya pasó por el detector de dinero, porque es el mismo
mensaje que se mandó al agente, y se vuelve a pasar por él en el `PUT`: el expediente
debe seguir siendo una fila limpia que se pueda reinyectar.

**Mesa vacía.** Si la fila no tiene expediente, el chat funciona igual y el primer
"Aplicar" crea la versión 1. Hoy `guardar_edicion` devuelve `None` sin vigente: hay
que darle ese camino (`version_base = 0`, lista blanca = los códigos agregados,
`apus_referencia = []`). Se resuelve en el plan.

### Lo que no cambia

El armado, `aprobar` (sigue por `autoria.crear_apu`), el validador y la generación con
"Componer".

## 2. Frontend

### Ubicación

Un panel a la derecha de la tabla de la mesa, de ~360 px y plegable. En pantallas
angostas pasa debajo de la tabla. Sin tarjetas: una cabecera con el avatar y el estado
en texto ("Buscando 'soldador' en mano de obra…"), el hilo de mensajes y la caja de
texto.

### Archivos

- `web/src/components/composicion/PanelAgente.tsx`: el chat, la lectura del SSE y
  Aplicar/Descartar.
- `web/src/components/composicion/AvatarIngeniero.tsx`: un SVG inline con partes
  separadas (cabeza, casco, ojos, brazo, lupa) y una sola prop, `estado`.
- `web/src/lib/cambiosAgente.ts`: una función pura
  `aplicarCambios(filas, cambios) → {filas, conflictos}`.

`Composicion.tsx` (819 líneas) solo monta el panel y le pasa la tabla y un callback
para guardar.

### El cambio propuesto en el hilo

```
+ 1023  OFICIAL         HH   0,125   (antecedente APU 4859, n=12)
~ 2210  CONCRETO 3000   M3   1,05 → 1,03
− 3017  VOLQUETA        VJE
         [Aplicar]  [Descartar]
```

- **Aplicar** pasa los cambios por `aplicarCambios` y guarda con el `PUT`. Los
  conflictos (agregar un código que ya está; quitar o modificar uno que ya no está) se
  muestran en una línea y el resto se aplica.
- **Descartar** solo marca el bloque como descartado en el hilo.
- Un 409 por `version_base` vieja reutiliza el aviso que ya existe.
- Mientras el agente responde, la caja de texto se deshabilita. Un mensaje bloqueado o
  con error vuelve a la caja para corregirlo y reenviarlo.

### Avatar

Un ingeniero de cabeza y hombros con casco, animado con CSS `@keyframes`, sin
librerías.

| Estado | Gesto |
|---|---|
| `espera` | Respira (escala de ±2 %) y parpadea cada ~4 s |
| `pensando` | Mano a la barbilla y ojos hacia arriba |
| `buscando` | Aparece una lupa que barre de lado a lado |
| `lista` | Pulgar arriba una vez y vuelve a `espera` |
| `error` / `bloqueado` | Niega con la cabeza dos veces, con el casco en el color de alerta |
| `deshabilitado` | Quieto, en gris |

- `prefers-reduced-motion`: sin movimiento, solo el color del casco y el texto de
  estado.
- El SVG lleva `role="img"` y un `aria-label` con el estado; el texto de estado va en
  `aria-live="polite"`.

### Sin `ANTHROPIC_API_KEY`

El panel se muestra deshabilitado (avatar `deshabilitado`) con el mismo mensaje que hoy
tiene el botón "Componer".

## 3. Errores

- Credencial inválida, sin saldo o sin SDK: las traducciones que ya existen en
  `ai_assist` (`credencial_invalida`, `sin_saldo`, `IANoDisponible`).
- Un 429, un timeout o un JSON ilegible → evento `error` con "No pude responder,
  vuelve a intentar". El mensaje vuelve a la caja.
- `PrivacyViolation` **sube**: no se disfraza como error de chat (mismo criterio que
  `componer` y `revision.barrer_lote`).
- Si se corta la conexión, no se pierde nada persistido: nada se escribe hasta
  Aplicar.

## 4. Pruebas

Con TDD y el SDK falso, igual que las pruebas de composición.

**Backend**
- Un mensaje con monto en **cualquier** posición del historial → `bloqueado` y el SDK
  falso no recibe ninguna llamada.
- El detector: una tabla de casos que deben bloquearse (`$45.000`, "cotizaron a 45000",
  "vale 3 millones", "COP 1200") y casos que deben pasar ("8 horas", "0,125",
  "1,05 m3", "rendimiento de 12 m2 por jornada").
- Los resultados de las herramientas pasan `assert_no_money`; las búsquedas no
  devuelven insumos ocultos.
- El bucle respeta el tope de 4 herramientas y termina con una respuesta.
- Los cambios con códigos inexistentes u ocultos salen en `descartados`, no en
  `cambios`.
- El `PUT` con `instruccion` deja `motivo="chat: …"` y `prompt_version="chat/v1"`; con
  una instrucción que tiene dinero, se rechaza.
- Regresión: el `PUT` sin los campos nuevos responde idéntico a hoy.
- La mesa vacía: el primer `PUT` crea la versión 1.
- No se esperan cambios en `datos/` (el `PUT` reusa `composiciones.agregar`). Si la
  mesa vacía obliga a tocar un repo, sus pruebas corren en SQLite y en Postgres.

**Frontend (vitest)**
- `aplicarCambios`: agregar, quitar, modificar y los tres conflictos.
- `PanelAgente` con un SSE falso: los eventos mueven el estado, Aplicar llama al
  guardado y bloqueado/error devuelven el texto a la caja.
- `AvatarIngeniero`: la clase y el `aria-label` de cada estado.
- `npm run build` (no solo `tsc --noEmit`).

**Navegador, antes del push:** el chat y el avatar en la mesa real, incluida la
animación de cada estado y el modo de movimiento reducido.

**Smoke con API real:** tres actividades, anotando la calidad de los cambios, cuántas
búsquedas usó por mensaje y el `usage` de cada mensaje.

## Por verificar al empezar el plan

- Que el modelo por defecto (`config.AI_MODEL`) acepte herramientas + salida
  estructurada + pensamiento adaptativo en la misma llamada. Si no, la respuesta final
  pasa a ser una herramienta `responder` con el esquema como `input_schema`.
- Qué primitiva de búsqueda de insumos usar (`search_insumos` o
  `search_insumos_por_palabras`, que tiene un N+1 anotado en
  `docs/pendientes-agente-composicion.md`) y cómo excluir los ocultos.

## Fuera de alcance

- Sub-APUs como componentes (fase 3 del agente).
- Guardar la conversación.
- El chat en la biblioteca de APUs y un asistente global.
- Que el agente edite la tabla sin confirmación.
