# Agregar líneas a una corrida activa

Fecha: 2026-08-18 · Rama: `feat/agregar-lineas-corrida` (desde `master`)

## Problema

Una corrida se arma de una lista de licitación. Si a esa lista le faltaban actividades
—se descubren después, o el pliego trae un adicional—, hoy no hay forma de sumarlas:
la única salida es borrar la corrida y rearmarla completa, perdiendo cada confirmación
y reasignación ya hecha.

## Qué se construye

Sobre una corrida en modo `activa`, dos vías para sumar actividades y una para deshacer:

1. **Una línea a mano** (descripción, unidad, cantidad, precio contractual, turno).
2. **Un Excel** con solo las que hicieron falta, con vista previa antes de aplicar.
3. **Borrar líneas** marcadas, como válvula para cualquier error.

Las líneas nuevas pasan por el **mismo camino que el armado inicial**: matcher, candidatos,
`use_ai` y `lista_precios_id` de la corrida. Quedan en `review`/`confirmed` según el match,
y se revisan con la UI que ya existe (confirmar, reasignar, duplicar APU).

## Decisiones

| Decisión | Por qué |
|---|---|
| Solo corridas `activa`; congelada → 409 "actívala primero" | Congelada = foto inmutable. Es la misma respuesta que ya da confirmar. |
| Vista previa **y** borrar líneas | La previa evita el error; el borrado lo arregla cuando igual pasó. |
| Una sola petición (sin SSE) | Reusa el patrón de importar insumos/APUs. Tope de 100 líneas por archivo. |
| Un botón `Agregar líneas` en la cabecera | La cabecera ya tiene 3 botones; el diálogo abre las dos vías. |
| Nunca renumerar `seq` | `seq` es identidad: URL del ítem y clave del `snapshot_json`. Renumerar casaría snapshots con la línea equivocada. Borrar deja huecos y los huecos no se reusan. |
| La previa **avisa** duplicados, no los filtra | Saltear en silencio es la sorpresa que este repo evita. Aplicar agrega todo lo que trae el archivo. |
| Agregar/borrar en corrida `finalizada` la devuelve a `en_revision` | El cuadro emitido ya no dice la verdad. |
| Rol `consulta` en los 4 endpoints | Es lo que ya piden confirmar, congelar y eliminar corrida. |
| Auditoría solo al borrar | Es la operación destructiva, igual que `corrida.eliminar`. Agregar es aditivo y reversible con el borrado. |

## Arquitectura

### `servicio/corridas.py`

Del bucle de `construir_corrida_stream` se extrae el trabajo por ítem —match →
`assemble_item` → `CorridaItemRow`— a un `_armar_fila(assembler, item, seq)`. El armado
inicial queda idéntico; las líneas nuevas usan ese mismo helper. Un solo camino de
armado, sin lógica de orquestación duplicada.

```python
preview_agregar(alm, cid, items) -> dict | None
# {"total": n,
#  "nuevas":     [{item, descripcion, unidad, cantidad, precio_contractual, shift}],
#  "duplicadas": [{..., "seq_existente": 12}]}
# No matchea ni arma: es barato y no toca la IA.

agregar_items(alm, cid, items) -> dict | None      # vista_corrida; CorridaCongelada si congelada
borrar_items(alm, cid, seqs, actor=None) -> dict | None  # ídem; seqs ajenos se saltean
```

- `seq` de la primera línea nueva = `max(seq de get_items()) + 1`. Esos ítems ya se leen
  para detectar duplicados, así que no hace falta ningún método nuevo de persistencia:
  `agregar_item` existe en los dos backends. Queda marcado en el código:
  `# ponytail: seq = max+1 leído fuera de transacción; dos usuarios agregando en el mismo
  instante pueden chocar. Índice UNIQUE (corrida_id, seq) si pasa.`
- **Duplicada** = descripción normalizada con `nucleo/texto.normalizar` que ya está en la
  corrida. Se reporta con el `seq` de la línea existente.
- `None` cuando la corrida no existe (el endpoint contesta 404), como el resto del módulo.

### Persistencia — un método nuevo

`borrar_items(corrida_id, seqs, conn=None) -> int` en `RepositorioCorridas`,
`datos/corridas_db.py` y `datos/pg/corridas_pg.py`. El `conn` opcional deja la auditoría
en la misma transacción (convención de `eliminar_corrida`). Sin columnas nuevas y sin
migración al boot.

### Endpoints — `servicio/rutas.py`, rol `consulta`

```
POST   /corridas/{cid}/items/preview    multipart archivo   -> preview
POST   /corridas/{cid}/items/importar   multipart archivo   -> vista_corrida  (tope 100)
POST   /corridas/{cid}/items            JSON {lineas:[...]} -> vista_corrida
POST   /corridas/{cid}/items/borrar     JSON {seqs:[...]}   -> vista_corrida  (POST: apiDelete no manda cuerpo)
```

El Excel es **la plantilla de licitación que ya existe** (`GET /corridas/plantilla`), leída
con `read_licitacion(..., default_shift=meta.turno_def, require_turno=True)`: la misma
exigencia de turno por ítem que el armado inicial.

El bloque tmpfile + `BadZipFile`/`InvalidFileException` está copiado 4 veces en `rutas.py`;
se extrae a `_items_del_upload(archivo, turno)` y se usa también en los dos endpoints
existentes (movimiento literal, cubierto por `tests/test_api_corridas.py`).

Línea a mano: `descripcion` obligatoria; `unidad` y `cantidad` con defaults (`1`);
`precio_contractual` admite 0 (un no previsto puede no tenerlo todavía); `shift` por
defecto el `turno_def` de la corrida; `item` vacío → `str(seq + 1)`.

### Frontend

- `api/corridas.ts`: `previewLineas`, `importarLineas`, `agregarLinea`, `borrarLineas`.
- `components/corrida/DialogoAgregarLineas.tsx`: dos modos en un diálogo — *una línea* y
  *desde Excel* (input → tabla de previa con las duplicadas marcadas → Aplicar). Copia las
  fases de `DialogoImportarInsumos` (idle/cargando/preview/aplicando, re-subida del archivo
  al aplicar) y el botón de descargar plantilla, que ya existe.
- `pages/Corrida.tsx`: botón `Agregar líneas` junto a Congelar/Descargar, oculto si la
  corrida está congelada o armando en vivo. La respuesta es la vista completa →
  `setCorrida(...)`; los filtros de la tabla siguen vivos.
- `components/corrida/TablaItems.tsx`: `Borrar` en la barra de líneas marcadas, con
  confirmación que dice cuántas se van.

## Errores

| Caso | Respuesta |
|---|---|
| Corrida inexistente | 404 |
| Corrida congelada | 409 "La corrida está congelada; actívala para modificar." |
| Excel sin columna de descripción / sin turno por ítem | 400 con el detalle de `read_licitacion` |
| Excel corrupto o no-Excel | 400 "El archivo no es un Excel válido o está corrupto." |
| Archivo con más de 100 líneas | 400 pidiendo partirlo |
| Sin líneas legibles | 400 |
| `seqs` que no son de la corrida | Se saltean; la vista vuelve igual |

## Pruebas

`tests/test_corridas_agregar_lineas.py`
- el `seq` de la línea nueva continúa tras el máximo existente
- corrida congelada → `CorridaCongelada` al agregar y al borrar
- corrida `finalizada` → vuelve a `en_revision`
- la previa marca la duplicada con su `seq_existente`, y aplicar la agrega igual
- borrar deja hueco y el snapshot del ítem sobreviviente sigue casado con su `seq`
- borrar y después agregar no reusa el hueco
- tope de 100 líneas

`tests/test_api_corridas.py`: los 4 endpoints (incluidos 404/409) y el borrado auditado.

Frontend: `DialogoAgregarLineas.test.tsx` (previa → aplicar, y el error del archivo malo) y
un test de borrado en `TablaItems.test.tsx`.

## Fuera de alcance

- Editar una línea existente (descripción, cantidad, precio): solo agregar y borrar.
- Progreso en vivo del armado de las líneas nuevas (SSE).
- Marcar visualmente qué líneas se agregaron después: el `status` ya las delata.
- Índice `UNIQUE (corrida_id, seq)`: crearlo al boot puede tumbar la app si algún dato
  viejo tuviera duplicados. Se deja anotado en el código.

## Aislamiento del PR de Google

Rama desde `master`. Esta feature no toca `servicio/auth.py`, `datos/perfiles*`,
`datos/repositorio.py::RepositorioPerfiles` ni `pages/Login.tsx`: cero solapamiento con
`feat/login-google`.
