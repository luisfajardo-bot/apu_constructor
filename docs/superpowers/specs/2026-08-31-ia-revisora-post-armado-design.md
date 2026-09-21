# IA revisora post-armado (y candado de filas sin APU)

Fecha: 2026-08-31
Rama: `feat/ia-revisora-post-armado`, apilada sobre `feat/distancias-transporte-proyecto`
Estado: diseño aprobado, sin implementar

## Problema

Hoy la IA entra **dentro** del armado, ítem por ítem (`assemble.py::assemble_item`):

| Caso | Hoy |
|---|---|
| Código IDU del presupuesto existe | AUTO, sin fuzzy ni IA |
| Similitud ≥ `MATCH_ACCEPT` (88%) | AUTO, sin IA |
| Entre `MATCH_REVIEW` (55%) y 88% | la IA elige entre los top-5 candidatos → REVIEW |
| Bajo 55% | la IA ve los candidatos; si dice "ninguno sirve" → `_try_generate` **inventa el APU desde cero** |

Tres problemas con eso:

1. **La IA decide sola que nada sirve y pasa a inventar.** Nadie aprueba ese salto. Un
   APU generado trae rendimientos inventados y se costea como si fuera de la biblioteca.
2. **Es por ítem y en línea.** Bloquea el armado (segundos por línea) y la IA nunca ve
   el presupuesto como un todo: no puede notar que la línea 12 y la 45 son la misma
   actividad con APUs distintos.
3. **Los AUTO no se cuestionan nunca.** Un 90% de parecido de nombre puede ser el APU
   equivocado ("excavación manual" vs "excavación mecánica") y hoy nadie mira. Ahí está
   el daño silencioso, y es la mayoría del presupuesto.

Aparte, cuando una fila queda **sin APU** (lo correcto: mejor $0 con alerta que un número
inventado) hoy solo hay una alerta pasiva. Se puede congelar y descargar el cuadro con
filas sin APU y a nadie le salta nada.

## Decisión

La IA deja de armar y pasa a **revisar**. El armado se vuelve 100% determinístico y
rápido; después, con un botón explícito, una pasada de IA audita la corrida completa y
**propone** — nunca aplica sola.

Y las filas sin APU se vuelven un **candado duro**: no se congela ni se descarga el
cuadro hasta que todas tengan APU.

## Alcance

### Dentro

- Quitar la IA del armado (`assemble.py`).
- Módulo nuevo `apu_tool/dominio/revision.py` (barrido + profundización).
- Persistencia del veredicto por fila.
- Endpoint SSE de revisión + UI en la corrida (columna Veredicto, aplicar suelto y en lote).
- Composición generativa a pedido (un botón, una fila).
- Candado de filas sin APU en `congelar` y en `generar_cuadro`, con contador visible antes.

### Fuera, a propósito

- `pricing.py` y el invariante #1 no se tocan.
- La biblioteca de APUs no se toca.
- CLI y GUI arman determinístico y **no** ofrecen revisión. El motor vive en `dominio/`,
  así que sumarla después son ~15 líneas.
- `corrida.use_ai` queda en la base como histórico, sin efecto.
- Ninguna alerta de costeo distinta de "sin APU" se vuelve candado. Siguen siendo avisos.

## Diseño

### 1. El armado pierde la rama de IA

`Assembler` deja de recibir `advisor`. `assemble_item` queda:

| Caso | Resultado |
|---|---|
| Código IDU existe | AUTO |
| Similitud ≥ 88% | AUTO |
| 55–88% | mejor candidato, **REVIEW** |
| < 55% | **sin APU, $0 con alerta** |

Esto **no cambia comportamiento**: es exactamente lo que hoy produce el camino
determinístico. El piso de `MATCH_REVIEW` ya existe (`ai_assist.py::_choose_deterministic`,
puesto tras el incidente de 2026-08-04 en que una "Localización y replanteo" quedó
costeada como pedestal de concreto). Solo se elimina la bifurcación.

`_try_generate` y `compose.py` **no se borran**: se mueven detrás de un disparo explícito
(ver §5). Nadie los llama en automático.

El interruptor "usar IA" sale de la pantalla de crear corrida.

### 2. `apu_tool/dominio/revision.py`

Sin HTTP, sin dinero. Recibe las filas ya armadas y el `Almacen`; devuelve un veredicto
por fila:

```python
@dataclass
class Veredicto:
    seq: int
    dictamen: str          # ok | dudoso | cambiar | sin_apu
    apu_sugerido: str | None
    turno_sugerido: str | None
    confianza: float
    justificacion: str
    nivel: str             # barrido | profundo
```

**Paso 1 — barrido.** Lotes de ~25 filas, pero cada lote lleva el índice de la corrida
completa (seq + descripción + APU asignado), así la IA ve el presupuesto entero aunque
dictamine por partes. Payload por fila:

```json
{"seq": 12, "item": "3.1", "descripcion": "...", "unidad": "M3",
 "cantidad": 120.5, "shift": "DIURNO",
 "apu_asignado": {"codigo": "...", "nombre": "...", "unidad": "...", "grupo": "..."},
 "candidatos": [{"codigo": "...", "nombre": "...", "unidad": "..."}]}
```

Sin composiciones (payload chico) y **sin el `score` del fuzzy**: si le damos la nota del
matcher, la copia en vez de pensar. Devuelve `ok` o `revisar` por fila, más incoherencias
entre líneas.

**Paso 2 — profundización.** Solo las marcadas `revisar`. Una llamada por fila, ahora con
la composición `DePriced` completa (insumos, rendimientos, unidades) del APU asignado y de
cada candidato. Sale el dictamen final con `nivel="profundo"`.

**Privacidad.** Los dos payloads se serializan con `privacy.safe_json`.
`licitacion_item_to_dict` ya omite `precio_contractual` y `depriced_apu_to_dict` ya existe:
no hace falta ninguna clave nueva en `_FORBIDDEN_KEYS`.

**Sin `ANTHROPIC_API_KEY` no hay fallback**, a propósito: un revisor determinístico sería
el matcher auditándose a sí mismo. El botón queda deshabilitado con el motivo.

**Modelo y esfuerzo.** `config.AI_MODEL`. Barrido con `effort: "low"`, profundización con
`"medium"`. Cliente inyectable, para que los tests le pasen un doble.

### 3. Persistencia del veredicto

Columna nueva `corrida_item.revision_json TEXT` (nullable). NULL = fila nunca revisada.

- SQLite: `db/corridas.sql` + el `PRAGMA table_info` / `ALTER TABLE` idempotente de
  `corridas_db.py::init_schema`, igual que `snapshot_json`.
- Postgres: `db/pg/corridas.sql`, en la tabla y en el bloque de
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` que ya está al final del archivo.

El veredicto viaja en `_vista_item`, así que **no hace falta endpoint de lectura**: la
tabla ya lo recibe con la vista.

**Invalidación.** Si una fila cambia de APU, su veredicto se borra en el mismo punto donde
se escribe la fila. Una opinión sobre un APU que ya no está es peor que ninguna. Efecto
lateral deseable: aplicar todas las sugerencias vacía el panel.

### 4. API

- `POST /api/corridas/{id}/revision/stream` — SSE con el `_event_stream` que ya usa el
  armado. Eventos: `started {total}`, `barrido {revisar}`, `progress {i, total, seq,
  veredicto}`, `done {resumen}`, `error {detail}`. Rol **editor**. Corrida congelada →
  409: una foto no se revisa. Entra en el rate limiting de `limites.py`.
- `POST /api/corridas/{id}/componer/{seq}` — dispara `_try_generate` para esa fila y
  devuelve la propuesta **sin persistir nada** (ver §5). Rol editor.
- **Aplicar sugerencias: sin endpoint nuevo.** `confirmar_items` ya es la primitiva de
  lote (valida que el APU exista antes de escribir, un solo recosteo, un solo
  `vista_corrida`). Se le agrega un parámetro opcional
  `asignaciones: dict[int, tuple[str, str]]` (seq → código, turno) para aplicar N
  sugerencias distintas en una llamada. Es un `if` dentro de la primera pasada que ya
  recorre las filas; el camino actual con un solo `apu_codigo` no cambia.

### 5. Composición generativa a pedido

Cuando la revisión dictamina `sin_apu` ("para esto no hay nada en la biblioteca"), la fila
muestra un botón. Solo si el usuario lo pulsa:

1. `POST /corridas/{id}/componer/{seq}` corre `_try_generate` y devuelve la composición
   propuesta (insumos + rendimientos, sin dinero). **No escribe nada.**
2. El frontend abre el alta de APU que ya existe (`autoria.py`), precargada con esa
   propuesta.
3. Al guardar, el APU entra a la biblioteca por el camino normal (con sus validaciones de
   duplicados) y se asigna a la fila con `confirmar_items`.

O sea: la IA nunca mete un APU a la biblioteca. Propone; el usuario crea.

### 6. Candado de filas sin APU

Helper `seqs_sin_apu(rows) -> list[int]` en `servicio/corridas.py`. Dos puntos de control:

- `congelar()` → 409 `{detail, seqs}` si hay filas sin `apu_codigo`.
- `generar_cuadro()` → el mismo chequeo, **aparte**. No basta con el de `congelar`: cuando
  la corrida ya está congelada con foto, `generar_cuadro` se salta el congelado, y una
  corrida congelada *antes* de esta feature sí puede traer filas sin APU.

**Sin callejón sin salida.** Una corrida congelada con filas sin APU no se puede revisar
(409) ni descargar (409), pero `activar()` ya existe: el 409 del cuadro dice explícitamente
"activá la corrida, asigná el APU de las N filas y volvé a congelar".

**Visible antes de la puerta.** Contador rojo permanente en la barra de la corrida —
"N filas sin APU" — que al pulsarlo filtra la tabla a esas filas. Congelar y Descargar
quedan deshabilitados mientras N > 0, con el motivo en el tooltip. El 409 es la red, no el
aviso: el usuario se entera al terminar el armado, no al final del día.

### 7. UI

Densa, table-first, sobre la tabla de corrida que ya existe. Sin cards.

- Botón **Revisar con IA** en la barra de acciones, con el conteo de filas a revisar antes
  de arrancar. Deshabilitado con motivo si no hay API key o si la corrida está congelada.
- Progreso reusando la barra del armado.
- Columna **Veredicto**: ✔ ok · ⚠ dudoso · ↔ cambiar a X · ✖ sin APU. La justificación en
  el detalle de la fila. Entra sola en los filtros por columna que ya tiene la tabla, así
  que "ver solo las que la IA objetó" sale gratis.
- Fila con `cambiar` → botón Aplicar. Barra de lote → "Aplicar N sugerencias" (una sola
  llamada, vía `asignaciones`).

## Manejo de errores

- **Sin API key** → botón deshabilitado, no error en tiempo de ejecución.
- **Fallo de la IA a mitad** → los veredictos ya guardados se quedan; el evento `error` lo
  dice y se puede re-correr solo sobre las filas sin veredicto.
- **`apu_sugerido` con código que no existe en la biblioteca** → se descarta la sugerencia
  y la fila baja a `dudoso` con nota. La IA no puede inventar un código.
- **JSON truncado / respuesta inválida** → esa fila (o ese lote) queda sin veredicto y se
  cuenta en el resumen del `done`. No se inventa un `ok`.

## Límites aceptados

Van con comentario `ponytail:` en el código, no escondidos:

- Sin tope duro de filas por revisión. El botón avisa cuántas va a revisar.
- Dos revisiones simultáneas sobre la misma corrida: gana la última. Los veredictos son
  por fila e idempotentes, así que el daño es gastar dos veces, no corromper.
- El barrido reparte la atención entre 25 filas por llamada. Si se le escapan objeciones,
  la palanca es bajar el lote, no rehacer el diseño.

## Pruebas

Ningún test toca la red: el revisor recibe su cliente por inyección y los tests le pasan
un doble con respuestas escritas a mano.

1. **Privacidad** — los dos payloads salen por `safe_json`; un test mete un precio a la
   fuerza y espera `PrivacyViolation`; otro verifica que el payload real no lleva
   `precio_contractual` ni el `score` del fuzzy.
2. **Armado sin IA** — un advisor espía que revienta si lo llaman, y los cuatro casos de
   la tabla de §1 dando exactamente lo mismo que hoy con `use_ai=False`. Es la prueba de
   no-regresión del cambio.
3. **Revisión** — el barrido marca N filas y la profundización corre sobre esas y solo
   esas; un `apu_sugerido` inexistente degrada a `dudoso`; un lote con JSON inválido no
   produce `ok`.
4. **Persistencia** — el veredicto sobrevive un `vista_corrida`; cambiar el APU de la fila
   lo borra.
5. **Aplicar** — `confirmar_items` con `asignaciones` mixtas asigna a cada seq el suyo en
   un solo recosteo, y `tests/test_corridas_confirmar_lote.py` sigue verde **sin tocarlo**
   (esa es la prueba de que el camino viejo no cambió).
6. **Candado** — congelar y cuadro con una fila sin APU → 409 con los seqs; con todas
   asignadas → 200. Y el caso legacy: corrida congelada antes de esta feature, con fila
   sin APU, el cuadro también da 409.
7. **Contrato dual-backend** — `revision_json` existe y se comporta igual en SQLite y en
   Postgres, por el test de contrato compartido que ya existe.
8. **Frontend (vitest)** — la columna Veredicto renderiza los cuatro dictámenes; Congelar
   y Descargar están deshabilitados mientras haya filas sin APU.

## Rama y riesgo de integración

El código que esta feature toca (`assemble.py`, `servicio/corridas.py`, `alertas.py` con
el parámetro `contexto`) vive en `feat/distancias-transporte-proyecto`, que está en espera
de PR y **no se toca**: ni un commit ni un push.

`feat/ia-revisora-post-armado` sale apilada encima de ella. Cuando distancias entre a
master, esta rama se rebasa encima sin conflictos. Si el PR de distancias cambia en
revisión, hay que rebasar; si se rechaza, esta rama arrastra su código y habría que
replantear la base.
