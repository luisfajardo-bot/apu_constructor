# Diseño — Corridas: turno requerido, lista "mis corridas", vivo, composición desplegable

> Fecha: 2026-06-25
> Estado: aprobado para implementación
> Contexto: tras el v1 + el progreso SSE, mejoras al flujo de corrida pedidas por el usuario.

## Objetivo

Cuatro mejoras al flujo de corrida, sin tocar la lógica de matching/costeo:
1. **Exigir el turno por fila** en la lista de entrada (que el programa separe por turno con la data, no con un default global ciego).
2. **Lista "mis corridas"** persistente, con eliminar, para volver a cualquier corrida.
3. **Corrida "viva"**: al volver a una corrida (o tras editar un precio en Insumos) se muestra recosteada con el precio vigente; descargar no la bloquea.
4. **Composición desplegable inline** en cualquier ítem del cuadro (ver insumos y rendimientos sin importar el estado).

## Global Constraints (cero regresiones — el usuario es estricto)

- NO se toca la lógica de matching ni de costeo. El re-costeo (`_costear_row` / `cost_components`) no cambia.
- `read_licitacion` se mantiene **retrocompatible**: el requisito de turno entra por un parámetro opcional `require_turno=False`; los demás llamadores no cambian.
- Persistencia solo en `apu_tool/datos/`; sin SQL crudo fuera de esa capa.
- Invariante #1: ningún archivo en `apu_tool/servicio/` contiene "ai_assist".
- UI densa, table-first, sin cards; imports `@/`.
- `python -m pytest tests/ -q` verde tras cada tarea de backend; el frontend compila (`npm run build`, 0 TS).

## 1. Turno requerido por fila

- `apu_tool/dominio/licitacion.py`: `read_licitacion(path, default_shift=..., require_turno: bool = False)`. Cuando `require_turno=True`:
  - si no se detecta columna de turno (no hay header que mapee a `shift`) → `ValueError("La lista debe incluir una columna de turno (DIURNO/NOCTURNO) por ítem.")`.
  - si alguna fila con descripción no resuelve a DIURNO/NOCTURNO (celda vacía o no reconocida) → `ValueError` indicando los ítems/filas problemáticos.
  - El default global deja de aplicarse cuando `require_turno=True` (cada fila debe traer su turno).
- Los endpoints de armado (`/api/corridas`, `/api/corridas/stream`) llaman `read_licitacion(tmp, require_turno=True)`; el `ValueError` ya se traduce a `400` (camino existente). El de **sample** (`generate_sample`) no cambia: el ejemplo ya escribe la columna TURNO.
- **Frontend:** en `CorridasInicio.tsx` se **quita el selector global de turno** (ya no aplica) y se deja de enviar `turno`. El endpoint mantiene `turno` como parámetro opcional con default (compatibilidad), pero el armado real usa el turno de cada fila.

> Nota de no-regresión: `read_licitacion(...)` sin `require_turno` se comporta igual que hoy; los tests y el `generate_sample` usan archivos con TURNO, así que siguen pasando.

## 2. Lista "mis corridas" (listar + eliminar)

### Datos — `apu_tool/datos/corridas_db.py` (+ Protocol en `repositorio.py`)
- `listar_corridas() -> list[CorridaMeta]` — todas las corridas, orden `creada_en DESC` (más reciente primero).
- `eliminar_corrida(corrida_id: int) -> bool` — borra la corrida; `corrida_item` se arrastra por `ON DELETE CASCADE` (la conexión ya hace `PRAGMA foreign_keys = ON`). Devuelve si borró algo.

### Servicio — `apu_tool/servicio/corridas.py`
- `listar_corridas(alm) -> list[dict]` — por corrida: `{id, archivo, creada_en, estado, n_items, n_revision}`. `n_items`/`n_revision` salen de los ítems guardados (status `review`/`new`); NO recostea (la lista es liviana). `nombre` se compone en el frontend (`archivo` + `creada_en`).
- `eliminar_corrida(alm, corrida_id) -> bool`.

### API — `apu_tool/servicio/rutas.py`
- `GET /api/corridas` → `listar_corridas` (lista para "mis corridas").
- `DELETE /api/corridas/{cid}` → `eliminar_corrida`; `404` si no existía.
- (Los endpoints existentes `POST /corridas`, `/sample`, `GET /corridas/{cid}`, `/items/{seq}`, `confirmar`, `cuadro`, y los `/stream` se conservan.)

### Frontend — navegación + página de lista
- Rutas (`App.tsx`): `/corridas` → **MisCorridas** (lista); `/corridas/nueva` → `CorridasInicio` (el formulario actual); `/corridas/:id` → `Corrida` (el cuadro). `/` redirige a `/corridas`.
- `web/src/pages/MisCorridas.tsx` (nuevo): tabla densa — Nombre (`archivo` + fecha) · nº ítems · nº por revisar · estado · acciones. Botón **"Nueva corrida"** (→ `/corridas/nueva`). Clic en fila → `/corridas/:id`. Botón **Eliminar** por fila con **confirmación** (`DELETE` → recarga la lista).
- `web/src/api/corridas.ts`: `listarCorridas()`, `eliminarCorrida(id)`. Tipo `CorridaResumen {id, archivo, creada_en, estado, n_items, n_revision}` en `tipos.ts`.
- Tras armar una corrida (formulario), navega a `/corridas/:id` (igual que hoy). Persisten entre reinicios; se borran solo con el botón.

## 3. Corrida "viva"

- Ya funciona en su mayoría: `Corrida.tsx` pide `getCorrida(id)` al montar, y el backend recostea con el precio vigente en cada `vista_corrida`. Volver desde la lista o tras editar un precio en Insumos muestra los números **al día**.
- Descargar el cuadro **no bloquea**: `generar_cuadro` puede seguir registrando `cuadro_path`/`estado`, pero el `estado` ya **no implica** que la corrida se congele — sigue re-costeable hasta que se elimine. (Sin cambio de comportamiento en el re-costeo; solo se documenta que "finalizada" no bloquea.)

## 4. Composición desplegable inline (cualquier estado)

- `web/src/components/corrida/TablaItems.tsx`: **toda fila** gana un control de **desplegar** (chevron). Al expandir, pide `getItem(corridaId, seq)` (`detalle_item`, que ya devuelve la composición costeada para cualquier estado) y muestra **inline debajo de la fila** una tabla densa: insumo · unidad · rendimiento · precio vigente · costo · calidad de cruce.
- Para filas **REVIEW/NEW**, el desplegable **además** muestra los candidatos (con score) y el botón **Confirmar** → `confirmar(id, seq, apu_codigo)` → refresca la corrida. Esto **unifica** el `PanelRevision` (dialog) dentro del desplegable: se elimina el dialog y queda una sola forma de interactuar.
- `Corrida.tsx` deja de pasar `onSelectItem`/abrir dialog; el manejo de detalle/confirmar vive en el desplegable de `TablaItems`. (El componente `PanelRevision.tsx` se retira.)
- Caché ligero: la composición de un ítem ya pedida se puede guardar en estado local para no re-pedir al colapsar/expandir; opcional.

## Errores y pruebas

**Errores:**
- Turno faltante → `400` con mensaje claro (qué falta).
- `GET /api/corridas/{id}`/`DELETE` sobre id inexistente → `404`.
- Eliminar una corrida que se está viendo → la lista la quita; si el usuario está en `/corridas/:id` de una borrada, `getCorrida` da 404 → mostrar aviso y volver a la lista.

**Pruebas:**
- **Backend (pytest + TestClient):**
  - `read_licitacion(require_turno=True)`: archivo sin columna de turno → `ValueError`; archivo con turno por fila → ok (mezcla DIURNO/NOCTURNO respetada).
  - `listar_corridas` (orden, n_items/n_revision) y `eliminar_corrida` (cascade: tras borrar, `get_corrida`→None y no quedan `corrida_item`).
  - Endpoints `GET /api/corridas` y `DELETE /api/corridas/{id}` (incl. 404).
  - Los tests existentes siguen verdes (read_licitacion retrocompatible; endpoints conservados).
- **Frontend (Vitest, ligero):** el armado del nombre (`archivo` + fecha); opcional un test del estado del desplegable.
- Verificación en vivo (controlador): lista, eliminar, desplegar composición de un ítem AUTO, y re-costeo tras editar un precio.

## Dependencias nuevas

Ninguna.

## Criterios de aceptación

1. Subir una lista sin columna de turno → error claro; con turno por fila → arma respetando DIURNO/NOCTURNO por ítem; ya no hay selector global de turno.
2. `/corridas` muestra "mis corridas" (nombre = archivo + fecha) con nº ítems / por revisar / estado; "Nueva corrida" abre el formulario; clic abre el cuadro; eliminar (con confirmación) la quita y arrastra sus ítems.
3. Volver a una corrida o editar un precio en Insumos y reabrirla muestra los números recosteados; descargar no la bloquea; persiste entre reinicios.
4. En el cuadro, cualquier fila se despliega inline mostrando su composición (insumos + rendimientos + costo); en REVIEW/NEW el desplegable trae candidatos + confirmar.
5. `pytest` verde (sin regresiones); el matcher/costeo no cambió.
