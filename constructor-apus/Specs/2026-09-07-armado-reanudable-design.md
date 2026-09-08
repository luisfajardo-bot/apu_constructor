> Espejo automático — no editar aquí. Fuente: `docs/superpowers/specs/2026-09-07-armado-reanudable-design.md`

# Armado reanudable — el armado deja la petición y pasa a ser trabajo del servidor

> **Revisado el 2026-09-08**, después de que entrara a master *igualar el costo al
> contractual* (`59e789b`). Esa feature cambió la definición del candado del cuadro y
> agregó un punto que escribe `estado`; las dos cosas tocan este diseño y están
> incorporadas abajo. También se corrigió un error propio: `max(seq)+1` **sí** puede
> retroceder.

## El problema, medido

Las listas de licitación reales de esta empresa traen **1000–2000 ítems**. El armado
corre hoy **dentro de la petición HTTP**, como un SSE que emite un evento por ítem.

Medido en los logs de Render del 2026-09-07 (instancia `srv-d93d6hlckfvc73c94t30-7mnb2`,
plan free):

- Dos armados corriendo **a la vez** e intercalados: uno de **1939** ítems y otro de **1250**.
- Ritmo real: **2,8 s/ítem** el de 1250 y **6,2 s/ítem** el de 1939 (se estorban entre sí;
  `WEB_CONCURRENCY` está en 1). Da **~1 hora** y **~3 horas** respectivamente.
- La instancia arrancó **11 veces ese día**. Solo 4 fueron deploys; las otras 7 son el
  spin-down del plan free. Vidas de instancia: 33, 94, 86, **18**, **20**, 109, **26**, **19** min.
- A las 20:02:57 se ve textual: `==> Deploying...` entre el ítem 180/1250 y el 290/1939.
  Los dos armados murieron ahí.

**Memoria descartada como causa:** pico de 151 MB contra un límite de 512 MB, sin OOM,
sin traceback, sin error de base en todo el día. El `could not accept SSL connection:
EOF detected` de los logs de Supabase es ruido (un TCP que se cierra antes de terminar
el handshake TLS; no corta conexiones establecidas).

Un armado de 1 a 3 horas contra una instancia que vive 18–30 minutos **no termina nunca**.

### Lo que hace que "reanudar" no sea trivial

**El archivo subido no se guarda en ningún lado.** `corrida.archivo` es solo el nombre
(procedencia) y `corrida_item.item_json` guarda cada ítem *ya armado*. Cuando la
instancia murió en el ítem 290 de 1939, el servidor sabe qué eran los ítems 0–289 y
**no tiene idea de qué eran los 290–1938**.

Dos agravantes encontrados en el camino:

- `corrida_item` **no tiene `UNIQUE (corrida_id, seq)`**: una fila duplicada entra
  callada y duplica la actividad en el cuadro. Es el motivo por el que `agregar_items`
  se niega a trabajar mientras la corrida está en `armando`.
- Mientras una corrida esté en `armando`, `Corrida.tsx:102` **la repolla cada 2 segundos
  indefinidamente**. Una corrida colgada deja ese bucle vivo en cada pestaña abierta, y
  no hay ninguna limpieza de corridas huérfanas en el repo.

## Decisiones tomadas

| Pregunta | Decisión |
|---|---|
| ¿Dónde corre el armado? | **En el servidor**, desacoplado de la petición. Se puede cerrar la pestaña. |
| ¿De dónde salen las líneas que faltan? | De **las líneas ya interpretadas**, guardadas al crear la corrida. |
| ¿Quién retoma un armado cortado? | **El servidor solo, al arrancar**, con tope de **3** intentos. |
| ¿Dos armados a la vez? | **Uno a la vez, con cola visible** (`tu corrida es la 2ª`). |
| ¿Cómo se ejecuta el trabajo de fondo? | **Hilo en el proceso web**, con la cola en la base. |

### Por qué un hilo y no un Background Worker de Render

Un worker aparte (~US$7/mes más, otro destino de deploy) aísla la web de los armados,
pero **sigue muriendo y reiniciándose**: necesitás reanudar igual. No ahorra nada del
trabajo de esta spec, solo suma aislamiento. Un Cron Job es más barato todavía pero te
hace esperar al próximo tick y tiene tope de duración.

El hilo es lo único que no agrega costo ni un segundo deploy, y su único defecto real
—morir con la instancia— es exactamente el problema que esta spec resuelve. **La lógica
se diseña leyendo su trabajo de la base y no de la memoria**, así que mudar a un worker
aparte el día que la web se ponga lenta no cambia una línea del motor.

**Seguridad de hilos, verificada:** SQLite abre una conexión nueva por llamada y la
cierra (`corridas_db.py:36`), y Postgres usa `psycopg_pool.ConnectionPool`. El worker
comparte el `Almacen` de `app.state` sin nada especial.

## Diseño

### Datos nuevos

Cinco columnas en `corrida`, por `ALTER TABLE ... ADD COLUMN` al boot en los dos
backends (el patrón ya existe: así se agregaron `duracion_ms`, `modo`, `carpeta_id`,
`nombre`, `lista_precios_id`, `snapshot_json`, `revision_json`).

| Columna | Para qué |
|---|---|
| `plan_json` | las líneas ya interpretadas del Excel, en orden. Única fuente de qué falta armar. |
| `intentos` | cuántas veces se intentó armar. Corta el bucle si algo la mata siempre en el mismo punto. |
| `ultimo_error` | por qué se detuvo, en español, para que la pantalla lo diga. |
| `armando_por` | qué instancia la reclamó. |
| `armando_desde` | cuándo fue el último latido de esa reclama. |

**Por qué la reclama.** Con `numInstances=1` y `WEB_CONCURRENCY=1` no puede haber dos
workers… salvo **durante un deploy**: Render arranca la instancia nueva mientras la
vieja drena. En esa ventana el worker nuevo vería la corrida en `armando` y la
retomaría *mientras el viejo sigue armándola*: dos workers escribiendo las mismas filas
sobre una tabla sin `UNIQUE (corrida_id, seq)`. La reclama lo cierra — solo se toma un
trabajo cuya reclama esté ausente o vencida.

**Índice único `UNIQUE (corrida_id, seq)`.** Cinturón además del tirante: con él un
duplicado revienta en vez de mentir, que es la preferencia declarada del repo
(«preferimos fallar a filtrar»).

**Estado nuevo `armado_detenido`.** Hoy hay `armando` / `en_revision` / `finalizada`.
`armando` pasa a significar «hay trabajo pendiente» — *es* la cola. Si `intentos` supera
**3**, la corrida tiene que **salir** de la cola o el worker la reintentaría para
siempre: pasa a `armado_detenido`, con `ultimo_error` visible y un botón para reintentar.

### El worker

Un solo hilo, arrancado en el `lifespan` de `app.py` (hoy ese hook solo cierra el pool
al salir). Su bucle:

1. **Reclamar** la corrida en `armando` más vieja cuya reclama esté ausente o vencida,
   con un `UPDATE ... WHERE` condicional para que la reclama sea atómica y no un «leo y
   después escribo». Incrementa `intentos` al reclamar.
2. **Calcular desde dónde seguir**: `max(seq) + 1` de `corrida_item`. No se cuentan
   filas: con un hueco en el medio (una línea borrada), contar reanudaría en el lugar
   equivocado y duplicaría.

   **`max(seq)+1` sí puede retroceder, y por eso se cierra la puerta.** Si se borran
   las ÚLTIMAS líneas mientras arma y después la instancia muere, el máximo baja y el
   worker re-arma justo lo que se acababa de borrar. Hoy no puede pasar porque durante
   el armado no se ven las filas (`Corrida.tsx:131`); este diseño las hace visibles y
   operables, así que abre el agujero. **`borrar_items` pasa a rechazar la corrida en
   `armando`**, con el mismo mensaje y por la misma razón que ya lo hace `agregar_items`
   (`corridas.py:233`). Es una guarda de una línea y deja el bucle en una escritura por
   ítem; la alternativa (un contador de `proximo_seq` en la corrida) obliga a escribirlo
   junto con cada fila y duplica las escrituras del camino que ya es el cuello de botella.
3. **Armar** los ítems de `plan_json` desde ese índice, con el mismo `_armar_fila` de
   hoy y un `Assembler` compartido. Cada fila se guarda al armarla, como ahora.
4. **Latir**: refrescar `armando_desde` **cada 25 ítems**, para que la reclama no venza
   mientras trabaja. Con el ritmo medido (2,8–6,2 s/ítem) eso es un latido cada 1–2,5
   minutos, holgado contra el TTL de 3 minutos.
5. Al terminar: `en_revision`, duración, y a buscar el siguiente trabajo.

**Se despierta por evento, no por reloj.** `POST /corridas` levanta un
`threading.Event` para que arranque al instante. Además hace un poll de respaldo **cada 30 segundos**, que es lo que cubre el arranque de la instancia: al bootear no hay ningún
evento, y sin el poll una corrida a medias esperaría a que alguien cree otra.

**Dos niveles de error, distintos a propósito:**

- **Un ítem revienta** → se atrapa, la fila queda armada **sin APU** con el motivo en
  `explicacion`, y el armado **sigue**. Un ítem venenoso cuesta una fila, no la corrida.
  Cae solo en el candado de `seqs_sin_apu`, que desde la feature de igualar el costo al
  contractual (master, 2026-09-07) es «sin APU **ni costo declarado positivo**». La fila
  envenenada no tiene `costo_manual`, así que el candado la sigue atrapando — y además
  ahora hay salida: se la puede **igualar al contractual** y emitir el cuadro sin armarle
  el APU, que es exactamente para lo que se construyó ese botón.
- **El proceso muere entero** (reinicio, OOM, deploy) → no hay nada que atrapar. La
  reclama vence, la instancia siguiente retoma, y `intentos` sube. Superado el tope de 3,
  `armado_detenido`.

**La cola es la base, no la memoria.** «Corridas en `armando` ordenadas por antigüedad»
*es* la cola; tu posición es cuántas hay más viejas que la tuya. Nada se pierde en un
reinicio.

### Invariante nuevo: `estado` deja de ser una etiqueta

Con este diseño `armando` **es** la cola de trabajo, no un rótulo informativo. De ahí
sale una regla que antes no existía:

> Nadie saca una corrida de `armando` salvo el worker al terminarla (o `reanudar`, que
> la vuelve a meter). Un `set_estado` sin guarda la borra de la cola para siempre y
> nadie se entera: queda a medio armar, sin worker que la retome y sin error que mirar.

Auditados los cinco puntos que escriben `estado` en `servicio/corridas.py` a la fecha
(`:162`, `:262`, `:291`, `:665`, `:839`): cuatro están guardados por
`estado == "finalizada"` —incluido el `:665` que agregó la feature de igualar el costo—
y el quinto es el fin del armado. **Ninguno lo rompe hoy.** Se escribe acá y se cubre
con un test porque el próximo que agregue un `set_estado` no va a tener este contexto.

### API

- **`POST /corridas/stream` se borra.** El SSE del armado deja de existir.
- **`POST /corridas`** pasa a ser el único camino de creación: lee el Excel, guarda
  `plan_json`, crea la corrida en `armando`, despierta al worker y **devuelve al
  instante** `{id, total, posicion_en_cola}`.
- **`GET /corridas/{id}`** suma un bloque
  `armado: {hechos, total, posicion_en_cola, intentos, ultimo_error}`.
- **`POST /corridas/{id}/reanudar`** (rol `editor`): para una corrida en
  `armado_detenido` — pone `intentos` en cero, la vuelve a `armando` y despierta al worker.

**El motor de armado no se reescribe.** El bucle por ítem de `construir_corrida_stream`
se extrae a una función que recibe *desde qué índice* arrancar. El worker la llama con
`max(seq)+1`; la CLI y la GUI la llaman con 0 y siguen armando en el acto, sin worker y
sin cola. Un solo camino de armado, como pide la convención del repo.

### Pantalla

`armado.tsx` (el `ArmadoVivoProvider` con su EventSource, 121 líneas) se queda sin razón
de ser: todo lo que informaba sale del poll que `Corrida.tsx:102` ya hace.

- Crear una corrida navega directo a su página, sin esperar.
- En `armando`: barra con `hechos / total` y, si hay cola, «tu corrida es la 2ª». El
  poll ya trae las filas, así que la tabla se sigue llenando sola — a segundos de
  granularidad en vez de por ítem, que en un armado de horas no cambia nada.
- En `armado_detenido`: el motivo y un botón «Reintentar armado».
- `MisCorridas` muestra el estado, para que una corrida a medias se vea en la lista.

**Ajuste que se aprovecha:** el poll de 2 s durante 3 horas son ~5.400 peticiones por
pestaña abierta, compitiendo con el worker por el único proceso. Sube a 5 s mientras la
corrida esté en `armando`.

## Riesgos

**Sale gratis:** como la reclama es un `UPDATE ... WHERE` atómico, si `WEB_CONCURRENCY`
sube a 2 el diseño **no se rompe** — solo un worker gana la corrida. Degrada en «no va
más rápido», no en «duplica filas». Es justo el modo de fallo que se comió a `presencia`
cuando ese valor derivó.

1. **Esto no acelera nada.** Un armado de 1939 ítems **sigue tardando 1 a 3 horas**; la
   diferencia es que termina. Dónde se van los 2,8 s/ítem **nadie lo midió todavía**.
   El armado no llama `precargar` (los 4 usos son para *leer* corridas ya armadas), pero
   tampoco puede llamarla igual que ellos: no sabe qué APUs va a usar hasta matchear cada
   ítem. El `PricingEngine` sí se comparte entre ítems, así que la caché se calienta con
   los APUs repetidos. **No se promete ninguna mejora en esta spec.**
2. **La ventana del deploy cuesta una espera.** Si la instancia muere de golpe, la
   reclama queda fresca aunque nadie trabaje: la nueva espera a que venza. Ese TTL es el
   tiempo de recuperación. Propuesto **~3 minutos**: más corto arriesga doble armado
   durante el drenaje de un deploy, más largo hace esperar de gusto.
3. **El `UNIQUE (corrida_id, seq)` puede no poder crearse** si producción ya trae
   duplicados de armados muertos. Hay que **contarlos antes de desplegar** y limpiarlos
   como paso manual. La creación del índice al boot tiene que ser **no-fatal**: si falla,
   la app arranca igual y lo grita en el log.
4. **`plan_json` engorda la base.** ~400 KB por corrida de 1900 ítems; 100 corridas ≈ 40 MB
   contra los 500 MB del Supabase free. No alarma hoy, pero crece. Se guarda también
   después de terminar: es el registro de qué se pidió armar.
5. **`plan_json` lleva `precio_contractual`, o sea dinero: entra en `_FORBIDDEN_KEYS`.**
   No es una advertencia en prosa, es una tarea. `CLAUDE.md` lo pide literal («Si agregas
   un campo monetario nuevo, añádelo a `_FORBIDDEN_KEYS`») y la feature de igualar acaba
   de sentar el precedente agregando `costo_manual`. Hoy no filtra —la revisión arma su
   payload campo por campo y nunca vuelca la fila— pero el guardián solo mira **nombres
   de clave**, así que la clave tiene que estar en la lista antes de que a alguien se le
   ocurra mandar el plan entero.
6. **Borrar la corrida mientras se arma** ya está resuelto: `agregar_item` lanza
   `CorridaEliminada` y el worker pasa al siguiente trabajo.

## Fuera de alcance

- **No acelera el armado.** Medir los 2,8 s/ítem es otro trabajo.
- **No arregla el spin-down del free tier.** Eso es subir el plan de Render, y sigue
  siendo lo primero a hacer: sin eso, la instancia se reinicia 7 veces al día y esta
  feature solo hace que el armado sobreviva a cada reinicio en vez de evitarlos.
- **No toca CLI ni GUI:** siguen armando síncrono, sin worker ni cola.
- **No cambia igualar el costo al contractual.** Se puede seguir usando sobre las filas
  ya armadas mientras el resto de la corrida se arma: escribe sobre `seq` que ya existen
  y el worker solo agrega `seq` nuevos, así que no se pisan. Lo único que se bloquea
  durante `armando` es **borrar**, por el punto de reanudación.
- **No hace reanudable la revisión con IA**, que tiene exactamente el mismo problema de
  forma (un SSE largo que un reinicio mata). Queda para después, y este worker es donde
  va a vivir cuando le toque.

## Pruebas

- **Worker:** reclama atómica (dos intentos concurrentes, uno solo gana); reclama vencida
  se puede retomar; reclama fresca no; `intentos` sube por intento y `armado_detenido` al
  pasar el tope.
- **Reanudación:** una corrida con N filas armadas retoma en `max(seq)+1` y no duplica
  ninguna; con un hueco en los `seq`, tampoco.
- **Errores:** un ítem que revienta deja la fila sin APU con el motivo y el armado sigue;
  la corrida borrada a mitad corta limpio.
- **Borrar durante `armando` da error** (no borra y no mueve el punto de reanudación), y
  la misma corrida en `en_revision` sí deja borrar.
- **`estado` como cola:** ninguna operación de fila (confirmar, igualar el costo al
  contractual, borrar) saca la corrida de `armando`.
- **Privacidad:** `assert_no_money` rechaza un payload con la clave `plan_json`.
- **Cola:** el orden es por antigüedad y la posición reportada coincide.
- **Contrato de los dos backends:** las columnas nuevas y los métodos de reclama, en
  `tests/test_paridad_backends.py` y en el contrato compartido que corre contra Postgres real.
- **Frontend:** progreso desde el poll, estado `armado_detenido` con su botón, y que la
  creación navegue sin esperar.
