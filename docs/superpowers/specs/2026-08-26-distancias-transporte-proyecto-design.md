# Distancias de transporte y ajustes por proyecto

**Fecha:** 2026-08-26 · **Rama:** `feat/distancias-transporte-proyecto`

## Problema

Cada carpeta nueva es un proyecto nuevo, y cada proyecto tiene su propia geografía: el
botadero queda a otra distancia, la planta de asfalto a otra, la cantera a otra, y la ruta
puede tener peaje o no. Hoy esas distancias viven **dentro del rendimiento de la
composición de la biblioteca**, así que cambiarlas para el Metro cambia también la Calle 13.
La única salida actual es `autoria.editar_apu`, que es global.

Además, aunque es poco común, un proyecto puede necesitar **cambios puntuales de
composición**: incluir un insumo que la especificación del cliente exige, quitar uno que el
cliente suministra, o ajustar un rendimiento.

Falta entonces una noción de **desviación del proyecto respecto de la biblioteca**.

## Cómo entra hoy la distancia (datos reales)

`data/apus.db`: 1182 APUs, 5213 componentes. Componentes M3-KM y afines:

| insumo | unidad | usos | tipo | qué es el rendimiento |
|---|---|---|---|---|
| `7462` TRANSPORTE DE PETREOS | M3-KM | 31 | insumo | m³ esponjados × km |
| `INT2` TRANSPORTE DE GRANULARES | M3-KM | 22 | insumo | m³ esponjados × km |
| `6878` TRANSPORTE DE BASES ASFALTICAS | M3-KM | 9 | insumo | m³ esponjados × km |
| `INT1` TRANSPORTE DE PETREOS | M3-KM | 2 | insumo | m³ esponjados × km |
| `7231` DERECHOS DE BOTADERO | M3 | 9 | insumo | volumen esponjado (no escala con km) |
| `INT3` PEAJE | GLB | 31 | insumo | 1,0 — lo que varía es el **precio** |
| `3017` / `3017 N` / `4613 N` escombros | M3 | 64 | **apu** | **sub-APU**, ver abajo |

Tres hechos de los datos que definen el diseño:

**1. El botadero ya es un sub-APU.** Los 64 componentes de escombros son `tipo='apu'`, y la
distancia vive **una sola vez por turno**, dentro de la composición del sub-APU:

| sub-APU | derechos `7231` | componente M3-KM | km implícito |
|---|---|---|---|
| `3017` DIURNO | 1,30 | `INT1` 20,0 | 15,4 |
| `3017 N` NOCTURNO | 1,00 | `7462` 21,0 | 21,0 |
| `4613` DIURNO | 1,30 | `INT1` 20,0 | 15,4 |
| `4613 N` NOCTURNO | 1,00 | `7462` 28,0 | 28,0 |

Reescalar el sub-APU una vez cambia los 64 APUs que lo usan. El costeo recursivo de
sub-APUs ya pasa por `PricingEngine.components()`, así que sale gratis.

**2. La categoría depende del APU dueño, no del insumo.** El mismo `7462`/`INT1`
(«TRANSPORTE DE PETREOS») es *granulares* dentro de un APU de base granular y *botadero*
dentro del sub-APU `3017`. Clasificar por código de insumo es imposible.

**3. Los códigos están duplicados en el catálogo, con significados distintos.** 6 de los 9
códigos de transporte tienen homónimo: `7462` es también NIPLE 16" (UN), `6878` es también
CONCRETO 3000 PSI (M3), `4613` es también UNION PVC (UN), `6462` es también TAPON HD (UN),
y `INT1` tiene dos nombres **con la misma unidad M3-KM** (*TRANSPORTE DE PETREOS* y
*TRANSPORTE A BOTADEROS*). Ni el código ni la unidad desambiguan: la identidad de un
componente es **código + nombre** (misma lección que el fix `6cb7c29`).

Los rendimientos M3-KM también son heterogéneos (26,25 · 29,61 · 27,3 · 35 · 8,4 · 0,28):
**la biblioteca no se armó toda a la misma distancia**. Un reescalado proporcional ciego
subcostearía las filas armadas a otra distancia — 8,4 (≈ 8 km) escalado a 32 km daría 10,75
en vez de 33,6, un subcosteo de 3×. De ahí la clasificación previa.

`6462` («a distancia mayor del acarreo libre») y el esquema «tramo fijo + excedente» **no
se usan** en la biblioteca: la única fila con ese código es la colisión con el TAPON HD. El
diseño no los modela; si algún día se usan, esa fila se clasifica como botadero y ya.

## Decisiones tomadas

1. **Una sola biblioteca.** La distancia es una propiedad del sitio, no del APU. No hay
   bases de APUs por proyecto: copiar 1182 APUs por proyecto obliga a replicar cada
   corrección N veces, duplica códigos IDU (rompe la regla de alta sin duplicados) y deja
   al matcher sin saber en qué biblioteca buscar. El «archivo del proyecto» ya existe:
   **congelar** la corrida guarda el snapshot inmutable de sus APUs.
2. **Dos capas de desviación** sobre la composición de la biblioteca: una **regla** de
   transporte (paramétrica, automática) y **ajustes** puntuales (explícitos, manuales).
3. **Alcance = proyecto** (carpeta de nivel 1), heredado en vivo por sus subcarpetas y
   corridas activas. Las congeladas conservan su snapshot.
4. **Una sola regla, sin casos especiales:** `rend = volumen × km_de_su_categoría`.
   Aplica igual a botadero, mezclas y granulares.
5. **La categoría se guarda por componente**, no por insumo (hecho 2), sugerida
   automáticamente y confirmada por el usuario.
6. **Peaje:** sí/no + valor ya prorrateado por unidad. Si es «no», el componente se
   **quita** de la composición del proyecto — no queda en $0, que la regla de negocio
   prohíbe.
7. **Clasificación previa** de las 64 filas M3-KM con km base default 25 y revisión fila por
   fila; sin clasificar no se reescala y se **alerta**.
8. **Los ajustes manuales ganan sobre la regla:** son la excepción explícita del ingeniero.
9. Las inconsistencias de la biblioteca (ver Hallazgos) **se muestran, no se corrigen** en
   esta feature.

## Arquitectura

```
composición de la biblioteca        (apus.db — know-how de la empresa, intacta)
        ↓
capa 1: regla de transporte         (proyecto_parametros + componente_transporte)
        ↓
capa 2: ajustes del proyecto        (proyecto_ajuste — ganan sobre la regla)
        ↓
composición efectiva del proyecto   → costeo → cuadro resumen → congelar
```

El enganche es **un solo punto de paso**: `PricingEngine.components()`. Por ahí ya pasan el
costeo de corrida activa (`_costear_row`), el congelado, el cuadro y el costeo recursivo de
sub-APUs — que es lo que hace que reescalar el sub-APU de botadero alcance a sus 64 APUs sin
código adicional. No hay un segundo camino que haya que mantener en sincronía.

## Modelo de datos

### 1. `config.py` — vocabulario y sugerencias

Patrón de la casa para vocabularios cerrados (`PUBLIC_PRICE_SOURCES`, `LISTA_PRINCIPAL_ID`,
grupos de APU). No hay tabla de vocabulario.

```python
TRANSPORTE_CATEGORIAS = ("botadero", "mezclas", "granulares")
KM_BASE_DEFECTO = 25.0          # supuesto inicial de la pantalla de clasificación
PEAJE = ("INT3", "PEAJE")       # código + nombre del insumo de peaje
DERECHOS_BOTADERO = ("7231", "DERECHOS DE BOTADERO")   # volumen: NO escala con km

# Solo para SUGERIR la categoría en la pantalla de clasificación; el usuario confirma.
TRANSPORTE_SUGERENCIAS = (
    ("apu_nombre", ("ESCOMBROS", "BOTADERO"), "botadero"),
    ("insumo_nombre", ("BASES ASFALTICAS", "ASFALTIC"), "mezclas"),
    ("insumo_nombre", ("PETREOS", "GRANULARES"), "granulares"),
)
```

### 2. `componente_transporte` — categoría y volumen por componente (`apus.db`)

```sql
CREATE TABLE IF NOT EXISTS componente_transporte (
  apu_codigo      TEXT NOT NULL,
  shift           TEXT NOT NULL,
  insumo_codigo   TEXT NOT NULL,
  insumo_nombre   TEXT NOT NULL,   -- identidad real: codigo + nombre (hecho 3)
  categoria       TEXT NOT NULL,   -- botadero | mezclas | granulares
  volumen         REAL NOT NULL,   -- m3 esponjados por unidad de APU
  km_base         REAL,            -- distancia asumida al clasificar (trazabilidad)
  actualizado_en  TEXT NOT NULL,
  actualizado_por TEXT,
  PRIMARY KEY (apu_codigo, shift, insumo_codigo)
);
```

`volumen = rendimiento_actual / km_base`. Solo se clasifican las filas M3-KM (64 hoy). La PK
es única en los datos reales (no hay ningún APU con el mismo código de insumo dos veces).
`insumo_nombre` viaja en la fila porque el cruce contra el catálogo desambigua por código +
nombre; sin él, `7462` podría resolverse al NIPLE.

Tabla aparte y **no** una columna en `apu_componentes`, por dos razones: `ApuComponent` lo
escriben seed, autoría, duplicar-APU, plantillas e importadores (agregar un campo toca los
seis), y `insert_components` reinserta filas con `seq` nuevo en cada semillado.

### 3. `proyecto_parametros` — las distancias del proyecto (`corridas.db`)

```sql
CREATE TABLE IF NOT EXISTS proyecto_parametros (
  carpeta_id      INTEGER PRIMARY KEY REFERENCES carpeta(id) ON DELETE CASCADE,
  km_botadero     REAL,
  km_mezclas      REAL,
  km_granulares   REAL,
  peaje_aplica    INTEGER,   -- NULL = no definido, 0 = no hay, 1 = si
  peaje_valor     REAL,
  actualizado_en  TEXT NOT NULL,
  actualizado_por TEXT
);
```

Solo se escribe en carpetas de **nivel 1** (`parent_id IS NULL`); el servicio rechaza una
subcarpeta. Una corrida resuelve subiendo por `parent_id` hasta la raíz. **Sin fila =
comportamiento actual, sin ninguna diferencia.**

### 4. `proyecto_ajuste` — las excepciones del proyecto (`corridas.db`)

```sql
CREATE TABLE IF NOT EXISTS proyecto_ajuste (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  carpeta_id          INTEGER NOT NULL REFERENCES carpeta(id) ON DELETE CASCADE,
  apu_codigo          TEXT NOT NULL,
  shift               TEXT NOT NULL,
  accion              TEXT NOT NULL,  -- rendimiento | agregar | quitar | reemplazar
  insumo_codigo       TEXT NOT NULL,  -- componente objetivo (o el nuevo, si 'agregar')
  insumo_nombre       TEXT NOT NULL DEFAULT '',
  unidad              TEXT NOT NULL DEFAULT '',
  rendimiento         REAL,
  insumo_nuevo_codigo TEXT,           -- solo 'reemplazar'
  insumo_nuevo_nombre TEXT,
  tipo                TEXT NOT NULL DEFAULT 'insumo',  -- insumo | apu (sub-APU)
  ref_shift           TEXT NOT NULL DEFAULT '',
  nota                TEXT NOT NULL DEFAULT '',
  creado_en           TEXT NOT NULL,
  creado_por          TEXT,
  UNIQUE (carpeta_id, apu_codigo, shift, accion, insumo_codigo)
);
```

`insumo_nombre` se guarda además del código por el hecho 3. `tipo` y `ref_shift` existen
para que un ajuste pueda meter un sub-APU sin rediseñar la tabla.

Esta capa **no ve dinero**: solo estructura (insumos y rendimientos). El precio por obra
sigue siendo la lista NP; el peaje sigue siendo un parámetro.

### 5. Privacidad (invariante #1)

`_FORBIDDEN_KEYS += {"peaje_valor"}` en `apu_tool/dominio/privacy.py` (la clave `valor` ya
está, pero el chequeo es por nombre exacto). Los rendimientos y las distancias son
cantidades, no dinero: siguen permitidos como hoy (`_ALLOWED_NUMERIC_KEYS`).

### 6. Migración

- SQLite: `CREATE TABLE IF NOT EXISTS` en `CorridasDB.init_schema` y `ApusDB.init_schema`.
- Postgres: mismo DDL idempotente vía `pg.conexion.aplicar_migracion` al boot (patrón de
  `modo` / `snapshot_json`), más `supabase/migrations/0006_transporte_proyecto_rls.sql` con
  las políticas RLS espejo de `0004_carpetas_rls.sql`.
- Los repos `pg/` replican los métodos nuevos 1:1 (espejo obligatorio del contrato en
  `datos/repositorio.py`).

## Reglas del motor — `apu_tool/dominio/transporte.py`

Módulo puro: recibe `list[ApuComponent]` + parámetros + clasificación + ajustes y devuelve
`list[ApuComponent]`. No abre bases y (salvo el peaje) no ve dinero.

```
aplicar(componentes, apu_codigo, shift, params, clasificacion, ajustes) -> componentes
```

### Capa 1 — regla de transporte

| caso | regla |
|---|---|
| componente clasificado (`categoria`, `volumen`) y el proyecto tiene km de esa categoría | `rend = volumen × km_categoria` |
| componente clasificado y el km de su categoría es `NULL` | no se toca |
| componente M3-KM **sin clasificar**, con distancias definidas en el proyecto | no se toca + **alerta** |
| `7231` derechos de botadero | no escala nunca (es volumen) |
| `INT3` peaje, `peaje_aplica = 0` | **se quita el componente** |
| `INT3` peaje, `peaje_aplica = 1` | el precio lo pone `peaje_valor` |
| sub-APU (`tipo='apu'`) | no se toca aquí; se reescala al costear su propia composición, que también pasa por `components()` |

La identificación de un componente (peaje, derechos, clasificado) es por **código + nombre
normalizado** (`nucleo/texto.normalizar`), nunca por código solo (hecho 3).

Los rendimientos calculados se redondean a 6 decimales, igual que `privacy` al serializar.
El redondeo monetario sigue siendo el de `nucleo/redondeo.py`, intacto.

### Capa 2 — ajustes del proyecto

Se aplican **después** de la regla, en orden `quitar` → `reemplazar` → `rendimiento` →
`agregar`, para que un ajuste pueda pisar lo que la regla puso.

### Enganche

- `PricingEngine(alm, lista_id=None, contexto=None)`, donde `contexto` trae `params`,
  `clasificacion` y `ajustes` ya resueltos (una sola lectura por request, igual que la
  precarga en lote de `precargar`). `contexto=None` → comportamiento idéntico al de hoy.
- `components(codigo, shift)` aplica `transporte.aplicar(...)` sobre lo que lee de la
  biblioteca, **antes** de cachear en `_comp_cache`. Así el costeo, el memo de sub-APUs y
  `precargar` ven la misma composición efectiva, sin caminos divergentes. El sub-APU de
  botadero se reescala por este mismo camino, una vez, y lo heredan sus 64 APUs.
- El **peaje toca precio**, así que su override va en `cost_component` (el único módulo que
  ve dinero): si el componente es el peaje y `params.peaje_valor` está definido,
  `precio = peaje_valor` y `fuente_precio = "peaje del proyecto"`.
- `corridas._costear_row`, `congelar` y `pipeline` construyen el contexto desde
  `meta.carpeta_id` (subiendo a la raíz). Corrida sin carpeta → contexto vacío.

## Servicio — `apu_tool/servicio/transporte.py`

| endpoint | rol | qué hace |
|---|---|---|
| `GET /api/carpetas/{id}/transporte` | consulta | parámetros vigentes + tabla de impacto + pendientes de clasificar |
| `PUT /api/carpetas/{id}/transporte` | editor | guarda los parámetros. Auditoría `proyecto.transporte` |
| `GET /api/transporte/componentes` | consulta | las 64 filas M3-KM con categoría sugerida/confirmada, volumen y km base |
| `PUT /api/transporte/componentes` | editor | batch de categoría + volumen. Auditoría `transporte.clasificar` |
| `GET /api/carpetas/{id}/ajustes` | consulta | ajustes del proyecto |
| `POST /api/carpetas/{id}/ajustes` | editor | crea un ajuste. Auditoría `proyecto.ajuste.crear` |
| `DELETE /api/carpetas/{id}/ajustes/{aid}` | editor | borra un ajuste. Auditoría `proyecto.ajuste.borrar` |

Todo cuelga del único `APIRouter` de `rutas.py`, que delega en el módulo de servicio
(convención del repo). Los endpoints de escritura validan: carpeta de nivel 1, km ≥ 0,
`peaje_valor > 0` cuando `peaje_aplica = 1` (regla «nada en $0»), `volumen > 0`,
`rendimiento > 0` en los ajustes, categoría dentro del vocabulario, e insumo existente en el
catálogo al agregar o reemplazar.

**Tabla de impacto** (`GET .../transporte`): recorre los APUs asignados en las corridas del
proyecto **más el cierre de sus sub-APUs**, aplica la regla en seco y devuelve por
componente `apu_codigo`, insumo, unidad, `rendimiento_actual`, `categoria`, `volumen`,
`rendimiento_nuevo`, `origen` y `sin_clasificar`. Es previsualización pura: no escribe nada.

## Web

**A. «Distancias del proyecto»** — botón en la carpeta de nivel 1 (`pages/MisCorridas.tsx`),
panel denso sin cards: km botadero, km mezclas, km granulares, peaje (checkbox + valor).
Debajo, la tabla de impacto con el rendimiento nuevo por componente y el contador de no
clasificados con enlace a la pantalla B. **Guardar escribe solo los parámetros**: las
corridas activas del proyecto se recostean en su siguiente lectura. Ese es el «batch»: un
guardado, no N escrituras.

**B. «Clasificación de transporte»** — las 64 filas M3-KM de la biblioteca: APU dueño,
insumo, rendimiento actual, categoría (sugerida, editable), km base editable (default 25),
volumen derivado, **km implícito**, y marca en las filas cuyo km implícito no coincide con la
distancia que declara el nombre del insumo o cuyo volumen sale atípico. Acción en bloque.
Es una vez, no por proyecto.

**C. Composición del ítem de corrida** (`pages/Corrida.tsx`) — hoy es de solo lectura; pasa
a editable con **alcance «este proyecto» por defecto**: cambiar rendimiento, agregar, quitar
y reemplazar insumo. Cada componente muestra su origen: `biblioteca` · `distancia` ·
`ajuste`. Editar la biblioteca sigue siendo la acción aparte de la pantalla de APUs — el
default es deliberado, porque el error caro es contaminar la biblioteca creyendo que se
ajusta una obra.

Todo en solo lectura si la corrida está congelada, igual que el resto de la edición.

## Salida

- Encabezado de la corrida: `botadero 34 km · mezclas 28 · granulares 32 · peaje $12.400`.
- `dominio/report.py` y `report_categorizado.py`: hoja **DESVIACIONES DEL PROYECTO** con los
  parámetros y la lista de ajustes (APU, acción, insumo, rendimiento, nota). Un cuadro
  entregado sin esa hoja no es defendible en una aclaración.

## Alertas — `dominio/alertas.py`

Se agrega un motivo: componente M3-KM **sin clasificar** en un proyecto con distancias
definidas → `"7462 TRANSPORTE DE PETREOS: distancia del proyecto no aplicada"`. Criterio del
repo: preferimos alertar a costear con una distancia equivocada en silencio.

Las inconsistencias de la biblioteca (Hallazgos) **no** generan alerta de costeo: se ven en
la pantalla de clasificación y su corrección es una decisión aparte.

## Hallazgos de datos (no se corrigen en esta feature)

Salieron al inspeccionar la biblioteca; quedan documentados para decidirlos aparte.

| hallazgo | evidencia | efecto |
|---|---|---|
| `3017` DIURNO costeado a 15,4 km cuando su nombre dice 21 km | `INT1` 20,0 con derechos 1,30 | subcosteo ≈ 27% del transporte de escombros diurno |
| `4613` DIURNO costeado a 15,4 km cuando su nombre dice 28 km | `INT1` 20,0 con derechos 1,30 | subcosteo ≈ 45% |
| derechos de botadero 1,30 diurno vs 1,00 nocturno | `7231` en los 4 sub-APUs | 30% de diferencia sin razón física |
| `INT1` tiene dos insumos distintos con la misma unidad M3-KM | *TRANSPORTE DE PETREOS* y *TRANSPORTE A BOTADEROS* | cruce ambiguo: uno de los dos precios nunca se usa |
| 6 de 9 códigos de transporte tienen homónimo en el catálogo | `7462`, `6878`, `4613`, `6462`, `INT1`, `3017` | obliga a identificar por código + nombre en todo el diseño |

## Pruebas

1. **Regresión:** sin `proyecto_parametros` ni `proyecto_ajuste`, el costeo de una corrida es
   idéntico al de hoy (mismos costos y misma composición, componente por componente).
2. `transporte.aplicar`: reescalado por categoría; km en `NULL` no toca su categoría;
   componente sin clasificar no se toca; derechos `7231` nunca escalan; peaje quitado (y
   verificar que **no** deja un $0); peaje con valor usa `peaje_valor` y lo dice en la fuente.
3. **Sub-APU de botadero:** reescalar su componente M3-KM cambia el costo de los APUs que lo
   usan, en una sola pasada, y el memo de sub-APUs no sirve un valor viejo.
4. Identidad por código + nombre: un componente `7462` cuyo nombre es NIPLE **no** se
   clasifica ni se reescala.
5. Ajustes: las cuatro acciones; un ajuste pisa a la regla; `UNIQUE` impide duplicados.
6. Herencia: corrida en subcarpeta usa los parámetros de la raíz; corrida sin carpeta no
   cambia; corrida congelada conserva su snapshot aunque cambien los parámetros.
7. **Aislamiento entre proyectos:** dos corridas en proyectos distintos sobre el **mismo**
   APU dan costos distintos, y la composición en `apus.db` no cambió.
8. Privacidad: un payload con `peaje_valor` lanza `PrivacyViolation`.
9. Servicio: roles (consulta no escribe), validaciones (nivel 1, km ≥ 0, peaje > 0,
   volumen > 0, rendimiento > 0, categoría inválida, insumo inexistente) y auditoría.
10. Espejo Postgres: los mismos tests de contrato contra los repos `pg/` — los de
    `CorridasPg` no se pueden omitir (lección de `agregar-lineas-corrida`).
11. Excel: la hoja DESVIACIONES DEL PROYECTO aparece con parámetros y ajustes.
12. Frontend: `npm run build` (`tsc -b`, no `--noEmit`) + tests de la tabla de impacto y del
    editor de composición con alcance proyecto.

## Riesgos documentados

- **`seed --force` borra `componente_transporte`** (misma suerte que las listas NP, ya
  documentada en CLAUDE.md). Reclasificar son unos 10 minutos y el default de 25 km deja
  casi todo listo. Va a la sección «No hacer» de CLAUDE.md.
- **Mover una corrida de carpeta le cambia el costo**, porque los parámetros se heredan en
  vivo. Es el precio de tener una sola fuente de verdad por proyecto. Mitigación: el
  encabezado de la corrida muestra las distancias vigentes y el movimiento queda en
  auditoría.
- **La clasificación es un juicio de ingeniería.** El default de 25 km es un supuesto: las
  filas cuyo volumen derivado salga raro (`0,28 → 0,011 m³/un`) hay que revisarlas a mano.
  La pantalla las marca; el sistema no las adivina.
- **El sub-APU de botadero es compartido:** reescalarlo alcanza a los 64 APUs que lo usan.
  Eso es lo correcto, y también significa que un error en su clasificación se propaga a
  todos. La pantalla de clasificación lo señala como fila de alto impacto.

## Fuera de alcance (agregables después sin rediseñar)

- Corregir las inconsistencias de la biblioteca (Hallazgos).
- Excepción por línea de corrida (dos ítems con el mismo APU y distinto ajuste).
- Histórico de distancias por proyecto (hoy queda en auditoría, no en una tabla propia).
- Categorías nuevas de acarreo (concreto premezclado, material de préstamo): una entrada en
  `TRANSPORTE_CATEGORIAS` + un campo de parámetro.
- El esquema «acarreo libre + excedente `6462`», que la biblioteca hoy no usa.
- Variantes de APU por cliente y un matcher que las prefiera.
- Precio por proyecto de un insumo cualquiera sin lista NP.
