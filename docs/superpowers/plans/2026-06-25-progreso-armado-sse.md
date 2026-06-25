# Progreso del armado (log + SSE) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mostrar el avance del armado de una corrida — log `[i/total]` en la consola del server y progreso en el navegador vía streaming SSE sobre el POST — sin cambiar la lógica de matching/costeo.

**Architecture:** Se extrae el loop de armado a un generador `construir_corrida_stream` que emite eventos `progress`/`done` e imprime el log; `construir_corrida` pasa a ser un envoltorio que lo drena y devuelve el id (comportamiento idéntico). Endpoints nuevos `/stream` devuelven `StreamingResponse(text/event-stream)`. El frontend lee el stream con `fetch` y muestra el avance.

**Tech Stack:** Python, FastAPI `StreamingResponse` (ya disponible), React/TS, `fetch` nativo. Sin dependencias nuevas.

## Global Constraints

- **CERO regresiones.** No se toca la lógica de matching ni de costeo. El armado por ítem es idéntico.
- `construir_corrida(alm, archivo, items, turno_def, use_ai) -> int` debe **conservar su firma y comportamiento** (devuelve el id). Tests existentes pasan sin cambio.
- Los endpoints **no-stream** `POST /api/corridas` y `POST /api/sample` **se conservan tal cual**.
- **Invariante #1:** ningún archivo en `apu_tool/servicio/` contiene la cadena `"ai_assist"`.
- Español en mensajes/logs de usuario.
- `python -m pytest tests/ -q` debe quedar **verde** tras cada tarea de backend; el frontend compila con `npm run build` (0 errores TS) y el test del parser pasa con Vitest.
- Formato SSE: bloques `event: <tipo>\ndata: <json>\n\n`. Tipos: `progress` `{i,total,descripcion}` (i de 1..total), `done` `{id,resumen}`, `error` `{detail}`.

---

## File Structure

```
apu_tool/servicio/corridas.py   # + construir_corrida_stream (generador); construir_corrida pasa a drenarlo
apu_tool/servicio/rutas.py      # + POST /corridas/stream y /sample/stream (StreamingResponse) + helper _event_stream
tests/test_servicio_corridas.py # + tests del generador y de la regresión de construir_corrida
tests/test_api_corridas.py      # + test de los endpoints /stream
web/src/lib/tipos.ts            # + tipo Progreso
web/src/api/corridas.ts         # + parseSse, streamCorrida, crearCorridaStream, crearSampleStream
web/src/pages/CorridasInicio.tsx# usa las versiones streaming; muestra "Armando i/total" + console.log
web/src/api/corridas.sse.test.ts# [nuevo] Vitest del parser SSE
```

---

### Task 1: Generador `construir_corrida_stream` + envoltorio `construir_corrida`

**Files:**
- Modify: `apu_tool/servicio/corridas.py`
- Test: `tests/test_servicio_corridas.py`

**Interfaces:**
- Consumes: `ApuAdvisor`, `Assembler`, `CorridaMeta`, `CorridaItemRow`, `_estructura`, `vista_corrida` (mismo módulo), `datetime`.
- Produces:
  - `construir_corrida_stream(alm, archivo, items, turno_def, use_ai)` → generador que hace `yield ("progress", {"i":int,"total":int,"descripcion":str})` por ítem y al final `yield ("done", {"id":int,"resumen":dict})`. Imprime `  [i/total] desc` por ítem.
  - `construir_corrida(alm, archivo, items, turno_def, use_ai) -> int` (sin cambios de firma; ahora drena el generador y devuelve el id).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_servicio_corridas.py  (agregar; reutiliza el fixture _almacen_seed ya existente)
from apu_tool.nucleo.models import LicitacionItem


def test_construir_corrida_stream_emite_progreso_y_done(tmp_path):
    alm = _almacen_seed(tmp_path)
    items = [LicitacionItem(item="1", descripcion="Concreto clase D", unidad="M3",
                            cantidad=10.0, precio_contractual=400000.0, shift="DIURNO")]
    eventos = list(svc.construir_corrida_stream(alm, "lic.xlsx", items, "DIURNO", False))
    tipos = [e[0] for e in eventos]
    assert tipos == ["progress", "done"]
    assert eventos[0][1] == {"i": 1, "total": 1, "descripcion": "Concreto clase D"}
    assert isinstance(eventos[1][1]["id"], int)
    assert eventos[1][1]["resumen"]["n_items"] == 1


def test_construir_corrida_sigue_devolviendo_id(tmp_path):
    # REGRESIÓN: el envoltorio debe comportarse igual que antes.
    alm = _almacen_seed(tmp_path)
    items = [LicitacionItem(item="1", descripcion="Concreto clase D", unidad="M3",
                            cantidad=10.0, precio_contractual=400000.0, shift="DIURNO")]
    cid = svc.construir_corrida(alm, "lic.xlsx", items, "DIURNO", False)
    assert isinstance(cid, int)
    assert svc.vista_corrida(alm, cid)["totales"]["n_items"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_servicio_corridas.py -q`
Expected: FAIL con `AttributeError: module ... has no attribute 'construir_corrida_stream'`.

- [ ] **Step 3: Refactor — reemplazar `construir_corrida` por el generador + envoltorio**

En `apu_tool/servicio/corridas.py`, **reemplaza la función `construir_corrida` actual** por estas dos (el cuerpo del loop es idéntico al actual; solo se le agregan el `print` y los `yield`):

```python
def construir_corrida_stream(alm: Almacen, archivo: str, items: list[LicitacionItem],
                             turno_def: str, use_ai: Optional[bool]):
    """Arma la corrida emitiendo progreso. Genera ('progress', {...}) por ítem y
    ('done', {'id', 'resumen'}) al final. La lógica de armado por ítem es idéntica
    a la versión no-stream; solo se añaden el log de consola y los yields."""
    advisor = ApuAdvisor(enabled=use_ai)
    assembler = Assembler(alm, advisor=advisor)
    corrida_id = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en=datetime.now().isoformat(timespec="seconds"),
        archivo=archivo, turno_def=turno_def, use_ai=use_ai,
        estado="en_revision", cuadro_path=None))
    filas: list[CorridaItemRow] = []
    total = len(items)
    for seq, item in enumerate(items):
        i = seq + 1
        print(f"  [{i}/{total}] {item.descripcion[:60]}", flush=True)
        result = assembler.matcher.match(item)
        candidatos = [{"apu_codigo": c.apu_codigo, "apu_nombre": c.apu_nombre,
                       "score": c.score, "motivo": c.motivo}
                      for c in result.candidatos]
        ens = assembler.assemble_item(item)
        filas.append(CorridaItemRow(
            seq=seq, item=item, status=ens.status.value, apu_codigo=ens.apu_codigo,
            apu_nombre=ens.apu_nombre, unidad=ens.unidad, shift=ens.shift,
            origen=ens.origen, confianza=ens.confianza, explicacion=ens.explicacion,
            componentes=_estructura(ens.componentes), candidatos=candidatos))
        yield ("progress", {"i": i, "total": total, "descripcion": item.descripcion})
    alm.corridas.guardar_items(corrida_id, filas)
    resumen = vista_corrida(alm, corrida_id)["totales"]
    yield ("done", {"id": corrida_id, "resumen": resumen})


def construir_corrida(alm: Almacen, archivo: str, items: list[LicitacionItem],
                      turno_def: str, use_ai: Optional[bool]) -> int:
    """Envoltorio no-stream: drena el generador e ignora el progreso; devuelve el id."""
    corrida_id = -1
    for evento, payload in construir_corrida_stream(alm, archivo, items, turno_def, use_ai):
        if evento == "done":
            corrida_id = payload["id"]
    return corrida_id
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_servicio_corridas.py -q`
Expected: PASS.

- [ ] **Step 5: Run full suite (regresión)**

Run: `python -m pytest tests/ -q`
Expected: PASS (todo verde; los endpoints no-stream y sus tests siguen funcionando porque `construir_corrida` se comporta igual).

- [ ] **Step 6: Commit**

```bash
git add apu_tool/servicio/corridas.py tests/test_servicio_corridas.py
git commit -m "feat(servicio): construir_corrida_stream (progreso) + construir_corrida lo drena"
```

---

### Task 2: Endpoints `/api/corridas/stream` y `/api/sample/stream`

**Files:**
- Modify: `apu_tool/servicio/rutas.py`
- Test: `tests/test_api_corridas.py`

**Interfaces:**
- Consumes: `svc.construir_corrida_stream` (Task 1), `read_licitacion`, `ensure_seeded`, `generate_sample`, `get_almacen`.
- Produces: `POST /api/corridas/stream` (multipart) y `POST /api/sample/stream`, ambos `StreamingResponse(media_type="text/event-stream")`; helper `_event_stream(gen)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_corridas.py  (agregar; reutiliza _cli y _xlsx_lic ya existentes)
def test_corridas_stream_emite_progreso_y_done(tmp_path):
    cli, _ = _cli(tmp_path)
    lic = _xlsx_lic(tmp_path)
    with open(lic, "rb") as f:
        r = cli.post("/api/corridas/stream",
                     data={"turno": "DIURNO", "use_ai": "false"},
                     files={"archivo": ("lic.xlsx", f,
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    body = r.text
    assert "event: progress" in body
    assert "event: done" in body


def test_sample_stream_ok(tmp_path):
    cli, _ = _cli(tmp_path)
    r = cli.post("/api/sample/stream")
    assert r.status_code == 200
    assert "event: done" in r.text


def test_corridas_stream_archivo_malo_400(tmp_path):
    cli, _ = _cli(tmp_path)
    mala = tmp_path / "mala.csv"
    mala.write_text("foo,bar\n1,2\n", encoding="utf-8")
    with open(mala, "rb") as f:
        r = cli.post("/api/corridas/stream", data={"turno": "DIURNO"},
                     files={"archivo": ("mala.csv", f, "text/csv")})
    assert r.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api_corridas.py -q`
Expected: FAIL (404 en `/api/corridas/stream`).

- [ ] **Step 3: Implement**

En `apu_tool/servicio/rutas.py`:

1. Asegura los imports al inicio del archivo: agrega `import json` y cambia la línea de respuestas a
   `from fastapi.responses import FileResponse, StreamingResponse`.

2. Agrega el helper y los dos endpoints (junto a los de corridas):

```python
def _event_stream(gen):
    """Serializa los eventos del generador como SSE; cualquier fallo a mitad -> event: error."""
    try:
        for evento, payload in gen:
            yield f"event: {evento}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
    except Exception as e:  # nunca dejar el stream a medias sin avisar
        yield f"event: error\ndata: {json.dumps({'detail': str(e)})}\n\n"


@router.post("/corridas/stream")
async def crear_corrida_stream(turno: str = Form(config.SHIFT_DIURNO),
                               use_ai: Optional[bool] = Form(None),
                               archivo: UploadFile = File(...),
                               alm: Almacen = Depends(get_almacen)):
    if alm.counts().get("apus", 0) == 0:
        ensure_seeded()
    suf = Path(archivo.filename or "lic.xlsx").suffix or ".xlsx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suf) as tmp:
        tmp.write(await archivo.read())
        tmp_path = tmp.name
    try:
        items = read_licitacion(tmp_path, default_shift=turno)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        os.unlink(tmp_path)
    if not items:
        raise HTTPException(status_code=400, detail="La lista no tiene ítems legibles.")
    gen = svc.construir_corrida_stream(alm, archivo.filename or "licitacion", items, turno, use_ai)
    return StreamingResponse(_event_stream(gen), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


@router.post("/sample/stream")
def crear_sample_stream(alm: Almacen = Depends(get_almacen)):
    if alm.counts().get("apus", 0) == 0:
        ensure_seeded()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        sample_path = tmp.name
    try:
        generate_sample(out_path=Path(sample_path), alm=alm)
        items = read_licitacion(sample_path, default_shift=config.SHIFT_DIURNO)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        os.unlink(sample_path)
    if not items:
        raise HTTPException(status_code=400, detail="El ejemplo generado no tiene ítems legibles.")
    gen = svc.construir_corrida_stream(alm, "ejemplo.xlsx", items, config.SHIFT_DIURNO, False)
    return StreamingResponse(_event_stream(gen), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})
```

(No modifiques los endpoints no-stream existentes.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_api_corridas.py -q`
Expected: PASS.

- [ ] **Step 5: Run full suite**

Run: `python -m pytest tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apu_tool/servicio/rutas.py tests/test_api_corridas.py
git commit -m "feat(api): endpoints /corridas/stream y /sample/stream (SSE de progreso)"
```

---

### Task 3: Cliente de streaming + parser SSE (frontend)

**Files:**
- Modify: `web/src/lib/tipos.ts`, `web/src/api/corridas.ts`
- Test: `web/src/api/corridas.sse.test.ts`

**Interfaces:**
- Consumes: `CorridaCreada`, `Totales` (de `@/lib/tipos`).
- Produces (en `corridas.ts`, todos exportados):
  - `Progreso` tipo `{ i: number; total: number; descripcion: string }` (en `tipos.ts`).
  - `parseSse(block: string): { event: string; data: unknown } | null`
  - `crearCorridaStream(form: FormData, onProgress: (p: Progreso) => void): Promise<CorridaCreada>`
  - `crearSampleStream(onProgress: (p: Progreso) => void): Promise<CorridaCreada>`

- [ ] **Step 1: Write the failing test (Vitest)**

```ts
// web/src/api/corridas.sse.test.ts
import { parseSse } from "@/api/corridas";

test("parseSse interpreta un bloque progress", () => {
  const ev = parseSse('event: progress\ndata: {"i":3,"total":10,"descripcion":"X"}');
  expect(ev).toEqual({ event: "progress", data: { i: 3, total: 10, descripcion: "X" } });
});

test("parseSse interpreta un bloque done", () => {
  const ev = parseSse('event: done\ndata: {"id":7,"resumen":{}}');
  expect(ev?.event).toBe("done");
  expect((ev?.data as { id: number }).id).toBe(7);
});

test("parseSse devuelve null si no hay data", () => {
  expect(parseSse("event: progress")).toBeNull();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/api/corridas.sse.test.ts`
Expected: FAIL (no existe `parseSse`).

- [ ] **Step 3: Implement**

En `web/src/lib/tipos.ts` agrega:

```ts
export interface Progreso {
  i: number;
  total: number;
  descripcion: string;
}
```

En `web/src/api/corridas.ts` agrega (importa `Progreso` junto a los demás tipos de `@/lib/tipos`):

```ts
export function parseSse(block: string): { event: string; data: unknown } | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return null;
  try {
    return { event, data: JSON.parse(dataLines.join("\n")) };
  } catch {
    return null;
  }
}

async function streamCorrida(
  path: string,
  init: RequestInit,
  onProgress: (p: Progreso) => void,
): Promise<CorridaCreada> {
  const r = await fetch("/api" + path, init);
  if (!r.ok || !r.body) {
    const err = await r.json().catch(() => ({}) as { detail?: string });
    throw new Error(err.detail || r.statusText);
  }
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let done: CorridaCreada | null = null;
  for (;;) {
    const { value, done: fin } = await reader.read();
    if (fin) break;
    buf += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const ev = parseSse(buf.slice(0, idx));
      buf = buf.slice(idx + 2);
      if (!ev) continue;
      if (ev.event === "progress") onProgress(ev.data as Progreso);
      else if (ev.event === "done") done = ev.data as CorridaCreada;
      else if (ev.event === "error")
        throw new Error((ev.data as { detail?: string }).detail || "Error al armar");
    }
  }
  if (!done) throw new Error("La corrida no terminó correctamente.");
  return done;
}

export function crearCorridaStream(form: FormData, onProgress: (p: Progreso) => void) {
  return streamCorrida("/corridas/stream", { method: "POST", body: form }, onProgress);
}

export function crearSampleStream(onProgress: (p: Progreso) => void) {
  return streamCorrida("/sample/stream", { method: "POST" }, onProgress);
}
```

(Deja las funciones `crearCorrida`/`crearSample` existentes como están — no se borran.)

- [ ] **Step 4: Run test + build**

Run: `cd web && npx vitest run src/api/corridas.sse.test.ts` → PASS.
Run: `cd web && npm run build` → 0 errores TS.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/tipos.ts web/src/api/corridas.ts web/src/api/corridas.sse.test.ts
git commit -m "feat(web): cliente de streaming SSE para el armado (parseSse + crear*Stream)"
```

---

### Task 4: Página muestra el progreso + verificación

**Files:**
- Modify: `web/src/pages/CorridasInicio.tsx`

**Interfaces:**
- Consumes: `crearCorridaStream`, `crearSampleStream`, `Progreso` (Task 3).

**Contrato:**
- Reemplaza el uso de `crearCorrida`/`crearSample` por `crearCorridaStream`/`crearSampleStream`.
- Estado nuevo `const [progreso, setProgreso] = useState<Progreso | null>(null)`.
- El callback `onProgress` hace: `setProgreso(p)` y `console.log(\`[${p.i}/${p.total}] ${p.descripcion}\`)` (el log del navegador).
- El botón "Armar" muestra, mientras `cargando`: `progreso ? \`Armando… ${progreso.i}/${progreso.total}\` : "Armando…"`. Debajo del formulario, mientras `cargando && progreso`, muestra una línea pequeña: `\`${progreso.i}/${progreso.total} — ${progreso.descripcion}\``.
- `finally`: `setCargando(false); setProgreso(null)`.
- En `done` (resuelve la promesa): `navigate(\`/corridas/${id}\`)`. En error: toast (igual que hoy).
- Mantén el manejo de errores y el guard de archivo vacío existentes.

- [ ] **Step 1: Implementar** los dos handlers con las versiones streaming y el estado de progreso, según el contrato. Ejemplo del handler de archivo:

```tsx
const { id } = await crearCorridaStream(form, (p) => {
  setProgreso(p);
  console.log(`[${p.i}/${p.total}] ${p.descripcion}`);
});
navigate(`/corridas/${id}`);
```

- [ ] **Step 2: Verificar build**

Run: `cd web && npm run build`
Expected: 0 errores TS.

- [ ] **Step 3: Commit**

```bash
git add web/src/pages/CorridasInicio.tsx
git commit -m "feat(web): nueva corrida muestra progreso i/total (SSE) + console.log"
```

- [ ] **Step 4: Verificación en vivo (la hace el controlador)**

Build del frontend (`cd web && npm run build`), levantar `uvicorn`/`run_web.py`, y con `/api/sample/stream` (o subiendo un archivo) confirmar: (a) la consola del server imprime `[i/total] desc`; (b) la página muestra "Armando i/total" avanzando y loguea en la consola del navegador; (c) al terminar navega al cuadro. `python -m pytest tests/ -q` verde.

---

## Self-Review

**1. Spec coverage:**
- Log en consola del server → `print` en `construir_corrida_stream` (Task 1). ✓
- SSE sobre POST (progress/done/error) → endpoints `/stream` (Task 2) + cliente (Task 3). ✓
- Página muestra avance + console.log → Task 4. ✓
- `construir_corrida` preserva comportamiento (devuelve id); endpoints no-stream intactos → Task 1 (regresión test) + nota en Task 2. ✓
- Errores: 400 antes de streamear; `event: error` a mitad → Task 2 (test 400) + `_event_stream`. ✓
- Pruebas backend (generador, regresión, endpoints stream) y frontend (parser SSE) → Tasks 1-3. ✓
- Sin optimización / sin tocar matcher → el cuerpo del loop es idéntico; Global Constraints. ✓

**2. Placeholder scan:** sin TBD/TODO; código completo en backend y en el cliente; el contrato de Task 4 lleva el snippet clave + criterios.

**3. Type consistency:** `construir_corrida_stream` emite `("progress",{i,total,descripcion})` y `("done",{id,resumen})`, consumidos igual por `_event_stream` (Task 2) y por `streamCorrida`/`parseSse` (Task 3); `Progreso {i,total,descripcion}` coincide entre tipos.ts, el cliente y la página; `CorridaCreada {id,resumen}` reutilizado. Consistente.
