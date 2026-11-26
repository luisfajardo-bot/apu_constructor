> Espejo automático — no editar aquí. Fuente: `docs/superpowers/specs/2026-11-25-contractual-sin-aiu-design.md`

# El contractual es el SIN AIU (ruta IDU, de aquí en adelante)

**Fecha:** 2026-11-25 · **Rama:** `feat/contractual-sin-aiu` · **Estado:** diseño aprobado, sin plan
**Reemplaza**, para las corridas nuevas, la §7 de `2026-09-11-ruta-idu-formulario-1-design.md`.

## Por qué

El costo interno de un APU es **costo directo**: no lleva A.I.U. Hasta hoy, en la ruta
IDU, `precio_contractual` era el valor unitario **con** AIU (columna «VALOR UNITARIO
(INCLUYE A.I.U)» del Formulario 1). Por eso «contractual − costo» traía metido el AIU
(~28 %), y el margen, los totales, el resumen por capítulo, el cuadro, el umbral de
«igualar costo» y el chat comparaban dos bases distintas.

**Decisión del usuario (2026-11-25):** el AIU desaparece de todo lo que se guarda, se
muestra y se compara. El contractual es el valor **básico sin AIU**. La columna con AIU
solo se lee para verificar el archivo contra los totales del Excel, y no se guarda.

## Alcance

**Solo las corridas nuevas.** Nada de lo ya corrido se toca: ni corridas activas, ni
congeladas, ni costos puestos a mano, ni su presentación. No hay migración.

## Lectura (`dominio/presupuesto.py`)

- `precio_contractual` = columna «VALOR UNITARIO BÁSICO (SIN A.I.U)». Es el único valor
  unitario que entra a `LicitacionItem`, a `plan_json` y a `item_json`.
- `precio_contractual_sin_aiu` = el mismo valor. Se mantiene el campo para que las
  corridas viejas sigan leyéndose igual, pero en una corrida nueva no aporta nada distinto.
- **No hay campo con AIU.** El valor «INCLUYE A.I.U» se lee fila por fila **solo** para
  verificar contra el Excel, y se descarta.
- Las dos columnas se siguen buscando **por su encabezado**, no por letra (J/K), y las dos
  siguen siendo obligatorias: sin la de AIU no hay cómo verificar el archivo.
- `PARSER_VERSION` pasa a `"idu-f1/2"` y queda en `corrida.origen_json`. Así se distingue
  una corrida nueva de una vieja sin migrar nada.

**Por qué no «leer con AIU y quitarle el AIU»:** el AIU no es un porcentaje fijo. En el
archivo de referencia, la proporción con/sin varía entre 1,2781 y 1,2797 según la
actividad, y dividir por un factor único corre cada fila unos pesos. El básico ya viene
escrito en el formulario: leerlo es exacto.

## Verificación contra el Excel (previsualización)

El «VALOR TOTAL» y los subtotales del Formulario 1 son cantidad × valor con AIU. Para
comprobar que el archivo se leyó bien, la conciliación compara contra esa columna:

- `total_fila_no_concilia`: el «VALOR TOTAL» de la fila contra cantidad × «incluye AIU».
- `subtotal_no_concilia` / `subtotales_ok`: los subtotales del Excel contra la suma de
  cantidad × «incluye AIU». La suma se calcula y se compara en el momento, y no se guarda.

**Qué se guarda de la conciliación** en `origen_json`: el contractual **sin AIU** total
(`contractual`), `subtotales_ok` y la `diferencia` en pesos si no concilia. Ningún total con
AIU. La previsualización muestra «Contractual (sin AIU) $X» y «Verificación contra el
Excel: OK».

- `sin_contractual` pasa a exigir el valor **básico** > 0, que es el que manda. Un valor con
  AIU ilegible sale por la conciliación de fila.
- `total_no_concilia` (capítulos contra actividades) es una suma interna y se hace con el
  básico.

## Lo que sigue solo

El margen, los totales (`_totales`), `resumen_por_capitulo`, el cuadro (`report.py`,
`report_categorizado.py`), el umbral y el botón «Igualar costo al contractual» y el chat
leen `precio_contractual` / `contractual_total`. Con el cambio de lectura pasan a usar el
valor sin AIU sin tocar el motor de costos.

## Presentación (web y cuadro Excel)

- **Corrida nueva:** una sola columna de contractual, la sin AIU, rotulada «Contractual
  (sin AIU)». No sale ninguna columna con AIU, ni la columna aparte «sin AIU» (sería igual
  a la principal).
- **Corrida vieja:** como hoy.
- **Regla, por datos:** la columna aparte «sin AIU» solo se muestra si algún ítem tiene
  `precio_contractual_sin_aiu` distinto de `precio_contractual` (es decir, una corrida
  vieja de la ruta IDU). La web y el cuadro deciden lo mismo sin leer `origen_json`.

## Chat de consulta

- El prompt (`consulta/v2`) deja de decir «el contractual del IDU lleva AIU». Ahora dice
  que el contractual es comparable con el costo directo, salvo cuando la cifra trae la
  nota «(con AIU)».
- `servicio/consulta.py` agrega **«(con AIU)»** a `contractual`, `diferencia` y `margen`
  de una corrida o capítulo **viejo**. «Viejo» = ruta IDU con `parser_version`
  `idu-f1/1`, leído de `vista_corrida(...)["origen"]`. Así nadie compara un contractual
  con AIU contra el costo directo sin darse cuenta.

## Riesgos

- **Mezcla de bases en un mismo proyecto:** puede haber una corrida vieja (con AIU) y una
  nueva (sin AIU). La nota del chat y la columna aparte de las viejas lo dejan claro. No se
  suman entre corridas.
- **Corridas creadas a medias:** el plan de una corrida que se está armando en el momento
  del deploy ya se leyó con el lector viejo, así que queda con AIU, igual que cualquier
  corrida vieja. Es consistente con el alcance (no se toca lo ya corrido).

## Pruebas

- **Lector:** con el formulario de ejemplo, `precio_contractual` = básico, ningún campo
  trae el valor con AIU, la verificación contra el Excel sigue en OK, y `sin_contractual`
  salta con el básico vacío.
- **Verificación:** un «VALOR TOTAL» de fila alterado sigue disparando
  `total_fila_no_concilia`, y un subtotal alterado sigue disparando `subtotal_no_concilia`.
- **`origen_json`:** no trae ningún total con AIU, y `privacy` lo sigue tratando como dinero.
- **Corrida vieja intacta:** su vista y su cuadro dan **exactamente** lo de antes.
- **Presentación:** una corrida nueva no muestra la columna aparte «sin AIU»; una vieja sí.
- **Chat:** el marcador de una corrida `idu-f1/1` lleva «(con AIU)»; el de una nueva, no.
- **Web:** la previsualización muestra el contractual sin AIU y la verificación, y ninguna
  cifra con AIU.
