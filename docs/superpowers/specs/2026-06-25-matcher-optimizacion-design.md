# Diseño — Optimización del matcher (etapa 2, sub-proyecto A)

> Fecha: 2026-06-25
> Estado: aprobado para implementación
> Contexto: el armado de una lista larga tarda ~1 s/ítem. El cuello de botella es
> el matcher determinístico. Esta es la pieza **prioritaria** de la etapa 2.

## Objetivo

Bajar drásticamente el tiempo de armado **sin cambiar las decisiones** del matcher:
para cada ítem, el **APU final elegido** y el **estado** (AUTO / REVISAR / NUEVO)
deben ser idénticos a los de hoy. Se acepta que la **cola** de la lista de
candidatos de baja puntuación pueda variar (candidatos de relleno).

## Diagnóstico (medido en el código actual)

1. **Doble match por ítem.** `apu_tool/servicio/corridas.py::construir_corrida_stream`
   llama `assembler.matcher.match(item)` (para los candidatos a mostrar) y luego
   `assembler.assemble_item(item)`, que **vuelve a correr** `self.matcher.match(item)`
   internamente. Mismo cómputo determinístico, dos veces.
2. **Escaneo del pool completo.** `Matcher.candidates()` puntúa la descripción del
   ítem contra **todos** los APUs del turno (599 DIURNO / 499 NOCTURNO) con
   `SequenceMatcher` O(L²) por par. Para ~200 ítems eso son ~120k comparaciones
   caras… ×2 por lo anterior.
3. **Recálculo de tokens.** `similarity()` recalcula los tokens del ítem y del APU
   en cada par, aunque el índice del Matcher ya los tiene precomputados.

## Global Constraints (cero regresiones — el usuario es estricto)

- **Barra de correctitud:** para **todo** ítem, mismo estado y mismo APU final que
  hoy (verificado con IA apagada = camino determinista). La cola de candidatos de
  baja puntuación puede diferir.
- No se toca el costeo (`pricing.py`) ni la persistencia.
- Sin dependencias nuevas (stdlib: `difflib`, `functools`).
- Invariante #1 intacto (el matcher no ve dinero; nada de `ai_assist` en `servicio/`).
- `python -m pytest tests/ -q` verde tras cada tarea.

## Diseño

### A.1 — Un solo match por ítem — `apu_tool/dominio/assemble.py`

- `Assembler.assemble_item(item, match_result: Optional[MatchResult] = None)`:
  si se le pasa `match_result`, lo usa; si es `None`, lo calcula con
  `self.matcher.match(item)` (comportamiento actual). Ningún otro llamador cambia
  (`assemble_all`, `reassemble_with_choice`, código directo por `codigo_sugerido`
  siguen igual; el armado por código no usa el matcher y se evalúa **antes**, así
  que `match_result` se ignora en ese caso).
- En `construir_corrida_stream`: calcular `result = assembler.matcher.match(item)`
  una vez, construir los candidatos desde `result`, y pasar
  `assembler.assemble_item(item, result)`. Resultado idéntico, ~2×.

> Nota: el comentario "Doble match intencional… no optimizar" se elimina/actualiza;
> la intención (mostrar candidatos + elegir APU) se preserva con **un** cómputo.

### A.2 — Índice invertido + ramificación y poda (branch-and-bound) — `apu_tool/dominio/matching.py`

> Nota: el bloqueo por tokens "puro" (puntuar toda la unión de postings) **no**
> aceleró lo suficiente — en obra civil los tokens frecuentes (CONCRETO, SUMINISTRO,
> EXCAVACIÓN…) están en cientos de APUs, así que la unión ≈ pool completo. El costo
> real es el `SequenceMatcher` O(L²). La solución es **branch-and-bound** sobre el
> jaccard (barato), calculando el `SequenceMatcher` caro solo donde aún pueda ganar.

- `Matcher.__init__` construye, además del `_by_shift` actual, un índice invertido
  `_postings_by_shift: dict[str, dict[str, list[int]]]` (token → posiciones en la
  lista del turno) y un índice/pool combinado para el *fallback* de turno.
- `Matcher.candidates(descripcion, shift, top_n=5)`:
  - `qtokens = _tokens(descripcion)`; vía el índice, cuenta tokens compartidos por
    APU candidato y calcula su **jaccard** = `|∩| / |∪|` (idéntico al de
    `similarity`, con sets precomputados — barato).
  - **Ramificación y poda:** ordena los candidatos por jaccard desc y recorre
    calculando `score = round(similarity(...), 4)` (función de score **sin cambios**),
    llevando el mejor. **Corta** en cuanto la cota superior `0.4 + 0.6·jaccard`
    (con `seq = 1`) cae por debajo del mejor actual (margen `1e-4` por el redondeo):
    ningún candidato restante (de menor jaccard) puede superarlo.
  - Si el mejor con tokens en común alcanza `MATCH_REVIEW (0.55)`, ese es el mejor
    global → devuelve `top_n` (orden score desc; empates por orden del pool, idéntico
    al escaneo). Si no, **escaneo completo exacto** del pool (caso novedoso, donde el
    mejor global podría ser un APU sin tokens comunes con alto `seq`).
  - Si el pool del turno está vacío, usa el índice/pool combinado (fallback actual).
- `Matcher.match()` no cambia su lógica de umbrales.

**Correctitud (exacta con IA apagada):**
- `score = 0.4·seq + 0.6·jaccard` y `seq ≤ 1` ⟹ la cota `0.4 + 0.6·jaccard` es un
  techo real del score. La poda solo descarta candidatos cuyo techo ya no alcanza al
  mejor, así que el **mejor global** (y su score) se encuentra exacto; el desempate
  se replica ordenando por `(−score, idx_pool)`.
- Un APU sin tokens compartidos tiene `jaccard = 0` → `score ≤ 0.4 < 0.55`. Si el
  mejor global `≥ 0.55`, tiene tokens comunes y la fase rápida lo encuentra (estado y
  `elegido` AUTO idénticos). Si `< 0.55`, el escaneo completo de respaldo preserva la
  base sugerida exacta (`candidatos[0]`, que usa el fallback determinista de
  `assemble_item`).
- Lo único que flexiona es la **cola** (posiciones 2..top_n) en ítems con match
  fuerte; no afecta la decisión (el armado con IA apagada usa solo `candidatos[0]`).

**Medido (catálogo real, 1098 APUs, 665 consultas):** 0 diferencias de decisión
contra el escaneo completo; ~427× más rápido en ítems que matchean (0.57 ms/consulta
vs 245 ms). Los ítems novedosos caen al escaneo completo (~245 ms) — minoría en una
licitación real; optimizarlos queda como mejora futura.

### A.3 — Reusar tokens precomputados (menor)

Opcional y de bajo riesgo: como `similarity()` se mantiene tal cual para no alterar
scores, esta micro-optimización es secundaria. Si se hace, exponer una variante
interna que reciba los tokens ya calculados; **no** debe cambiar ningún score.
Si añade riesgo, se omite (el grueso del ahorro es A.1 + A.2).

## Caso borde

- Ítem sin tokens (solo stopwords / vacío): la vía rápida no halla candidatos →
  cae al **escaneo completo** → resultado idéntico a hoy.
- Lista de puros ítems novedosos (todos `< 0.55`): degrada a escaneo completo en
  esos ítems (sin ganancia, pero exacto). En una licitación real la mayoría matchea
  el histórico, así que el grueso usa la vía rápida.

## Pruebas

- **Gate viejo-vs-nuevo (la garantía):** test que instancia el `Matcher` actual y
  el optimizado sobre el **mismo** índice de APUs y, para un conjunto de consultas,
  exige por consulta: **mismo estado** y **mismo `apu_codigo` final** de
  `assemble_item` (IA apagada). Conjunto de consultas: nombres de APU del fixture
  (match exacto), reformulaciones (dudosos), y descripciones nuevas (sin match).
  - En desarrollo se corre además sobre el **catálogo real** (1098 APUs) como
    verificación de campo (script de control, no test de CI si requiere la DB real).
- Los tests de matching existentes (`tests/test_matching.py`) siguen verdes.
- `assemble_item(item, match_result=...)` produce el mismo `AssembledApu` que
  `assemble_item(item)` (test de equivalencia del refactor A.1).
- Suite completa verde.

## Criterios de aceptación

1. Armar la misma lista produce, ítem por ítem, el mismo estado y el mismo APU
   final que antes (gate verde), en una fracción del tiempo.
2. Cada ítem corre el matcher **una** vez (no dos).
3. `pytest` verde; sin dependencias nuevas; Invariante #1 intacto.
