# Pendientes del agente de composición asistida

> Estado al **2026-09-10**. La fase 0 + fase 1 están **en producción** (`b017eec`).
> Diseño: `docs/superpowers/specs/2026-09-10-agente-composicion-design.md`.
> Plan de implementación: `docs/superpowers/plans/2026-09-10-agente-composicion.md`.

Este documento es el backlog vivo de la feature. Lo que ya está hecho no se repite acá:
para eso está el diseño.

---

## 1. Probar si las propuestas sirven — BLOQUEA A TODO LO DEMÁS

**Qué:** componer cinco actividades reales de familias distintas (una excavación, un
concreto, una tubería, un transporte, una señalización) y juzgar la calidad técnica.

**Por qué primero:** es lo único que decide si el resto del backlog vale la pena.
Optimizar el costo, agregar el lote o ajustar el prompt de algo que todavía no sabemos
si funciona es empezar por el final.

**El riesgo concreto que hay que descartar:** pasamos de pedirle al modelo **dos campos
por componente a diez**. Eso puede cargarle la atención y darnos **peores** rendimientos
que la versión vieja. Ningún test puede verlo — es criterio de ingeniería, no aserción.

**Qué anotar por cada actividad:**

- ¿Los insumos son los correctos?
- **¿Los rendimientos son plausibles?** Es lo único que importa de verdad: un
  rendimiento mal puesto es un APU mal costeado.
- ¿El `origen` declarado es honesto — dice `sin_evidencia` cuando no tiene antecedente?
- ¿Las advertencias apuntan a algo real o son ruido que uno aprende a ignorar?
- ¿El nivel de confianza coincide con el juicio de quien revisa?
- Cuánto tardó y **cuántos tokens costó** (`response.usage` lo reporta).

**Si sale mal:** la palanca es partir la llamada en dos —una técnica, una de
contabilidad— que es lo que la fase 2 hace de todos modos.

**De paso queda medido lo que no pudimos medir en local:** el costo real. La estimación
es **$0,03 a $0,07 USD por composición** (~120 a 280 pesos), con el pensamiento
adaptativo como la parte variable y sin medir.

---

## 2. Componer varias líneas a la vez, con la API asíncrona

**Qué:** seleccionar varias filas sin APU y componerlas de una.

**Por qué vale doble:** la API de lotes de Anthropic cobra **la mitad** por trabajo
asíncrono. La funcionalidad que se pidió y el 50 % de descuento salen en el mismo
movimiento: de $0,03–0,07 por composición a $0,015–0,035.

**Necesita brainstorm, y la decisión de fondo no es técnica:** generar en lote es fácil;
**revisar en lote es el problema**. La mesa existe para que alguien mire una propuesta
con cuidado antes de aprobarla. Si el botón termina siendo *"componer 20 y aprobar
todas"*, volvemos exactamente a lo que la feature vino a evitar.

**La forma que parece correcta** (a validar en el brainstorm): separar las dos cosas —
**generar en lote**, que es lo lento y lo que cuesta, y **revisar de a una**, con las
propuestas ya listas. Preguntas abiertas: qué pasa si una falla, cómo se ve el avance,
si se puede cerrar el navegador mientras corre, y si el lote debe respetar el mismo
candado de fila (sin APU o veredicto `sin_apu`).

---

## 3. Bajar el esfuerzo del pensamiento

**Qué:** pasar `effort` de `medium` a `low` en `ApuAdvisor.componer`.

**Por qué:** el pensamiento adaptativo es la parte que **domina el costo** — entre
$0,01 y $0,05 de los $0,03–0,07 totales.

**Por qué no ahora:** hay que medir si la propuesta empeora, y para eso hace falta el
punto 1. Es una prueba de un día una vez que haya línea base.

**Otras palancas de costo, en orden de conveniencia:**

| Palanca | Ahorro | Riesgo |
|---|---|---|
| API de lotes (punto 2) | 50 % | ninguno — es el mismo modelo |
| Bajar `effort` a `low` | alto | propuestas más flojas; hay que medir |
| Mandar 20 insumos candidatos en vez de 40 | ~50 % de la entrada | el modelo tiene menos de dónde elegir |
| Modelo más barato (Haiku) | 50 % | **no recomendado**: esto es criterio técnico sobre cantidades de obra, es donde menos conviene ahorrar |

El *prompt caching* **no sirve acá**: el prompt de sistema es chico (~800 tokens) y el
resto del payload cambia por actividad, así que no hay prefijo estable que cachear.

---

## 4. Reporte de correcciones — la métrica de mejora

**Qué:** una consulta sobre la tabla `composicion` que muestre *"cuánto corrigen los
humanos las propuestas, por familia y por versión de prompt"*.

**Por qué importa:** es lo más parecido a una función de pérdida que este sistema puede
tener, y es legible y manual. Si el promedio de corrección baja de `composicion/v4` a
`v5`, el prompt mejoró; si sube, se revierte.

**No hace falta nada del modelo de datos:** el expediente ya guarda la propuesta
original, la corregida, el modelo y `prompt_version`. **Los datos se están acumulando
desde el 2026-09-10.** Falta solo quien los lea.

**Ojo con la expectativa:** esto **no es reentrenamiento**. No hay pesos que ajustar —
le pegamos a una API. El aprendizaje real que sí funciona ya está andando: cada APU
aprobado entra a la biblioteca y se vuelve antecedente de la próxima propuesta de esa
familia, vía el retriever y `rendimientos_observados`.

---

## 5. Las fases 2, 3 y 4 del diseño

Cubren los 4 criterios de aceptación que la fase 1 no alcanzó (de 36, quedaron 32).

| Fase | Qué trae | Depende de |
|---|---|---|
| **2. Interpretación y preguntas** | ficha técnica estructurada; preguntas críticas / importantes / opcionales; bucle responder→regenerar; estado `requiere_informacion` | el expediente de la fase 1 (ya existe: `ficha_json` está en la tabla, en `NULL`) |
| **3. Recuperación híbrida** | retriever guiado por la ficha (unidad, familia, método, turno); estadísticas de antecedentes comparables; **sub-APUs en el conjunto candidato** | la ficha de la fase 2 |
| **4. Correcciones como evidencia** | las propuestas aprobadas y corregidas se reinyectan como antecedentes | historial acumulado (ver punto 4) |

Los puntos de extensión ya están previstos: `ficha_json` existe y es `NULL`, las etapas
nuevas son un evento SSE más, `requiere_informacion` es un estado más en la máquina, y
el contrato ya distingue `tipo: "apu"`.

**Cuando llegue la fase 3**, hay que revertir dos cosas que hoy están acotadas a
propósito: el esquema JSON vuelve a `list(TIPOS)` y `list(FUNCIONES)` (hoy `tipo` solo
acepta `"insumo"`), y el retriever deja de filtrar los componentes con `tipo="apu"`.

---

## 6. Deuda técnica anotada, no arreglada

**`search_insumos_por_palabras` es N+1 en los dos backends** (`precios_db.py`,
`pg/precios_pg.py`): una consulta para los ids y después hasta **60** `get_insumo_por_id`.
Contra Supabase desde Render son ~61 round-trips en el camino de generación.

Es código **preexistente**, pero la composición lo puso en un camino nuevo y caliente.

**Cuidado al arreglarlo:** el `LIMIT` sin `ORDER BY` devuelve las filas en orden
indefinido, y el `sorted(..., key=similarity)` de `retrieve` es **estable** — o sea que
el orden de inserción desempata entre insumos con la misma similitud y decide quién
entra en los 40. Para no cambiar el comportamiento del matcher: dejar la consulta de ids
**exactamente como está** y reemplazar solo los 60 lookups por uno con `id IN (...)`,
reordenando en Python según la lista de ids.

---

## 7. Cosas chicas que quedaron abiertas

- **Los errores de la API que NO son 401/403/400-por-saldo siguen saliendo como
  "Error interno".** Hoy se traducen tres casos: credencial inválida (401/403), saldo
  agotado (400 con las señales de facturación) y falta de SDK. Todo lo demás cae al
  `except Exception` de `_event_stream`, con el detalle solo en el log. El primer
  intento real de componer en producción se perdió exactamente así — ver el caso del
  saldo, ya arreglado. Vale revisar, cuando aparezca el siguiente, si hay otra familia
  de errores que merezca su propio mensaje: un 429 sostenido, por ejemplo, es "la
  cuenta está pasada de rate limit", no un fallo de la aplicación.

- **La mesa no detecta que la corrida se congeló mientras está abierta.** Cubre el caso
  de abrirla ya congelada (el estado viaja con el expediente); si la congelan después, el
  409 de la primera escritura sigue siendo la red. Cubrir eso pedía un poll de fondo, que
  este repo no hace por regla.
- **Los nombres de insumo muy largos** (hay de 830 caracteres) se truncan en la celda y
  se leen completos en el desplegable de la fila. Si en el uso real resulta incómodo, hay
  margen para mejorarlo.
- **`_MAX_TEXTO = 500` en el parseo del contrato** está por debajo del nombre más largo
  del catálogo (830). Hoy no rompe nada porque ningún nombre pasa por ahí — el modelo
  manda códigos y el nombre lo pone el catálogo. Es una trampa para quien agregue un
  campo `nombre` al contrato.
- **Una `hipotesis` con valores anidados** (una lista de 10.000 elementos, un dict dentro
  del dict) pasa sin tope: el filtro acota claves, longitud de clave y valores de tipo
  string, no estructuras arbitrarias.

---

## 8. Verificación pendiente en producción

- [x] **`ANTHROPIC_API_KEY` está puesta en Render** — confirmado: la petición llegó a
      la API y el rechazo vino del otro lado.
- [ ] **Comprar créditos en Anthropic.** El primer intento real de componer falló con
      un 400: *"Your credit balance is too low"*. La cuenta no tiene saldo. Con la
      estimación de $0,03–0,07 por composición, US$10 alcanzan para 150–300.
- [ ] Correr el punto 1 de este documento y anotar los resultados en un
      `smoke-test-composicion-AAAA-MM-DD.md`, como se hizo con las features anteriores.
