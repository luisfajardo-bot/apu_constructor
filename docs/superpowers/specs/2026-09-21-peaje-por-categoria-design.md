# Peaje por categoría de acarreo

**Fecha:** 2026-09-21
**Estado:** aprobado por el usuario, listo para implementar

## El problema

Hoy un proyecto tiene **un** peaje: `proyecto_parametros.peaje_aplica` +
`peaje_valor`, que se aplican a toda fila `INT3 PEAJE` de cualquier APU de ese
proyecto. En la obra real el peaje no es uno: el viaje al botadero, el de mezclas
asfálticas y el de granulares salen por casetas distintas, y a veces una categoría
paga peaje y otra no. Con un solo valor hay que elegir cuál se cobra mal.

## Qué se construye

Una casilla marcable **y** un valor de peaje por cada categoría, al lado de su
distancia, en la pantalla de distancias del proyecto. Las tres son independientes:
granulares con peaje de $12.400, mezclas sin peaje y botadero con $8.000 es una
configuración válida.

## Decisiones tomadas

### 1. La categoría de una fila de peaje se deriva del acarreo del APU

La fila `INT3 PEAJE` no tiene categoría propia: la tienen los acarreos M3-KM. El
peaje de un APU toma la categoría de **sus** acarreos.

Medido sobre la biblioteca real: hay **31 filas de peaje en 31 APUs**, y **cada uno
tiene acarreos de una sola categoría** (22 granulares, 9 mezclas, 0 botadero). No
hay un solo caso ambiguo, así que la regla está bien definida sobre los datos de
hoy y no hace falta clasificar 31 filas más a mano.

**Descartado:** clasificar la fila de peaje a mano en la pantalla de clasificación
(explícito, pero son 31 filas más de trabajo antes de que el peaje funcione, y si
no se clasifican el peaje no se aplica).

### 2. Sin categoría determinable → como hoy, más alerta

| Caso | Qué pasa con la fila de peaje |
|---|---|
| 1 categoría · casilla marcada · valor > 0 | se costea con **ese** valor, fuente «peaje del proyecto» |
| 1 categoría · casilla desmarcada | **se quita la fila** (igual que hoy con `peaje_aplica=False`) |
| 1 categoría · marcada pero sin valor | camino normal del catálogo (igual que hoy) |
| acarreo sin clasificar | catálogo + alerta «peaje del proyecto no aplicado» |
| acarreos de 2+ categorías | igual que sin clasificar: catálogo + alerta |
| sin categoría · las **tres** categorías dicen que no hay peaje | **se quita la fila** |

La última fila apareció implementando, no diseñando: el APU cuyo *único* componente es
el peaje no tiene acarreo del que heredar categoría, así que sin esa regla un proyecto
sin peajes ya no podría vaciarlo — una regresión contra el peaje único de antes.
«Este proyecto no paga peajes» no depende de saber por qué caseta pasa el acarreo.

Y la alerta se emite solo si la fila de peaje **sobrevivió** a la regla: un peaje que el
proyecto excluyó no es un peaje «sin aplicar», y decir lo contrario tapaba la alerta del
$0 con un motivo falso (lo encontró un test existente, no una revisión).

Lo de "sin clasificar" no es un caso de borde teórico: **es el estado de producción
hoy** (0 acarreos clasificados). Que se comporte como antes de esta feature es lo
que garantiza que desplegar no mueva ningún número, y la alerta dice dónde falta
clasificar.

Los 2+ categorías reciben el mismo trato por consistencia, no por una regla de
desempate inventada: hoy no existe ninguno.

**Descartado:** quitar el peaje cuando no se sabe la categoría. En prod, hoy mismo,
desaparecería el peaje de los 31 APUs y cotizarían más baratos sin que nadie lo
pida — contra la regla de que un costo no se cae solo.

**Descartado:** un cuarto campo «peaje por defecto» para el caso sin clasificar.
Tapa el problema real (que falta clasificar) y agrega un campo que hay que explicar.

### 3. Se borran las dos columnas viejas

`peaje_aplica` y `peaje_valor` salen de `proyecto_parametros` en la migración del
boot. **Verificado antes de decidirlo:** la tabla tiene 0 filas en la base local y
en Postgres de producción todavía no existe (la crea el boot del deploy), así que no
hay dato que migrar. Dejarlas muertas sería una trampa para quien las lea después y
crea que siguen vivas.

## Forma

### Modelo — `nucleo/models.py`

`ParametrosProyecto` gana los mismos accesores por categoría que ya tienen los km,
para que no haya dos formas de preguntar lo mismo:

```python
params.km("granulares")            # ya existía
params.peaje_aplica("granulares")  # nuevo: True | False | None
params.peaje_valor("granulares")   # nuevo: float | None
```

Campos: `peaje_{botadero,mezclas,granulares}_{aplica,valor}` (6), en lugar de
`peaje_aplica` / `peaje_valor`.

`vacio` sigue siendo "nada definido" y ahora mira los 6 campos: si alguien cargó
solo el valor del peaje de mezclas, el contexto NO es vacío (mismo criterio que
hoy, donde `peaje_valor` cuenta — si no, el motor descartaría el contexto y
costearía con el catálogo sin avisar).

`AssembledApu` gana `peaje_sin_categoria: bool = False`, que viaja con el ítem igual
que `sin_distancia` / `en_subapus`: los consumidores de la alerta son varios (vista
de corrida, cuadro, totales) y solo uno tiene el motor a mano.

### Persistencia — `datos/carpetas_db.py`, `datos/pg/carpetas_pg.py`, `db/corridas.sql`, `db/pg/corridas.sql`

6 columnas nuevas, 2 borradas, con el patrón de migración al boot que el repo ya usa
(`PRAGMA table_info` + `ALTER TABLE ADD COLUMN` en SQLite;
`ADD COLUMN IF NOT EXISTS` / `DROP COLUMN IF EXISTS` en Postgres). Los dos backends
espejo, como siempre.

### Frontera de privacidad — `dominio/privacy.py`

Los 3 valores son dinero: `peaje_botadero_valor`, `peaje_mezclas_valor`,
`peaje_granulares_valor` entran a `_FORBIDDEN_KEYS`. Las 3 casillas (`*_aplica`) no:
son booleanos, estructura. `peaje_valor` se queda en la lista aunque el campo ya no
exista — la lista es de nombres prohibidos, y que un nombre muerto siga prohibido no
cuesta nada.

### La regla — `dominio/transporte.py`

Helper nuevo: dado un APU y sus componentes, las categorías de sus acarreos M3-KM
(la clasificación ya está en memoria: cero consultas nuevas).

`_aplicar_regla` decide sobre la fila de peaje con ese conjunto:
una sola categoría con `peaje_aplica(cat) is False` → se quita la fila; cualquier
otro caso → la fila pasa y el valor lo pone el motor.

**El módulo sigue sin ver dinero:** lee `peaje_aplica` (booleano), nunca
`peaje_valor`. Lo dice su docstring y no cambia.

### El motor — `dominio/pricing.py`

`_efectivos` ya recorre cada `(apu, turno)` para calcular los pendientes de
distancia; ahí mismo guarda la categoría del peaje de ese APU (o que no se pudo
determinar). `cost_component` recibe la clave del APU como **parámetro explícito**;
sus llamadores ya la tienen a mano. No se usa `_visitando[-1]`, que la tiene pero
por casualidad — apoyarse en eso es una trampa para el próximo cambio.

Con categoría y casilla marcada y valor > 0: `precio_unitario = ese valor`,
`fuente_precio = "peaje del proyecto"`. Sin eso: camino normal del catálogo.

### Alertas — `dominio/alertas.py`

Motivo nuevo cuando `peaje_sin_categoria`: «peaje del proyecto no aplicado (falta
clasificar el acarreo)». Se suma a los motivos existentes, no los reemplaza.

### El cuadro — `dominio/report.py`

La hoja DESVIACIONES DEL PROYECTO pasa de una fila de peaje a tres, una por
categoría, con su «sí / no / sin definir» y su valor.

### API y UI — `servicio/esquemas.py`, `web/src/pages/DistanciasProyecto.tsx`, `web/src/lib/tipos.ts`

`TransporteParamsIn` y `ParametrosTransporte` con los 6 campos. En la pantalla, al
lado de cada distancia: una casilla y, cuando está marcada, el campo del valor —
exactamente el patrón que la pantalla ya usa hoy para el peaje único, repetido tres
veces.

## Pruebas

- **Regla por categoría:** un proyecto con peaje solo en granulares costea el peaje
  del APU de granulares y no el del de mezclas.
- **Casilla desmarcada:** la fila de peaje desaparece de la composición efectiva de
  esa categoría, y sigue en la de las otras.
- **Sin clasificar:** el peaje se costea con el catálogo y el ítem alerta — el mismo
  número que antes de la feature (no regresión, que es lo que protege el deploy).
- **2+ categorías:** mismo trato que sin clasificar.
- **Privacidad:** los 3 valores disparan `PrivacyViolation`; las 3 casillas no.
- **Ida y vuelta en los dos backends:** guardar y leer los 6 campos (el contrato
  compartido de repos, que ya cubre carpetas).
- **UI:** marcar la casilla de mezclas y guardar manda `peaje_mezclas_aplica=true`
  con su valor, y no toca las otras dos.
- **Turno nocturno:** un APU `X N` con peaje toma la categoría de su propio acarreo
  nocturno. (La feature de distancias no tiene ningún test de nocturno hoy; este
  paga esa deuda en el punto donde importa.)

## Fuera de alcance

- Un peaje distinto por sentido (ida/vuelta) o por caseta: el dato de la obra es uno
  por categoría.
- Peaje por línea de corrida: la excepción por línea no existe para las distancias y
  tampoco se agrega acá.
- Clasificar la fila de peaje a mano (ver Decisión 1).
