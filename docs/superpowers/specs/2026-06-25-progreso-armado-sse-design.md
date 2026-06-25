# Diseño — Progreso del armado (log en consola + SSE)

> Fecha: 2026-06-25
> Estado: aprobado para implementación
> Contexto: el armado de una corrida (`POST /api/corridas` / `/api/sample`) es una
> única petición síncrona sin feedback; con listas grandes la UI se queda en
> "Armando…" sin moverse. Esta etapa agrega **visibilidad** (no optimización).

## Objetivo

Que el usuario vea el avance del armado, de dos formas:
1. **Log en la consola del server** — `[i/total] descripción` por ítem, en la terminal de uvicorn.
2. **Progreso en el navegador** vía streaming SSE sobre el POST: la página muestra
   "Armando… 45/300 — \<descripción\>" y lo escribe en `console.log`.

**Explícitamente fuera de alcance (es etapa 2):** optimizar el matcher, quitar el doble
match, pre-filtrado, armado en segundo plano, edición de APUs, presupuesto por capítulos.
Esta etapa NO cambia la lógica de matching/costeo ni el rendimiento — solo añade progreso.

## Decisión de transporte

`EventSource` (SSE clásico) es solo GET y no puede subir el archivo multipart. Por eso el
progreso viaja **en streaming sobre el mismo POST** (`StreamingResponse`, `text/event-stream`),
leído en el frontend con `fetch` + lectura del cuerpo en streaming (no `EventSource`). Una sola
llamada cubre subida + progreso + resultado, igual para "subir archivo" y "usar ejemplo".

## Backend

### 1. Generador de progreso — `apu_tool/servicio/corridas.py`
- Nuevo generador `construir_corrida_stream(alm, archivo, items, turno, use_ai)` que hace el
  armado y va emitiendo tuplas de evento:
  - por cada ítem: `("progress", {"i": i, "total": total, "descripcion": desc})` (1-based `i`);
  - al final: `("done", {"id": cid, "resumen": <totales de vista_corrida>})`.
  - Dentro del loop imprime el **log de consola**: `print(f"  [{i}/{total}] {desc[:60]}", flush=True)`
    (mismo estilo que la CLI) → visible en la terminal de uvicorn.
- `construir_corrida(alm, archivo, items, turno, use_ai) -> int` se reescribe como envoltorio
  fino que **drena** `construir_corrida_stream`, ignora los `progress` y devuelve el `id` del
  evento `done`. Comportamiento idéntico para tests y llamadas existentes (DRY).
- La lógica de armado por ítem (matcher + `assemble_item` + snapshot) NO cambia.

### 2. Endpoints de streaming — `apu_tool/servicio/rutas.py`
- `POST /api/corridas/stream` (multipart: `turno`, `use_ai`, `archivo`) y
  `POST /api/sample/stream`.
- **Primero parsean** (seed guard + temp file + `read_licitacion`, o `generate_sample` para el
  ejemplo) **antes** de empezar a streamear; si el Excel está mal o no hay ítems → `400` limpio,
  como hoy.
- Luego devuelven `StreamingResponse(..., media_type="text/event-stream")` cuyo generador
  recorre `construir_corrida_stream` y emite, por cada tupla, líneas SSE:
  - `event: progress\ndata: {json}\n\n`
  - `event: done\ndata: {json}\n\n`
  - si algo falla a mitad: `event: error\ndata: {"detail": "..."}\n\n`
- Los endpoints actuales no-stream (`POST /api/corridas`, `POST /api/sample`) **se conservan**
  (los tests del backend v1 dependen de ellos; no estorban).

## Frontend

### 3. Cliente — `web/src/api/corridas.ts`
- `crearCorridaStream(form: FormData, onProgress: (p: {i:number,total:number,descripcion:string}) => void): Promise<{id:number, resumen:Totales}>`
- `crearSampleStream(onProgress): Promise<{id, resumen}>`
- Ambos: `fetch` al `/stream`, leen `response.body.getReader()`, decodifican e interpretan los
  bloques SSE (`event:`/`data:`), llaman `onProgress(...)` por cada `progress`, resuelven con el
  payload de `done`, y lanzan error en `event: error` o respuesta no-ok.

### 4. Página — `web/src/pages/CorridasInicio.tsx`
- Usa las versiones streaming. Estado `progreso: {i,total,descripcion} | null`.
- En cada `onProgress`: actualiza el botón/etiqueta a **"Armando… {i}/{total} — {descripcion}"**
  y hace `console.log(...)` (el log del navegador que pediste).
- En `done`: navega a `/corridas/{id}`. En error: toast (igual que hoy).

## Errores y pruebas

**Errores:**
- Parseo (archivo ilegible / sin ítems) → `400` antes de abrir el stream.
- Fallo a mitad del armado → `event: error` con `detail`; el frontend muestra toast y limpia el
  estado de carga.

**Pruebas:**
- **Backend (pytest + TestClient):**
  - `construir_corrida_stream` con el almacén-fixture: emite exactamente `total` eventos
    `progress` (con `i` de 1..total) y un `done` final con un `id` válido.
  - `construir_corrida` (drenado) sigue devolviendo el `id` (los tests existentes pasan sin cambio).
  - `POST /api/corridas/stream` vía `TestClient`: leer el contenido streameado y aseverar que
    contiene líneas `event: progress` y un `event: done` con `id`.
- **Frontend (Vitest):** test del parser de eventos SSE — dados chunks de texto
  (`event: progress\ndata: {...}\n\n` …), produce la secuencia de eventos correcta y el `done`.
- `python -m pytest tests/ -q` permanece verde.

## Dependencias nuevas

Ninguna. `StreamingResponse` es de FastAPI/Starlette (ya presente); el frontend usa `fetch`
nativo. Sin librerías nuevas.

## Criterios de aceptación

1. Al armar (subir archivo o "usar ejemplo"), la terminal de uvicorn imprime `[i/total] desc`
   por ítem mientras arma.
2. La página muestra "Armando… {i}/{total} — {descripcion}" que avanza, y lo loguea en la
   consola del navegador.
3. Al terminar, navega al cuadro de la corrida (`/corridas/{id}`).
4. Un Excel inválido sigue dando un error claro (400 → toast), sin colgar la UI.
5. `pytest` verde, incluido el test del stream; el matcher/costeo no cambió (sin optimización).
