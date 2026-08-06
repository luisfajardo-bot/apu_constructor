# Asignar / confirmar APU en lote desde la corrida

Fecha: 2026-08-05

## Problema

En una licitación el mismo APU se repite en muchos ítems. Hoy la única forma de
cambiar el APU de un ítem es expandir su fila y usar *Cambiar APU* (`BuscadorApu`),
una fila a la vez. Con 15 líneas de "EXCAVACIÓN MANUAL" mal matcheadas son 15
expansiones, 15 búsquedas y 15 clicks.

Lo mismo del otro lado: cuando el matcher acertó y solo hay que confirmar, cada
`review` se confirma de a uno.

## Alcance

- Marcar varias líneas de la corrida y **asignarles el mismo APU** de un tirón.
- Marcar varias líneas y **confirmar el APU que ya tienen** (sin reasignar).
- Selección por checkbox, con "marcar todo lo filtrado" y rango con Shift.

Fuera de alcance: duplicar un APU y asignarlo al lote (se puede agregar después
reusando `abrirDuplicar`); editar cantidades en lote.

## Backend

### La primitiva pasa a ser la de lote

`servicio/corridas.py::confirmar_item` (línea 319) hace su trabajo y devuelve
`vista_corrida(...)` — **la corrida entera recosteada**. Un loop desde el frontend
paga ese recosteo N veces. Se da vuelta la relación:

```python
def confirmar_items(alm, corrida_id, seqs, apu_codigo=None, shift=None) -> Optional[dict]:
    """Confirma varios ítems en UN solo recosteo de la corrida.

    apu_codigo=None => cada ítem confirma el APU que ya tiene (no se reasigna).
    apu_codigo dado => se le asigna ese APU (codigo+turno) a todos los seqs.
    Devuelve la vista de la corrida; None si la corrida no existe.
    """
```

- `meta is None` → `None` (404). `meta.modo == "congelada"` → `CorridaCongelada` (409).
- Un **solo** `Assembler(alm, advisor=ApuAdvisor(enabled=False), lista_id=meta.lista_precios_id)`
  para todo el lote. `assemble.py:44-50` deja matcher/retriever perezosos y el camino
  de confirmar no los toca, y su `PricingEngine` cachea: asignar el mismo APU a 20
  filas cuesta ≈ 1 costeo + 20 UPDATE + 1 vista.
- `seqs` que no existen en la corrida se **saltan** en silencio (la vista devuelta es
  la autoridad; el frontend solo manda seqs que está viendo).
- Un `vista_corrida(alm, corrida_id)` al final, no uno por ítem.

`confirmar_item(alm, cid, seq, apu_codigo, shift)` queda como wrapper de una línea
sobre `confirmar_items`. Así confirmar-uno y confirmar-muchos no se pueden separar
con el tiempo, y la validación de abajo cubre los dos caminos.

### Validación del APU elegido (arregla un hueco de hoy)

Con `apu_codigo` explícito se valida **una vez, antes del loop**, que
`alm.apus.get_apu(apu_codigo, shift)` exista → si no, `ValueError` (400) y no se
toca nada.

Esto también tapa un hueco del camino actual de un solo ítem: hoy confirmar un
código inexistente produce una composición vacía y el ítem queda **costeado en $0**,
que es exactamente lo que prohíbe la regla "nada en $0". Al vivir la validación en
la primitiva compartida, los dos caminos quedan cubiertos con un solo guard.

El `shift` NUNCA es obligatorio, ni con `apu_codigo` explícito: cada fila resuelve
su propio turno con `turno = shift or row.shift`. Exigirlo rompería llamadores
reales que confirman sin turno — `rutas.py` lo recibe opcional desde el body
(`ConfirmarIn`/`ConfirmarLoteIn`), y en el frontend tanto el botón *Elegir* de los
candidatos como *Confirmar el APU actual* llaman sin él. `BuscadorApu` sí entrega
siempre el par (código, turno), pero no es el único llamador. La validación usa
el turno ya resuelto por fila (`codigo, turno` tal como quedó calculado), así que
sigue cubierta sin necesitar que el llamador lo mande.

### Sin transacción para el lote

`actualizar_eleccion` abre su propia conexión en los dos backends y no acepta
`conn=`. Darle atomicidad al lote significaría propagar `conn=None` por
`corridas_db.py`, `pg/corridas_pg.py` y el `Protocol` de `repositorio.py`.

Se salta a propósito: la operación es **idempotente** (reasignar el mismo APU da el
mismo resultado), el único fallo posible a mitad de camino es que se muera la
conexión, y el resultado parcial es visible en la tabla y se arregla repitiendo el
lote. Va con comentario `ponytail:` nombrando el techo y el camino de upgrade.

### HTTP

- `esquemas.py`: `ConfirmarLoteIn(seqs: list[int], apu_codigo: Optional[str] = None,
  shift: Optional[str] = None)`.
- `rutas.py`: `POST /api/corridas/{cid}/items/confirmar-lote`, con
  `requiere_rol("consulta")` (mismo guard que el `confirmar` de un ítem),
  409 congelada, 400 `ValueError`, 404 corrida inexistente.
- Respuesta: la vista de la corrida, **misma forma** que `confirmar` — el frontend
  ya sabe hacer `setCorrida(vista)` y no hay tipo nuevo.

## Frontend

Todo en `web/src/components/corrida/TablaItems.tsx`.

- `const [marcadas, setMarcadas] = useState<Set<number>>(new Set())` con seqs, y un
  `ultimoIdxRef` para el rango con Shift.
- **Columna de checkbox** al principio, solo cuando hay selección disponible (ver
  abajo). `TOTAL_COLS` pasa a calcularse (13 o 14) porque lo usa el `colSpan` de la
  fila expandida.
- **Cabecera**: checkbox que marca/desmarca todo `visible` (que con `control` ya son
  las filas filtradas). `indeterminate` por callback de `ref` cuando la selección es
  parcial.
- **Shift-click**: `alternar(idx, seq, shiftKey)`; con Shift y `ultimoIdxRef` no nulo,
  marca el rango `visible[min..max]`.
- **Al actuar, se intersecta `marcadas` con los seqs visibles.** Si el usuario marca
  filas y después cambia el filtro, las que se fueron no se tocan (y el contador de
  la barra muestra la intersección, no el Set crudo).
- **Barra de acciones** cuando la intersección tiene ≥1: sticky abajo, con
  `BuscadorApu` (ya existe) + *Asignar a N líneas* + *Confirmar el APU actual (N)* +
  *Limpiar*. Deshabilitada mientras hay un pedido en vuelo.
  - *Confirmar el APU actual* filtra en el cliente las filas sin `apu_codigo`, así
    el backend nunca recibe seqs sin APU y no hace falta un canal de "omitidos".
- Éxito: `onConfirmado(vista)`, se limpia la selección, un `toast.success` con el N.
- Sin selección si `readOnly` (corrida congelada) ni en modo vivo (`control ===
  undefined`): mientras se arma, la tabla viene del stream.
- `api/corridas.ts`: `confirmarLote(corridaId, seqs, apuCodigo?, turno?)`.

## Pruebas

`tests/test_corridas_confirmar_lote.py` (pytest):

- asignar un APU a 3 seqs deja los 3 en `confirmed` con ese código, y devuelve una
  sola vista coherente;
- `apu_codigo=None` confirma el APU que cada fila ya tenía, sin cambiarlo;
- corrida congelada → `CorridaCongelada`;
- `apu_codigo` inexistente → `ValueError` y **ninguna** fila modificada;
- seq inexistente en la lista → se salta, las demás se aplican;
- `confirmar_item` (el wrapper) sigue dando lo mismo que antes — los tests que ya
  existen sobre confirmar tienen que seguir verdes sin tocarlos, salvo alguno que
  dependa del hueco del código inexistente (si aparece, se ajusta y se anota).

`TablaItems.test.tsx` (vitest): el checkbox marca; Shift-click marca el rango; la
barra aparece con el contador correcto; *Asignar* llama a `confirmarLote` con los
seqs marcados y el codigo+turno del buscador; cambiar de filtro no arrastra filas
invisibles al lote; con `readOnly` no hay checkboxes.

## Verificación manual

Levantar la web en local (receta: `SUPABASE_URL` + `APU_ADMIN_EMAILS`, si no todo
`/api` rebota 401), abrir una corrida con ítems repetidos, filtrar por descripción,
marcar todo, asignar un APU y comprobar en la tabla y en los totales. El navegador
va **antes** del push (lección de `DialogoTexto`).
