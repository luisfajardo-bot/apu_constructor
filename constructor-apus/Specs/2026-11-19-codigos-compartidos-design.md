> Espejo automático — no editar aquí. Fuente: `docs/superpowers/specs/2026-11-19-codigos-compartidos-design.md`

# Códigos compartidos en el alta de APUs — diseño

Fecha: 2026-11-19 · Rama: `fix/codigos-compartidos`

## Problema

El catálogo tiene **652 códigos con dos insumos** (586 con los dos visibles). Vienen de la hoja
`INSUMOS_IDU-INT` del Excel, que pega dos listados del IDU con numeración propia: el de insumos
(filas 1-2744) y el de ítems de obra (desde la 2745). Siempre son 2 filas por código y la de
id menor es la del listado de insumos.

La **lectura** está bien: `cruce.resolver` costea por código + nombre. La **escritura** no:
`servicio/autoria.py::_componentes_de` hace `get_candidatos(cod)[0]` e **ignora** el
`insumo_nombre` que llega. Afecta a los cuatro caminos del alta (crear, editar, duplicar,
aprobar composición). Reproducido en local:

- Editar el APU 4506 BACHEO sin cambiar nada cambia 4513 «BASE GRANULAR CLASE C» ($190.300)
  por «DUCTO TELEFÓNICO» ($16.925), con calidad EXACTO: sin alerta.
- Crear un APU con la señal 7406 ($468.040) guarda la REDUCCIÓN HD ($1.785.000).

**Producción medida (2026-11-19, solo lectura):** 0 APUs dañados. De 5767 componentes, 2110
usan código compartido con la fila 1 (bien), **1** usa la fila 2 (4506 → 4513, nunca editado
desde la app: intacto pero en riesgo) y 4 tienen nombre aproximado. El bug es real y latente.

## Decisiones

1. **Bloquear, no adivinar.** Si el nombre no alcanza para decidir entre las filas de un
   código, el alta no escribe nada y responde con las opciones. Nunca se guarda la primera en
   silencio.
2. **Decide el ingeniero, en la fila.** El error trae las opciones y la interfaz muestra un
   selector en la fila afectada; escoger fija el nombre y se vuelve a guardar.
3. **La identidad sigue siendo código + nombre.** No se guarda el `id` del insumo
   (`seed --force` lo cambia).
4. **No se pregunta cuando el nombre resuelve.** 6092 HERRAMIENTA MENOR está en 904 APUs:
   preguntar siempre sería fricción pura.
5. **No se tocan datos de producción.** El 4506 queda protegido solo: al editarlo viaja su
   nombre guardado, que resuelve EXACTO.

## Diseño

### 1. El embudo: `autoria._componentes_de`

Para cada componente con `tipo != "apu"`:

| Candidatos del código | Resultado |
|---|---|
| 0 | como hoy: se guarda lo que venga (enlace blando, cruce huérfano al costear) |
| 1 | como hoy: nombre y unidad del catálogo, sin mirar el nombre que llegó |
| 2+ y `cruce.resolver(cands, insumo_nombre)` da EXACTO o APROXIMADO | se guarda **esa** fila (nombre y unidad del catálogo) |
| 2+ y da AMBIGUO, o `insumo_nombre` vacío | **duda**: no se guarda |

La elección por nombre sale de **una sola función** nueva en `dominio/cruce.py`,
`elegir(nombres: list[str], objetivo: str) -> int | None` (índice de la fila, o `None` si es
ambiguo), con la lógica que hoy tiene `resolver` (exacto normalizado, luego difuso con
`CRUCE_UMBRAL`/`CRUCE_MARGEN`). `resolver` pasa a usarla, sin cambio de comportamiento. Hace
falta porque `resolver` recibe `Insumo`, que exige `precio`, y el validador de composición
solo tiene nombres.

Las dudas se juntan **todas** (no se corta en la primera) y al final se lanza
`CodigoCompartido(conflictos)`, con
`conflictos = [{"codigo": str, "opciones": [{"nombre": str, "unidad": str, "oculto": bool}]}]`.
Las opciones salen en el orden del catálogo (id) e **incluyen los ocultos, marcados**: ocultar
no es borrar, y si el ingeniero escoge uno lo hace a sabiendas (el selector lo dice). `oculto`
se lee con `identidades_en_conflicto`, que ya lo trae. Nada más: `Insumo` lleva `precio` y el
error viaja por la API, así que se copian campo por campo (misma regla que `_catalogo_de`).

**Histórico de respaldo.** `hist` (precio histórico heredado del APU de origen o del propio)
pasa a indexarse por `(codigo, normalizar(nombre))` en vez de solo por código. El selector
permite cambiar de fila dentro del mismo código, y heredar el histórico de la otra fila sería
un respaldo con el precio de otro insumo. Sin coincidencia cae a `PISO_HIST`, como hoy.
`previos` (marcas de sub-APU) sigue por código: es de los componentes `tipo == "apu"`.

Los componentes `tipo == "apu"` (sub-APU) no cambian: se resuelven contra la biblioteca, no
contra el catálogo de insumos.

`CodigoCompartido` es una excepción propia (subclase de `ValueError`, para que los llamadores
que ya atrapan `ValueError` no se rompan) con el atributo `conflictos`. Las rutas
`POST /api/apus/crear` y `PUT /api/apus/{codigo}/{turno}` (hoy atrapan `ValueError` → 400) la
atrapan **antes** y responden **422** con `detail = {"mensaje": str, "conflictos": [...]}`. El
mensaje dice qué hacer: «El código 7406 es de 2 insumos distintos: escoge cuál va en la fila».

En `aprobar` de composición no se envuelve: `_composicion_o_error` (`rutas.py`) hoy hace
`detail=str(e)` para `ComposicionInvalida` y `ValueError`, y perdería los `conflictos`. Se le
agrega una rama `CodigoCompartido` **antes**, con el mismo `detail` dict. En la práctica no
debería llegar: el validador la frena antes (§2). El cliente web ya tolera un `detail` dict
(`mensajeDeError` lee `detail.mensaje`, `ErrorApi` conserva el `detail`).

### 2. Composición

**Contrato.** `ComponentePropuesto` gana `nombre: str = ""` (en `to_dict` y en el parseo
tolerante) con **tope propio `_MAX_NOMBRE = 1000`**, no `_MAX_TEXTO = 500`: hay nombres reales
de 830 caracteres, y uno recortado nunca da EXACTO (el comentario de `composicion.py` ya avisa
esta trampa; se actualiza). El `PUT` de la mesa también: `ComponenteComposicionIn`
(`servicio/esquemas.py`) gana `nombre: str = ""` y el tipo TS del componente lo mismo — sin
eso Pydantic bota el campo y el selector nunca se guarda. Las versiones viejas del expediente,
sin `nombre`, siguen cargando: el expediente es append-only y no se migra. Una vigente vieja
con un código compartido no queda trabada: la ficha muestra el selector y el validador da
`CODIGO_COMPARTIDO`, así que Aprobar queda deshabilitado hasta escoger (ver §3).

**Generación.** El esquema JSON de "Componer" (`ai_assist`) agrega `nombre` como `required`
(el nombre exacto del insumo tal como lo devolvió el catálogo), y el prompt lo pide. Se sube
`PROMPT_VERSION` de `"composicion/v4"` a `"composicion/v5"`.

**Validador** (`validacion_composicion`). Error nuevo `CODIGO_COMPARTIDO` para un componente
`tipo == "insumo"` cuyo código tiene 2+ filas en el catálogo y cuyo `nombre` no resuelve con
`cruce.elegir`. Pasa la prueba de CLAUDE.md: el ingeniero lo destraba escogiendo en la mesa.
El contexto del validador necesita los nombres por código: se agrega
`candidatos_compartidos: dict[codigo, tuple[(nombre, unidad), ...]]` (solo los códigos con 2+
filas, sin dinero), armado en lote con `get_candidatos_bulk` en los **dos** lugares donde hoy
se arma `unidades_catalogo`: `composicion_agente.py` (contexto inicial) y
`servicio/composicion.py::_con_lista_blanca` (códigos agregados por una persona; sin esto un
código del buscador no se valida). La unidad de un código compartido sale de la fila que
resuelve el nombre, no de `cands[0]`: si no, `UNIDAD_INCOHERENTE` compararía contra la otra
fila.

**Candidatos para el modelo** (`dominio/compose.py`). Hoy se deduplican por código, así que el
modelo ve un solo nombre por código compartido (el del antecedente, que es el correcto para
ese caso). Se deja así: con `nombre` en el esquema, el modelo devuelve el nombre que vio.

**Aprobar.** `_componentes_para_autoria` pasa `insumo_nombre = c.get("nombre", "")`.

**Ficha de la mesa** (`_catalogo_de`). Deja de indexar solo por código. Para cada componente
de la propuesta resuelve con su `nombre`; la entrada del mapa trae `nombre`, `unidad`, `grupo`
de la fila resuelta y, si el código es compartido, `opciones: [{nombre, unidad}]`. Si no
resuelve, la ficha va sin `nombre` y con `opciones`. El mapa sigue indexado por código: una
propuesta no lleva el mismo código dos veces (la mesa y `cambiosAgente.ts` ya lo impiden).

**Chat.** Se borra `composicion_chat._motivo_compartido` y su descarte. El `nombre` que manda
el agente se copia al componente propuesto y lo juzga el validador como cualquier otro: si
resuelve, entra; si no, entra a la mesa con `CODIGO_COMPARTIDO` y el ingeniero escoge. Los
puntos del chat que hoy toman `cands[0]` (`_catalogo` y la tarjeta de la propuesta) resuelven
con el `nombre` del componente, y lo que se muestra o se le reenvía al agente es **siempre el
nombre del catálogo**, nunca el que mandó el cliente (es texto libre: podría traer un monto).
Se quita del prompt la regla del código compartido y se sube `PROMPT_VERSION_CHAT` a
`"chat/v5"`.

### 3. Interfaz

**`DialogoAgregarApu`.** Si el guardado responde 422 con `conflictos`, cada fila cuyo código
esté ahí muestra en línea un selector «¿Cuál de los dos?» con las opciones (nombre + unidad).
Escoger fija `insumo_nombre` (y la unidad que se muestra) y limpia la duda de esa fila; el
botón Guardar vuelve a intentar. No hay diálogo nuevo. El resto de las filas no cambia.

**Mesa de composición** (`pages/Composicion.tsx`). Una fila cuya ficha trae `opciones` y no
resolvió (o que tiene el hallazgo `CODIGO_COMPARTIDO`) muestra el mismo selector. Escoger es
una edición normal de la mesa: cambia `nombre` del componente y se guarda con el `PUT` de
siempre, así que queda en el expediente como una versión `editada`.

**Buscador de la mesa.** Al agregar un insumo desde el buscador, el componente nuevo guarda
también `nombre`.

El selector es un solo componente reusado en los dos lugares.

### 4. CLAUDE.md

- Reemplazar la regla de "No hacer" del código compartido en el chat por la nueva: «El alta
  elige la fila de un código compartido por código + nombre (`cruce.resolver`); si no
  resuelve, bloquea con las opciones. No vuelvas a `get_candidatos(cod)[0]`».
- Anotar `CODIGO_COMPARTIDO` junto a las demás reglas del validador.

## Fuera de alcance

- Un APU que use **las dos** filas del mismo código a la vez: la mesa y `cambiosAgente.ts`
  indexan por código y no lo permiten; no existe en producción.
- Otros caminos de escritura: revisados y limpios. El importador de APUs y el seed guardan el
  nombre del Excel (sin `cands[0]`); subapus, transporte y ajustes no reescriben la identidad.
- Renumerar los ítems de obra del IDU: son códigos oficiales.
- Reparar datos: no hay nada dañado.

## Pruebas

Rojo primero:

- Editar el 4506 sin cambios conserva 4513 «BASE GRANULAR CLASE C» (hoy lo cambia).
- Crear con 7406 + «SEÑAL VERTICAL SR 90X30…» guarda la señal (hoy guarda la reducción).
- Crear con 7406 sin nombre → `CodigoCompartido` con las dos opciones; la ruta da 422 con
  `detail.conflictos`.
- Dos códigos ambiguos en el mismo APU → un solo error con los dos.
- Un código de un solo insumo sigue igual aunque el nombre no coincida.
- Los 4 casos aproximados de producción (5225/5241 D y N, TARIFA DIA/MES) resuelven a la
  fila correcta y quedan guardados con el nombre canónico.
- `hist`: cambiar de fila dentro del mismo código no hereda el histórico de la otra.
- `PUT` de la mesa conserva `nombre`; un nombre de 830 caracteres no se recorta.
- `aprobar` con conflicto responde 422 con `detail.conflictos` (no un string).
- `cruce.resolver` sin cambio de comportamiento tras extraer `elegir`.

Además: `CODIGO_COMPARTIDO` en el validador (y que no salga si el nombre resuelve); aprobar una
composición con `nombre` guarda la fila correcta; parseo de una versión vieja sin `nombre`;
`_catalogo_de` con `opciones`; el chat ya no descarta un código compartido cuyo nombre
resuelve. Vitest: el selector en el diálogo (422 → escoger → reintento) y en la mesa. Suite
completa en SQLite y contra Postgres (`env -u DATABASE_URL` en local), `npm run build` y
navegador antes del push.
