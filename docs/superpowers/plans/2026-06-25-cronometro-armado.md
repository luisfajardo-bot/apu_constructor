# Cronómetro del armado — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persistir el tiempo que tardó el armado de cada corrida y mostrarlo al terminar ("N APUs · armada en Y") en el cuadro y en "Mis corridas".

**Architecture:** `corrida` gana `duracion_ms` (con migración idempotente). `construir_corrida_stream` cronometra el armado existente y lo persiste; `vista_corrida`/`listar_corridas` lo exponen. El frontend formatea y muestra el número final (sin reloj en vivo).

**Tech Stack:** Python, SQLite; React/TS. Sin dependencias nuevas.

## Global Constraints

- **CERO regresiones.** No se toca la lógica de matching/costeo; solo se cronometra el armado existente. `construir_corrida` conserva su contrato (devuelve id).
- Migración idempotente: las corridas viejas (sin la columna) quedan con `duracion_ms` NULL → "—". `duracion_ms` nullable en todos los modelos.
- Persistencia solo en `apu_tool/datos/`. Invariante #1: sin `ai_assist` en `servicio/`.
- `python -m pytest tests/ -q` verde tras cada tarea de backend; frontend `npm run build` 0 TS.

---

## File Structure

```
db/corridas.sql                  # + columna duracion_ms en corrida
apu_tool/nucleo/models.py        # CorridaMeta gana duracion_ms
apu_tool/datos/corridas_db.py    # migración en init_schema; _row_to_meta lee duracion_ms; set_duracion
apu_tool/datos/repositorio.py    # + set_duracion en RepositorioCorridas
apu_tool/servicio/corridas.py    # construir_corrida_stream mide+persiste; vista/lista exponen duracion_ms
tests/test_corridas_db.py        # + tests set_duracion + migración
tests/test_servicio_corridas.py  # + tests stream persiste + vista/lista exponen
web/src/lib/tiempo.ts            # [nuevo] fmtDuracion
web/src/lib/tiempo.test.ts       # [nuevo] Vitest
web/src/lib/tipos.ts             # CorridaDetalle + CorridaResumen ganan duracion_ms
web/src/pages/Corrida.tsx        # encabezado "N APUs · armada en Y"
web/src/pages/MisCorridas.tsx    # columna Tiempo
```

---

### Task 1: `duracion_ms` en datos (esquema + migración + meta + set_duracion)

**Files:**
- Modify: `db/corridas.sql`, `apu_tool/nucleo/models.py`, `apu_tool/datos/corridas_db.py`, `apu_tool/datos/repositorio.py`
- Test: `tests/test_corridas_db.py` (se amplía)

**Interfaces:**
- Produces: `CorridaMeta.duracion_ms: Optional[int] = None`; `CorridasDB.set_duracion(corrida_id: int, duracion_ms: int) -> None`; `get_corrida`/`listar_corridas` devuelven `CorridaMeta` con `duracion_ms`; `init_schema` agrega la columna a DBs viejas.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_corridas_db.py  (agregar; reutiliza _almacen_tmp)
import sqlite3
from apu_tool.datos.corridas_db import CorridasDB


def test_set_duracion_y_lee(tmp_path):
    alm = _almacen_tmp(tmp_path)
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-06-25T10:00:00", archivo="a.xlsx",
        turno_def="DIURNO", use_ai=False, estado="en_revision"))
    assert alm.corridas.get_corrida(cid).duracion_ms is None
    alm.corridas.set_duracion(cid, 3210)
    assert alm.corridas.get_corrida(cid).duracion_ms == 3210
    assert alm.corridas.listar_corridas()[0].duracion_ms == 3210


def test_migracion_agrega_duracion_ms(tmp_path):
    # DB con esquema viejo (sin duracion_ms): init_schema la agrega sin romper
    p = tmp_path / "old.db"
    conn = sqlite3.connect(p)
    conn.executescript(
        "CREATE TABLE corrida (id INTEGER PRIMARY KEY AUTOINCREMENT, creada_en TEXT, "
        "archivo TEXT, turno_def TEXT, use_ai INTEGER, estado TEXT, cuadro_path TEXT);")
    conn.execute("INSERT INTO corrida (creada_en, archivo, turno_def, use_ai, estado) "
                 "VALUES ('x','a.xlsx','DIURNO',0,'en_revision')")
    conn.commit(); conn.close()
    db = CorridasDB(p)
    db.init_schema()  # debe agregar duracion_ms (idempotente) sin perder la fila
    metas = db.listar_corridas()
    assert len(metas) == 1 and metas[0].duracion_ms is None
    db.set_duracion(metas[0].id, 999)
    assert db.get_corrida(metas[0].id).duracion_ms == 999
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_corridas_db.py -q`
Expected: FAIL (`CorridaMeta` no tiene `duracion_ms` / `set_duracion` no existe).

- [ ] **Step 3: Esquema + modelo**

En `db/corridas.sql`, agrega la columna a la tabla `corrida` (al final de sus columnas, antes del cierre):

```sql
  cuadro_path   TEXT,
  duracion_ms   INTEGER
);
```

En `apu_tool/nucleo/models.py`, en `CorridaMeta` agrega el campo (tras `cuadro_path`):

```python
    cuadro_path: Optional[str] = None
    duracion_ms: Optional[int] = None
```

- [ ] **Step 4: Migración + _row_to_meta + set_duracion**

En `apu_tool/datos/corridas_db.py`:

Reemplaza `init_schema` por (agrega la migración idempotente):

```python
    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(_load_schema())
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(corrida)").fetchall()}
            if "duracion_ms" not in cols:
                conn.execute("ALTER TABLE corrida ADD COLUMN duracion_ms INTEGER")
```

En `_row_to_meta`, agrega `duracion_ms` (las filas viejas ya tienen la columna tras la migración):

```python
    def _row_to_meta(self, r: sqlite3.Row) -> CorridaMeta:
        return CorridaMeta(
            id=r["id"], creada_en=r["creada_en"], archivo=r["archivo"],
            turno_def=r["turno_def"],
            use_ai=None if r["use_ai"] is None else bool(r["use_ai"]),
            estado=r["estado"], cuadro_path=r["cuadro_path"],
            duracion_ms=r["duracion_ms"])
```

Agrega el método (junto a `set_estado`/`set_cuadro`):

```python
    def set_duracion(self, corrida_id: int, duracion_ms: int) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE corrida SET duracion_ms=? WHERE id=?",
                         (int(duracion_ms), int(corrida_id)))
```

En `apu_tool/datos/repositorio.py`, agrega a `RepositorioCorridas`:

```python
    def set_duracion(self, corrida_id: int, duracion_ms: int) -> None: ...
```

(`crear_corrida` NO cambia: `duracion_ms` no va en el INSERT, queda NULL.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_corridas_db.py -q` → PASS. Luego `python -m pytest tests/ -q` → verde.

- [ ] **Step 6: Commit**

```bash
git add db/corridas.sql apu_tool/nucleo/models.py apu_tool/datos/corridas_db.py apu_tool/datos/repositorio.py tests/test_corridas_db.py
git commit -m "feat(datos): duracion_ms en corrida (esquema + migración + set_duracion)"
```

---

### Task 2: Cronometrar en el armado + exponer en vista/lista

**Files:**
- Modify: `apu_tool/servicio/corridas.py`
- Test: `tests/test_servicio_corridas.py` (se amplía)

**Interfaces:**
- Consumes: `CorridasDB.set_duracion` (Task 1), `CorridaMeta.duracion_ms`.
- Produces: `construir_corrida_stream` persiste `duracion_ms` y su evento `done` pasa a `{"id","resumen","duracion_ms"}`; `vista_corrida` y `listar_corridas` incluyen `"duracion_ms"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_servicio_corridas.py  (agregar; reutiliza _almacen_seed)
def test_stream_persiste_duracion(tmp_path):
    alm = _almacen_seed(tmp_path)
    items = [LicitacionItem(item="1", descripcion="Concreto clase D", unidad="M3",
                            cantidad=10.0, precio_contractual=400000.0, shift="DIURNO")]
    eventos = list(svc.construir_corrida_stream(alm, "lic.xlsx", items, "DIURNO", False))
    done = next(p for ev, p in eventos if ev == "done")
    assert isinstance(done["duracion_ms"], int) and done["duracion_ms"] >= 0
    assert alm.corridas.get_corrida(done["id"]).duracion_ms == done["duracion_ms"]


def test_vista_y_lista_exponen_duracion(tmp_path):
    alm = _almacen_seed(tmp_path)
    items = [LicitacionItem(item="1", descripcion="Concreto clase D", unidad="M3",
                            cantidad=10.0, precio_contractual=400000.0, shift="DIURNO")]
    cid = svc.construir_corrida(alm, "lic.xlsx", items, "DIURNO", False)
    assert "duracion_ms" in svc.vista_corrida(alm, cid)
    assert "duracion_ms" in svc.listar_corridas(alm)[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_servicio_corridas.py -q`
Expected: FAIL (`done` no tiene `duracion_ms` / vista/lista no lo incluyen).

- [ ] **Step 3: Cronometrar en `construir_corrida_stream`**

En `apu_tool/servicio/corridas.py`: asegura `import time` arriba. En `construir_corrida_stream`, añade el cronómetro (no cambies el loop de armado):

- Justo después de crear la corrida (antes del `for`): `t0 = time.monotonic()`
- Tras `alm.corridas.guardar_items(corrida_id, filas)` y antes del `yield ("done", ...)`, reemplaza el bloque final por:

```python
    alm.corridas.guardar_items(corrida_id, filas)
    duracion_ms = round((time.monotonic() - t0) * 1000)
    alm.corridas.set_duracion(corrida_id, duracion_ms)
    resumen = vista_corrida(alm, corrida_id)["totales"]
    yield ("done", {"id": corrida_id, "resumen": resumen, "duracion_ms": duracion_ms})
```

- [ ] **Step 4: Exponer en `vista_corrida` y `listar_corridas`**

En `vista_corrida`, agrega `"duracion_ms": meta.duracion_ms` al dict que retorna (junto a `id`/`archivo`/`estado`):

```python
    return {
        "id": meta.id, "archivo": meta.archivo, "estado": meta.estado,
        "duracion_ms": meta.duracion_ms, "items": items,
        "totales": {...},
    }
```

En `listar_corridas`, agrega `"duracion_ms": meta.duracion_ms` al dict de cada corrida:

```python
        out.append({"id": meta.id, "archivo": meta.archivo, "creada_en": meta.creada_en,
                    "estado": meta.estado, "duracion_ms": meta.duracion_ms,
                    "n_items": len(items), "n_revision": n_rev})
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_servicio_corridas.py -q` → PASS. Luego `python -m pytest tests/ -q` → verde.

- [ ] **Step 6: Commit**

```bash
git add apu_tool/servicio/corridas.py tests/test_servicio_corridas.py
git commit -m "feat(servicio): cronometrar el armado y exponer duracion_ms"
```

---

### Task 3: Mostrar el tiempo en el frontend

**Files:**
- Create: `web/src/lib/tiempo.ts`, `web/src/lib/tiempo.test.ts`
- Modify: `web/src/lib/tipos.ts`, `web/src/pages/Corrida.tsx`, `web/src/pages/MisCorridas.tsx`

**Interfaces:**
- Produces: `fmtDuracion(ms: number | null | undefined): string`; `CorridaDetalle.duracion_ms`/`CorridaResumen.duracion_ms` (`number | null`).

- [ ] **Step 1: Write the failing test (Vitest)**

```ts
// web/src/lib/tiempo.test.ts
import { fmtDuracion } from "@/lib/tiempo";

test("fmtDuracion formatea null, segundos y minutos", () => {
  expect(fmtDuracion(null)).toBe("—");
  expect(fmtDuracion(undefined)).toBe("—");
  expect(fmtDuracion(3210)).toBe("3.2 s");
  expect(fmtDuracion(65000)).toBe("1 m 05 s");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/lib/tiempo.test.ts`
Expected: FAIL (no existe `fmtDuracion`).

- [ ] **Step 3: Implement `tiempo.ts`**

```ts
// web/src/lib/tiempo.ts
export function fmtDuracion(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 60000) return (ms / 1000).toFixed(1) + " s";
  const totalSeg = Math.round(ms / 1000);
  const m = Math.floor(totalSeg / 60);
  const s = totalSeg % 60;
  return `${m} m ${String(s).padStart(2, "0")} s`;
}
```

- [ ] **Step 4: Tipos + display**

En `web/src/lib/tipos.ts`: a `CorridaDetalle` y `CorridaResumen` agrega `duracion_ms: number | null`.

En `web/src/pages/Corrida.tsx`: en el encabezado (junto a los totales), muestra una línea/badge densa: **`{corrida.totales.n_items} APUs · armada en {fmtDuracion(corrida.duracion_ms)}`** (importa `fmtDuracion` de `@/lib/tiempo`; usa el nombre real del objeto de la corrida en ese componente).

En `web/src/pages/MisCorridas.tsx`: agrega una columna **"Tiempo"** a la tabla con `fmtDuracion(c.duracion_ms)` por fila (cabecera + celda; mantener densa).

- [ ] **Step 5: Verificar**

Run: `cd web && npx vitest run src/lib/tiempo.test.ts` → PASS.
Run: `cd web && npm run build` → 0 errores TS.

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/tiempo.ts web/src/lib/tiempo.test.ts web/src/lib/tipos.ts web/src/pages/Corrida.tsx web/src/pages/MisCorridas.tsx
git commit -m "feat(web): mostrar tiempo de armado (cuadro + Mis corridas)"
```

- [ ] **Step 7: Verificación en vivo (controlador)**

`cd web && npm run build`; `run_web.py`; armar por ejemplo → al terminar el cuadro muestra "N APUs · armada en Y"; Mis corridas muestra el tiempo; corridas viejas (si las hay) muestran "—". `python -m pytest tests/ -q` verde.

---

## Self-Review

**1. Spec coverage:**
- duracion_ms columna + migración idempotente → T1. ✓
- CorridaMeta.duracion_ms + set_duracion + Protocol → T1. ✓
- Cronometrar en construir_corrida_stream + done incluye duracion_ms → T2. ✓
- vista_corrida + listar_corridas exponen duracion_ms → T2. ✓
- fmtDuracion (null/seg/min) + tipos + display cuadro + Mis corridas → T3. ✓
- No-regresión: crear_corrida sin cambio (NULL), matcher/costeo intactos, construir_corrida contrato intacto, migración no rompe DBs viejas (test) → T1/T2. ✓

**2. Placeholder scan:** backend código completo; frontend fmtDuracion completo + contrato de display + Vitest. Sin TBD/TODO.

**3. Type consistency:** `duracion_ms` es `Optional[int]`/`number|null` en CorridaMeta (T1), en el dict de vista/lista (T2) y en CorridaDetalle/CorridaResumen + fmtDuracion (T3) — consistente. `set_duracion(corrida_id, duracion_ms)` igual en datos y Protocol (T1) y usado en T2. El evento `done` `{id,resumen,duracion_ms}` consistente.
