# Alta sin códigos ni nombres repetidos (insumos y APUs)

Fecha: 2026-08-10

## Problema

La identidad de un insumo es hoy **(código, nombre)**: `precios_db.py:143` deja crear
`10014` mientras el nombre sea distinto al del `10014` que ya existe. Por esa puerta
entró la basura que hay en la base:

| | total | códigos repetidos | nombres repetidos |
|---|---|---|---|
| insumos | 8157 | **652** (1304 filas) | 1070 (2175 filas) |
| APUs | 1182 | 0 | 499 |

`10014` es a la vez *«USO DEL PENETRÓMETRO DINÁMICO DE CONO…»* y *«ESTABILIZACIÓN DE
SUBRASANTE CON RAJÓN…»*. Y no es cosmético: `get_candidatos(codigo)` devuelve **los
dos**, así que el cruce insumo↔catálogo queda ambiguo y el costeo puede tomar el precio
del insumo equivocado.

En APUs la identidad es (código, turno) — `apus_db.py:107` —, así que `3010` DIURNO y
`3010` NOCTURNO conviven con el código pelado, el mismo bug que ya se arregló en el
importador (memoria del incidente del código sin `" N"`) pero que sigue abierto en el
formulario.

## Los nombres repetidos NO son todos basura

De los 1070 nombres repetidos de insumos, una buena parte es el **par nocturno**:

```
4859    BORDE CONTENEDOR DE RAICES A 70 (…)   ML   ANDENES Y SARDINELES
4859 N  BORDE CONTENEDOR DE RAICES A 70 (…)   ML   SARDINELES Y BORDILLOS
```

Mismo nombre, código distinto: es la tarifa nocturna. En APUs los 499 son el par
DIURNO/NOCTURNO — **dentro del mismo turno hay cero nombres repetidos**.

Prohibir el nombre repetido a secas obligaría a bautizar el nocturno *«… NOCTURNO»*, o
sea el mismo trabajo con dos nombres. La regla lleva por eso una excepción explícita.

## Alcance

- El **alta** de insumos y de APUs rechaza código repetido y nombre repetido.
- Aplica a las dos puertas: el formulario individual y el **import por Excel**.
- Los datos existentes no se tocan. No hay migración ni limpieza en esta feature.

Fuera de alcance:

- **Limpiar los 652 códigos repetidos que ya están.** Es otro trabajo, con su propio
  riesgo de costeo, y hay que decidir a mano cuál gana.
- La **edición**: no existe endpoint para renombrar un insumo, y `editar_apu` no toca
  la identidad (código y turno son fijos). Cuando exista el renombrado tendrá que pasar
  por el mismo helper.
- El `seed` y `insert_insumos`. El histórico ES el que trae los 652 repetidos: tiene que
  poder seguir cargándose.
- **Duplicar un APU** sigue exigiendo un nombre distinto al del origen
  (`_origen_duplicado`, comportamiento de hoy). Ver "Techo conocido".

## La regla

```
INSUMO nuevo (código C, nombre N):
  choca si  ∃ insumo con código == C                      (incluidos los ocultos)
  choca si  ∃ insumo con normalizar(nombre) == normalizar(N)
            SALVO gemelo nocturno: base(C) == base(existente.código)

APU nuevo (código C, turno T, nombre N):
  choca si  ∃ APU con código == C  en CUALQUIER turno      (hoy solo mira (C,T))
  choca si  ∃ APU con normalizar(nombre) == normalizar(N)
            SALVO gemelo nocturno: base(C) == base(existente.código)  Y  T != existente.turno

base(x) = x sin el sufijo " N", insensible a mayúsculas   # convención de _codigo_con_turno
```

`normalizar` es `nucleo/texto.py::normalizar` (sin tildes, MAYÚSCULAS, sin puntuación),
el mismo criterio que ya usan `_match_identidad` y `_renombrar_lista`.

### Por qué los ocultos también bloquean

`get_candidatos` **no** filtra `oculto` (`precios_db.py:318`): el motor de precios ve
los 1062 ocultos. Un código nuevo que choque con uno oculto haría el cruce ambiguo
exactamente igual que uno visible. El mensaje lo dice para que no parezca un error:
*«El código 3017 ya lo usa un insumo oculto: "…"»*.

### Por qué `base()` no quita el sufijo de copia

`baseDe()` del frontend (`web/src/lib/duplicarApu.ts`) quita la marca nocturna **y** el
sufijo `-2` de copia. El `base()` del backend quita **solo** la marca nocturna: si
quitara el `-2`, un `3454-2` podría reclamar el nombre del `3454` y la excepción
dejaría de significar "el gemelo nocturno" para significar "cualquier copia". Son dos
helpers con nombre parecido y alcance distinto a propósito; el del backend lleva un
comentario que lo dice.

## Dónde vive: `servicio/autoria.py`

Un helper nuevo, junto a `_origen_duplicado` y `_codigo_con_turno`:

```python
def _base_codigo(codigo: str) -> str: ...
def _conflicto_insumo(alm, codigo, nombre) -> Optional[str]:   # None o el motivo en español
def _conflicto_apu(alm, codigo, turno, nombre, index=None) -> Optional[str]:
```

Devuelven el **motivo en español o `None`**, no un bool: el motivo es lo que necesita
tanto el `ValueError` → 400 del formulario como el balde `conflicto` del preview del
import, y así el texto se escribe una sola vez.

Se descartaron dos alternativas:

- **`UNIQUE` en la DB** (el rung natural): imposible, los datos actuales lo violan 652 +
  1070 veces.
- **La regla en `datos/`** (donde ya vive el check de `(código, nombre_norm)`): habría
  que escribirla espejada en SQLite y en Postgres, y quedaría a un paso de alcanzar al
  `seed`, que tiene que poder cargar el histórico repetido. El precedente de validación
  de altas ya está en `autoria.py`: `_origen_duplicado` rechaza el nombre igual al del
  APU de origen.

El check de `(código, nombre_norm)` de `precios_db._crear_insumo` **se queda como
está**: es la última red para cualquier ruta que no pase por `autoria.py`.

## Backend

### Una lectura nueva, solo para insumos

`datos/repositorio.py` (Protocol de precios), `datos/precios_db.py` y
`datos/pg/precios_pg.py`:

```python
def identidades_en_conflicto(self, codigo: str, nombre_norm: str
                             ) -> list[tuple[str, str, bool]]:
    """(codigo, nombre, oculto) de los insumos cuyo código O nombre normalizado choca."""
    # SELECT codigo, nombre, oculto FROM insumos WHERE codigo = ? OR nombre_norm = ?
```

Una sola consulta cubre los dos lados y trae lo que el mensaje necesita —incluido
`oculto`, que `get_candidatos` no devuelve porque `Insumo` no tiene ese campo—.

**Para APUs no hace falta ningún método nuevo:** `alm.apus.apu_index()` ya devuelve
`(código, nombre, turno)` de los 1182 y existe en los dos backends. La tabla `apus` no
tiene columna `nombre_norm`, así que el match normalizado se hace en Python de todos
modos. Es el mismo patrón que `subapus.py::nombres_apu`, que ya llama `apu_index()` en
cada import.

### Los seis puntos de entrada

| Función | Cambio |
|---|---|
| `crear_insumo` | llama `_conflicto_insumo`; si hay motivo → `ValueError` |
| `crear_apu` | llama `_conflicto_apu`; si hay motivo → `ValueError` |
| `preview_importar_insumos` | fila que iría a `crear` y choca → balde `conflicto` |
| `aplicar_importar_insumos` | ninguno: itera `prev["crear"]`, que ya viene filtrado |
| `preview_importar_apus` | APU que iría a `crear` y choca → balde `conflicto` |
| `aplicar_importar_apus` | **sí lo necesita**: no usa los baldes del preview, recorre los APUs parseados y solo saltea los `get_apu(codigo, shift)` existentes. Sin el check aquí, las filas en conflicto se crearían igual. Van a `errores`. |

`ValueError` → 400 ya está cableado en `rutas.py` para las cuatro rutas.

### El índice de APUs se lee una vez por import, no por fila

`_conflicto_apu` acepta un `index` opcional: el resultado de `apu_index()` ya leído. En
`preview_importar_apus` y `aplicar_importar_apus` se lee **una vez** al entrar y se pasa
en cada vuelta. Sin eso, un archivo de 200 APUs haría 200 viajes de 1182 filas a
Postgres, justo lo contrario de la optimización de round-trips que ya está en producción.
`crear_apu` (una sola alta) lo llama sin `index` y lee ahí mismo.

Para insumos, `identidades_en_conflicto` es una consulta por fila. Se acepta: el import
ya hace `get_candidatos` por fila en `_match_identidad`, así que no cambia el orden de
magnitud. Si algún día molesta, el upgrade es un método en lote como
`get_candidatos_bulk`.

### Conflictos dentro del propio archivo

El barrido del preview lleva un set de los códigos y nombres normalizados que las filas
anteriores ya reclamaron. Sin eso, un archivo con dos filas nuevas del mismo código
diría "crear 2" y el aplicar crearía 1 con un error — el preview mentiría.

### La no-regresión que importa

Un Excel histórico con el par `3010` DIURNO + `3010` NOCTURNO **sigue importando los
dos**: `_codigo_con_turno` convierte el nocturno en `3010 N` antes de cualquier check
(no choca por código), y el nombre repetido cae en la excepción del gemelo. Va como
test explícito.

## Frontend

`DialogoAgregarInsumo.tsx:88-90` y `DialogoAgregarApu.tsx:308-310` ya hacen
`toast.error(msg)` con el detalle del 400, así que el 400 queda como red de todos modos.

**Addendum 2026-08-10: el aviso sale en vivo, debajo del campo.** El diseño original
esperaba al guardado. Lo que se descartó —y sigue descartado— es un chequeo que
**reimplemente** la regla en el frontend: `GET /api/insumos` filtra `oculto = 0`, así que
diría "libre" donde el servidor rechaza, y dos implementaciones de la misma regla es justo
la forma de que se desincronicen. Un endpoint que llama **al mismo** `_conflicto_insumo` /
`_conflicto_apu` que usa el guardado no tiene ese problema: es la misma respuesta, solo
antes. Ver "Aviso en vivo" más abajo.

Los diálogos de import sí muestran el balde nuevo:

- `web/src/lib/tipos.ts`: `conflicto: ImportConflicto[]` en `ImportInsumosUpsertPreview`
  y en `ImportApusPreview`, con `{ codigo, nombre, motivo }`.
- `web/src/components/insumos/DialogoImportarInsumos.tsx` y
  `web/src/components/autoria/DialogoImportarApus.tsx`: una sección más, con el mismo
  tratamiento visual que `invalida` / `ya_existe`, mostrando el motivo por fila. El
  botón de aplicar sigue contando solo `crear`.

## Aviso en vivo (addendum)

El motivo aparece **debajo del campo culpable** mientras se escribe, sin esperar al botón.
Los dos diálogos ya envuelven cada input en un `<label className="flex flex-col gap-1">`,
así que el `<p className="text-xs text-destructive">` va dentro del mismo label, después
del `<input>` — el patrón que `DialogoAgregarApu.tsx:562-576` ya usa para el rendimiento
inválido y para las reglas de la copia.

**Una regla, dos formas.** Para saber **qué campo** señalar, los helpers se parten en dos
sin duplicar nada:

```
_conflicto_insumo_detalle(alm, codigo, nombre, extra=()) -> Optional[tuple[str, str]]  # (campo, motivo)
_conflicto_insumo(alm, codigo, nombre, extra=()) -> Optional[str]                      # devuelve solo el motivo
```

La regla vive **una vez**, en la función `_detalle`; la de siempre queda como envoltorio de
una línea, así que los 6 llamadores existentes (los dos formularios y los dos imports) no
se tocan. Igual para `_conflicto_apu`. `campo` es `"codigo"` o `"nombre"`.

**Endpoints** (rol `consulta`, solo lectura):

- `GET /api/insumos/conflicto?codigo=&nombre=` → `{"campo": "codigo"|"nombre"|null, "motivo": str|null}`
- `GET /api/apus/conflicto?codigo=&turno=&nombre=` → lo mismo

Van declarados **junto a `/insumos/grupos` y `/insumos/fuentes`, antes de `/insumos/{id}`**:
FastAPI resuelve en orden de declaración y `/insumos/{id}` con `id: int` devolvería 422 al
intentar parsear `"conflicto"` como entero. `/apus/conflicto` no colisiona con
`/apus/{codigo}/{turno}` (dos segmentos).

**Comportamiento en la pantalla:**

- Se consulta con debounce de 400 ms tras dejar de escribir, no en cada tecla. Sin
  dependencia nueva: `useEffect` + `setTimeout`.
- Solo con código **y** nombre no vacíos: preguntar por un formulario a medio llenar daría
  falsos avisos mientras se teclea.
- **El botón de guardar se deshabilita** cuando hay conflicto: la respuesta sale de la misma
  regla que aplicaría el servidor, así que es autoritativa.
- **Falla abierta:** mientras la consulta está en vuelo, o si falla la red, no se bloquea
  nada. El 400 del guardado sigue siendo la red de seguridad.
- **En modo editar no corre.** `editar_apu` no aplica la regla (está fuera de alcance, ver
  Alcance), así que avisar de algo que el servidor va a aceptar sería mentir. Sí corre al
  crear y al duplicar.

## Mensajes (van al usuario, en español)

```
El código 10014 ya lo usa el insumo «USO DEL PENETRÓMETRO DINÁMICO DE CONO…».
El código 3017 ya lo usa un insumo oculto: «TRANSPORTE …».
Ese nombre ya lo usa el insumo 4859. Si es la tarifa nocturna, usa el código 4859 N.
El código 3010 ya lo usa el APU DIURNO «EXCAVACIÓN…». Si es el nocturno, usa 3010 N.
Ese nombre ya lo usa el APU 3454 en turno DIURNO.
```

El mensaje del nombre repetido **nombra la salida** (`4859 N`, `3010 N`): es la
diferencia entre una regla que enseña la convención y una que solo estorba.

## Pruebas

`tests/test_autoria_sin_duplicados.py` (pytest, nuevo; los vecinos son
`test_servicio_autoria.py`, `test_api_autoria.py` y `test_subapus_import.py`):

- código tomado → rechazo, con o sin nombre distinto (el caso `10014` de hoy);
- código tomado por un insumo **oculto** → rechazo, y el motivo dice "oculto";
- nombre tomado, código sin relación → rechazo;
- **gemelo nocturno permitido**: `4859 N` con el mismo nombre que `4859` se crea;
- APU: código repetido en el **otro** turno → rechazo (hoy pasa);
- APU: mismo nombre en el otro turno con `X N` → se crea; con un código sin relación →
  rechazo;
- normalización: `EXCAVACIÓN` vs `excavacion` chocan;
- import de insumos: fila en conflicto va a `conflicto`, no se crea, y el aplicar no la
  cuenta; dos filas nuevas del mismo código → la segunda es conflicto **en el preview**;
- import de APUs: el par DIURNO/NOCTURNO del histórico sigue creando los dos
  (no-regresión); una fila en conflicto no se crea ni por `aplicar`;
- `identidades_en_conflicto` da lo mismo en SQLite y en Postgres (con los tests de
  Postgres existentes).

`seed` no se toca, así que los tests de ingesta quedan igual. Toca revisar los tests que
crean insumos/APUs con códigos de mentira repetidos entre sí (`"100"`, `"3454"`) por si
alguno crea dos altas colisionantes en el mismo test.

Vitest: los diálogos de import muestran la sección `conflicto` con su motivo.

## Verificación manual

Levantar la web en local; intentar crear un insumo con el código `10014`, y un APU
NOCTURNO con un código que ya exista en DIURNO; comprobar que el mensaje sugiere el
` N`. Importar el Excel histórico de APUs y confirmar que los pares día/noche siguen
entrando. El navegador va antes del push.

## Techo conocido

`_origen_duplicado` (duplicar un APU) sigue exigiendo un nombre distinto al del origen,
y `codigoSugerido` propone `3454-2 N` en vez de `3454 N`. O sea: **el gemelo nocturno
con el mismo nombre no se puede crear duplicando**, hay que usar el alta normal
escribiendo el código `X N`. Es el comportamiento de hoy, esta feature no lo empeora,
pero es el camino que la gente va a intentar primero. Anotar con un comentario
`ponytail:` en `_origen_duplicado`. El upgrade, si molesta: que `codigoSugerido`
proponga `base + " N"` cuando el turno cambia y ese código está libre, y que
`_origen_duplicado` y `nombreEsDistinto` deleguen la excepción en el mismo helper.
