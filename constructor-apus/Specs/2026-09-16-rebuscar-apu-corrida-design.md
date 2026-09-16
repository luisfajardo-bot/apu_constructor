> Espejo automático — no editar aquí. Fuente: `docs/superpowers/specs/2026-09-16-rebuscar-apu-corrida-design.md`

# Volver a buscar APU en una corrida activa

Fecha: 2026-09-16
Estado: aprobado, sin implementar

## Problema

El match de una actividad contra la biblioteca corre **una sola vez**, al armar
(`_armar_fila` → `Matcher.match` → `assemble_item`). Lo que queda guardado en la fila es
`apu_codigo`, `status`, `confianza`, `explicacion` y `candidatos`, y ese `candidatos` es
una foto del día del armado.

Una corrida `activa` sí sigue la biblioteca, pero **solo para costear**: `_costear_row`
re-lee la composición del APU asignado y la costea con precios vigentes. El match no se
vuelve a correr nunca.

Resultado: los APUs creados después del armado son invisibles para la corrida. Duplicar
desde la corrida asigna el APU nuevo **a esa fila** (`duplicado()` → `confirmar_item`),
pero las demás filas que también lo querrían siguen en $0, y un APU creado desde la
pestaña APUs no llega a ninguna. El único camino hoy es "Cambiar APU" con `BuscadorApu`,
fila por fila.

## Solución

Un botón en la corrida activa que vuelve a correr **el mismo matcher del armado** sobre
las filas no confirmadas, muestra qué cambiaría con la plata incluida, y aplica lo que el
usuario marque.

### Flujo

1. El usuario crea APUs (duplicando desde la corrida o desde la pestaña APUs — esos
   caminos no cambian).
2. En la corrida aprieta **Volver a buscar APU**.
3. Se abre un diálogo con la propuesta. Vienen marcadas las filas que hoy están sin APU.
4. **Aplicar** reasigna y recostea las marcadas en un solo recosteo.

## Decisiones

| Decisión | Valor | Por qué |
|---|---|---|
| Filas que re-buscan | todas menos las `confirmed` | Una persona confirmó esa fila; el re-match no se la pisa. Las de `costo_manual` caen ahí solas (`set_costo_manual` deja la fila `confirmed`). |
| Disparo | botón manual | Explícito y barato. El usuario crea los APUs que necesite y aprieta cuando quiera. |
| Qué hace con lo que encuentra | los umbrales del armado (≥0,88 auto, ≥0,55 revisar) | Una sola regla que entender, la misma que armar. |
| Alcance | la corrida abierta | Las congeladas son snapshot inmutable; las demás corridas no se tocan. |
| Aplicar | vista previa y el usuario aprueba | Es el patrón de la casa (previsualizar IDU, revisión con IA, composición: proponen, no aplican) y con "todas menos las confirmadas" un apretón puede mover plata en filas que ya estaban bien. |
| Exhaustividad | vía rápida, síncrono (<1 s) | Ver "La optimización que hace esto síncrono". |
| Previa | muestra costo y margen que quedarían | Se decide viendo la plata. Para una fila en $0 es la diferencia entre "te propongo un APU" y "te propongo $847.320/m³". |
| Estado al aplicar | conserva su nivel (`auto` / `review`) | El usuario aprobó la asignación, no la auditoría: un 62% sigue apareciendo en "Solo revisión" y la fila queda disponible para un próximo re-buscar. |
| Marcado por defecto | solo las filas que hoy están sin APU | Están en $0 y traban el cuadro: cualquier APU es mejor que nada. Las que ya tienen APU vienen desmarcadas, con su antes → después a la vista. |
| Candidatos | se refrescan, y se persisten solo donde cambiaron | Así un APU nuevo aparece en "Elegir" aunque se quede por debajo del 0,55 y no se asigne solo. |
| Rol | `consulta` | El mismo que `confirmar-lote`, que es literalmente esta operación (asignar un APU existente a N filas). No es `igualar-costo`, que declara un monto de la nada. |

## La optimización que hace esto síncrono

Medido sobre la biblioteca real (1182 APUs):

| Tipo de fila | Costo del re-match |
|---|---|
| Con match fuerte (`auto` / `review`) | 0,2 ms — índice invertido |
| Sin APU | 41,7 ms — cae al `_full_scan` de la biblioteca entera |

Con 200-800 filas sin APU, el escaneo completo son 8-35 s acá y 1-3 min en Render, con el
worker único de la app trabado. Eso obligaría a barra de progreso (SSE) o a una cola.

No hace falta. `similarity` es `0.4·secuencia + 0.6·jaccard`. Un APU que **no comparte ni
una palabra** con la actividad tiene jaccard 0, así que su score no puede pasar de **0,40**
— por debajo del **0,55** que se necesita para asignar. O sea: **todo APU asignable comparte
tokens**, y la vía rápida del índice invertido ya lo encuentra. Es la misma garantía que el
matcher ya documenta en su propio comentario; el `_full_scan` existe solo para rellenar la
lista de candidatos de las filas flojas con cosas que igual no se pueden asignar.

Entonces el re-match corre por la vía rápida: **<1 s para 1939 filas**, con las asignaciones
exactas. Sin SSE, sin cola, sin barra de progreso.

## Backend

### `dominio/matching.py`

Un parámetro nuevo:

```python
def candidates(self, descripcion, shift, top_n=5, escaneo_completo=True)
```

Con `escaneo_completo=False` se salta el `_full_scan` de respaldo. El armado sigue llamando
con el default: cero cambio de comportamiento.

### `servicio/corridas.py`

```python
def rebuscar(alm, corrida_id) -> Optional[dict]                  # NO escribe
def aplicar_rebusqueda(alm, corrida_id, seqs) -> Optional[dict]
```

`rebuscar`:

- `None` si la corrida no existe; `CorridaCongelada` si `modo == "congelada"`.
- Rechaza si `_plan_a_medias(meta)`: mientras el armador escribe, la corrida es suya.
- Salta las filas `confirmed`.
- Matchea con **`row.item.shift`**, no `row.shift`. El turno del ítem es el que usó
  `_armar_fila`; `row.shift` puede haber caído a otro turno al asignar (el fallback de
  `_build`).
- Misma regla que `assemble_item`: si el ítem trae `codigo_sugerido` y ese APU existe, ese
  manda; si no, el matcher. Una sola regla, no dos.
- Propone solo cuando el resultado **difiere** del APU que la fila ya tiene, comparando el
  par `(código, turno)`: mismo código en otro turno es una propuesta.
- Costea solo las propuestas, con un `PricingEngine` compartido y `precargar(...)` — el
  patrón que ya bajó 540 round-trips a 2.
- Devuelve `{propuestas: [...], escaneadas: N, sin_cambio: M}`. Cada propuesta lleva `seq`,
  `descripcion`, el APU actual, el APU propuesto con su parecido, y `costo_unitario`,
  `margen_unitario` y `margen_pct` del propuesto (el frontend no suma plata).

`aplicar_rebusqueda`:

- **Recalcula la propuesta del lado del servidor** y aplica solo los `seqs` pedidos cuya
  propuesta siga siendo la misma. Los que cambiaron (otro usuario reasignó, alguien borró
  el APU) se saltan y salen en la respuesta. Es el mismo candado que `apu_evaluado` en la
  revisión: una previa de hace cinco minutos no manda sobre la fila de ahora. De paso, el
  cliente no dicta qué APU se escribe.
- Reusa `confirmar_items(..., asignaciones=...)` con un parámetro nuevo
  `estados: Optional[dict[int, str]]` — el status por `seq`, porque en un mismo lote hay
  filas que entran `auto` y filas que entran `review`. Los seq que no estén ahí siguen
  quedando `confirmed`, así que ningún llamador de hoy cambia. Un solo recosteo para todo
  el lote.
- Persiste los `candidatos` frescos **solo de las filas cuya lista cambió** y no quedó
  vacía. Una lista fresca vacía no pisa la guardada: sería perder información.

### `datos/` — método nuevo

`set_candidatos(corrida_id, seq, candidatos)` en `repositorio.py` (Protocol),
`corridas_db.py` y `pg/corridas_pg.py`. No pasa por `actualizar_eleccion`: esa borra
`revision_json` y `costo_manual`, y refrescar candidatos no es cambiar el APU elegido.

### `servicio/rutas.py` + `esquemas.py`

```
POST /api/corridas/{cid}/rebuscar           -> propuesta, no escribe
POST /api/corridas/{cid}/rebuscar/aplicar   {seqs: [...]} -> vista + salteadas
```

Rol `consulta` en los dos. `CorridaCongelada` → 409; corrida a medio armar → 409 con el
motivo; corrida inexistente → 404.

## Frontend

- Botón **Volver a buscar APU** en la barra de la corrida, junto a "Revisar con IA".
  Oculto si la corrida está congelada o a medio armar.
- `components/corrida/DialogoRebuscar.tsx`: tabla densa, sin cards. Columnas:
  `✓ · # · actividad · APU actual → APU propuesto (parecido) · costo actual → costo nuevo ·
  margen nuevo`.
- Marcado por defecto: las filas que hoy están sin APU. Selección con shift+clic y "marcar
  todas", mismo patrón que los conflictos del import.
- Vacío: *"Ninguna actividad encontró un APU mejor que el que ya tiene."*
- Al aplicar, la respuesta trae la vista de la corrida: la tabla se actualiza con un solo
  render, como después de confirmar en lote. Si hubo filas salteadas, un toast las nombra.

## Lo que NO hace

- No corre solo al crear un APU: el usuario aprieta.
- No toca otras corridas ni las congeladas.
- No toca filas `confirmed` — ni con un "forzar".
- No persiste la previa: volver a apretar cuesta menos de un segundo.

## Techos conscientes

Los dos llevan comentario `ponytail:` en el código.

- La vía rápida no refresca candidatos de relleno con score <0,40 que no comparten ninguna
  palabra con la actividad. Son inasignables por definición.
- Patológico: una descripción cuyo texto normalizado sea idéntico al nombre de un APU pero
  cuyo set de tokens sea vacío — `similarity` devuelve 1.0 por atajo antes de mirar tokens,
  y la vía rápida no la vería. No existe ningún caso así hoy.

## Pruebas

**pytest**

- Propone el APU creado después del armado para una fila que quedó sin APU.
- No toca filas `confirmed` ni filas con `costo_manual`.
- Corrida congelada → `CorridaCongelada`; corrida a medio armar → rechazo.
- Aplicar saltea los seq cuya propuesta cambió desde la previa, y los reporta.
- Los candidatos se persisten solo donde la lista cambió; una lista fresca vacía no pisa la
  guardada.
- Vía rápida ≡ escaneo completo: sobre un corpus, mismo `elegido` y mismo `status`. Es el
  candado de la optimización.
- Contrato dual-backend de `set_candidatos` (SQLite y Postgres).

**vitest**

- Marcado por defecto (solo las sin APU), marcar todas, aplicar, estado vacío.
