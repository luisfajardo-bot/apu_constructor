> Espejo automático — no editar aquí. Fuente: `docs/superpowers/specs/2026-07-27-apus-np-design.md`

# Diseño — APUs para NP (No Previstos): listas de precios

> Fecha: 2026-07-27
> Estado: propuesto (aprobado en brainstorming; pendiente de revisión del spec escrito)
> Rama de trabajo sugerida: `feat/listas-precios-np`

## Objetivo

Durante una obra aparecen actividades **no previstas** (NP) que no estaban en el
presupuesto inicial pero hay que cobrarlas. Se arman igual que cualquier APU —misma
lista de ítems, mismo matching, mismo cuadro resumen— pero se costean contra **precios
distintos**, y esos precios **cambian de una obra a otra**.

Este proyecto introduce **listas de precios** como dimensión del catálogo: un mismo
insumo puede tener un precio vigente en la lista `Principal` y otro en la lista
`NP Calle 13`. Una corrida elige su lista al crearse y se costea contra ella.

La feature es genérica (N listas nombradas); NP es su caso de uso.

## Decisiones tomadas (brainstorming)

- **Catálogo:** los insumos de NP son **los mismos** del catálogo actual (mismo
  código+nombre) con otro valor, **más algunos nuevos** que hoy no existen.
- **Nº de listas:** varias, nombradas. Los NP difieren **por obra**; el nombre de la
  lista lleva la obra (`NP Calle 13`). **No** se modela una entidad `obra`.
- **`NP-3002` es el código de la ACTIVIDAD**, no del insumo. Los insumos conservan sus
  códigos normales.
- **Biblioteca de APUs: compartida.** Un APU es estructura (insumos + rendimientos); el
  precio lo pone la lista al costear. Los APUs `NP-xxxx` viven con los demás, el matcher
  los puede sugerir, y se distinguen por código/grupo. **Cero cambios en el matcher.**
- **Insumo sin precio en la lista → alerta, sin caer al Principal.** Costear NP con
  precios contractuales a escondidas es cobrar con la tarifa equivocada sin que nadie se
  entere. Consecuencia deliberada: en el camino NP se **desactiva** el respaldo al
  precio histórico embebido.
- **Carga de una lista:** importando un Excel **y** editando a mano insumo por insumo.
  (Descartados por YAGNI: clonar la lista principal, clonar con un factor.)
- **Elección de lista: por corrida, al crearla.** Inmutable después.

## Invariante #1 (recordatorio)

Esta feature **no toca la IA**. La lista es un selector de precios: vive del lado con
dinero (`precios_db`, `pricing.py`, `report.py`) y **ningún payload hacia la IA cambia
de forma**. La IA sigue viendo solo `DePriced*` — no recibe el precio, ni el nombre de
la lista, ni el `lista_id`. `privacy.py` no se toca y no se añade ninguna clave a
`_FORBIDDEN_KEYS` (`lista_id` no es un campo monetario).

## Enfoque elegido y alternativas descartadas

**Elegido — columna `lista_id` en `insumo_precios`.** La tabla ya es un libro de
historial de precios; añadir la lista como dimensión da historial por lista gratis,
mantiene **un solo catálogo de identidades** (código+nombre) y deja el camino Principal
idéntico al de hoy.

**Descartado — segunda base de datos completa** (`precios_np.db` / schema por obra).
Es la lectura literal de "otra base de insumos" y da aislamiento total, pero los APUs
referencian insumos por **código+nombre**, no por id: dos catálogos que derivan por
separado es el escenario que ya costó dos incidentes en este proyecto (`TRANSPORTE en
$0` y el falso sub-APU del código 6270), donde un catálogo divergente hizo fallar el
cruce **en silencio**. Además "una por obra" implicaría provisionar y migrar N bases.

**Descartado — reusar `fuente` como selector de lista.** No funciona:
`_insertar_precio_vigente` pone `vigente=0` en **todas** las filas del insumo, así que
dos listas no pueden estar vigentes a la vez; habría que cambiar la semántica de
`vigente` igual. Y `fuente` alimenta `config.classify_price_source` (público vs. interno
confidencial): sobrecargarla mezclaría el nombre de la lista con la clasificación de
confidencialidad.

## El invariante que hace pequeño el cambio

> **`lista_id = NULL` ≡ Principal ≡ comportamiento de hoy.**

Todo parámetro `lista_id` nuevo es opcional con default `None`. Con `None` (o con el id
de Principal) cada camino de código se comporta **exactamente** como hoy. La lista
Principal es intocable: no se renombra ni se borra.

Corolario: **el dataclass `Insumo` no cambia**. Sigue con un solo campo `precio`, que
significa "el precio de este insumo **en la lista con la que lo leí**". Por eso el
motor de precios, el cruce, `assemble.py`, los reportes y las alertas no cambian de
forma — reciben un `Insumo` igual que siempre. Toda la dimensión "lista" vive en la capa
de datos y en un parámetro que se propaga hacia abajo.

## 1. Modelo de datos

### Tabla nueva

`db/precios.sql` y `db/pg/precios.sql`:

```sql
CREATE TABLE IF NOT EXISTS lista_precios (
    id         INTEGER PRIMARY KEY,   -- Postgres: BIGINT GENERATED ALWAYS AS IDENTITY
    nombre     TEXT NOT NULL UNIQUE,  -- 'Principal', 'NP Calle 13', ...
    creada_en  TEXT NOT NULL,         -- ISO 8601
    creado_por TEXT                   -- user_id (NULL = sistema/migración)
);
```

Fila semilla obligatoria, creada por `init_schema` de forma idempotente:
`(1, 'Principal', <fecha>, NULL)`. Constante `LISTA_PRINCIPAL_ID = 1` en
`apu_tool/config.py`.

### Columna nueva

`insumo_precios.lista_id INTEGER NOT NULL DEFAULT 1`, más el índice
`(insumo_id, lista_id, vigente)`. El índice actual `(insumo_id, vigente)` se conserva.

Semántica de `vigente`: pasa de "uno por insumo" a "uno por insumo **y** lista".
`_insertar_precio_vigente` cambia su `UPDATE ... SET vigente=0 WHERE insumo_id=?` por
`WHERE insumo_id=? AND lista_id=?`.

**No se añade un índice único parcial** sobre `(insumo_id, lista_id) WHERE vigente=1`.
Hoy la unicidad de `vigente` tampoco está en el esquema (la garantiza el código), y una
migración con UNIQUE podría fallar sobre datos de producción sucios. Queda anotado como
mejora futura, no como parte de este proyecto.

### Migración

Al boot, en `init_schema` de ambos backends, con el mismo patrón ya usado para `oculto`
y para `modo`/`snapshot_json`:

- SQLite: `PRAGMA table_info` → si falta, `ALTER TABLE insumo_precios ADD COLUMN
  lista_id INTEGER NOT NULL DEFAULT 1`.
- Postgres: `ALTER TABLE precios.insumo_precios ADD COLUMN IF NOT EXISTS lista_id BIGINT
  NOT NULL DEFAULT 1 REFERENCES precios.lista_precios(id)`.

Todas las filas existentes quedan en Principal por definición del `DEFAULT`. No hay
backfill que escribir ni datos que mover.

**Drift declarado entre backends:** SQLite no permite `ADD COLUMN` con `NOT NULL DEFAULT`
*y* cláusula `REFERENCES` a la vez, así que la FK a `lista_precios` existe en Postgres y
en el `CREATE TABLE` canónico, pero **no** en la columna que la migración añade a una
base SQLite preexistente. Se documenta con una nota en ambos archivos de esquema, igual
que la nota ya existente sobre `ON DELETE CASCADE` en `db/pg/precios.sql`.

### `corrida.lista_precios_id`

`db/corridas.sql` y `db/pg/corridas.sql`: `lista_precios_id INTEGER` (**nulo =
Principal**), migración `ADD COLUMN` al boot. Se fija al crear la corrida y es
**inmutable**: no existe `set_lista`.

**Sin FK, a propósito.** `lista_precios` vive en `precios.db` y `corrida` en
`corridas.db`: archivos SQLite distintos, la FK es imposible. En Postgres son schemas del
mismo motor y sí sería posible, pero mantener el mismo contrato en ambos backends vale
más que la FK. Es el mismo trato que ya recibe `corrida_item.apu_codigo`, que tampoco
tiene FK contra la biblioteca.

La integridad se cuida por el otro lado: **no se borran listas** (ver §4).

### Modelo

```python
@dataclass(frozen=True)
class ListaPrecios:
    id: Optional[int]
    nombre: str
    creada_en: str
    creado_por: Optional[str] = None
```

`CorridaMeta` gana `lista_precios_id: Optional[int] = None`. El **nombre** de la lista
no se guarda en la corrida: se resuelve en la capa de servicio al construir la vista. Si
una lista se renombra, las corridas muestran el nombre nuevo — es la misma lista con otra
etiqueta. Los **números** de una corrida congelada no dependen de esto (§3).

### Contrato de `RepositorioPrecios`

Parámetro `lista_id: Optional[int] = None` **añadido al final** de:
`get_candidatos`, `get_candidatos_bulk`, `get_insumo_por_id`, `set_precio_por_id`,
`price_history`, `list_insumos`, `fuentes`, `crear_insumo`.

`list_insumos` gana además el filtro `sin_precio: bool = False` (§4).

Métodos nuevos: `listar_listas() -> list[ListaPrecios]`,
`crear_lista(nombre, creado_por=None, conn=None) -> int`,
`get_lista(lista_id) -> Optional[ListaPrecios]`,
`renombrar_lista(lista_id, nombre, conn=None) -> None`.

Sin cambios **de firma**: `grupos()` (el grupo cuelga del insumo, no del precio),
`set_oculto`, `todos_no_ocultos`, `search_insumos*` (búsqueda por texto, sin precio en el
criterio), e `insert_insumos` y `set_precio`, que internamente escriben siempre en
Principal (seed y CLI).

**Qué devuelve `list_insumos` con una lista seleccionada:** **todos** los insumos del
catálogo, tengan o no precio en esa lista; los que no lo tienen vienen con `precio`
nulo/0 y la UI los pinta `—`. El catálogo de identidades es único y compartido entre
listas (§ enfoque elegido); la lista solo decide **qué precio** se lee, no **qué insumos
existen**. Filtrar a los que sí tienen precio se hace con el filtro `fuente`.

`sin_precio=True` es **excluyente** con los filtros `fuente` y `clasificacion`: ambos son
atributos de una fila de precio que, por definición, no existe. Si llegan combinados, la
capa de servicio responde 400 en vez de devolver una lista vacía sin explicación.

`RepositorioCorridas.crear_corrida` toma el `lista_precios_id` dentro del `CorridaMeta`
que ya recibe; no cambia de firma.

Ambos backends (`precios_db.py` y `pg/precios_pg.py`) implementan lo mismo — son espejo
1:1 y el `Protocol` es el contrato compartido.

## 2. Motor de precios

`PricingEngine(almacen, lista_id: Optional[int] = None)`. La instancia queda **atada a
una lista**, y por eso sus tres cachés (`_cache` de precios, `_comp_cache` de
composiciones, `_apu_cost_cache` de costos de sub-APU) siguen indexados igual que hoy,
sin añadir la lista a la clave: no hay riesgo de que un costo de Principal se filtre a
una corrida NP porque son instancias distintas.

`_candidatos` y `_precargar_lote` pasan `lista_id=self.lista_id` a
`get_candidatos` / `get_candidatos_bulk`. `precargar` conserva su envoltura fail-safe.

### El único cambio de lógica: el respaldo

`cost_component`, hoy:

```python
if r.insumo is not None and r.insumo.precio > 0:
    precio, fuente = r.insumo.precio, r.insumo.fuente_precio
else:                                       # AMBIGUO o HUERFANO
    precio, fuente = comp.precio_unitario_hist, "histórico"
```

Queda:

```python
if r.insumo is not None and r.insumo.precio > 0:
    precio, fuente = r.insumo.precio, r.insumo.fuente_precio
elif self._respalda_con_historico():        # Principal -> IDÉNTICO a hoy
    precio, fuente = comp.precio_unitario_hist, "histórico"
else:                                       # lista NP -> señal, no un número inventado
    precio, fuente, calidad = 0.0, "sin precio en lista", "sin_precio_lista"
```

con `_respalda_con_historico()` = `self.lista_id in (None, config.LISTA_PRINCIPAL_ID)`.

La rama `sin_precio_lista` **pisa** la `calidad_cruce` que venía del resolver
(`huerfano`, `ambiguo`, `exacto`, `aproximado`): en una lista NP el motivo accionable es
siempre el mismo —falta el precio en esa lista— y es el que hay que mostrar.

La misma regla se aplica en `_fallback_historico`, el respaldo de los sub-APUs con ciclo
o sin composición: ahí el histórico es igual de contractual y mezclaría tarifas. En una
lista no-Principal devuelve `precio = 0.0` y `fuente = "sin precio en lista"`,
**conservando** su `calidad_cruce` (`ciclo` / `apu_vacio`), porque el problema real es
estructural, no de precio faltante.

Nuevo valor posible de `CostedComponent.calidad_cruce`: `"sin_precio_lista"`. Se añade
al comentario del dataclass que ya enumera los valores válidos.

`cost_apu`, `cost_components` y `_cost_subapu` no cambian de firma.

### Alertas

`alertas_costeo` ya dispara con la regla dura `costo <= 0 or precio_unitario <= 0`, así
que un componente sin precio en la lista **queda alertado solo**. El único cambio es una
rama **antes** de esa regla, para que el motivo sea accionable en vez de genérico:

```python
if c.calidad_cruce == "sin_precio_lista":
    motivos.append(f"{etiqueta}: sin precio en la lista")
elif c.costo <= 0 or c.precio_unitario <= 0:
    motivos.append(f"{etiqueta}: en $0")
elif c.calidad_cruce in _MOTIVO_CRUCE:
    ...
```

Como `sin_precio_lista` solo puede aparecer costeando contra una lista distinta de
Principal, el camino de hoy queda bit a bit igual: mismo conteo de alertas, misma hoja
`ALERTAS`, mismos totales.

### Propagación

Nueve sitios construyen un `PricingEngine`:

| Sitio | Lista |
|---|---|
| `servicio/corridas.py` × 5 (`vista_corrida`, `congelar`, `detalle_item`, `listar_corridas`, `generar_cuadro`) | la de la corrida (`meta.lista_precios_id`) |
| `servicio/apus.py` × 2 | `lista_id` opcional del query param, default Principal |
| `dominio/assemble.py` | la que reciba el `Assembler` |
| `dominio/pipeline.py` | Principal (CLI y GUI se quedan en Principal) |

`_costear_row(alm, row, pricing=None, lista_id=None)`: cuando recibe un motor compartido
la lista viaja dentro de él; el parámetro solo se usa para el motor que crea por su
cuenta. `Assembler(alm, advisor=..., lista_id=None)` se la pasa a su motor, para que
armar y confirmar un ítem coste contra la lista correcta.

## 3. La corrida

**Congelar sale gratis.** El snapshot por ítem ya guarda `precio_unitario` y
`fuente_precio` de cada componente, así que una corrida NP congelada es una foto
inmutable **aunque después se edite la lista NP** — misma semántica de hoy. No hay que
tocar `congelar`, `_assembled_desde_snapshot` ni la estructura del snapshot; solo pasar
la lista al motor que costea lo que aún no tiene foto.

**El cuadro dice con qué tarifa se emitió.**
`write_report(apus, path, lista_nombre="Principal")` — kwarg opcional que agrega una fila
`["Lista de precios", <nombre>]` en la hoja `INFO`, junto a "Generado" y la nota del
invariante #1. Los llamadores actuales (CLI, GUI) no cambian y siguen diciendo
"Principal". Sin esto, un cuadro NP y uno contractual son indistinguibles en el archivo,
que es el error caro de esta feature.

`report_categorizado.py` recibe el mismo tratamiento si emite su propia hoja de
metadatos; si reusa la de `report.py`, no se toca.

## 4. API y web

### Endpoints nuevos

| Método | Ruta | Rol | Notas |
|---|---|---|---|
| `GET` | `/listas-precios` | cualquiera | `[{id, nombre, creada_en}]` |
| `POST` | `/listas-precios` | editor | `{nombre}`; 400 si vacío o duplicado |
| `PATCH` | `/listas-precios/{id}` | editor | `{nombre}`; **400 sobre la lista 1** |

**No hay `DELETE`.** Es lo que evita que una corrida quede huérfana de su tarifa (no hay
FK que lo impida, §1). Un nombre mal escrito se corrige renombrando. Si más adelante
hiciera falta, requeriría un guard tipo `contar_corridas` de carpetas — decisión aparte.

### Endpoints modificados

Todos con parámetro opcional, default Principal, así que ningún cliente actual se rompe:

| Endpoint | Cambio |
|---|---|
| `GET /insumos`, `/insumos/fuentes`, `/insumos/{id}` | query param `lista` — precio, fuentes e historial de esa lista |
| `POST /insumos/cambios` | `lista_id` en el body |
| `POST /insumos/importar/preview` y `/importar` | campo `lista_id` — **la carga del Excel NP** |
| `POST /insumos/crear` | `lista_id` |
| `POST /corridas` y `/corridas/stream` | campo `lista_id` |
| `GET /corridas` y `/corridas/{cid}` | devuelven `lista_precios_id` y `lista_nombre` |
| `GET /apus/{codigo}/{turno}` | query param `lista` para el costo mostrado |

`GET /insumos/grupos` no cambia.

### El importador ya existe

`autoria.py::preview_importar_insumos` / `aplicar_importar_insumos` ya hacen el upsert
por identidad código+nombre con preview y reporte de errores: crean el insumo si no
existe, actualizan el precio si existe, y marcan ambiguas / no encontradas / inválidas.
Es exactamente el comportamiento que necesita la carga de una lista NP —incluidos los
"insumos nuevos que solo existen en NP"—. Solo hay que propagarle `lista_id` a
`crear_insumo` y `set_precio_por_id`. La validación `precio > 0` (`MSG_PRECIO_POSITIVO`)
se mantiene: la regla "nada en $0" aplica igual en una lista NP.

### Filtro "sin precio en esta lista"

Requisito derivado de la decisión de editar a mano: para completar una lista NP hay que
poder **ver qué falta**. `list_insumos` recibe `sin_precio: bool = False`, que devuelve
los insumos sin fila vigente en la lista seleccionada, y la columna de precio muestra
`—` en vez de `$0` cuando no hay fila. Sin esto, completar una lista a mano es adivinar.

### Web

Denso, table-first, sin cards, como el resto de la app.

- **Insumos** (`web/src/pages/Insumos.tsx`): un `<select>` de listas en la barra de
  filtros que ya tiene grupo/fuente/clasificación, con el mismo patrón de estado → query
  param. Manda en toda la página: qué precio se ve, dónde escribe la edición, a qué lista
  importa el Excel. Cuando la lista seleccionada **no** es Principal, un indicador
  persistente y bien visible — editar precios en la lista equivocada es el error caro de
  esta feature y la UI tiene que hacerlo difícil. Chip de filtro para "sin precio en esta
  lista".
- **Nueva corrida** (`CorridasInicio.tsx`): selector de lista junto a turno y carpeta,
  campo visible (no escondido en un "avanzado"): es inmutable después, así que el momento
  de elegir bien es ese.
- **Corrida** (`Corrida.tsx`): la lista en el encabezado. Las alertas "sin precio en la
  lista" aparecen solas en la columna de alertas que ya existe.
- **Mis corridas** (`MisCorridas.tsx`): columna con la lista, para no confundir un cuadro
  NP con uno contractual.
- **APUs** (`Apus.tsx`): selector de lista para el costo mostrado. Prioridad baja.

Cliente API: `web/src/api/insumos.ts` y `corridas.ts` propagan el parámetro; tipo
`ListaPrecios` nuevo.

### Auditoría

Acciones nuevas en la taxonomía: `lista.crear`, `lista.renombrar`. Además,
`precio.editar` e `insumo.crear` llevan `lista_id` en `contexto` — sin eso el log no
puede decir **qué tarifa** tocó un cambio de precio, que es justo lo que hará falta
cuando algo no cuadre.

### RBAC

Sin cambios en el modelo de roles: `consulta` lee listas, `editor` las crea/renombra y
edita precios en cualquier lista, `admin` igual que hoy.

## 5. Pruebas

Pruebas nuevas, todas con SQLite en `tmp_path` como el resto de `tests/`:

**Regresión (lo más importante).** El cuerpo de la suite actual **no se modifica**: que
siga verde con las firmas nuevas es la evidencia de que `lista_id=None` no cambió nada.
Se añade además un test explícito de que costear con `lista_id=None`, con
`lista_id=LISTA_PRINCIPAL_ID` y con la firma vieja dan el **mismo** `CostedComponent`
(precio, fuente, costo y `calidad_cruce`), incluido el caso que cae a histórico.

**Datos.** Migración idempotente (`init_schema` dos veces); las filas preexistentes
quedan en Principal; `vigente` es por (insumo, lista) — fijar precio en NP no toca el
vigente de Principal ni al revés; `price_history` filtra por lista; `crear_lista` rechaza
nombre duplicado y vacío; `renombrar_lista` rechaza la lista 1; `list_insumos` con una
lista NP vacía devuelve **todo** el catálogo con precio nulo (no una lista vacía);
`sin_precio=True` combinado con `fuente` o `clasificacion` responde 400.

**Motor.** Insumo con precio en NP → usa ese precio. Insumo sin precio en NP pero **con**
precio en Principal → `precio = 0`, `fuente = "sin precio en lista"`,
`calidad_cruce = "sin_precio_lista"` y **no** cae a Principal ni al histórico (es el
corazón de la decisión de negocio). El mismo caso en Principal → sí cae a histórico.
Sub-APU con ciclo y con composición vacía en una lista NP → `0` conservando `ciclo` /
`apu_vacio`. Dos motores con listas distintas sobre el mismo `Almacen` no se contaminan
los cachés.

**Alertas.** `sin_precio_lista` produce "sin precio en la lista" y no "en $0"; el ítem
entra en `filas_alertadas` y suma en `n_alertas_costeo`.

**Servicio.** Una corrida creada con `lista_id` la conserva y costea con ella; congelar
y luego cambiar el precio en la lista NP no mueve los totales congelados; el cuadro
generado trae la fila `Lista de precios` en la hoja `INFO`; el import con `lista_id`
crea insumos nuevos con precio solo en esa lista.

**Frontend** (Vitest): el selector de lista propaga el query param; `—` en vez de `$0`
cuando no hay precio en la lista. Verificación del build con `npm run build` (`tsc -b`),
**no** `tsc --noEmit` — lección registrada del proyecto de nombre/alias de corridas.

## Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Editar precios en la lista equivocada | Indicador persistente y visible en Insumos cuando la lista ≠ Principal; `lista_id` en el contexto de auditoría para poder rastrearlo |
| Confundir un cuadro NP con uno contractual | Fila `Lista de precios` en la hoja `INFO`; columna de lista en Mis corridas; lista en el encabezado de la Corrida |
| Migración sobre el Postgres de producción | Validar el `ADD COLUMN` contra el Postgres real **antes** de desplegar, como se hizo con nombre/alias de corridas; es aditiva y con default, sin backfill |
| Una lista NP incompleta produce un total bajo (underbid) | El componente queda en `$0` **con alerta explícita**, que es la regla de negocio ya establecida; el filtro "sin precio en esta lista" permite completar antes de emitir |
| Regresión silenciosa en el costeo Principal | El invariante `None ≡ Principal ≡ hoy` + la suite actual sin modificar + el test explícito de equivalencia |

## Fuera de alcance (deliberado)

- Entidad `obra`. La obra vive en el nombre de la lista.
- Clonar una lista (tal cual o con un factor de reajuste).
- Borrar listas.
- Elegir lista **por ítem** dentro de una corrida.
- Cambiar la lista de una corrida ya creada.
- Excluir los APUs `NP-xxxx` del matcher en corridas contractuales.
- Índice único parcial sobre `(insumo_id, lista_id) WHERE vigente=1`.
- Selector de lista en CLI y GUI (se quedan en Principal).
