> Espejo automático — no editar aquí. Fuente: `docs/superpowers/specs/2026-11-25-contractual-sin-aiu-design.md`

# El contractual que manda es el SIN AIU (ruta IDU, de aquí en adelante)

**Fecha:** 2026-11-25 · **Rama:** `feat/contractual-sin-aiu` · **Estado:** diseño aprobado, sin plan
**Reemplaza**, para las corridas nuevas, la §7 de `2026-09-11-ruta-idu-formulario-1-design.md`.

## Por qué

El costo interno de un APU es **costo directo**: no lleva A.I.U. Hasta hoy, en la ruta
IDU, `precio_contractual` era el valor unitario **con** AIU (columna «VALOR UNITARIO
(INCLUYE A.I.U)» del Formulario 1). Por eso «contractual − costo» traía metido el AIU
(~28 %), y el margen, los totales, el resumen por capítulo, el umbral de «igualar costo» y
el chat de consulta comparaban dos bases distintas.

Decisión del usuario (2026-11-25): lo que importa es el contractual **sin** AIU. Se leen
las dos columnas, pero manda el básico.

## Qué cambia

**Solo las corridas nuevas.** Nada de lo ya corrido se toca: ni corridas activas, ni
congeladas, ni costos puestos a mano. No hay migración.

### Lectura (`dominio/presupuesto.py`)

| Campo de `LicitacionItem` | Antes (`idu-f1/1`) | Ahora (`idu-f1/2`) |
|---|---|---|
| `precio_contractual` (el que manda) | col. «incluye AIU» | col. «básico (sin AIU)» |
| `precio_contractual_sin_aiu` | col. «básico (sin AIU)» | col. «básico (sin AIU)» (igual al principal) |
| `precio_contractual_con_aiu` (**nuevo**) | — (0 en corridas viejas) | col. «incluye AIU» |

- Las dos columnas se siguen leyendo **por su encabezado**, no por letra (J/K). Las dos
  siguen siendo obligatorias.
- `PARSER_VERSION` pasa a `"idu-f1/2"`. Ya se guarda en `corrida.origen_json`, así que
  sirve para distinguir una corrida nueva de una vieja sin migrar nada.
- `precio_contractual_con_aiu` es dinero: va a `privacy._FORBIDDEN_KEYS` y no viaja en
  `licitacion_item_to_dict`.
- `item_json` se rehidrata con `LicitacionItem(**d)`: las filas viejas, que no traen el
  campo nuevo, toman el default `0.0` sin explotar.

**Por qué no «leer con AIU y quitarle el AIU»:** el AIU no es un porcentaje fijo. En el
archivo de referencia, la proporción con/sin varía entre 1,2781 y 1,2797 según la
actividad. Dividir por un factor único corre cada fila unos pesos. El básico ya viene
escrito en el formulario: leerlo es exacto.

### Validación y conciliación

- **La conciliación contra el Excel sigue con el valor CON AIU.** El «VALOR TOTAL» y los
  subtotales del Formulario 1 son cantidad × valor con AIU. Eso aplica a
  `total_fila_no_concilia`, `subtotal_no_concilia` y `conciliacion()["contractual_con_aiu"]`.
- **`sin_contractual`** pasa a exigir el valor **básico** > 0, que es el que manda. Un
  valor con AIU ilegible sigue saliendo por la conciliación de fila.
- `total_no_concilia` (capítulos contra actividades) es una suma interna: da igual en
  qué base se haga, y se queda con el principal.

### Lo que sigue solo

Margen, totales (`_totales`), `resumen_por_capitulo`, cuadro (`report.py`,
`report_categorizado.py`), umbral de «igualar costo» (`contractual_total`), «Igualar costo
al contractual» y el chat leen `precio_contractual` / `contractual_total`. **No se tocan:**
con el cambio de lectura pasan a usar el valor sin AIU solos.

### Columna de referencia (web y cuadro)

Se muestra la **otra** base como referencia:

- **Corrida nueva** (algún ítem con `precio_contractual_con_aiu > 0`): principal «sin AIU»,
  referencia **«con AIU»**.
- **Corrida vieja:** como hoy. Principal «con AIU», referencia «sin AIU».

La regla se mira por los datos (si hay algún `con_aiu > 0`), no por la versión del
lector, para que el cuadro y la web decidan lo mismo sin leer `origen_json`.
`resumen_por_capitulo` suma también `contractual_con_aiu` por capítulo, y sigue siendo la
**única** función que suma por capítulo.

**Previsualización IDU:** muestra los dos totales. El principal queda rotulado «sin AIU»
y la conciliación «con AIU».

### Chat de consulta

- El prompt (`consulta/v2`) deja de decir «el contractual del IDU lleva AIU». Dice que
  el contractual es comparable con el costo directo, salvo cuando la cifra trae la nota
  «(con AIU)».
- `servicio/consulta.py` agrega **«(con AIU)»** a `contractual`, `diferencia` y `margen`
  de una corrida o capítulo **viejo**. «Viejo» = ruta IDU con `parser_version`
  `idu-f1/1`, leído de `vista_corrida(...)["origen"]`. Así nadie compara contractual con
  AIU contra costo sin darse cuenta.

## Riesgos

- **Mezcla de bases en una misma carpeta:** un proyecto puede tener una corrida vieja (con
  AIU) y una nueva (sin AIU). La columna de referencia y la nota del chat dicen en qué base
  está cada una. No se suman entre corridas, igual que en el chat.
- **Rollback:** el código anterior no conoce `precio_contractual_con_aiu`, y
  `LicitacionItem(**d)` explotaría con una corrida nueva. Si hay que revertir, se revierte
  también la escritura (o se tolera la clave extra). Queda anotado: no es un caso esperado.

## Pruebas

- **Lector:** con el formulario de ejemplo, `precio_contractual` = básico,
  `precio_contractual_con_aiu` = incluye AIU, y la conciliación sigue en OK.
  `sin_contractual` salta con el básico vacío.
- **Corrida vieja intacta:** un `item_json` sin la clave nueva se rehidrata con `0.0`, y
  su vista y su cuadro dan **exactamente** lo de antes.
- **Resumen por capítulo y cuadro:** la columna de referencia es «con AIU» en una corrida
  nueva y «sin AIU» en una vieja.
- **Chat:** el marcador de una corrida `idu-f1/1` lleva «(con AIU)»; el de una nueva, no.
- **Privacidad:** `precio_contractual_con_aiu` está en `_FORBIDDEN_KEYS`.
- **Web:** la previa y el resumen muestran la referencia correcta en cada caso.
