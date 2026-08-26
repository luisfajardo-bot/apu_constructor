> Espejo automático — no editar aquí. Fuente: `docs/superpowers/specs/2026-08-26-distancias-transporte-proyecto-design.md`

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

## Cómo entra hoy la distancia

Datos reales de `data/apus.db` (1182 APUs, 5213 componentes):

| insumo | unidad | usos | qué es el rendimiento |
|---|---|---|---|
| `7462` TRANSPORTE DE PETREOS | M3-KM | 31 | m³ esponjados × km |
| `INT2` TRANSPORTE DE GRANULARES | M3-KM | 22 | m³ esponjados × km |
| `6878` TRANSPORTE DE BASES ASFALTICAS | M3-KM | 9 | m³ esponjados × km |
| `INT1` TRANSPORTE DE PETREOS | M3-KM | 2 | m³ esponjados × km |
| `3017` / `3017 N` escombros, **acarreo libre 21 km incluido** | M3 | 51 | volumen esponjado (no distancia) |
| `4613 N` escombros, **acarreo libre 28 km incluido** | M3 | 13 | volumen esponjado (no distancia) |
| `6462` escombros «a distancia mayor del acarreo libre» | M3-KM | 1 | km excedentes × volumen |
| `7231` DERECHOS DE BOTADERO | M3 | 9 | volumen esponjado |
| `INT3` PEAJE | GLB | 31 | 1,0 — lo que varía es el **precio** |

Los rendimientos M3-KM son heterogéneos (26,25 · 29,61 · 27,3 · 35 · 8,4 · 0,28), es decir
**la biblioteca no se armó toda a la misma distancia**. Un reescalado proporcional ciego
subcostearía las filas armadas a otra distancia: 8,4 (≈ 8 km) escalado a 32 km daría 10,75
en vez de 33,6, un subcosteo de 3×. De ahí la clasificación previa.

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
4. **Mezclas y granulares** se ajustan por rendimiento M3-KM: `rend = volumen × km`.
5. **Botadero:** insumo base por tramo (`3017` 21 km / `4613` 28 km, elegido explícitamente
   por el proyecto) + `6462` con los km excedentes. Derechos (`7231`) no escalan.
6. **Peaje:** sí/no + valor ya prorrateado por unidad. Si es «no», el componente se
   **quita** de la composición del proyecto — no queda en $0, que la regla de negocio
   prohíbe.
7. **Clasificación previa** de las 64 filas M3-KM con default 25 km y revisión fila por
   fila; sin clasificar no se reescala y se **alerta**.
8. **Los ajustes manuales ganan sobre la regla:** son la excepción explícita del ingeniero.

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
sub-APUs. No hay un segundo camino que haya que mantener en sincronía.

## Modelo de datos

### 1. `config.py` — vocabulario cerrado de insumos de transporte

Patrón de la casa para vocabularios cerrados (`PUBLIC_PRICE_SOURCES`, `LISTA_PRINCIPAL_ID`,
grupos de APU). No es una tabla: son 9 códigos y agregar uno es una línea de código.

```python
# categoria: botadero | mezclas | granulares | peaje
# rol:       km (escala con la distancia) | base (acarreo libre incluido) |
#            excedente | derechos | peaje
TRANSPORTE_INSUMOS = {
    "7462": ("granulares", "km",        None),
    "INT1": ("granulares", "km",        None),
    "INT2": ("granulares", "km",        None),
    "6878": ("mezclas",    "km",        None),
    "3017": ("botadero",   "base",      21),
    "4613": ("botadero",   "base",      28),
    "6462": ("botadero",   "excedente", None),
    "7231": ("botadero",   "derechos",  None),
    "INT3": ("peaje",      "peaje",     None),
}
BOTADERO_EXCEDENTE = "6462"
KM_BASE_DEFECTO = 25.0        # supuesto de la pantalla de clasificación
```

El sufijo `" N"` de los nocturnos se resuelve quitándolo antes de buscar en el dict
(`"3017 N"` → `"3017"`), igual que ya hace el importador tras el fix `3b9ae18`.

### 2. `componente_transporte` — el volumen de cada fila M3-KM (`apus.db`)

```sql
CREATE TABLE IF NOT EXISTS componente_transporte (
  apu_codigo      TEXT NOT NULL,
  shift           TEXT NOT NULL,
  insumo_codigo   TEXT NOT NULL,
  volumen         REAL NOT NULL,   -- m3 esponjados por unidad de APU
  km_base         REAL,            -- distancia asumida al clasificar (trazabilidad)
  actualizado_en  TEXT NOT NULL,
  actualizado_por TEXT,
  PRIMARY KEY (apu_codigo, shift, insumo_codigo)
);
```

Tabla aparte y **no** una columna en `apu_componentes`, por dos razones: `ApuComponent` lo
escriben seed, autoría, duplicar-APU, plantillas e importadores (agregar un campo toca los
seis), y `insert_components` reinserta filas con `seq` nuevo en cada semillado.

`volumen = rendimiento_actual / km_base`. Solo aplica a las filas con rol `km` (64 filas
hoy). Las de rol `base` y `derechos` no la necesitan: su rendimiento **ya es** el volumen
esponjado.

### 3. `proyecto_parametros` — las distancias del proyecto (`corridas.db`)

```sql
CREATE TABLE IF NOT EXISTS proyecto_parametros (
  carpeta_id           INTEGER PRIMARY KEY REFERENCES carpeta(id) ON DELETE CASCADE,
  km_botadero          REAL,
  botadero_base_codigo TEXT,     -- 3017 | 4613 | NULL = el que traiga el APU
  km_mezclas           REAL,
  km_granulares        REAL,
  peaje_aplica         INTEGER,  -- NULL = no definido, 0 = no hay, 1 = si
  peaje_valor          REAL,
  actualizado_en       TEXT NOT NULL,
  actualizado_por      TEXT
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

`insumo_nombre` se guarda además del código porque el cruce contra el catálogo desambigua
por **código + nombre** (fix `6cb7c29`): un código repetido con otra descripción no debe
resolverse al insumo equivocado. `tipo` y `ref_shift` existen para que un ajuste pueda meter
un sub-APU sin rediseñar la tabla.

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

Módulo puro: recibe `list[ApuComponent]` + parámetros + ajustes y devuelve
`list[ApuComponent]`. No abre bases y (salvo el peaje, ver abajo) no ve dinero.

```
aplicar(componentes, apu_codigo, shift, params, ajustes, volumenes) -> componentes
```

### Capa 1 — regla de transporte

| categoría / rol | regla |
|---|---|
| `granulares` rol `km` | `rend = volumen × km_granulares` |
| `mezclas` rol `km` | `rend = volumen × km_mezclas` |
| `botadero` rol `base` | no escala. Si `botadero_base_codigo` está definido y es distinto, se **reemplaza** el insumo base conservando el rendimiento (el volumen esponjado no cambia con el tramo) |
| `botadero` rol `excedente` (`6462`) | `rend = volumen_base × max(0, km_botadero − km_libre)`. Si la composición no lo tiene, **se agrega**; si el resultado es ≤ 0 no se agrega, y si venía en la composición se quita |
| `botadero` rol `derechos` (`7231`) | no escala |
| `peaje` (`INT3`) | `peaje_aplica = 0` → **se quita el componente**; `= 1` → el precio lo pone `peaje_valor` |
| rol `km` **sin `volumen` clasificado** | no se toca + alerta (ver Alertas) |
| parámetro en `NULL` | esa categoría no se toca |

`volumen_base` y `km_libre` del excedente salen del componente base presente en el APU (su
rendimiento y su tramo en `TRANSPORTE_INSUMOS`); si el proyecto fijó
`botadero_base_codigo`, manda el tramo de ese código. Si el APU no tiene componente base de
botadero, no se agrega excedente (no hay volumen del cual derivarlo) y se alerta.

Los rendimientos calculados se redondean a 6 decimales, igual que `privacy` al serializar.
El redondeo monetario sigue siendo el de `nucleo/redondeo.py`, intacto.

### Capa 2 — ajustes del proyecto

Se aplican **después** de la regla, en orden `quitar` → `reemplazar` → `rendimiento` →
`agregar`, para que un ajuste pueda pisar lo que la regla puso (incluido el `6462`).

### Enganche

- `PricingEngine(alm, lista_id=None, contexto=None)`, donde `contexto` trae `params`,
  `ajustes` y `volumenes` ya resueltos (una sola lectura por request, igual que la precarga
  en lote de `precargar`). `contexto=None` → comportamiento idéntico al de hoy.
- `components(codigo, shift)` aplica `transporte.aplicar(...)` sobre lo que lee de la
  biblioteca, **antes** de cachear en `_comp_cache`. Así el costeo, el memo de sub-APUs y
  `precargar` ven la misma composición efectiva, sin caminos divergentes.
- El **peaje toca precio**, así que su override va en `cost_component` (el único módulo que
  ve dinero): si el insumo es el del rol `peaje` y `params.peaje_valor` está definido,
  `precio = peaje_valor` y `fuente_precio = "peaje del proyecto"`.
- `corridas._costear_row`, `congelar` y `pipeline` construyen el contexto desde
  `meta.carpeta_id` (subiendo a la raíz). Corrida sin carpeta → contexto vacío.

## Servicio — `apu_tool/servicio/transporte.py`

| endpoint | rol | qué hace |
|---|---|---|
| `GET /api/carpetas/{id}/transporte` | consulta | parámetros vigentes + tabla de impacto + pendientes de clasificar |
| `PUT /api/carpetas/{id}/transporte` | editor | guarda los parámetros. Auditoría `proyecto.transporte` |
| `GET /api/transporte/componentes` | consulta | las 64 filas M3-KM con su volumen y su km base |
| `PUT /api/transporte/componentes` | editor | batch de volúmenes. Auditoría `transporte.clasificar` |
| `GET /api/carpetas/{id}/ajustes` | consulta | ajustes del proyecto |
| `POST /api/carpetas/{id}/ajustes` | editor | crea un ajuste. Auditoría `proyecto.ajuste.crear` |
| `DELETE /api/carpetas/{id}/ajustes/{aid}` | editor | borra un ajuste. Auditoría `proyecto.ajuste.borrar` |

Todo cuelga del único `APIRouter` de `rutas.py`, que delega en el módulo de servicio
(convención del repo). Los endpoints de escritura validan: carpeta de nivel 1, km ≥ 0,
`peaje_valor > 0` cuando `peaje_aplica = 1` (regla «nada en $0»), `rendimiento > 0` en los
ajustes, e insumo existente en el catálogo al agregar o reemplazar.

**Tabla de impacto** (`GET .../transporte`): recorre los APUs asignados en las corridas del
proyecto, aplica la regla en seco y devuelve por componente `apu_codigo`, insumo, unidad,
`rendimiento_actual`, `volumen`, `rendimiento_nuevo`, `origen` y `sin_clasificar`. Es
previsualización pura: no escribe nada.

## Web

**A. «Distancias del proyecto»** — botón en la carpeta de nivel 1 (`pages/MisCorridas.tsx`),
panel denso sin cards: km botadero + tramo base (desplegable `3017` 21 km / `4613` 28 km /
«el del APU»), km mezclas, km granulares, peaje (checkbox + valor). Debajo, la tabla de
impacto con el rendimiento nuevo por componente y el contador de no clasificados con enlace
a la pantalla B. **Guardar escribe solo los parámetros**: las corridas activas del proyecto
se recostean en su siguiente lectura. Ese es el «batch»: un guardado, no N escrituras.

**B. «Clasificación de transporte»** — las 64 filas M3-KM de la biblioteca: APU, insumo,
rendimiento actual, km base editable (default 25), volumen derivado, marca en las filas con
volumen atípico, y acción en bloque. Es una vez, no por proyecto.

**C. Composición del ítem de corrida** (`pages/Corrida.tsx`) — hoy es de solo lectura; pasa
a editable con **alcance «este proyecto» por defecto**: cambiar rendimiento, agregar, quitar
y reemplazar insumo. Cada componente muestra su origen: `biblioteca` · `distancia` ·
`ajuste`. Editar la biblioteca sigue siendo la acción aparte de la pantalla de APUs — el
default es deliberado, porque el error caro es contaminar la biblioteca creyendo que se
ajusta una obra.

Todo en solo lectura si la corrida está congelada, igual que el resto de la edición.

## Salida

- Encabezado de la corrida: `botadero 34 km (base 4613) · mezclas 28 · granulares 32 ·
  peaje $12.400`.
- `dominio/report.py` y `report_categorizado.py`: hoja **DESVIACIONES DEL PROYECTO** con los
  parámetros y la lista de ajustes (APU, acción, insumo, rendimiento, nota). Un cuadro
  entregado sin esa hoja no es defendible en una aclaración.

## Alertas — `dominio/alertas.py`

Se agrega un motivo: componente de rol `km` **sin volumen clasificado** en un proyecto con
distancias definidas → `"7462 TRANSPORTE DE PETREOS: distancia del proyecto no aplicada"`.
Igual para un botadero con `km_botadero` definido y sin componente base del cual derivar el
excedente. Criterio del repo: preferimos alertar a costear con una distancia equivocada en
silencio.

## Pruebas

1. **Regresión:** sin `proyecto_parametros` ni `proyecto_ajuste`, el costeo de una corrida es
   idéntico al de hoy (mismos costos y misma composición, componente por componente).
2. `transporte.aplicar`: reescalado de granulares y mezclas; excedente agregado y calculado;
   excedente no agregado cuando `km ≤ km_libre`; reemplazo de tramo base; peaje quitado (y
   verificar que **no** deja un $0); parámetro en `NULL` no toca su categoría.
3. Componente de rol `km` sin volumen: no se reescala y aparece la alerta.
4. Peaje con `peaje_aplica = 1`: el precio usado es `peaje_valor` y la fuente lo dice.
5. Ajustes: las cuatro acciones; un ajuste pisa a la regla; `UNIQUE` impide duplicados.
6. Herencia: corrida en subcarpeta usa los parámetros de la raíz; corrida sin carpeta no
   cambia; corrida congelada conserva su snapshot aunque cambien los parámetros.
7. **Aislamiento entre proyectos:** dos corridas en proyectos distintos sobre el **mismo**
   APU dan costos distintos, y la composición en `apus.db` no cambió.
8. Privacidad: un payload con `peaje_valor` lanza `PrivacyViolation`.
9. Servicio: roles (consulta no escribe), validaciones (nivel 1, km ≥ 0, peaje > 0,
   rendimiento > 0, insumo inexistente) y auditoría registrada.
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

## Fuera de alcance (agregables después sin rediseñar)

- Excepción por línea de corrida (dos ítems con el mismo APU y distinto ajuste).
- Histórico de distancias por proyecto (hoy queda en auditoría, no en una tabla propia).
- Categorías nuevas de acarreo (concreto premezclado, material de préstamo): una línea en
  `TRANSPORTE_INSUMOS` + un campo de parámetro.
- Variantes de APU por cliente y un matcher que las prefiera.
- Precio por proyecto de un insumo cualquiera sin lista NP.
