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

### A.2 — Índice invertido por tokens (bloqueo) — `apu_tool/dominio/matching.py`

- `Matcher.__init__` construye, además del `_by_shift` actual, un índice
  `_postings_by_shift: dict[str, dict[str, list[int]]]` (token → posiciones en la
  lista del turno) y un índice combinado para el *fallback* de turno.
- `Matcher.candidates(descripcion, shift, top_n=5)`:
  - `qtokens = _tokens(descripcion)`. Si `qtokens` está vacío → `return []`.
  - Reúne los índices candidatos = unión de postings de cada token de `qtokens`.
  - Puntúa **solo** esos APUs con `similarity(descripcion, nombre)` (la función de
    score **no cambia**, para que los scores sean idénticos a los de hoy en los
    APUs puntuados), filtra `score > 0`, ordena desc, devuelve `top_n`.
  - Si el pool del turno está vacío, usa el índice combinado (fallback actual).
- `Matcher.match()` no cambia su lógica de umbrales.

**Correctitud del bloqueo:** `score = 0.4·seq + 0.6·jaccard`. Un APU sin tokens
compartidos con el ítem tiene `jaccard = 0` → `score ≤ 0.4 < MATCH_REVIEW (0.55)
< MATCH_ACCEPT (0.88)`. Por tanto un APU excluido **nunca** puede ser el mejor en
AUTO ni alcanzar REVISAR; el `elegido` (solo se fija en AUTO) y el estado quedan
idénticos. Solo cambia la cola de relleno cuando hay menos de `top_n` APUs con
tokens compartidos.

### A.3 — Reusar tokens precomputados (menor)

Opcional y de bajo riesgo: como `similarity()` se mantiene tal cual para no alterar
scores, esta micro-optimización es secundaria. Si se hace, exponer una variante
interna que reciba los tokens ya calculados; **no** debe cambiar ningún score.
Si añade riesgo, se omite (el grueso del ahorro es A.1 + A.2).

## Caso borde

- Ítem sin tokens (solo stopwords / vacío): hoy puntúa todo el pool con score ≤ 0.4
  y devuelve estado NUEVO; con el bloqueo devuelve `[]` → estado NUEVO ("Sin
  candidatos"). **Mismo estado**, distinta `explicacion`/`confianza` (cosmético,
  dentro de la barra acordada).

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
