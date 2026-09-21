# Ruta IDU — Formulario 1 de Presupuesto Oficial

> Entidad de origen en la corrida, lectura directa del Formulario 1 del IDU con detección
> determinística de capítulos, previsualización obligatoria antes de crear la corrida, y
> capítulo conservado hasta el cuadro. **No toca el matcher, no toca el motor de precios,
> no mete IA en ninguna parte de la lectura.**

## 0. El hallazgo que redimensiona el trabajo

`presupuesto.py::read_presupuesto`, apuntado a la hoja `PROPUESTA ECONÓMICA` del archivo
de referencia, **ya produce exactamente los números esperados**:

```
items = 1939        capítulos = 14        sin capítulo = 0        nocturnos = 872
1 PRELIMINARES · 2 PAVIMENTOS · … · 14 OTROS
```

Sus reglas (col `Nº` vacía + col `ITEM DE PAGO` entera + descripción ⇒ capítulo;
`cantidad > 0` + código en `Nº` ⇒ actividad) son las mismas del pliego de requisitos. La
fila 2201, los `Subtotal`, los `TURNO`, los subtítulos y el resumen de la 2204 en adelante
ya caen solos.

**Lo que falta no es el parser: es todo lo que está alrededor.** Detección de hoja y de
encabezado, mapeo por nombre de columna, validaciones, conciliación, previsualización,
entidad de origen, salida a la web y resumen por capítulo.

### Mediciones sobre el archivo de referencia

`Formulario 1 Formulario de Presupuesto Oficial (version 1).xlsx`, hoja
`PROPUESTA ECONÓMICA`, encabezado en la fila 10:

| Chequeo | Resultado |
|---|---|
| `round(CANTIDAD × K)` vs `VALOR TOTAL` (col L) | **1939 / 1939 exacto** |
| `round(CANTIDAD × J)` vs `VALOR TOTAL` | **0 / 1939** |
| Σ col L de actividades vs Σ de los 14 `Subtotal` | 158.456.072.140 = 158.456.072.140 |
| Σ `round(CANT × J)` | 123.871.215.068 |
| Discrepancias prefijo-de-ítem vs posición | **0** |
| Ítem de pago duplicado | 0 |
| Filas sin unidad / sin descripción / sin valor con AIU | 0 |
| Filas con `cantidad > 0` y col `Nº` vacía (actividad perdida) | 0 |
| Ratio K/J | 1,2781 – 1,2797 (el AIU, ~27,9 %) |
| Hojas `PROPUESTA ECONÓMICA` y `PROPUESTA ECONÓMICA (2)` | **idénticas valor a valor** |
| Ítem de pago almacenado como `float` | 1067 de 1939 (los diurnos) |
| … de esos, con cero significativo perdido por `float` | **100** (`2.010`→`2.01`, `3.100`→`3.1`) |
| Código IDU (col `Nº`) presente en la biblioteca local | 876 / 1939 (45 %) ⇒ armado directo |

**Los ceros perdidos son recuperables.** Las celdas de `ITEM DE PAGO` traen
`number_format='0.000'` (y `'0'` en las filas de capítulo), y `openpyxl` lo expone en modo
`read_only`. `2.01` + formato `0.000` ⇒ `"2.010"`. No hay que adivinar nada.

## 1. Cómo funciona hoy la carga de licitaciones

```
CorridasInicio.tsx → POST /api/corridas (multipart)
  → rutas.py::_items_del_upload → read_licitacion(require_turno=True)
       encabezados en la FILA 1, mapeo por palabras clave, una fila = un ítem, sin jerarquía
  → svc.crear_corrida_encolada → plan_json = [asdict(item)] , estado='armando'  ← ES la cola
  → servicio/armador.py reclama → armar_pendientes → _armar_fila por línea, persistiendo
  → generar_cuadro → write_report  (RESUMEN / DESGLOSE / ALERTAS / INFO)
```

Con el Formulario 1 esta ruta no sirve: la fila 1 está vacía, el encabezado real está en la
10 y la estructura es jerárquica.

## 2. Qué hace hoy `presupuesto.py`

Es, literalmente, el lector del Formulario 1 del IDU — con la hoja y las columnas clavadas
(`HOJA_DEFECTO = "FOR 1-PPTO OFICIAL"`, `COL_CODIGO=2 … COL_PRECIO=9`). Recorre de arriba
abajo llevando estado `(capítulo, turno)`; cada ítem hereda ambos. Emite `LicitacionItem`
con `categoria` (`"2 · PAVIMENTOS"`) y `codigo_sugerido` (código IDU), que `assemble.py`
usa para **armado directo por código, sin fuzzy y sin IA** (`AUTO`, confianza 1.0).

## 3. Qué hace hoy `report_categorizado.py`

`agrupar_por_capitulo(apus)` agrupa por `item.categoria` preservando orden de aparición, y
escribe cuatro hojas: RESUMEN POR CAPÍTULO, DETALLE, APUS, ALERTAS, más INFO. Reusa los
estilos de `report.py`. **Solo lo llama la CLI** (`pipeline.build_desde_presupuesto`); la
web nunca lo toca.

## 4. Qué se reutiliza

| Ya existe | Qué evita construir |
|---|---|
| `presupuesto.py` (reglas capítulo / turno / ítem) | El parser entero |
| `LicitacionItem.categoria` + `codigo_sugerido` | El cableado del capítulo |
| `plan_json` / `item_json` (`asdict` ↔ `LicitacionItem(**d)`) | **La migración para conservar el capítulo: no hace falta** |
| `assemble.py` armado por código | Matching de 876 de 1939 filas |
| `report_categorizado.py` | Las hojas por capítulo |
| `ux_corrida_armando_archivo` (ambos backends) | Protección del doble clic |
| `nucleo/redondeo.mul_redondeado` | Las reglas de redondeo monetario |
| Filtros por columna de `TablaItems` | "Ver las actividades de un capítulo" |
| `PRAGMA table_info` + `ALTER` / `ADD COLUMN IF NOT EXISTS` | El patrón de migración dual |

## 5. Entidad de origen

### El tipo

`nucleo/models.py`, junto a `MatchStatus`:

```python
class EntidadOrigen(str, Enum):
    IDU = "IDU"
    METRO_BOGOTA = "METRO_BOGOTA"
    INVIAS = "INVIAS"
    OTRA_PUBLICA = "OTRA_PUBLICA"
    PRIVADA = "PRIVADA"
    NO_IDENTIFICADA = "NO_IDENTIFICADA"
```

`str, Enum` como `MatchStatus`: serializa solo a JSON y sobrevive a `asdict`.

### El despacho

Un módulo nuevo, `apu_tool/dominio/entrada.py` (~50 líneas). **Un diccionario, no una
jerarquía de clases**: hay una sola implementación especializada, y un `Protocol` con una
implementación es andamiaje.

```python
LECTORES: dict[EntidadOrigen, Lector] = {
    EntidadOrigen.IDU: leer_formulario_idu,
    # el resto usa el importador genérico a propósito: no se inventan formatos
    EntidadOrigen.METRO_BOGOTA:    leer_generico,
    EntidadOrigen.INVIAS:          leer_generico,
    EntidadOrigen.OTRA_PUBLICA:    leer_generico,
    EntidadOrigen.PRIVADA:         leer_generico,
    EntidadOrigen.NO_IDENTIFICADA: leer_generico,
}

def leer(entidad, path, **kw) -> LecturaPresupuesto: ...
def requiere_confirmacion(entidad) -> bool:  # hoy: solo IDU
```

Agregar INVIAS mañana es **una entrada del diccionario y una función**, sin tocar ningún
`if` de `rutas.py`. `leer_generico` envuelve `read_licitacion` en un `LecturaPresupuesto`
sin capítulos, sin advertencias y sin conciliación, para que el resto del sistema tenga un
solo tipo de retorno.

## 6. El parser IDU

Vive en `dominio/presupuesto.py`, que es su lugar coherente (crece de 134 a ~380 líneas).
`read_presupuesto` **se conserva con la firma de hoy** y pasa a ser un envoltorio que
devuelve `.items`, para no romper CLI, GUI ni `tests/test_presupuesto.py`.

### Tipos que expone

```python
@dataclass(frozen=True)
class Capitulo:
    codigo: str        # "2"
    nombre: str        # "PAVIMENTOS"
    orden: int         # 2  (posición de aparición, 1-based)
    fila_origen: int   # 21

@dataclass(frozen=True)
class Advertencia:
    tipo: str          # vocabulario cerrado (ver 6.8)
    fila: int          # 0 = no aplica a una fila puntual
    detalle: str

@dataclass(frozen=True)
class LecturaPresupuesto:
    items: list[LicitacionItem]
    capitulos: list[Capitulo]
    hoja: str
    fila_encabezado: int
    filas_ignoradas: int
    errores: list[str]                 # bloqueantes: con uno solo no se puede aprobar
    advertencias: list[Advertencia]
    conciliacion: dict
    parser_version: str                # "idu-f1/1"

def leer_formulario_idu(path, hoja: str | None = None) -> LecturaPresupuesto: ...
```

### 6.1 Detección de hoja

Nombres normalizados; candidata la que contenga `propuesta economica`, `ppto oficial` o
`presupuesto oficial`. Se toma la **primera** candidata y, si hay más de una, se emite
`hoja_ambigua` diciendo cuál se usó y cuáles se descartaron (en el archivo de referencia
hay dos idénticas). Cero candidatas ⇒ **error bloqueante** con la lista de hojas del libro.
Un `hoja=` explícito gana sobre la detección.

### 6.2 Detección de la fila de encabezado

Se escanean las primeras 40 filas buscando la que contenga, normalizados,
`descripcion` + `cantidad` + (`item de pago` | `no`). La primera que cumple es el
encabezado; su número queda en `fila_encabezado` (10 en el archivo de referencia).

### 6.3 Mapeo de columnas por nombre

Normalización compartida: NFD sin tildes → minúsculas → saltos de línea y espacios
repetidos colapsados a uno → puntos eliminados. Así `ITEM`/`ÍTEM`, `Nº`/`N°`/`No.`/`No`,
`UND.`/`UNIDAD` y el salto de línea de `VALOR UNITARIO SIN AIU\nCORREGIDO` colapsan solos.

| Campo lógico | Encabezado (normalizado) | Col. observada | Obligatorio |
|---|---|---|---|
| `codigo` | `no` | C | sí |
| `item_pago` | `item de pago` | D | sí |
| `descripcion` | `descripcion` | G | sí |
| `unidad` | `und` / `unidad` | H | sí |
| `cantidad` | `cantidad` | I | sí |
| `unitario_sin_aiu` | `valor unitario basico (sin aiu)` | J | sí |
| `unitario_con_aiu` | `valor unitario (incluye aiu)` | K | sí |
| `total_excel` | `valor total` | L | no (solo concilia) |

Las letras de columna **no se usan**: son documentación de qué se observó, no la regla.
Falta una obligatoria ⇒ **error bloqueante** nombrando cuál.

### 6.4 Clasificación de filas

Determinística, **en este orden**; la primera que aplica gana:

```
1. todas las celdas mapeadas vacías            → IGNORADA
2. la fila reproduce el encabezado mapeado     → ENCABEZADO   (cubre la fila 2201)
3. col Nº (texto) empieza con "subtotal"       → SUBTOTAL     (se guarda para conciliar)
4. Nº vacío + ítem-pago entero + descripción   → CAPITULO
5. Nº vacío + descripción que empieza "turno"  → TURNO        (cambia el estado)
6. Nº vacío + descripción                      → SUBTITULO
7. cantidad numérica > 0 + Nº no vacío         → ACTIVIDAD
8. resto                                       → IGNORADA     (resumen, notas, firmas)
```

"Ítem-pago entero" se decide por **texto normalizado** (`"2"` sí, `"2.001"` no) y por el
formato de celda (`0` vs `0.000`), **nunca** por una división de punto flotante.

### 6.5 Normalización del ítem de pago

Tres funciones puras, todas sobre texto, en `presupuesto.py`:

```python
item_pago_texto(valor, formato)   # 2.01 + '0.000' -> "2.010"   ← recupera el cero
normalizar_item_pago(s)           # "2,001-N" -> "2.001 N" ; comillas y espacios fuera
capitulo_de(s)                    # "2.014" | "2.014 N" | "2,014-N" -> "2"
```

`capitulo_de` toma el prefijo entero hasta el primer separador (`.` o `,`). El valor crudo
se preserva en `item_pago_original`. **Nunca** se convierte a `float` para decidir
estructura.

### 6.6 Asociación actividad ↔ capítulo

Dos controles complementarios:

1. **Posición**: el capítulo vigente del recorrido de arriba abajo.
2. **Prefijo**: `capitulo_de(item_pago)`.

Coinciden ⇒ asociación confiable. Difieren ⇒ se usa la **posición**, se marca la actividad
como ambigua y se emite `capitulo_ambiguo` con la fila, el prefijo y el capítulo posicional.
**No se decide en silencio y no se asocia solo por posición sin dejar rastro.** La
previsualización lista esas filas, y aprobar con advertencias exige confirmación explícita.
Medido en el archivo de referencia: 0 casos.

### 6.7 Errores bloqueantes

| Código | Cuándo |
|---|---|
| `sin_hoja` | ninguna hoja compatible (lista las del libro) |
| `sin_encabezado` | no se encontró la fila de encabezado en las primeras 40 |
| `falta_columna` | falta una columna obligatoria (dice cuál) |
| `sin_actividades` | 0 actividades detectadas |
| `cantidad_invalida` | una actividad con cantidad no numérica, ≤ 0 o NaN |
| `item_duplicado` | dos actividades con el mismo `item_pago` normalizado **y** la misma descripción y turno |
| `sin_contractual` | una actividad sin valor unitario con AIU legible |
| `total_no_concilia` | Σ capítulos ≠ Σ actividades importadas |
| `archivo_invalido` | no es un Excel válido, o excede el límite (15 MB) |

El límite de tamaño ya lo aplica `LimiteSubida` por `Content-Length` antes de leer el
cuerpo; el parser solo traduce el fallo.

### 6.8 Advertencias

`actividad_sin_capitulo`, `capitulo_sin_actividades`, `capitulo_ambiguo`,
`total_fila_no_concilia`, `subtotal_no_concilia`, `codigo_apu_vacio`, `unidad_vacia`,
`encabezado_repetido`, `item_pago_formato_inusual`, `formula_sin_valor`,
`fila_relevante_ignorada`, `hoja_ambigua`, `oferta_diligenciada`.

`formula_sin_valor`: el libro se abre con `data_only=True`; una celda de fórmula sin valor
almacenado llega como `None`. Si eso pasa en una columna obligatoria de una fila que por
todo lo demás parece actividad, se advierte con el número de fila — y si es la cantidad o el
valor con AIU, escala a error bloqueante (`cantidad_invalida` / `sin_contractual`).

## 7. Precio contractual y columnas ofertadas

Se leen **las dos** columnas de valor unitario y viajan las dos:

```
precio_contractual          = VALOR UNITARIO (INCLUYE A.I.U)       col K
precio_contractual_sin_aiu  = VALOR UNITARIO BASICO (SIN A.I.U)    col J
contractual_total           = mul_redondeado(precio_contractual, cantidad)
contractual_total_sin_aiu   = mul_redondeado(precio_contractual_sin_aiu, cantidad)
```

`precio_contractual` = K (decisión del usuario), así que margen, totales y cuadro siguen la
fórmula actual **sin tocar el motor de costos**. La col L del Excel **no se usa para
calcular**: solo como control de conciliación.

Consecuencia declarada: el costo interno es costo directo sin AIU, de modo que
`contractual − costo` incluye el A.I.U. El usuario lo pidió así; el sistema no lo
reinterpreta ni renombra la columna, y por eso muestra las dos bases lado a lado.

**Columnas ofertadas y corregidas (O–S): no se leen en esta entrega.** En el archivo de
referencia están en cero (la oferta no está diligenciada) y la col S dice `ERROR` en las
1939 filas. El parser las detecta y las ignora explícitamente; si alguna trae valor ≠ 0
emite `oferta_diligenciada` con el conteo de filas, para que el día que llegue un archivo
con oferta el sistema avise en vez de callarse.

## 8. Modelo de datos

### 8.1 `LicitacionItem` — cinco campos, todos con default

```python
capitulo_codigo: str = ""                 # "2"            ← la referencia estable
capitulo_nombre: str = ""                 # "PAVIMENTOS"
item_pago_original: str = ""              # "2,001-N" tal cual venía
fila_origen: int = 0                      # 24
precio_contractual_sin_aiu: float = 0.0   # ← DINERO
```

Los defaults son lo que hace que **las corridas viejas sigan abriendo**: `plan_de` hace
`LicitacionItem(**d)` sobre el `plan_json` guardado, y un campo nuevo con default se
resuelve solo (el propio `plan_de` ya lo documenta).

`categoria` se conserva y se **deriva** de `capitulo_codigo` + `capitulo_nombre` en el
lector (`f"{cod} · {nombre}"`), para que `report_categorizado.agrupar_por_capitulo` y sus
tests no se toquen. Los consumidores nuevos usan código y nombre por separado.

### 8.2 `AssembledApu` — una propiedad

```python
@property
def contractual_total_sin_aiu(self) -> int:
    return mul_redondeado(self.item.precio_contractual_sin_aiu, self.item.cantidad)
```

### 8.3 `corrida` — una columna

`origen_json TEXT` nullable, mismo patrón que `plan_json` / `snapshot_json` / `revision_json`:

```json
{"entidad": "IDU",
 "formato": "idu_formulario_1",
 "archivo": "Formulario 1 … .xlsx",
 "hoja": "PROPUESTA ECONÓMICA",
 "fila_encabezado": 10,
 "parser_version": "idu-f1/1",
 "importada_en": "2026-09-11T09:12:03",
 "confirmada_por": "luisfajardo@indugravas.com",
 "estructura_confirmada": true,
 "capitulos": 14,
 "actividades": 1939,
 "filas_ignoradas": 804,
 "advertencias": {"hoja_ambigua": 1},
 "conciliacion": {"contractual_con_aiu": 158456072140,
                  "contractual_sin_aiu": 123871215068,
                  "total_excel": 158456072140,
                  "diferencia": 0}}
```

Una columna y no ocho: el repo ya usa ese patrón, y así la migración es una línea por
backend. Fecha de importación y usuario van adentro; `creada_en` de la corrida sigue siendo
la fecha de la corrida.

`CorridaMeta` gana `origen: Optional[dict] = None`.

### 8.4 Sin tabla `CapituloCorrida` — por qué

Una tabla nueva son dos backends × (DDL + repo + método del `Protocol` + test de paridad),
una FK a `corrida` que hay que mantener en `agregar_items`, `borrar_items` y la
reanudación, y una segunda fuente de verdad del capítulo. El capítulo **ya persiste** en
`item_json` y en `plan_json`, sin migración; la lista de capítulos se deriva de los ítems en
orden de aparición, que es lo que `agrupar_por_capitulo` ya hace.

Lo único que se pierde es un **capítulo sin ninguna actividad**: no existiría fila que lo
mencione. En el archivo de referencia son 0, y la previsualización los señala con
`capitulo_sin_actividades` **antes** de crear la corrida. Queda documentado como límite
conocido: si algún día hay que conservarlos, el punto de paso es `origen_json`, no una tabla.

## 9. Privacidad (invariante #1)

Campos nuevos que son dinero y entran a `privacy._FORBIDDEN_KEYS`:

```
precio_contractual_sin_aiu · contractual_total_sin_aiu · origen_json ·
conciliacion · total_excel · subtotal_excel · unitario_sin_aiu · unitario_con_aiu
```

`origen_json` va por la misma razón que `plan_json`: lleva la conciliación —dinero—
adentro.

`privacy.licitacion_item_to_dict` gana **solo texto**, explícito clave por clave:

```python
"capitulo_codigo": item.capitulo_codigo,
"capitulo_nombre": item.capitulo_nombre,
```

El capítulo sí puede llegar a la IA (saber que una actividad es de `RED DE ACUEDUCTO` es
estructura, no precio). `precio_contractual_sin_aiu` **no** viaja, igual que
`precio_contractual` no viaja hoy: la función se arma campo por campo, así que un campo
nuevo del dataclass no se cuela por existir.

Tests nuevos en `tests/test_privacy.py` y `tests/test_servicio_privacidad.py`: cada nombre
monetario nuevo dispara `PrivacyViolation`, y el payload de composición de una fila con
capítulo sigue pasando el guardián.

## 10. API

### `POST /api/corridas/previsualizar` (nuevo)

Multipart: `archivo`, `entidad`. Rol `consulta`. **No escribe nada en la base.** Devuelve:

```json
{"entidad":"IDU","formato":"idu_formulario_1","hoja":"PROPUESTA ECONÓMICA",
 "fila_encabezado":10,"parser_version":"idu-f1/1",
 "capitulos":[{"codigo":"1","nombre":"PRELIMINARES","orden":1,"fila_origen":13,
               "actividades":2,"contractual":137605594,"contractual_sin_aiu":107565459}],
 "actividades":1939,"filas_ignoradas":804,
 "totales":{"contractual":158456072140,"contractual_sin_aiu":123871215068},
 "conciliacion":{"total_excel":158456072140,"diferencia":0,"subtotales_ok":true},
 "errores":[],"advertencias":[],"filas_senaladas":[]}
```

`filas_senaladas` trae **hasta 50** filas con problema (ambiguas, campo faltante), no las
1939: la previsualización valida la **estructura**, no reemplaza la tabla de la corrida.

Una entidad ≠ IDU responde el mismo sobre con `capitulos: []` y los contadores del lector
genérico, para que el frontend tenga un solo camino.

### `POST /api/corridas` (extendido)

Dos campos de formulario nuevos, ambos con default:

```python
entidad: str = Form("NO_IDENTIFICADA")
confirmada: bool = Form(False)
```

Si `entrada.requiere_confirmacion(entidad)` y no llega `confirmada=true` ⇒ **400**
("la estructura detectada debe confirmarse antes de crear la corrida").

El servidor **relee y revalida** el archivo al crear: si aparece un error bloqueante ⇒ 400,
aunque el cliente mienta con `confirmada=true`. El parser es determinístico, así que el
mismo archivo da la misma estructura; si diera otra, el error es la respuesta correcta.

Todo lo demás del endpoint queda igual: `carpeta_id` obligatorio, `lista_id`, `nombre`,
`turno`, el 409 de `ArmadoDuplicado` y el `_encolar`.

### `GET /api/corridas/{id}` (extendido)

`vista_corrida` gana dos claves:

```json
"origen": null,
"capitulos": []
```

(`origen` es `null` en corridas viejas; `capitulos` es `[]` cuando no hay capítulos.)

Cada ítem de `items` gana `capitulo_codigo`, `capitulo_nombre`, `item_pago_original`,
`precio_contractual_sin_aiu` y `contractual_total_sin_aiu`.

## 11. Resumen por capítulo — fuente única

Una función en el dominio, y **todos** consumen su salida: la API, la web y las dos hojas de
Excel. `_build_resumen_capitulo` deja de tener cálculo propio.

```python
# dominio/report_categorizado.py
def resumen_por_capitulo(apus: list[AssembledApu]) -> list[dict]
```

Por capítulo, en orden de aparición:

| Campo | Definición |
|---|---|
| `codigo`, `nombre`, `orden` | del ítem (vacío ⇒ `"(sin capítulo)"`) |
| `actividades` | nº de filas |
| `con_apu` / `sin_apu` | misma regla que `seqs_sin_apu`: sin APU **y** sin `costo_manual > 0` |
| `contractual` | Σ `contractual_total` (con AIU) |
| `contractual_sin_aiu` | Σ `contractual_total_sin_aiu` |
| `costo` | Σ `costo_total` |
| `diferencia` | `contractual − costo` |
| `margen_pct` | `diferencia / contractual` (0 si contractual = 0) |
| `cobertura` | actividades con costo válido / actividades |
| `cobertura_valor` | Σ contractual de las cubiertas / Σ contractual del capítulo |
| `completo` | `sin_apu == 0` **y** sin alertas de costeo |

Redondeo: se suman `contractual_total` y `costo_total`, que ya pasaron por
`mul_redondeado`. No se redondea dos veces y no se multiplica de nuevo.

**Las actividades sin APU no se esconden**: cuentan en `sin_apu`, el capítulo sale con
`completo: false`, y la web muestra el margen marcado como **parcial** cuando
`completo == false`, no como cifra definitiva.

**Cobertura ponderada por valor, justificada**: un capítulo puede estar casi entero
por conteo y a media máquina por plata. Medido en el archivo real: en PAVIMENTOS,
2 de 42 actividades son el 32 % del capítulo; en RED DE GAS, 2 de 8 son el 57 %.
Sin esta métrica, «95 % costeado» puede querer decir que falta la mitad del dinero.
Son dos sumas más dentro de la misma función.

## 12. Reporte

`write_report` gana una hoja `RESUMEN POR CAPÍTULO` **solo si algún ítem tiene capítulo**,
construida con `resumen_por_capitulo`. Una corrida plana produce un cuadro **idéntico al de
hoy**. Las hojas RESUMEN y DETALLE ganan las columnas `P. Contractual sin AIU` y
`Total Contractual sin AIU`.

`write_report_categorizado` pasa a usar la misma función: deja de tener su propio cálculo.
Así no hay tres sumas de dinero (frontend, backend, Excel), hay una.

## 13. Frontend

### `CorridasInicio.tsx`

Un `<select>` nativo nuevo arriba del formulario (nativo como los otros: los tests usan
`fireEvent.change` y `getByRole("option")`, que no funcionan contra el `Select` de Radix):

```
Entidad o fuente del presupuesto *   [ IDU ▾ ]
```

- **Entidad ≠ IDU** ⇒ el botón sigue diciendo "Armar" y hace exactamente lo de hoy.
- **Entidad = IDU** ⇒ el botón dice "Previsualizar"; al responder, se abre el panel de
  previa **en la misma página**. Ruta nueva no: el objeto `File` vive en el `<input>` y no
  sobrevive a una navegación.

### `components/corrida/PreviaIdu.tsx` (nuevo, ~200 líneas)

```
Hoja «PROPUESTA ECONÓMICA» · encabezado en la fila 10 · parser idu-f1/1
Se detectaron 14 capítulos y 1.939 actividades.  Filas ignoradas: 804.
Contractual (con AIU) $158.456.072.140 · sin AIU $123.871.215.068
Conciliación contra el Excel: OK (diferencia $0 en los 14 subtotales)
0 advertencias      0 errores

Capítulo  Nombre                Actividades   Contractual (c/AIU)   Contractual (s/AIU)
1         PRELIMINARES                    2         $137.605.594          $107.565.459
…
TOTAL                                 1.939     $158.456.072.140    $123.871.215.068

[ Aprobar y crear corrida ]  [ Volver a seleccionar archivo ]  [ Cancelar ]
```

- **Errores** ⇒ "Aprobar" deshabilitado y la lista de errores visible (nunca un botón muerto
  sin explicación: la lección del smoke test del 2026-08-03).
- **Solo advertencias** ⇒ aprobar exige un checkbox "Entiendo las N advertencias".
- **Cancelar** cierra el panel. No hay nada que limpiar: no se escribió nada.
- El candado `enVuelo` que ya existe cubre el doble clic del lado del navegador; el índice
  `ux_corrida_armando_archivo` lo cubre del lado del servidor.
- Moneda en formato colombiano con el helper `lib/moneda.ts` que ya existe.
- Accesibilidad: `<label htmlFor>` en el selector, tabla con `<caption>` y `scope="col"`,
  errores en un contenedor `role="alert"`.

### `Corrida.tsx` + `TablaItems.tsx`

- Columna `Capítulo` (visible solo si la corrida tiene capítulos), que hereda gratis el
  filtro por columna y el orden que ya existen ⇒ "inspeccionar las actividades de un
  capítulo" sale sin UI nueva.
- Panel plegable **Resumen por capítulo** encima de la tabla, pintando `vista.capitulos`
  tal cual llega: Capítulo · Actividades · Con APU · Sin APU · Contractual · Costo ·
  Diferencia · Margen · Cobertura · Estado. El frontend **no calcula dinero**.
- Corrida sin capítulos ⇒ ni columna ni panel; la pantalla queda como hoy.

## 14. Migración

| Backend | Cambio |
|---|---|
| SQLite | `db/corridas.sql`: `origen_json TEXT` en el `CREATE TABLE`. `corridas_db.py::init_schema`: `if "origen_json" not in cols: ALTER TABLE corrida ADD COLUMN origen_json TEXT` |
| Postgres | `db/pg/corridas.sql`: la columna en el `CREATE TABLE` + `ALTER TABLE corridas.corrida ADD COLUMN IF NOT EXISTS origen_json TEXT` |

Idempotente por construcción, en el patrón que el repo ya usa. Sin migración de Supabase
aparte: la política RLS es por tabla, no por columna.

Riesgo conocido y aceptado: una corrida **encolada justo antes del deploy** reanuda con los
defaults de los campos nuevos (arma sin capítulo). Es el comportamiento que `plan_de` ya
documenta; no corrompe nada y se puede volver a armar si importa.

## 15. Pruebas

TDD: la prueba primero, en cada fase.

**Fixture chico** (`tests/conftest.py`, generado con `openpyxl`, ~45 filas): 2 capítulos,
turno diurno y nocturno, subtítulo, `Subtotal`, encabezado repetido a mitad, fila de
resumen, ítem con coma y `-N`, ítem con cero significativo, una fila ambigua y una con
unidad vacía. Es el que corre siempre.

**Regresión contra el archivo real**: `@pytest.mark.skipif` si no está en la ruta que
indique `APU_IDU_F1_XLSX` — el mismo trato que el Excel histórico. Verifica 14 / 1939 / 0
sin capítulo / conciliación exacta. El archivo **no se versiona** (4,5 MB).

| # | Grupo | Qué fija |
|---|---|---|
| 1–4 | Entidad | crear una importación IDU; las demás entidades usan el flujo genérico sin romperse; la entidad queda en `origen_json`; una corrida sin `origen_json` abre igual |
| 5–15 | Parser | hoja; encabezados con tildes, saltos y espacios; 14 capítulos; 1939 actividades; la fila 2201 no cuenta; turnos, subtítulos, subtotales, resúmenes y notas no cuentan; `2.001`/`2.001 N`/`2,001-N` → capítulo `2`; ceros significativos; ítem original preservado; diurno vs nocturno; filas ambiguas |
| 16–22 | Totales | `mul_redondeado(cant, K)`; conciliación contra la col L; suma por capítulo sin doble conteo; Σ capítulos = Σ actividades; el costo por capítulo sale solo de `PricingEngine`; una actividad sin APU no aparece como costo cero válido; margen marcado incompleto |
| 23–27 | Confirmación | no hay corrida antes de aprobar; los errores bloquean; las advertencias exigen confirmación; cancelar no deja datos; doble clic no crea dos corridas |
| 28–31 | Persistencia | paridad SQLite/PG de `set_origen`/`get_origen`; capítulos con orden y asociación tras recargar; corridas viejas abren; migraciones idempotentes (correr `init_schema` dos veces) |
| 32–34 | Privacidad | capítulo y descripción sí llegan a la IA; totales y costos nunca; cada nombre monetario nuevo dispara `PrivacyViolation` |
| 35–40 | Frontend | selector accesible; resumen legible; moneda colombiana; errores y advertencias visibles; filtro por capítulo en la tabla; contractual y costo por capítulo tras el armado |

Además se extienden `tests/test_paridad_backends.py`, `tests/test_repositorios_contrato.py`,
`tests/test_corridas_contrato.py` y `tests/test_mapa_arquitectura.py`. `npm run build` (que
es `tsc -b`, no `tsc --noEmit`) antes de dar por terminado el frontend.

## 16. Plan incremental

| # | Fase | Entrega verificable |
|---|---|---|
| 1 | Núcleo del parser | `item_pago_texto` / `normalizar_item_pago` / `capitulo_de`; detección de hoja, encabezado y clasificación de filas. Tests 5–15 |
| 2 | Lectura + conciliación | `leer_formulario_idu` → `LecturaPresupuesto` con errores, advertencias y conciliación. Tests 16–19 + regresión 14/1939 |
| 3 | Modelo + privacidad | campos de `LicitacionItem`, `EntidadOrigen`, `dominio/entrada.py`, `_FORBIDDEN_KEYS`. Tests 1–4, 32–34 |
| 4 | Persistencia | `origen_json` en los dos backends + `Protocol` + paridad. Tests 28–31 |
| 5 | Servicio | `POST /corridas/previsualizar`, `entidad` + `confirmada`, `capitulos` y `origen` en `vista_corrida`. Tests 23–27 |
| 6 | Reporte | `resumen_por_capitulo` única + hoja nueva en `write_report` + columnas sin AIU. Tests 20–22 |
| 7 | Frontend | selector de entidad, `PreviaIdu`, columna Capítulo, panel de resumen. Tests 35–40 + `npm run build` |

Cada fase cierra con `python -m pytest tests/ -q` verde. La suite completa y una pasada por
el navegador van antes de cualquier push; el push a master queda para aprobación explícita.

## 17. Fuera de alcance

Parser de Metro de Bogotá · parser de INVIAS · PDF · OCR · IA para leer el Excel o detectar
capítulos · migración de infraestructura · cambio de proveedor de IA · reemplazo del matcher
· generación automática de APUs antes del matching · modificación automática de APUs
aprobados · lectura de las columnas ofertadas y corregidas.

## 18. Lo que este diseño NO cambia

- El matching determinístico sigue primero y sigue siendo el único que arma.
- La IA no participa de la lectura del presupuesto ni de la detección de capítulos.
- La IA no ve dinero (invariante #1), y los campos monetarios nuevos entran a la denylist.
- La IA solo compone actividades sin APU, a pedido explícito, y el usuario aprueba.
- El costo interno lo sigue calculando `dominio/pricing.py`, el único módulo que ve dinero.
- `estado='armando'` sigue siendo la cola; nadie la saca de ahí con un `set_estado` pelado.
- Los candados de `seqs_sin_apu` y `_exigir_armado_completo` quedan intactos.
