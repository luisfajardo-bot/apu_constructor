> Espejo automático — no editar aquí. Fuente: `docs/superpowers/specs/2026-08-04-piso-match-fallback-design.md`

# Diseño — piso de similaridad para el fallback determinístico

> Fecha: 2026-08-04
> Estado: aprobado en brainstorming
> Rama de trabajo: `fix/piso-match-fallback`

## El problema

Caso real de producción. Una fila de licitación:

```
Descripción: Localización y replanteo (Incluye material…)   Und: UN   Cantidad: 423
Ítem: 3007        APU: 4987        Estado: REVISAR
Unit. Costo: $1.861.500            Total Costo: $787.414.500
Margen: $-787.414.500              %: 0.0%

[deterministico] Mejor similaridad de nombre (25%). (IA no disponible: TypeError)

CANDIDATOS
  4987  PEDESTAL PARA EQUIPO DE CONTROL EN CONCRETO DE 3000 PSI    25%
  6192  PISOS EN METALDECK 2" CALIBRE 18 PARA PUENTES PEATONALES   22%
  4802  BLOQUEO Y TRANSPLANTE DE ARBOLES 1 - 5MT                   20%
  4860  DEMARCACIÓN PICTOGRAMA TRIÁNGULOS CEDA EL PASO             20%
  3716  CILINDRO POZO INSPECCION PREFABRICADO D=1.2M               20%
```

Un replanteo quedó costeado como un **pedestal de concreto**. El APU correcto
(`3007 REPLANTEO GENERAL`) cuesta **926 por M2**; la fila salió en **$1.861.500 por UN**.
Con 423 unidades: **$787.414.500** en vez de **$391.698** — **2010 veces**.

La causa: `ai_assist.py::_choose_deterministic` devolvía `candidatos[0]`
**sin mirar ningún umbral**:

```python
def _choose_deterministic(self, candidatos):
    best = candidatos[0]
    return AIDecision(apu_codigo=best.apu_codigo, ...)
```

Con candidatos en 25%, 22%, 20%, 20%, 20%, el ganador no lo decide el sentido: lo decide
el ruido. Un pedestal le ganó a todo por tres centésimas. Y de ahí salió un precio de seis
cifras con pinta de autoritativo.

Esto también explica el síntoma que originó la investigación —«la misma actividad en
varios tramos da precios distintos»—: no era la cantidad ni el sufijo «Tramo N», era que
cada fila caía en un APU distinto de ese montón apiñado en 20-25%.

## Decisiones tomadas (brainstorming)

**Umbral: `config.MATCH_REVIEW` (0.55).** No se inventa un número nuevo: ese token ya
existe y ya significa «por debajo de esto hay que revisar», y el matcher ya lo usa para
decidir REVIEW vs NEW. Se descartó un piso más bajo (0.45), que habría dejado la banda
0.45–0.55 asignando sola y habría requerido justificar un número sin significado en el
resto del código.

**Solo el fallback, no la IA.** El piso va en `_choose_deterministic`, no en
`_choose_with_ai`. La IA recibe la composición completa de cada candidato (insumos,
rendimientos, unidad, turno), así que puede elegir con criterio uno cuyo *nombre* puntúe
bajo — filtrarla por similaridad de nombre la reduciría a un matcher fuzzy con más pasos.
El piso sí aplica cuando la IA **falla**, porque ese camino cae a `_choose_deterministic`.

## Impacto medido, antes de decidir

Sobre `ejemplos/plantilla_licitacion-13-3.xlsx`, **1166 ítems reales**:

| | |
|---|---|
| ACEPTA (score ≥ 0.88) | 1119 · 96.0% |
| se siguen armando solos | **1144 · 98.1%** |
| quedan para elegir a mano | **22 · 1.9%** |
| distribución | min 0.263 · p25 1.000 · mediana 1.000 · máx 1.000 |

La distribución es **bimodal**: los matches son o perfectos o basura, casi no hay nada en
el medio. Por eso el piso cuesta 1.9% y limpia exactamente el problema.

## Diseño

```python
if best.score < config.MATCH_REVIEW:
    return AIDecision(
        apu_codigo=None, confianza=best.score,
        justificacion=(f"Mejor coincidencia {best.score:.0%}, por debajo del mínimo de "
                       f"{config.MATCH_REVIEW:.0%} para asignar un APU. "
                       f"Elige uno de los candidatos o ármalo a mano."),
        fuente="deterministico",
    )
```

Con `apu_codigo=None`, `assemble_item` (línea 98) sigue su camino ya existente: intenta la
composición generativa con IA y, si no hay, devuelve el `AssembledApu` manual en $0 con
status NEW. **No hace falta código nuevo para el estado resultante.**

### Por qué no deja al usuario sin salida

Verificado en `corridas.py:94-103`: los candidatos se calculan con
`assembler.matcher.match(item)` y se guardan en la fila **independientemente** de lo que
devuelva `assemble_item`. La lista con «Elegir» sigue apareciendo igual. El ítem no pierde
información: pierde una decisión que no se podía tomar sola.

### La alerta sale sola

`alertas.py:38-39` ya tiene `if not motivos and a.costo_unitario <= 0`, así que el ítem en
$0 queda alertado sin tocar nada. Cumple la regla «nada en $0 en silencio» — y la cumple en
el sentido correcto: **mejor un $0 con alerta que un número inventado**.

## El costo, dicho explícito

**El piso también rechaza matches correctos.** En el catálogo local, `3007 REPLANTEO
GENERAL` es el APU correcto para «Localización y replanteo» y puntúa **0.3159**: con el
piso queda sin armar y hay que elegirlo a mano.

Eso no es un defecto del piso, es la razón por la que el **arreglo #1 importa más**: la
lista trae el código `3007` en su columna, y `read_licitacion` no lo usa
(`codigo_sugerido` solo lo llena `presupuesto.py`). Con ese arreglo la fila se armaría
directo por código, en AUTO con confianza 1.0, y el piso nunca entraría en juego. Los dos
son complementarios: el piso frena la basura, el código acierta sin adivinar.

## Qué NO cambia

- El umbral `MATCH_ACCEPT` (0.88) y el camino AUTO: intactos.
- `_choose_with_ai`: intacto.
- Los candidatos que se muestran y se pueden elegir: intactos.
- Corridas **congeladas**: usan snapshot por ítem, no se recostean.
- Frontend: ni una línea. El estado NEW y el APU vacío ya se renderizan.

## Consecuencia en datos existentes

Las corridas **activas** se recostean al abrirse. Un ítem que hoy muestra un APU asignado
con menos de 55% de parecido va a pasar a $0 con alerta. Es el objetivo, pero es un cambio
visible sobre datos ya vistos: hay que avisarlo antes de desplegar.

## Pruebas

Tres tests en `tests/test_assemble.py`, dos en rojo primero:

1. `test_fallback_no_asigna_apu_por_debajo_del_piso` — 0.2303 → `apu_codigo is None`,
   costo 0, status NEW, la explicación dice «23%» y «55%», y el candidato sigue existiendo.
2. `test_fallback_sigue_asignando_arriba_del_piso` — 0.7022 → sigue armando 3009 como
   REVISAR. **Ya pasaba antes del cambio**: es guard anti-regresión, no una mejora.
3. `test_item_sin_apu_queda_con_alerta_de_costeo` — el ítem en $0 sale alertado.

Verificado: **621 passed, 15 skipped** en la suite completa (eran 618 + 3 nuevos), cero
regresiones, diff de 27 líneas en un solo archivo.
