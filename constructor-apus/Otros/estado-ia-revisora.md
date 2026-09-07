> Espejo automático — no editar aquí. Fuente: `docs/estado-ia-revisora.md`

# Estado — la IA pasa de armar a revisar

Rama `feat/ia-revisora-post-armado`, **rebaseada sobre `origin/master`** (`7fdc6dd`) el
2026-09-07. Nació encima de `feat/distancias-transporte-proyecto` (base `7be02a9`), pero
esa rama sigue esperando la demo con el superior y esta ya está lista, así que se
independizó para poder mergearse primero. Al rebasear se quitaron los tres restos de
distancias que el 3-way merge había arrastrado: el `contexto=` de `PricingEngine`/
`Assembler` en `servicio/corridas.py`, el párrafo del prompt de `dominio/revision.py` que
le avisaba a la IA que un proyecto puede ajustar los km de acarreo, y dos tests de
`Corrida.test.tsx` que son de aquella feature. **Cuando distancias entre habrá que
reponer esos tres puntos** — el orden de merge invirtió quién arrastra a quién.

- Spec: `docs/superpowers/specs/2026-08-31-ia-revisora-post-armado-design.md`
- Plan: `docs/superpowers/plans/2026-08-31-ia-revisora-post-armado.md`

## Qué hace

**Antes:** la IA participaba del armado. Para un ítem dudoso elegía entre los candidatos y,
si decidía que ninguno servía, **inventaba un APU desde cero** con rendimientos inventados,
que se costeaba como si viniera de la biblioteca. Un número inventado con pinta de
autoritativo es el peor resultado posible en una licitación.

**Ahora:**

1. **El armado es determinístico y nunca inventa.** `assemble_item` elige entre los APUs
   del histórico (con el piso de `MATCH_REVIEW`) o deja la fila **sin APU**. No llama a la
   IA: `tests/test_assemble.py::test_armado_nunca_llama_a_la_ia` revienta si alguien la
   vuelve a meter.
2. **La IA entra después, como revisora.** `dominio/revision.py` audita la corrida ya
   armada y emite un veredicto por fila: `ok | dudoso | cambiar` (a otro candidato) `|
   sin_apu`. **Propone; nunca aplica.** Quien aplica es el usuario, con `confirmar_items`.
3. **La composición generativa quedó detrás de un botón por fila.** Lo que devuelve es una
   propuesta de estructura (sin costos), que el usuario confirma por el alta normal de APUs
   (`servicio/autoria.py`, con sus validaciones de duplicados). La IA nunca mete un APU en
   la biblioteca.
4. **Una fila sin APU pasó de alerta pasiva a candado duro.** `congelar` y `generar_cuadro`
   lanzan `FilasSinApu` y dicen qué `seq` faltan.

Piezas nuevas: `apu_tool/dominio/revision.py`, la columna `corrida_item.revision_json` en
los dos backends, y tres endpoints:

| Endpoint | Rol | Qué hace |
|----------|-----|----------|
| `POST /corridas/{id}/revision/stream` | editor | SSE: `started`, `barriendo` (uno por lote), `barrido`, `veredicto` (uno por fila), `done`, y `error` si la IA falta o se cae con el stream ya abierto |
| `POST /corridas/{id}/componer/{seq}` | editor | propone una composición; **no escribe nada** |
| `POST /corridas/{id}/items/confirmar-lote` | consulta | extendido con `asignaciones`: un APU distinto por fila (aplicar sugerencias en lote) |

## Estado

Terminada y verde. Verificación en serie del 2026-09-07 (tras el rebase a master), después de cerrar los hallazgos de la
revisión final (`sin_veredicto` visible en la interfaz, la carrera del veredicto pegado a
otro APU, el `ok` imposible en una fila sin APU y la `PrivacyViolation` disfrazada al
componer):

```
python -m pytest tests/ -q   → 888 passed, 15 skipped, 1 warning (slowapi, preexistente)
npm run build                → OK (tsc -b + vite)
npm test                     → 46 archivos, 259 pruebas
npm run lint                 → 11 warnings, todos preexistentes
```

Migración de esquema: `revision_json` se agrega al boot en los dos backends
(`ALTER TABLE ... ADD COLUMN` en SQLite, `ADD COLUMN IF NOT EXISTS` en Postgres). No se
desplegó nada: la rama no es `master`.

## Decisiones de diseño que no se leen en el código

- **El barrido manda el índice de la corrida completa en cada lote.** Sin el índice, la IA
  ve 25 filas sueltas y no puede detectar la incoherencia que más importa: dos actividades
  gemelas con APUs distintos, o una escalera de excavaciones donde una fila rompe el patrón.
  El índice (`indice_corrida`: seq, descripción, unidad, apu) es una línea por ítem, barato
  comparado con las composiciones. Se paga en tokens repetidos, no en llamadas.
- **Dos vocabularios distintos, a propósito.** El barrido devuelve `ok | revisar` y es un
  **triaje**: solo decide a quién vale la pena mirarle la composición. `revisar` NO está en
  `DICTAMENES`. El veredicto (`ok | dudoso | cambiar | sin_apu`) sale de la profundización,
  que sí vio insumos y rendimientos. Mezclarlos convertiría un "no sé" en un dictamen.
- **Sin `ANTHROPIC_API_KEY` no hay fallback determinístico, y es deliberado.** Un revisor
  determinístico sería **el matcher auditándose a sí mismo**: diría "ok" exactamente en las
  filas donde el matcher ya está convencido, que son justo las que no hace falta revisar.
  Un veredicto así no informa y sí da falsa tranquilidad. Preferimos un 503 honesto
  (`IANoDisponible`) y el botón deshabilitado.
- **El candado es solo "sin APU", no cualquier alerta de costeo.** Una alerta
  (`sin_precio_lista`, acarreo sin clasificar, margen raro) es información para decidir: el
  usuario puede tener razones para emitir el cuadro igual. Una fila **sin APU** no es una
  advertencia, es un hueco: la fila va en $0 y el cuadro **se ve completo sin estarlo**.
  Trabar todas las alertas convertiría el candado en un botón de "ignorar" que se aprende a
  ignorar; trabar solo el hueco lo mantiene creíble.
- **El veredicto se borra en TODO confirm, no solo cuando cambia el APU.**
  `corridas.actualizar_eleccion` escribe `revision_json=NULL` y es el único punto de paso
  de un confirm — así que "Confirmar el APU actual" (mismo código, mismo turno) también
  borra el veredicto. O sea: reconfirmar una fila `⚠ dudoso` para dejar registro de que la
  miraste te borra la justificación que decía por qué. Con una revisión costando US$2–3 la
  diferencia importa, pero el comportamiento es **conservador** (se pierde una
  justificación, no se gana una mentira) y no se cambió: lo que estaba mal era el
  documento, que decía "cuando cambia el APU".
- **El veredicto dice QUÉ APU evaluó, y se descarta si ya no coincide.** Borrar al
  confirmar no alcanza: `revisar_corrida_stream` lee las filas al **abrir** el request y el
  generador corre por minutos con la tabla sin bloquear (el `readOnly` del frontend solo
  mira si la corrida está congelada). Secuencia real: la revisión dictamina `ok` sobre la
  fila 7 con el APU A → el usuario la reasigna al B (`revision_json=NULL`) → el
  `set_revision` de la revisión, ya en vuelo, escribe el `ok` **después**. Quedaba una fila
  con el APU B y un visto bueno sobre el A, que es la mentira más creíble de la pantalla.
  De ahí `Veredicto.apu_evaluado` (el `apu_codigo` de la fila en el momento de evaluarla) y
  el descarte en `_vista_item`: un veredicto sobre otro APU no dice nada del actual. Tres
  decisiones dentro de esa: se filtra al **hidratar** y no dentro del stream, porque una
  lectura por fila reintroduciría el N+1 contra Postgres que este repo ya arregló una vez;
  es **auto-sanador**, el veredicto zombi no se vuelve a mostrar y no hay que limpiar la
  base; y la **ausencia** de la clave (veredictos guardados antes del campo) se trata como
  "no sé qué evalué, muéstralo", no como "evalué None". El campo **no viaja al frontend**:
  filtrar en el backend alcanza y es menos superficie de contrato.
- **Una fila sin APU nunca puede salir en `ok`.** El cortocircuito de `sin_apu` solo cubre
  "sin APU **y** sin candidatos vivos"; el resto se degrada en `revisar`, que es el único
  punto por el que pasan los dos caminos posibles (el barrido contestando `ok` a una fila
  con `apu_asignado: null` —el prompt le pide `revisar`, pero eso es una instrucción, no
  una restricción— y una profundización que dictamina `ok` sin asignado, donde "el APU
  asignado es el correcto" no significa nada). Un `✔ ok` verde sobre una fila que el
  candado rojo cuenta como hueco es la pantalla contradiciéndose.
- **El `Revisor` se instancia por request**, no compartido en `app.state`: compartirlo
  mezclaría estado entre peticiones.
- **`revisar()` recibe el `almacen` por parámetro** en vez de guardarlo en el `Revisor`. Así
  el `Revisor` queda como fachada pura de la IA y los tests lo sustituyen sin montar base.
- **El barrido reporta lote por lote**, no de una: con 300 líneas son 12 llamadas con
  pensamiento adaptativo, varios minutos. Un stream mudo tanto rato lo corta el proxy, y la
  interfaz no tiene cómo saber si avanza. Los lotes se cuentan **antes** del primer `yield`
  para poder pintar "0 de N" en vez de un indeterminado.
- **Las filas que el barrido no contestó quedan SIN veredicto**, contadas en
  `sin_veredicto`. No se inventa un `ok`: "no contestada" y "sin objeciones" no son lo
  mismo, y confundirlas es exactamente el underbid silencioso que este repo evita. Y se
  **ven**: con `sin_veredicto > 0` el aviso final es un `toast.warning` (no un `success`)
  que dice "N sin revisar (la IA no las contestó): no significa que estén bien", y la
  columna Veredicto ofrece la opción **«— sin revisar»** (centinela `SIN_VEREDICTO` en
  `lib/corridaTabla.ts`, hermano del `SIN_APU`) para filtrarlas. Lo que **no** se puede es
  distinguir en la celda "la IA no contestó esta fila" de "esta fila nunca se revisó": las
  dos llegan como `revision: null`, y persistir la diferencia sería un 5º dictamen guardado
  en la base — justo el vocabulario que este módulo evita ampliar. La celda dice las dos
  posibilidades en el `title` y no afirma ninguna; contarlas es el aviso, encontrarlas es
  el filtro.
- **`componer_item` devuelve solo estructura**, sin costos: mandar el costo de un APU que
  todavía no existe es ruido, y el precio de cada insumo ya se ve en el catálogo.

## Riesgos residuales conocidos

- **Heartbeat SSE (el más probable de morder).** El barrido ahora emite un evento por lote,
  así que la ventana de silencio bajó de ⌈n/`TAM_LOTE`⌉ llamadas a **una sola**. Pero si esa
  única llamada con pensamiento adaptativo se pasa del idle timeout del proxy de Render
  (~100 s), el stream muere y el usuario ve un corte sin explicación. La palanca correcta es
  un **heartbeat SSE en `_event_stream`** (`rutas.py`), no bajar `TAM_LOTE`: el índice viaja
  en cada lote, así que el costo del índice crece como **O(n²/TAM_LOTE)** y bajarlo compra
  latencia con dinero. **Sin arreglar a propósito:** hay que medir el tiempo real de una
  llamada en el despliegue antes de elegir el intervalo del heartbeat.
- **Los tests de Postgres nunca corrieron en local en esta rama.** Se saltean sin
  `TEST_DATABASE_URL` (`tests/test_migracion_pg.py`, `test_transporte_pg.py`,
  `test_auditoria_contrato.py`…). La receta del Postgres desechable (binarios portables EDB,
  puerto 55433, sin Docker ni admin) está documentada en la memoria del proyecto.
  **Nunca apuntarlos a producción: hacen `DROP SCHEMA`.** El espejo Postgres de
  `revision_json` está cubierto por `tests/test_paridad_backends.py` (firmas, sin servidor),
  que es una red más fina que nada pero no ejecuta SQL.
- **Costo.** Una revisión completa de una corrida de ~300 líneas se estimó en el orden de
  **US$2–3** con `claude-sonnet-5`: ~225k tokens de entrada en el barrido, de los cuales
  ~165k son **el índice repetido** en los 12 lotes. No es problema hoy (una corrida se revisa
  una vez, no en bucle). Si algún día duele, la optimización natural **no** es bajar
  `TAM_LOTE` sino `cache_control: {"type": "ephemeral"}` sobre el bloque del índice, que es
  byte por byte idéntico en todos los lotes.
- **`assert_no_money` mira solo nombres de clave, no valores.** Un monto embebido en un
  string de texto libre pasa el guardián sin que salte nada. De ahí la regla operativa, ya
  escrita en el docstring de la función y en "No hacer" de `CLAUDE.md`: **nunca meter en un
  payload hacia la IA texto generado por el motor de costos** (mensajes de `alertas.py`,
  explicaciones de `pricing.py`). El payload de la revisión respeta la regla — copia clave
  por clave y usa `DePricedApu`, un tipo que estructuralmente no puede llevar dinero — pero
  el guardián no lo garantizaría si alguien agrega un campo de texto libre.
- **Dos revisiones simultáneas sobre la misma corrida se pisan** (gana la última). Los
  veredictos son por fila e idempotentes, así que el daño es **gastar dos veces**, no
  corromper. Arreglo si molesta: un lock por corrida
  (`ponytail:` en `servicio/corridas.py:698`).
- **`revision/stream` y `componer` piden rol `editor`, pero `confirmar-lote` pide
  `consulta`.** O sea: quien no puede *pedir* una revisión sí puede *aplicar* sus
  sugerencias. Es la asimetría preexistente de `confirmar` (ver el hallazgo "rol consulta
  escribe" de `docs/auditoria-seguridad-2026-08-28.md`), no algo que esta rama introdujo, y
  no se tocó acá para no arrastrar la auditoría entera.
- **`use_ai` quedó sin efecto y sigue vivo.** La casilla salió de la web
  (`CorridasInicio.tsx` ya no manda el campo), pero el flag sigue existiendo entero:
  `Form(None)` en dos endpoints, la columna `corrida.use_ai` en los dos backends,
  `--no-ai` en la CLI y el checkbox "Usar IA" de la GUI Tkinter. Todos terminan en
  `ApuAdvisor(enabled=use_ai)` **que el armado ya no consulta**, y `componer_item` crea su
  propio `ApuAdvisor()` ignorando `meta.use_ai`. O sea: hoy es un no-op que se persiste.
  No se borró acá porque el borrado toca columna, modelo, CLI, GUI y cuatro endpoints, y
  esta tanda era la limpieza de `ai_assist.py`. Si se saca, hay que decidir qué pasa con
  las corridas viejas que tienen el valor guardado.
- **Un `seq` o un código de APU inventados por la IA se descartan**, no degradan a error:
  `marcadas &= {f.seq for f in filas}` y la validación de `apu_sugerido` (que degrada a
  `dudoso`). Si la IA alucina mucho, el síntoma será "muchos dudosos", no un fallo ruidoso.
- **El candado de "sin APU" NO está en la puerta de la CLI ni de la GUI.** `pipeline.py`
  (`run_pipeline`, `build_desde_presupuesto`) y el "Exportar" de Tkinter llaman
  `write_report` sin pasar por `seqs_sin_apu`: el candado vive en `congelar` y
  `generar_cuadro`, que son web. Es alcance consciente —la feature es web-only— y el cuadro
  de la CLI ya trae hoja `ALERTAS` con esas filas resaltadas, así que ahí el hueco se ve;
  lo que no hay es puerta trabada. Si se decide hacerlo global, el punto de paso es
  `pipeline.py`, no `report.py`.
- **El backend no rechaza revisar una corrida en estado `armando`.** El guard vive solo en
  el frontend (`motivoNoRevisar`); forzando el POST, la revisión corre sobre una corrida a
  medio armar. Encaja con el patrón preexistente de `congelar`/`confirmar` (que tampoco
  miran `estado`, solo `modo`), pero la asimetría con el guard de `congelada` —ese sí es del
  backend, con su 409— queda escrita acá: es una decisión, no un olvido.
- **Un veredicto `cambiar` no se invalida si el APU sugerido se borra de la biblioteca.**
  El clic en `Aplicar` da un 400 accionable (`confirmar_items` valida código+turno antes de
  escribir), así que el daño está contenido; lo que queda es una sugerencia muerta
  invitando a reintentar. En lote es peor de leer: un solo APU borrado tumba las N
  sugerencias, porque la validación es atómica a propósito (nada se aplica a medias).
- **La composición propuesta llega al alta con los precios en 0.** `componer_item` devuelve
  estructura sin costos (a propósito), así que en el diálogo de alta la columna "Costo" y la
  edición bidireccional costo↔rendimiento quedan muertas — justo cuando el diálogo le pide
  al usuario revisar los rendimientos. El precio de cada insumo sí se ve en el catálogo.
- **Aplicar una sugerencia de la IA no queda en auditoría.** `confirmar_items` no llama
  `registrar_auditoria` (preexistente: tampoco lo hacía confirmar a mano). Ahora hay una
  fuente de cambios nueva, así que no se puede reconstruir quién aplicó qué propuso la IA.

## Verificación manual en el navegador

Los tests no cubren nada de esto, y el repo ya se quemó una vez con un modal que se cerraba
solo con toda la suite verde (ver la memoria de `DialogoTexto`). **En cambios de UI el
navegador va antes del push.**

1. **Crear una corrida** (`CorridasInicio`): la casilla **"Usar IA"** ya no está. El armado
   corre igual y con la misma duración. El `FormData` manda solo `archivo`, `carpeta_id`,
   `nombre` y `lista_id`.
2. **Candado sin APU** (`Corrida.tsx`, cabecera): con filas sin APU tiene que verse el
   contador rojo subrayado **`{N} sin APU`**, y **`Congelar`** y **`Descargar cuadro`**
   deshabilitados con el motivo en el tooltip. Clic en el contador filtra a las líneas sin
   APU (la caja de filtro muestra `(sin APU)`); clic de nuevo lo apaga. Asignar la última
   fila que faltaba debe habilitar los dos botones **sin recargar**. Ojo con dos casos:
   - **`Activar` NO se deshabilita** (es el mismo botón que `Congelar`, con el label
     alternado): una corrida congelada con filas sin APU tiene que poder reactivarse.
   - `Descargar cuadro` queda bloqueado **incluso congelada**, con el mensaje "actívala,
     asígnalas y vuelve a congelar".
3. **Revisión completa con `ANTHROPIC_API_KEY` de verdad** (no un mock), sobre una corrida
   de tamaño real (≥100 líneas, mejor ~300). El botón dice **`Revisar {N} líneas con IA`**
   y pasa a `Revisando…`:
   - el progreso avanza: `Triaje: {n} de {N} lotes listos` y después
     `Veredictos: {n} de {N} filas` — nunca un indeterminado eterno;
   - **el proxy no corta el SSE** — es el riesgo #1 de esta rama y solo se ve acá;
   - al terminar, el toast `Revisión lista: {n} por cambiar, {n} dudosas, {n} sin APU.`
     cuadra con lo que muestra la tabla, y las filas `sin_veredicto` salen con `—`, no
     con `✔ ok`;
   - **si la IA dejó filas sin contestar** (el caso que hay que provocar, p. ej. bajando
     `max_tokens` o cortando la red a mitad del barrido): el aviso es **amarillo** y dice
     `{n} sin revisar (la IA no las contestó): no significa que estén bien`, y el
     desplegable de la columna Veredicto ofrece **`— sin revisar`**, que deja exactamente
     esas filas. Sin las dos cosas, 40 filas sin auditar en 300 son invisibles;
   - si corta a mitad, el toast tiene que decir que "los veredictos que alcanzó a guardar
     se conservan" y esos veredictos tienen que estar ahí al recargar.
4. **Aplicar sugerencias.** Por fila: botón `Aplicar` en la celda Veredicto (solo con
   dictamen `↔ cambiar`). En lote: `Aplicar {N} sugerencias` en la cabecera. En los dos
   casos el total de la corrida recalcula y **el veredicto de la fila aplicada
   desaparece** (lo borra `actualizar_eleccion`, en cualquier confirm): que no quede un
   `✔ ok` viejo pegado a un APU nuevo. Mientras una fila está en vuelo, los `Aplicar` de
   las demás se deshabilitan. **La carrera, a mano:** con la revisión corriendo, reasignar
   una fila que ya salió `ok`; al terminar, esa fila tiene que quedar **sin** veredicto
   (lo descarta `apu_evaluado`), no con el `ok` del APU viejo.
5. **Diálogo de composición** (botón `Componer`, solo en filas `✖ sin APU`), título
   `Componer un APU con IA para: {actividad}`:
   - **no se cierra solo** (el escarmiento de `DialogoTexto`);
   - **`Descartar` en el alta no vuelve a pagarle a la IA**: al abrir `Crear APU con esto`
     el diálogo se esconde sin desmontarse, así que cancelar el alta debe volver a la
     **misma** propuesta, sin una segunda llamada. Verificarlo mirando la latencia (o el
     log del servidor), no solo que "aparezca algo".
   - **el 503 sin API key se lee dentro del diálogo**, en la banda roja
     ("...necesita ANTHROPIC_API_KEY en el servidor"), no en un toast que se va.
6. **Ancho de la tabla antes y después de revisar.** Sin revisar, la columna Veredicto **no
   se dibuja** (`hayVeredicto`): contar las columnas, tienen que ser las mismas de siempre.
   Después de revisar aparece con su select de filtro. Que al aparecer no empuje las
   columnas de dinero fuera de la pantalla — mirar en la ventana angosta que usa el
   superior, no solo en pantalla grande.
7. **Sin `ANTHROPIC_API_KEY`:** el botón de revisar queda **deshabilitado** con el motivo
   en el tooltip ("El servidor no tiene IA configurada..."). Ojo: el frontend lo lee del
   campo `ia_disponible` de `GET /api/corridas/{id}`, y lo fuerza a `false` **durante el
   armado en vivo**, así que ahí también sale deshabilitado (es correcto, pero se ve igual
   que el caso sin llave). Con rol `consulta` el botón **no existe** en vez de estar
   deshabilitado: probar con los dos roles.
8. **Corrida congelada:** el botón deshabilitado con "actívala para revisar"; y forzando el
   POST, 409 legible.
9. **Volver a revisar la misma corrida:** los veredictos se sobrescriben, no se acumulan ni
   se duplican en la tabla.

## Limpieza que trajo esta última tanda

Al sacar la IA del armado quedaron ~90 líneas sin llamador en `dominio/ai_assist.py`:
`ApuAdvisor.choose_apu`, `_choose_with_ai`, `_choose_deterministic`, la dataclass
`AIDecision`, `_SYSTEM_PROMPT` y `_RESPONSE_SCHEMA`. Borradas. Sigue vivo `compose_apu` (y
`ComposeResult` / `ComposedComponent` / `_COMPOSE_SYSTEM` / `_COMPOSE_SCHEMA`), que alimenta
el endpoint de componer.

El comentario largo sobre el incidente de producción de 2026-08-04 (una "Localización y
replanteo" costeada como pedestal de concreto, 2010 veces el costo correcto) **no se perdió**:
ya vivía duplicado en `dominio/assemble.py`, que es donde ahora está el piso de
`MATCH_REVIEW`.

También se borró `_ALLOWED_NUMERIC_KEYS` de `privacy.py` — definido y nunca leído desde la
auditoría de 2026-07, aparentaba enforcement sin hacer nada — y en su lugar el docstring de
`assert_no_money` dice ahora su limitación real.
