# Decidir fila por fila qué conflictos del import se aplican igual

**Fecha:** 2026-09-15
**Estado:** aprobado

## Problema

Al importar insumos en lote, una fila cae en el balde `conflicto` y **no se puede hacer
nada con ella**: el preview la lista con su motivo y ahí muere. El caso real del usuario:

> «estoy teniendo unos en conflicto solo porque le faltan unas palabras o incluso porque
> le falta una letra»

El punto de paso es `servicio/autoria.py::conflicto_insumo_detalle`. La identidad de un
insumo es **código + nombre normalizado**; si el código del archivo ya existe pero el
nombre difiere aunque sea en una letra, `_match_identidad` falla y la fila se reporta como
conflicto de código:

> *El código 3202 ya lo usa el insumo «CONCRETO 3000 PSI HECHO EN OBRA PARA REDES».*

`nucleo/texto.py::normalizar` ya perdona mayúsculas, tildes, puntuación y espacios de más.
Lo que no perdona —y no debe perdonar solo— es una palabra menos o un carácter distinto.

## El dato que define el diseño

**652 códigos del catálogo están repetidos, y afectan a 1304 insumos: el 16%.** No son
variantes del mismo material: el código `10000` lo comparten un CHEVRON reflectivo y un
PISO EN LOSETA PREFABRICADA.

Consecuencia: "el código ya existe" a menudo significa "existe varias veces, y son cosas
distintas". Cualquier solución tiene que decir **contra cuál** de los candidatos se está
ofreciendo actualizar, y hacerlo visible.

## Por qué el premarcado no puede ser solo por parecido

El usuario pidió que las filas muy parecidas vengan premarcadas (marcar 200 a mano no es
realista). Medido con `nucleo/relevancia.py::similarity` sobre casos construidos con
nombres del estilo del catálogo real:

| Parecido | Caso | ¿Se quiere importar? |
|---|---|---|
| 89.0% | una letra distinta (`OBRA` → `OVRA`) | **Sí** |
| 88.7% | `CONCRETO … MR-42` vs `MR-40` | **No** |
| 86.1% | `ACERO FY=420 MPA` vs `FY=240 MPA` | **No** |
| 84.4% | `TUBERIA … 6 PULGADAS` vs `8 PULGADAS` | **No** |
| 81.7% | le falta una palabra | **Sí** |
| 78.1% | `CONCRETO 3000 PSI` vs `2500 PSI` | **No** |
| 67.0% | le faltan dos palabras | **Sí** |
| 60.2% | `LADRILLO TOLETE COMUN` vs `PRENSADO` | **No** |
| 55.5% | nombre abreviado (`SUM E INST …`) | **Sí** |
| 10.0% | cosas distintas | **No** |

**No existe un umbral que separe las dos columnas.** Con nombres largos —los del IDU lo
son— cambiar un solo dígito puntúa tan alto como el typo que sí se quiere aceptar. Un
umbral del 80% premarcaría tomar el precio de la tubería de 8" para la de 6".

**El patrón que parecía separarlos:** en todos esos casos peligrosos **cambió un número**;
en los buenos los números son idénticos. La regla `parecido ≥ 80% Y mismos números` daba
0 falsos positivos **sobre esos diez casos**.

### Por qué el premarcado se descartó

**Esos diez casos eran sintéticos y estaban sesgados.** Medida la misma regla contra el
catálogo real (8157 insumos), premarcaría **2602 pares de materiales distintos**:

| Parecido | Par real del catálogo | Diferencia de plata |
|---|---|---|
| **98.9%** | `TARIFA MES … (NO INCLUYE FACTOR DE PRESTACIONES)` vs `(INCLUYE FACTOR …)` | 50-60% |
| **96.7%** | una actividad diurna vs la misma con `HORARIO NOCTURNO` | el turno es parte de la identidad |
| **93.8%** | `SUBBASE GRANULAR CLASE B` [4160] vs `CLASE A` [4161] | otro material |
| 88.3% | `TARIFA JORNAL … SECRETARIA` vs `TARIFA HORA …` | factor ~8 |

El `NO` del primero es *stopword* en `relevancia._STOPWORDS`: el scorer ni lo ve.

**El atenuante, y por qué no alcanza:** `_mejor_candidato` solo compara insumos con el
**mismo código**, y dentro de un mismo código el catálogo no pasa de **49.8%** — medido
sobre todos los pares. O sea que con los datos de hoy la regla no se equivoca ni una vez.

Pero los gemelos peligrosos tienen **códigos consecutivos**: `4159/4160/4161` son SUBBASE
CLASE C/B/A. Basta un dígito mal en la columna `codigo` del archivo para caer en el gemelo,
y la fila vendría premarcada al 93.8%. **La premisa de esta feature es que el archivo trae
errores de dedo**, así que un código mal tecleado no es un supuesto rebuscado: es el mismo
supuesto que justifica la feature.

### Lo que se hace en vez de premarcar

Ninguna casilla viene marcada. La comodidad que el premarcado iba a dar —no cazar 15 filas
entre 200— la da el **orden**: la lista sale ordenada por parecido de mayor a menor, así
que los typos obvios quedan juntos arriba y se marcan de corrido.

Los números siguen siendo la señal más útil, pero se **muestran** en vez de aplicarse: una
fila cuyos números no coincidan se marca visualmente («los números no coinciden»). Es
información para la persona que decide, no una decisión tomada por el servidor.

## Alcance

- `apu_tool/servicio/autoria.py` — resolver el candidato, enriquecer el balde `conflicto`,
  y desviar las filas forzadas al embudo.
- `apu_tool/servicio/rutas.py` — `forzar_ids` en los dos endpoints de import.
- `web/src/lib/tipos.ts`, `web/src/components/insumos/DialogoImportarInsumos.tsx` — las
  casillas y las columnas nuevas.
- `tests/`, `web/src/.../DialogoImportarInsumos.test.tsx`.

**Fuera de alcance, decidido:**

- **Los conflictos por nombre** (nombre repetido bajo otro código). Forzar ahí significaría
  actualizarle el precio a un insumo con un código distinto al que trae el archivo, y el
  código es lo que identifica al insumo en el resto de la app.
- **Corregir el nombre del catálogo** con el del archivo. El usuario confirmó que el typo
  puede estar de los dos lados, sin patrón: el nombre en la base no se toca nunca.
- **Un botón de "forzar todo"**.
- **Elegir un candidato distinto al mejor.** Si el código tiene varios insumos se ofrece el
  de mayor parecido; si no convence, no se marca la casilla. Si resulta que hace falta
  redirigir seguido, se agrega después (YAGNI).

## Diseño

### 1. El candidato se resuelve y se muestra

Cuando una fila con nombre no hace `_match_identidad` y `conflicto_insumo_detalle`
devuelve campo `"codigo"`, se compara el nombre del archivo contra **todos** los insumos
que tienen ese código (`alm.precios.get_candidatos(cod, lista_id)`) y se elige el de mayor
`similarity`. La entrada del balde `conflicto` gana:

```python
{**f, "motivo": motivo,
 "insumo_id": ins.id, "nombre_actual": ins.nombre,
 "precio_actual": ins.precio, "fuente_actual": ins.fuente_precio,
 "parecido": round(sim, 3), "numeros_coinciden": bool(...),
 "sin_precio_actual": ins.sin_precio, "oculto": ...}
```

Los conflictos por **nombre** siguen como están hoy (sin esos campos): el frontend les
pinta la fila sin casilla.

`preview_importar_insumos` pasa a llamar `conflicto_insumo_detalle` en vez de
`_conflicto_insumo`, para distinguir el campo. Las dos ya existen y son públicas; no hay
regla nueva ni duplicada.

### 2. El orden y la señal de los números

El balde `conflicto` sale **ordenado por parecido, de mayor a menor**. Ese orden es la
comodidad: los typos obvios quedan arriba y juntos, y se marcan de corrido sin cazarlos
entre 200 filas. Ordena el backend, no el frontend — en este repo el frontend solo pinta.

Cada conflicto de código lleva además:

```python
def _mismos_numeros(a: str, b: str) -> bool:
    """Los dos nombres traen los mismos números, en el mismo orden.

    Comparar las listas crudas y no `Counter` ni `sorted`: los dos son insensibles al
    orden, así que darían iguales «CABLE 3 X 40 AMP» y «CABLE 40 X 3 AMP», que son dos
    materiales distintos (el catálogo tiene `BREAKER INDUSTRIAL ABB 3 X 40 AMP`)."""
    return re.findall(r"\d+", a or "") == re.findall(r"\d+", b or "")
```

y el resultado viaja como `numeros_coinciden`. La fila donde da `False` se marca visualmente
en el diálogo. **Es una señal, no una decisión**: ninguna casilla viene marcada, el
servidor no decide nada, y lo que se aplica es exactamente lo que el usuario mandó en
`forzar_ids`.

No hay umbral ni constante de configuración: sin premarcado, no hay nada que umbralar.

### 3. La decisión viaja por id

`preview_importar_insumos` y `aplicar_importar_insumos` ganan
`forzar_ids: Optional[set[int]] = None`. Los endpoints lo reciben como
`forzar_ids: list[int] = Form([])`.

**Por `insumo_id` y no por código:** con 652 códigos repetidos, un código no identifica a
un insumo. El id es el único identificador que no se puede malinterpretar.

`aplicar_importar_insumos` ya recalcula el preview internamente, así que con pasarle el
mismo `forzar_ids` queda: **no hay una segunda regla de resolución que se pueda
desincronizar de la que viste en pantalla.**

Si al aplicar ese id ya no resuelve —el catálogo cambió entre el preview y el aplicar— la
fila vuelve a caer en `conflicto` y no se aplica. Falla del lado seguro, sin error.

### 4. La fila forzada entra por el embudo, no por un atajo

Este es el punto que hace que la feature no abra un hueco:

```python
forzados = forzar_ids or set()          # None y [] se tratan igual: no se fuerza nada
...
if campo == "codigo" and ins is not None and ins.id in forzados:
    _upsert_o_invalida(ins, f, fuente_import, actualizar, invalida, protegida)
else:
    conflicto.append({...})
```

Esto vive **solo en la rama "con nombre"** del preview. Una fila sin nombre nunca llega a
`conflicto`: va por `get_candidatos` y termina en `actualizar`, `ambigua` o
`no_encontrada`. Forzar es exclusivamente para filas que traen nombre.

Forzar resuelve una pregunta de **identidad**, no de **permiso**. Al pasar por
`_upsert_o_invalida`, la fila forzada hereda sin código nuevo:

- **el candado**: si la importación es pública y ese insumo tiene precio interno, queda en
  `protegida` aunque esté marcada;
- **el guard del $0** y el guard de no-op, que viven en `aplicar_importar_insumos`;
- la fuente declarada como única etiqueta.

`aplicar_importar_insumos` **no necesita ningún cambio** más allá de pasar el parámetro:
las filas forzadas ya llegan a `actualizar` y su bucle las recorre como a cualquier otra.

### 5. El diálogo

La sección "En conflicto" pasa a mostrar, para los conflictos de código:

| ☐ | Código | Nombre en el archivo | Nombre en tu base | Parecido | Precio actual → nuevo |

Las filas salen **ordenadas por parecido, de mayor a menor**: los typos obvios quedan
arriba y juntos. Ninguna casilla viene marcada. La fila cuyos `numeros_coinciden` sea
`False` lleva un aviso visible («los números no coinciden»), que es la señal más útil que
tenemos y por eso se muestra en vez de aplicarse.

Los conflictos por nombre se siguen listando abajo, con su motivo y sin casilla.

`nAcciones` (el número del botón Aplicar) suma las marcadas, porque van a escribir.

Cambiar una casilla **no** re-dispara el preview: la selección es estado del cliente y solo
viaja al aplicar. (El preview sí se re-dispara al cambiar la fuente, que es lo que ya hace.)

### 6. Pruebas

1. Forzar un conflicto de código actualiza el precio del insumo elegido.
2. **Una fila forzada sobre un insumo con precio interno, con importación pública, sigue
   en `protegida`.** Es la prueba que fija que forzar no es un permiso.
3. `numeros_coinciden` es `False` cuando cambia un número y `True` cuando solo cambian
   letras, incluidos los casos donde el orden difiere (`3 X 40` vs `40 X 3`).
4. Con varios insumos del mismo código, se ofrece el de mayor parecido.
5. Un `forzar_ids` con un id que no resuelve deja la fila en `conflicto` y no escribe.
6. Un conflicto por **nombre** no trae `insumo_id` ni casilla, y forzarlo no hace nada.

7. El balde `conflicto` sale ordenado por `parecido` descendente.

En el frontend: ninguna casilla arranca marcada; marcar una la mete en `forzar_ids` y sube
el conteo del botón Aplicar; y la fila con `numeros_coinciden: false` muestra el aviso.

## Riesgos

- **El usuario marca mirando el parecido y el aviso de números, y puede equivocarse.**
  No hay forma de evitarlo sin que el sistema decida, que es justo lo que se descartó. Se
  mitiga con el orden (lo dudoso queda abajo), con el aviso de números, y con que el
  candado de los precios internos siga mandando sobre una fila forzada.
- **El parecido puede ser alto entre materiales distintos.** Medido sobre el catálogo:
  `(NO INCLUYE FACTOR)` vs `(INCLUYE FACTOR)` da 98.9% y `CLASE A` vs `CLASE B` da 93.8%.
  Por eso el número que se muestra es un dato más de la fila —junto al nombre completo del
  candidato— y no un veredicto.
- **Ofrecer solo el mejor candidato** puede esconder que había un segundo razonable. Se
  mitiga mostrando el nombre elegido y su parecido en la fila.

## Addendum (2026-09-16): marcar en lote

**Estado:** aprobado

Tras el smoke con un archivo real, el usuario pidió poder marcar en lote: *"que si le doy
shift y selecciono hacia abajo se seleccione en batch, cuando son muchas líneas puede ser
molesto ir uno a uno"*, y también una casilla de marcar todas.

### El patrón se copia, no se inventa

`web/src/components/corrida/TablaItems.tsx` ya resolvió exactamente esto para la tabla de
corridas (`alternar` en la línea 129, `marcarTodas` en la 147). Se reusa el mismo
comportamiento para que las dos tablas de la app se manejen igual:

- **Un ancla en un `ref`** con el id de la última fila marcada **sin** Shift. Corridas
  guarda el `seq` y no el índice porque su tabla se filtra y se reordena; acá se guarda el
  `insumo_id` por la misma robustez.
- **Shift+click marca el rango** entre el ancla y la fila clickeada, **sumando** — nunca
  desmarca — y el **ancla no se mueve**, así que se pueden encadenar varios Shift+click
  desde el mismo punto. Sin ancla previa, un Shift+click se comporta como un clic normal.
- **El checkbox usa `onClick` y no `onChange`** (con `onChange={() => {}}` al lado para no
  romper el input controlado): el evento `change` de React no expone `shiftKey`. Es
  literalmente cómo está en corridas.

**Por qué anclar por `insumo_id` es seguro acá:** dentro de esa tabla los ids son únicos,
porque si dos filas del archivo apuntan al mismo insumo **ninguna de las dos lleva
casilla** (ver el arreglo del doble forzado). Sin esa garantía, el ancla sería ambigua.

### Marcar todas, y el conteo del riesgo

Una casilla en el encabezado marca y desmarca todas las filas de la tabla, igual que
`marcarTodas` en corridas. Marcar todas **también marca las filas con el aviso de números**
— el rótulo no miente.

Lo que lo hace aceptable es que el riesgo queda a la vista: junto al conteo se dice cuántas
de las marcadas traen el aviso. Con el orden por parecido descendente, **la fila más
peligrosa suele quedar primera**: en el smoke real, un `TRANSFORMADOR … 75 KVA` contra el
`45 KVA` del catálogo (que vale $28.577.850) puntuó 91.4%, más alto que el typo genuino.

Es la misma política que el resto de la feature: **el sistema muestra, la persona decide**.
Un "marcar todas" que silenciosamente saltara las filas con aviso sería el premarcado
entrando por otra puerta — el sistema volviendo a decidir cuáles son seguras — y eso ya se
descartó con evidencia medida.

### Alcance

Solo `web/src/components/insumos/DialogoImportarInsumos.tsx` y su archivo de pruebas. Sin
backend: la selección es y sigue siendo estado del cliente que solo viaja al aplicar.

### Pruebas

1. Shift+click marca el rango entre el ancla y la fila clickeada.
2. Un Shift+click **sin ancla previa** se comporta como un clic normal (marca una sola).
3. Dos Shift+click seguidos siguen midiendo desde el ancla original (el ancla no se mueve).
4. La casilla del encabezado marca todas y, al volver a hacer clic, las desmarca.
5. El conteo dice cuántas de las marcadas traen `numeros_coinciden: false`.
