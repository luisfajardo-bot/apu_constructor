> Espejo automático — no editar aquí. Fuente: `docs/superpowers/specs/2026-09-15-forzar-conflictos-import-design.md`

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

**El patrón que sí separa:** en todos los casos peligrosos **cambió un número**; en todos
los buenos los números son idénticos. La regla `parecido ≥ 80% Y mismos números` da, sobre
esos diez casos:

- **0 falsos positivos** — ninguno de los seis peligrosos se premarca.
- 2 falsos negativos — "abreviado" y "faltan 2 palabras" quedan sin marcar, con su casilla
  disponible. Ese error cuesta un clic; el otro cuesta un precio equivocado.

Esa asimetría es la que corresponde a una frontera de dinero.

## Alcance

- `apu_tool/config.py` — el umbral del premarcado.
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
 "parecido": round(sim, 3), "premarcar": bool(...)}
```

Los conflictos por **nombre** siguen como están hoy (sin esos campos): el frontend les
pinta la fila sin casilla.

`preview_importar_insumos` pasa a llamar `conflicto_insumo_detalle` en vez de
`_conflicto_insumo`, para distinguir el campo. Las dos ya existen y son públicas; no hay
regla nueva ni duplicada.

### 2. El premarcado

```python
def _mismos_numeros(a: str, b: str) -> bool:
    """Los dos nombres traen exactamente los mismos números, con las mismas repeticiones.

    Es lo que separa «una letra distinta» (el mismo insumo) de «MR-42 vs MR-40» (otro
    material), que el parecido NO separa: con nombres largos los dos puntúan ~89%."""
    return Counter(re.findall(r"\d+", a or "")) == Counter(re.findall(r"\d+", b or ""))
```

`premarcar = parecido >= config.UMBRAL_PREMARCA_CONFLICTO and _mismos_numeros(...)`, con
`UMBRAL_PREMARCA_CONFLICTO = 0.80` en `config.py` junto a los otros umbrales de matching.

El premarcado es **una sugerencia del servidor**: lo que se aplica es lo que el usuario
manda en `forzar_ids`, no lo que el servidor calculó. Si el frontend desmarca una fila
premarcada, esa fila no viaja.

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

Encima de la tabla, el conteo explícito: *"18 de 43 vienen marcadas (parecido ≥80% y
mismos números)"*. El premarcado tiene que ser algo que se ve, no un default invisible.

Los conflictos por nombre se siguen listando abajo, con su motivo y sin casilla.

`nAcciones` (el número del botón Aplicar) suma las marcadas, porque van a escribir.

Cambiar una casilla **no** re-dispara el preview: la selección es estado del cliente y solo
viaja al aplicar. (El preview sí se re-dispara al cambiar la fuente, que es lo que ya hace.)

### 6. Pruebas

1. Forzar un conflicto de código actualiza el precio del insumo elegido.
2. **Una fila forzada sobre un insumo con precio interno, con importación pública, sigue
   en `protegida`.** Es la prueba que fija que forzar no es un permiso.
3. El premarcado es `False` en los seis casos de número distinto y `True` en la letra y la
   palabra faltante (tabla de arriba, como casos parametrizados).
4. Con varios insumos del mismo código, se ofrece el de mayor parecido.
5. Un `forzar_ids` con un id que no resuelve deja la fila en `conflicto` y no escribe.
6. Un conflicto por **nombre** no trae `insumo_id` ni casilla, y forzarlo no hace nada.

En el frontend: la casilla premarcada viaja en `forzar_ids`; desmarcarla la saca; y el
conteo del botón Aplicar sube al marcar.

## Riesgos

- **El premarcado es una decisión de dinero tomada por el servidor.** Se mitiga con la
  regla de los números (0 falsos positivos en los diez casos medidos) y con el conteo
  visible. No se mitiga del todo: un nombre sin números que difiera en algo importante y
  pase el 80% se premarcaría. El caso medido más cercano (`LADRILLO TOLETE COMUN` vs
  `PRENSADO`) da 60.2%, bien por debajo.
- **Ofrecer solo el mejor candidato** puede esconder que había un segundo razonable. Se
  mitiga mostrando el nombre elegido y su parecido en la fila.
