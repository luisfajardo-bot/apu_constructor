# Estados de corrida (activa / congelada) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar un `modo` por corrida — **activa** (sigue la biblioteca: re-lee composición + precios vigentes) vs **congelada** (foto inmutable: snapshot de composición + precios) — reversible, con auto-congelado al generar el cuadro y solo-lectura mientras está congelada.

**Architecture:** Columnas nuevas `corrida.modo` y `corrida_item.snapshot_json` (dual-backend, migración idempotente). El servicio `corridas.py` decide el costeo por `modo`: activa re-lee `alm.apus.get_components`; congelada reconstruye la vista desde el `snapshot_json`. `congelar`/`activar` cambian el modo; `generar_cuadro` auto-congela; `confirmar` se bloquea si congelada. El frontend agrega badge + botones + solo-lectura.

**Tech Stack:** Python 3, FastAPI, SQLite + Postgres (psycopg), pytest + TestClient, React + TypeScript + Vite + Vitest.

## Global Constraints

- **Dual-backend:** cada método de datos nuevo va en SQLite (`corridas_db.py`) **y** Postgres (`corridas_pg.py`) y se declara en el `Protocol` `RepositorioCorridas` (`repositorio.py`).
- **Migración idempotente y segura para prod:** SQLite via `ALTER TABLE ADD COLUMN` en `init_schema` (patrón de `duracion_ms`); Postgres via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` en `db/pg/corridas.sql`. `Almacen.init_schema()` corre en cada arranque → migra sin perder corridas. Corridas existentes → `modo='activa'` (por el DEFAULT).
- **`modo` es ortogonal a `estado`** (`armando`/`en_revision`/`finalizada`), que no cambia.
- **Rol** `consulta` para `congelar`/`activar` (consistente con confirmar/eliminar corrida, que hoy son `consulta`).
- **Congelada = solo lectura:** `confirmar` (reasignar/confirmar) → `409` si la corrida está congelada.
- **Invariante #1:** `snapshot_json` tiene dinero → dato interno, **NUNCA** a la IA. No importar `ai_assist` en `servicio/`. `componentes_json` sigue money-free.
- **Español** en nombres/mensajes. Persistencia aislada en `apu_tool/datos/`.
- **Solo la última foto:** recongelar sobrescribe el snapshot (sin versionado).
- Comandos web desde `web/`. Verificación: backend `python -m pytest tests/ -q`; web `npx tsc --noEmit`, `npx vitest run`, `npm run build`.

---

### Task 1: Datos — columnas `modo`/`snapshot_json`, migración, `CorridaMeta.modo`, `set_modo`

**Files:**
- Modify: `db/corridas.sql`, `db/pg/corridas.sql`
- Modify: `apu_tool/nucleo/models.py`
- Modify: `apu_tool/datos/corridas_db.py`, `apu_tool/datos/pg/corridas_pg.py`
- Modify: `apu_tool/datos/repositorio.py`
- Test: `tests/test_corridas_db.py`

**Interfaces:**
- Produces: `corrida.modo` (TEXT default 'activa') y `corrida_item.snapshot_json` (TEXT nullable) en ambos esquemas; `CorridaMeta.modo: str = "activa"`; `set_modo(corrida_id, modo)` en `RepositorioCorridas`, `CorridasDB`, `CorridasPg`; migración idempotente en `CorridasDB.init_schema`.

- [ ] **Step 1: Write the failing test**

En `tests/test_corridas_db.py`, al final, agregar (usa `sqlite3`, `CorridasDB`, `CorridaMeta` ya importados):

```python
def test_migracion_agrega_modo_y_snapshot(tmp_path):
    # Base "vieja" sin modo/snapshot_json: init_schema debe agregarlas sin perder la corrida.
    p = tmp_path / "old.db"
    conn = sqlite3.connect(p)
    conn.executescript(
        "CREATE TABLE corrida (id INTEGER PRIMARY KEY AUTOINCREMENT, creada_en TEXT, "
        "archivo TEXT, turno_def TEXT, use_ai INTEGER, estado TEXT, cuadro_path TEXT, duracion_ms INTEGER);"
        "CREATE TABLE corrida_item (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "corrida_id INTEGER NOT NULL REFERENCES corrida(id) ON DELETE CASCADE, seq INTEGER, "
        "item_json TEXT, status TEXT, apu_codigo TEXT, apu_nombre TEXT, unidad TEXT, shift TEXT, "
        "origen TEXT, confianza REAL, explicacion TEXT, componentes_json TEXT, candidatos_json TEXT);")
    conn.execute("INSERT INTO corrida (creada_en, archivo, turno_def, use_ai, estado) "
                 "VALUES ('x','a.xlsx','DIURNO',0,'en_revision')")
    conn.commit(); conn.close()
    db = CorridasDB(p)
    db.init_schema()   # agrega modo + snapshot_json (idempotente)
    db.init_schema()   # 2ª vez: no falla
    metas = db.listar_corridas()
    assert len(metas) == 1 and metas[0].modo == "activa"      # existente → activa por DEFAULT
    db.set_modo(metas[0].id, "congelada")
    assert db.get_corrida(metas[0].id).modo == "congelada"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_corridas_db.py::test_migracion_agrega_modo_y_snapshot -v`
Expected: FAIL (`CorridaMeta` no tiene `modo` / `set_modo` no existe / la columna no existe).

- [ ] **Step 3: Add the columns to both schemas**

En `db/corridas.sql`, en `CREATE TABLE IF NOT EXISTS corrida (...)`, agregar tras `duracion_ms   INTEGER`:
```sql
  duracion_ms   INTEGER,
  modo          TEXT NOT NULL DEFAULT 'activa'
```
y en `CREATE TABLE IF NOT EXISTS corrida_item (...)`, agregar tras `candidatos_json  TEXT`:
```sql
  candidatos_json  TEXT,
  snapshot_json    TEXT
```

En `db/pg/corridas.sql`: lo mismo en los `CREATE TABLE` (agregar `modo TEXT NOT NULL DEFAULT 'activa'` a `corridas.corrida` y `snapshot_json TEXT` a `corridas.corrida_item`), y al **final del archivo** agregar la migración idempotente para bases existentes:
```sql
ALTER TABLE corridas.corrida ADD COLUMN IF NOT EXISTS modo TEXT NOT NULL DEFAULT 'activa';
ALTER TABLE corridas.corrida_item ADD COLUMN IF NOT EXISTS snapshot_json TEXT;
```

- [ ] **Step 4: Add `modo` to `CorridaMeta`**

En `apu_tool/nucleo/models.py`, en `class CorridaMeta`, agregar el campo tras `duracion_ms`:
```python
    duracion_ms: Optional[int] = None
    modo: str = "activa"
```

- [ ] **Step 5: SQLite migration + modo + set_modo (`corridas_db.py`)**

En `CorridasDB.init_schema`, tras el bloque de `duracion_ms`, agregar:
```python
            if "modo" not in cols:
                conn.execute("ALTER TABLE corrida ADD COLUMN modo TEXT NOT NULL DEFAULT 'activa'")
            icols = {r["name"] for r in conn.execute("PRAGMA table_info(corrida_item)").fetchall()}
            if "snapshot_json" not in icols:
                conn.execute("ALTER TABLE corrida_item ADD COLUMN snapshot_json TEXT")
```
En `_insert_corrida`, incluir `modo`:
```python
    def _insert_corrida(self, conn: sqlite3.Connection, meta: CorridaMeta) -> int:
        cur = conn.execute(
            "INSERT INTO corrida (creada_en, archivo, turno_def, use_ai, estado, "
            "cuadro_path, duracion_ms, modo) VALUES (?,?,?,?,?,?,?,?)",
            (meta.creada_en, meta.archivo, meta.turno_def,
             None if meta.use_ai is None else int(meta.use_ai),
             meta.estado, meta.cuadro_path, meta.duracion_ms, meta.modo))
        return int(cur.lastrowid)
```
En `_row_to_meta`, leer `modo` (con respaldo por si algún row viejo lo trae null):
```python
            estado=r["estado"], cuadro_path=r["cuadro_path"],
            duracion_ms=r["duracion_ms"], modo=(r["modo"] or "activa"))
```
Agregar el método `set_modo` (junto a `set_estado`):
```python
    def set_modo(self, corrida_id: int, modo: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE corrida SET modo=? WHERE id=?", (modo, int(corrida_id)))
```

- [ ] **Step 6: Postgres migration parity + modo + set_modo (`corridas_pg.py`)**

En `CorridasPg._insert_corrida`, incluir `modo`:
```python
    def _insert_corrida(self, conn, meta: CorridaMeta) -> int:
        cur = conn.execute(
            "INSERT INTO corridas.corrida (creada_en, archivo, turno_def, use_ai, estado, "
            "cuadro_path, duracion_ms, modo) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (meta.creada_en, meta.archivo, meta.turno_def,
             None if meta.use_ai is None else int(meta.use_ai),
             meta.estado, meta.cuadro_path, meta.duracion_ms, meta.modo))
        return int(cur.fetchone()["id"])
```
En `_row_to_meta`:
```python
            estado=r["estado"], cuadro_path=r["cuadro_path"],
            duracion_ms=r["duracion_ms"], modo=(r["modo"] or "activa"))
```
Agregar `set_modo`:
```python
    def set_modo(self, corrida_id: int, modo: str) -> None:
        with self.cx.connection() as conn:
            conn.execute("UPDATE corridas.corrida SET modo=%s WHERE id=%s", (modo, int(corrida_id)))
```
(La migración PG vive en `db/pg/corridas.sql` del Step 3; `CorridasPg.init_schema` la corre.)

- [ ] **Step 7: Declare `set_modo` in the Protocol**

En `apu_tool/datos/repositorio.py`, en `class RepositorioCorridas(Protocol)`, tras `def set_estado(...)`:
```python
    def set_modo(self, corrida_id: int, modo: str) -> None: ...
```

- [ ] **Step 8: Run test to verify it passes**

Run: `python -m pytest tests/test_corridas_db.py -v`
Expected: PASS (nuevo test + los existentes de corridas, incl. `test_migracion_agrega_duracion_ms`).

- [ ] **Step 9: Commit**

```bash
git add db/corridas.sql db/pg/corridas.sql apu_tool/nucleo/models.py apu_tool/datos/corridas_db.py apu_tool/datos/pg/corridas_pg.py apu_tool/datos/repositorio.py tests/test_corridas_db.py
git commit -m "feat(datos): corrida.modo + corrida_item.snapshot_json (migración dual-backend) + set_modo"
```

---

### Task 2: Datos — `set_snapshot` / `get_snapshots` (SQLite + PG + Protocol)

**Files:**
- Modify: `apu_tool/datos/corridas_db.py`, `apu_tool/datos/pg/corridas_pg.py`, `apu_tool/datos/repositorio.py`
- Test: `tests/test_corridas_db.py`

**Interfaces:**
- Consumes: la columna `corrida_item.snapshot_json` (Task 1).
- Produces: `set_snapshot(corrida_id, seq, payload: dict) -> None` (serializa a JSON) y `get_snapshots(corrida_id) -> dict[int, dict]` (seq → payload, solo ítems con snapshot) en `RepositorioCorridas`, `CorridasDB`, `CorridasPg`.

- [ ] **Step 1: Write the failing test**

En `tests/test_corridas_db.py`, al final, agregar (usa `_almacen_tmp`, `_fila`, `CorridaMeta` ya definidos en el archivo):

```python
def test_set_get_snapshots(tmp_path):
    alm = _almacen_tmp(tmp_path)
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="x", archivo="a.xlsx", turno_def="DIURNO",
        use_ai=False, estado="en_revision"))
    alm.corridas.guardar_items(cid, [_fila(0), _fila(1)])
    alm.corridas.set_snapshot(cid, 0, {
        "composicion": [{"insumo_codigo": "100", "insumo_nombre": "CEMENTO", "unidad": "KG",
                         "rendimiento": 2.0, "precio_unitario": 1000.0, "fuente_precio": "PRECIO IDU",
                         "costo": 2000.0, "calidad_cruce": "exacto"}],
        "costo_unitario": 2000.0})
    snaps = alm.corridas.get_snapshots(cid)
    assert set(snaps.keys()) == {0}                       # solo el ítem con snapshot
    assert snaps[0]["costo_unitario"] == 2000.0
    assert snaps[0]["composicion"][0]["insumo_codigo"] == "100"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_corridas_db.py::test_set_get_snapshots -v`
Expected: FAIL (`set_snapshot`/`get_snapshots` no existen).

- [ ] **Step 3: Implement in SQLite (`corridas_db.py`)**

Tras `set_modo`, agregar:
```python
    def set_snapshot(self, corrida_id: int, seq: int, payload: dict) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE corrida_item SET snapshot_json=? WHERE corrida_id=? AND seq=?",
                (json.dumps(payload, ensure_ascii=False), int(corrida_id), int(seq)))

    def get_snapshots(self, corrida_id: int) -> dict[int, dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT seq, snapshot_json FROM corrida_item "
                "WHERE corrida_id=? AND snapshot_json IS NOT NULL", (int(corrida_id),)).fetchall()
        return {r["seq"]: json.loads(r["snapshot_json"]) for r in rows}
```

- [ ] **Step 4: Implement in Postgres (`corridas_pg.py`)**

Tras `set_modo`, agregar:
```python
    def set_snapshot(self, corrida_id: int, seq: int, payload: dict) -> None:
        with self.cx.connection() as conn:
            conn.execute(
                "UPDATE corridas.corrida_item SET snapshot_json=%s WHERE corrida_id=%s AND seq=%s",
                (json.dumps(payload, ensure_ascii=False), int(corrida_id), int(seq)))

    def get_snapshots(self, corrida_id: int) -> dict[int, dict]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT seq, snapshot_json FROM corridas.corrida_item "
                "WHERE corrida_id=%s AND snapshot_json IS NOT NULL", (int(corrida_id),)).fetchall()
        return {r["seq"]: json.loads(r["snapshot_json"]) for r in rows}
```

- [ ] **Step 5: Declare in the Protocol (`repositorio.py`)**

En `RepositorioCorridas`, tras `set_modo`:
```python
    def set_snapshot(self, corrida_id: int, seq: int, payload: dict) -> None: ...
    def get_snapshots(self, corrida_id: int) -> dict[int, dict]: ...
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_corridas_db.py::test_set_get_snapshots -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apu_tool/datos/corridas_db.py apu_tool/datos/pg/corridas_pg.py apu_tool/datos/repositorio.py tests/test_corridas_db.py
git commit -m "feat(datos): set_snapshot/get_snapshots en CorridasDB/CorridasPg + Protocol"
```

---

### Task 3: Servicio — costeo según modo (activa re-lee biblioteca; congelada desde snapshot) + `modo` en vista/detalle/listar

**Files:**
- Modify: `apu_tool/servicio/corridas.py`
- Test: `tests/test_servicio_corridas.py`

**Interfaces:**
- Consumes: `CorridaMeta.modo` (Task 1); `get_snapshots` (Task 2); `alm.apus.get_components`, `PricingEngine.cost_components`, `CostedComponent`, `AssembledApu` (ya existen).
- Produces: costeo por modo dentro de `vista_corrida`/`detalle_item`; `_costear_row` re-lee la biblioteca (activa); `_assembled_desde_snapshot(row, snap)`; `vista_corrida`/`listar_corridas` incluyen `"modo"`.

- [ ] **Step 1: Write the failing test**

En `tests/test_servicio_corridas.py`, agregar (imports arriba del archivo: `from apu_tool.datos.almacen import Almacen`; `from apu_tool.nucleo.models import Apu, ApuComponent, Insumo, CorridaMeta, CorridaItemRow, LicitacionItem`; `from apu_tool.servicio import corridas`):

```python
def _alm_con_apu(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([Insumo("100", "CEMENTO", "KG", "MAT", 1000.0, "PRECIO IDU")])
    alm.apus.crear_apu(Apu("A1", "MURO", "M2", "DIURNO", "ESTR"),
                       [ApuComponent("A1", "DIURNO", "100", "CEMENTO", "KG", 2.0, 0.0)])
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="x", archivo="a.xlsx", turno_def="DIURNO",
        use_ai=False, estado="en_revision"))
    item = LicitacionItem(item="1", descripcion="muro", unidad="M2", cantidad=1.0,
                          precio_contractual=10000.0, shift="DIURNO")
    row = CorridaItemRow(
        seq=0, item=item, status="matched", apu_codigo="A1", apu_nombre="MURO",
        unidad="M2", shift="DIURNO", origen="historico", confianza=1.0, explicacion="",
        componentes=[{"insumo_codigo": "100", "insumo_nombre": "CEMENTO", "unidad": "KG",
                      "rendimiento": 2.0}], candidatos=[])
    alm.corridas.guardar_items(cid, [row])
    return alm, cid


def test_activa_relee_composicion_de_biblioteca(tmp_path):
    alm, cid = _alm_con_apu(tmp_path)
    v1 = corridas.vista_corrida(alm, cid)
    assert v1["modo"] == "activa"
    assert v1["items"][0]["costo_unitario"] == 2000.0        # 2.0 * 1000
    # editar el APU en la biblioteca: rendimiento 2.0 -> 3.0
    alm.apus.editar_apu(Apu("A1", "MURO", "M2", "DIURNO", "ESTR"),
                        [ApuComponent("A1", "DIURNO", "100", "CEMENTO", "KG", 3.0, 0.0)])
    v2 = corridas.vista_corrida(alm, cid)
    assert v2["items"][0]["costo_unitario"] == 3000.0        # activa re-leyó la biblioteca
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_servicio_corridas.py::test_activa_relee_composicion_de_biblioteca -v`
Expected: FAIL (`vista_corrida` no trae `"modo"`; el costo no cambia porque hoy costea desde `row.componentes`).

- [ ] **Step 3: Reemplazar `_costear_row` por el costeo activa (re-lee la biblioteca)**

En `apu_tool/servicio/corridas.py`, reemplazar la función `_costear_row` por:
```python
def _costear_row(alm: Almacen, row: CorridaItemRow) -> AssembledApu:
    """Costeo ACTIVA: re-lee la composición del APU asignado desde la biblioteca y
    costea con precios vigentes. Si no hay apu_codigo o el APU fue borrado, usa la
    composición guardada del ítem (respaldo)."""
    pricing = PricingEngine(alm)
    costed = None
    if row.apu_codigo:
        lib = alm.apus.get_components(row.apu_codigo, row.shift)
        if lib:
            costed, total = pricing.cost_components(lib)
    if costed is None:
        comps = [ApuComponent(
            apu_codigo=row.apu_codigo or "", shift=row.shift,
            insumo_codigo=c["insumo_codigo"], insumo_nombre=c["insumo_nombre"],
            unidad=c["unidad"], rendimiento=c["rendimiento"],
            precio_unitario_hist=0.0) for c in row.componentes]
        costed, total = pricing.cost_components(comps)
    return AssembledApu(
        item=row.item, apu_codigo=row.apu_codigo, apu_nombre=row.apu_nombre,
        unidad=row.unidad or row.item.unidad, shift=row.shift, componentes=costed,
        costo_unitario=total, status=MatchStatus(row.status),
        confianza=row.confianza, explicacion=row.explicacion, origen=row.origen)


def _assembled_desde_snapshot(row: CorridaItemRow, snap: dict) -> AssembledApu:
    """Reconstruye un AssembledApu desde un snapshot congelado (composición + costos fijos)."""
    comps = [CostedComponent(
        insumo_codigo=c["insumo_codigo"], insumo_nombre=c["insumo_nombre"],
        unidad=c["unidad"], rendimiento=c["rendimiento"],
        precio_unitario=c["precio_unitario"], fuente_precio=c["fuente_precio"],
        costo=c["costo"], calidad_cruce=c.get("calidad_cruce", "exacto"))
        for c in snap.get("composicion", [])]
    return AssembledApu(
        item=row.item, apu_codigo=row.apu_codigo, apu_nombre=row.apu_nombre,
        unidad=row.unidad or row.item.unidad, shift=row.shift, componentes=comps,
        costo_unitario=snap["costo_unitario"], status=MatchStatus(row.status),
        confianza=row.confianza, explicacion=row.explicacion, origen=row.origen)
```
Agregar `CostedComponent` al import de `apu_tool.nucleo.models` (arriba del archivo):
```python
from apu_tool.nucleo.models import (
    ApuComponent, AssembledApu, CostedComponent, CorridaItemRow, CorridaMeta,
    LicitacionItem, MatchStatus,
)
```

- [ ] **Step 4: Branch `vista_corrida` y `detalle_item` por modo; agregar `modo`**

Reemplazar `vista_corrida` por:
```python
def vista_corrida(alm: Almacen, corrida_id: int) -> Optional[dict]:
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    rows = alm.corridas.get_items(corrida_id)
    if meta.modo == "congelada":
        snaps = alm.corridas.get_snapshots(corrida_id)
        ensambles = [_assembled_desde_snapshot(r, snaps[r.seq]) if r.seq in snaps
                     else _costear_row(alm, r) for r in rows]
    else:
        ensambles = [_costear_row(alm, r) for r in rows]
    items = [_vista_item(ens, r.seq, r.status) for ens, r in zip(ensambles, rows)]
    tot_c = sum(i["contractual_total"] for i in items)
    tot_k = sum(i["costo_total"] for i in items)
    n_rev = sum(1 for i in items if i["status"] in ("review", "new"))
    return {
        "id": meta.id, "archivo": meta.archivo, "estado": meta.estado, "modo": meta.modo,
        "duracion_ms": meta.duracion_ms, "items": items,
        "totales": {"contractual": tot_c, "costo": tot_k, "margen": tot_c - tot_k,
                    "margen_pct": ((tot_c - tot_k) / tot_c) if tot_c else 0.0,
                    "n_items": len(items), "n_revision": n_rev},
    }
```
Reemplazar el cuerpo de `detalle_item` para respetar el modo:
```python
def detalle_item(alm: Almacen, corrida_id: int, seq: int) -> Optional[dict]:
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    row = alm.corridas.get_item(corrida_id, seq)
    if row is None:
        return None
    if meta.modo == "congelada":
        snaps = alm.corridas.get_snapshots(corrida_id)
        ens = _assembled_desde_snapshot(row, snaps[seq]) if seq in snaps else _costear_row(alm, row)
    else:
        ens = _costear_row(alm, row)
    return {
        "seq": row.seq, "descripcion": row.item.descripcion,
        "apu_codigo": row.apu_codigo, "apu_nombre": row.apu_nombre,
        "status": row.status, "explicacion": row.explicacion,
        "candidatos": row.candidatos,
        "composicion": [{
            "insumo_codigo": c.insumo_codigo, "insumo_nombre": c.insumo_nombre,
            "unidad": c.unidad, "rendimiento": c.rendimiento,
            "precio_unitario": c.precio_unitario, "fuente_precio": c.fuente_precio,
            "costo": c.costo, "calidad_cruce": c.calidad_cruce}
            for c in ens.componentes],
        "costo_unitario": ens.costo_unitario,
    }
```
En `listar_corridas`, agregar `"modo": meta.modo` al dict de cada corrida:
```python
        out.append({"id": meta.id, "archivo": meta.archivo, "creada_en": meta.creada_en,
                    "estado": meta.estado, "modo": meta.modo, "duracion_ms": meta.duracion_ms,
                    "n_items": len(items), "n_revision": n_rev})
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_servicio_corridas.py -v`
Expected: PASS (nuevo test + los existentes de servicio de corridas).

- [ ] **Step 6: Commit**

```bash
git add apu_tool/servicio/corridas.py tests/test_servicio_corridas.py
git commit -m "feat(corridas): costeo según modo (activa re-lee biblioteca; congelada desde snapshot) + modo en vista/listar"
```

---

### Task 4: Servicio — `congelar` / `activar` + `generar_cuadro` auto-congela + `confirmar` bloqueado

**Files:**
- Modify: `apu_tool/servicio/corridas.py`
- Test: `tests/test_servicio_corridas.py`

**Interfaces:**
- Consumes: `set_modo`, `set_snapshot`, `get_snapshots` (Tasks 1-2); `_costear_row`, `_assembled_desde_snapshot`, `vista_corrida` (Task 3).
- Produces: `congelar(alm, corrida_id) -> dict | None`; `activar(alm, corrida_id) -> dict | None`; `class CorridaCongelada(Exception)`; `generar_cuadro` auto-congela; `confirmar_item` lanza `CorridaCongelada` si la corrida está congelada.

- [ ] **Step 1: Write the failing test**

En `tests/test_servicio_corridas.py`, agregar (reusa `_alm_con_apu` de Task 3):

```python
import pytest


def test_congelar_fija_todo_y_activar_libera(tmp_path):
    alm, cid = _alm_con_apu(tmp_path)
    v = corridas.congelar(alm, cid)
    assert v["modo"] == "congelada"
    congelado = v["items"][0]["costo_unitario"]              # 2000.0
    # cambiar el APU y el precio del insumo: la congelada NO debe moverse
    alm.apus.editar_apu(Apu("A1", "MURO", "M2", "DIURNO", "ESTR"),
                        [ApuComponent("A1", "DIURNO", "100", "CEMENTO", "KG", 5.0, 0.0)])
    alm.precios.set_precio("100", 9999.0, "COMPRAS")
    assert corridas.vista_corrida(alm, cid)["items"][0]["costo_unitario"] == congelado
    # activar → vuelve a seguir la biblioteca
    v2 = corridas.activar(alm, cid)
    assert v2["modo"] == "activa"
    assert corridas.vista_corrida(alm, cid)["items"][0]["costo_unitario"] == 5.0 * 9999.0


def test_confirmar_bloqueado_si_congelada(tmp_path):
    alm, cid = _alm_con_apu(tmp_path)
    corridas.congelar(alm, cid)
    with pytest.raises(corridas.CorridaCongelada):
        corridas.confirmar_item(alm, cid, 0, "A1", "DIURNO")


def test_generar_cuadro_auto_congela(tmp_path):
    alm, cid = _alm_con_apu(tmp_path)
    out = corridas.generar_cuadro(alm, cid)
    assert out is not None
    meta = alm.corridas.get_corrida(cid)
    assert meta.modo == "congelada" and meta.estado == "finalizada"
    assert alm.corridas.get_snapshots(cid)                   # hay snapshots
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_servicio_corridas.py -k "congelar or confirmar_bloqueado or auto_congela" -v`
Expected: FAIL (`congelar`/`activar`/`CorridaCongelada` no existen; `generar_cuadro` no congela).

- [ ] **Step 3: Add `CorridaCongelada`, `congelar`, `activar`**

En `apu_tool/servicio/corridas.py`, tras los imports, agregar la excepción:
```python
class CorridaCongelada(Exception):
    """Se intentó modificar (confirmar/reasignar) una corrida en modo congelada."""
    def __init__(self, corrida_id: int):
        super().__init__(f"La corrida {corrida_id} está congelada (solo lectura).")
        self.corrida_id = corrida_id
```
Y agregar las funciones (por ejemplo, tras `detalle_item`):
```python
def congelar(alm: Almacen, corrida_id: int) -> Optional[dict]:
    """Fija una foto inmutable: costea la vista ACTIVA ahora y guarda el snapshot de
    cada ítem; luego marca modo='congelada'. Idempotente (recongelar = foto nueva)."""
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    for r in alm.corridas.get_items(corrida_id):
        ens = _costear_row(alm, r)
        payload = {"composicion": [{
            "insumo_codigo": c.insumo_codigo, "insumo_nombre": c.insumo_nombre,
            "unidad": c.unidad, "rendimiento": c.rendimiento,
            "precio_unitario": c.precio_unitario, "fuente_precio": c.fuente_precio,
            "costo": c.costo, "calidad_cruce": c.calidad_cruce} for c in ens.componentes],
            "costo_unitario": ens.costo_unitario}
        alm.corridas.set_snapshot(corrida_id, r.seq, payload)
    alm.corridas.set_modo(corrida_id, "congelada")
    return vista_corrida(alm, corrida_id)


def activar(alm: Almacen, corrida_id: int) -> Optional[dict]:
    """Vuelve la corrida a seguir la biblioteca. El snapshot queda pero se ignora."""
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    alm.corridas.set_modo(corrida_id, "activa")
    return vista_corrida(alm, corrida_id)
```

- [ ] **Step 4: Block `confirmar_item` when congelada; auto-freeze in `generar_cuadro`**

En `confirmar_item`, al inicio (antes de `get_item`):
```python
def confirmar_item(alm: Almacen, corrida_id: int, seq: int, apu_codigo: str,
                   shift: Optional[str] = None) -> Optional[dict]:
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    if meta.modo == "congelada":
        raise CorridaCongelada(corrida_id)
    row = alm.corridas.get_item(corrida_id, seq)
    if row is None:
        return None
    # ... resto igual ...
```
Reemplazar `generar_cuadro` para auto-congelar y escribir desde la foto congelada:
```python
def generar_cuadro(alm: Almacen, corrida_id: int) -> Optional[Path]:
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    config.ensure_dirs()
    congelar(alm, corrida_id)                     # guarda snapshots + modo='congelada'
    rows = alm.corridas.get_items(corrida_id)
    snaps = alm.corridas.get_snapshots(corrida_id)
    assembled = [_assembled_desde_snapshot(r, snaps[r.seq]) if r.seq in snaps
                 else _costear_row(alm, r) for r in rows]
    stamp = meta.creada_en.replace(":", "").replace("-", "").replace("T", "_")
    out = config.OUTPUT_DIR / f"cuadro_corrida_{corrida_id}_{stamp}.xlsx"
    write_report(assembled, out)
    alm.corridas.set_cuadro(corrida_id, str(out))
    alm.corridas.set_estado(corrida_id, "finalizada")
    return out
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_servicio_corridas.py -v`
Expected: PASS (los 3 nuevos + los existentes).

- [ ] **Step 6: Commit**

```bash
git add apu_tool/servicio/corridas.py tests/test_servicio_corridas.py
git commit -m "feat(corridas): congelar/activar + generar_cuadro auto-congela + confirmar bloqueado si congelada"
```

---

### Task 5: API — endpoints `congelar`/`activar` + `409` al confirmar si congelada

**Files:**
- Modify: `apu_tool/servicio/rutas.py`
- Test: `tests/test_api_corridas.py`

**Interfaces:**
- Consumes: `svc.congelar`, `svc.activar`, `svc.CorridaCongelada`, `svc.confirmar_item` (Task 4).
- Produces: `POST /api/corridas/{cid}/congelar` y `/activar` (rol `consulta`); `confirmar` → `409` si congelada; `modo` en las respuestas de vista/lista (ya viene del servicio).

- [ ] **Step 1: Write the failing test**

En `tests/test_api_corridas.py`, agregar (mira los imports/fixtures existentes del archivo para armar una corrida; usa el mismo `cliente(create_app(almacen=alm))` y siembra un APU + un ítem como en `_alm_con_apu`). Test:

```python
def test_congelar_activar_y_confirmar_409(tmp_path):
    from apu_tool.datos.almacen import Almacen
    from apu_tool.nucleo.models import (Apu, ApuComponent, Insumo, CorridaMeta,
                                        CorridaItemRow, LicitacionItem)
    from apu_tool.servicio.app import create_app
    from tests.conftest import cliente

    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([Insumo("100", "CEMENTO", "KG", "MAT", 1000.0, "PRECIO IDU")])
    alm.apus.crear_apu(Apu("A1", "MURO", "M2", "DIURNO", "ESTR"),
                       [ApuComponent("A1", "DIURNO", "100", "CEMENTO", "KG", 2.0, 0.0)])
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="x", archivo="a.xlsx", turno_def="DIURNO",
        use_ai=False, estado="en_revision"))
    item = LicitacionItem(item="1", descripcion="muro", unidad="M2", cantidad=1.0,
                          precio_contractual=10000.0, shift="DIURNO")
    alm.corridas.guardar_items(cid, [CorridaItemRow(
        seq=0, item=item, status="matched", apu_codigo="A1", apu_nombre="MURO", unidad="M2",
        shift="DIURNO", origen="historico", confianza=1.0, explicacion="",
        componentes=[{"insumo_codigo": "100", "insumo_nombre": "CEMENTO", "unidad": "KG",
                      "rendimiento": 2.0}], candidatos=[])])
    cli = cliente(create_app(almacen=alm), rol="consulta")

    r = cli.post(f"/api/corridas/{cid}/congelar")
    assert r.status_code == 200 and r.json()["modo"] == "congelada"
    # confirmar en congelada → 409
    assert cli.post(f"/api/corridas/{cid}/items/0/confirmar",
                    json={"apu_codigo": "A1", "shift": "DIURNO"}).status_code == 409
    # activar → modo activa; ahora confirmar funciona
    assert cli.post(f"/api/corridas/{cid}/activar").json()["modo"] == "activa"
    assert cli.post(f"/api/corridas/{cid}/items/0/confirmar",
                    json={"apu_codigo": "A1", "shift": "DIURNO"}).status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api_corridas.py::test_congelar_activar_y_confirmar_409 -v`
Expected: FAIL (rutas `congelar`/`activar` no existen → `404`/`405`; confirmar no da `409`).

- [ ] **Step 3: Add the endpoints and the 409 mapping (`rutas.py`)**

En `apu_tool/servicio/rutas.py`, reemplazar el endpoint `confirmar` por (envuelve la llamada para mapear `CorridaCongelada` → `409`):
```python
@router.post("/corridas/{cid}/items/{seq}/confirmar")
def confirmar(cid: int, seq: int, body: ConfirmarIn,
              alm: Almacen = Depends(get_almacen),
              _: object = Depends(requiere_rol("consulta"))):
    try:
        v = svc.confirmar_item(alm, cid, seq, body.apu_codigo, body.shift)
    except svc.CorridaCongelada:
        raise HTTPException(status_code=409,
                            detail="La corrida está congelada; actívala para modificar.")
    if v is None:
        raise HTTPException(status_code=404, detail="Ítem no encontrado.")
    return v


@router.post("/corridas/{cid}/congelar")
def congelar(cid: int, alm: Almacen = Depends(get_almacen),
             _: object = Depends(requiere_rol("consulta"))):
    v = svc.congelar(alm, cid)
    if v is None:
        raise HTTPException(status_code=404, detail="Corrida no encontrada.")
    return v


@router.post("/corridas/{cid}/activar")
def activar(cid: int, alm: Almacen = Depends(get_almacen),
            _: object = Depends(requiere_rol("consulta"))):
    v = svc.activar(alm, cid)
    if v is None:
        raise HTTPException(status_code=404, detail="Corrida no encontrada.")
    return v
```

- [ ] **Step 4: Run test + full backend suite**

Run: `python -m pytest tests/test_api_corridas.py -v` → PASS.
Run: `python -m pytest tests/ -q` → todo verde (incluye `test_servicio_privacidad`, seed, contrato).

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/rutas.py tests/test_api_corridas.py
git commit -m "feat(api): POST /corridas/{id}/congelar y /activar; confirmar 409 si congelada"
```

---

### Task 6: Frontend — cliente `congelarCorrida`/`activarCorrida` + `modo` en tipos

**Files:**
- Modify: `web/src/api/corridas.ts`, `web/src/lib/tipos.ts`
- Test: `web/src/api/corridas.estados.test.ts` (Create)

**Interfaces:**
- Consumes: endpoints de Task 5.
- Produces: `congelarCorrida(id): Promise<CorridaDetalle>`, `activarCorrida(id): Promise<CorridaDetalle>`; `modo: string` en `CorridaDetalle` y `CorridaResumen`.

- [ ] **Step 1: Write the failing test**

Crear `web/src/api/corridas.estados.test.ts`:
```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { congelarCorrida, activarCorrida } from "@/api/corridas";
import * as client from "@/api/client";

describe("corridas: congelar/activar", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("congelarCorrida hace POST a /corridas/{id}/congelar", async () => {
    const spy = vi.spyOn(client, "apiPost").mockResolvedValue({} as never);
    await congelarCorrida(7);
    expect(spy).toHaveBeenCalledWith("/corridas/7/congelar");
  });

  it("activarCorrida hace POST a /corridas/{id}/activar", async () => {
    const spy = vi.spyOn(client, "apiPost").mockResolvedValue({} as never);
    await activarCorrida(7);
    expect(spy).toHaveBeenCalledWith("/corridas/7/activar");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (desde `web/`): `npx vitest run src/api/corridas.estados.test.ts`
Expected: FAIL (funciones no existen).

- [ ] **Step 3: Add the client functions (`corridas.ts`)**

En `web/src/api/corridas.ts`, tras `confirmar(...)`, agregar:
```typescript
export function congelarCorrida(id: number): Promise<CorridaDetalle> {
  return apiPost<CorridaDetalle>(`/corridas/${id}/congelar`);
}

export function activarCorrida(id: number): Promise<CorridaDetalle> {
  return apiPost<CorridaDetalle>(`/corridas/${id}/activar`);
}
```
(`apiPost` y `CorridaDetalle` ya están importados en el archivo.)

- [ ] **Step 4: Add `modo` to the types (`tipos.ts`)**

En `web/src/lib/tipos.ts`, agregar `modo: string;` a `CorridaDetalle` y a `CorridaResumen`:
```typescript
export interface CorridaResumen {
  id: number;
  archivo: string;
  creada_en: string;
  estado: string;
  modo: string;
  n_items: number;
  n_revision: number;
  duracion_ms: number | null;
}
```
```typescript
export interface CorridaDetalle {
  id: number;
  archivo: string;
  estado: string;
  modo: string;
  items: ItemCuadro[];
  totales: Totales;
  duracion_ms: number | null;
}
```

- [ ] **Step 5: Run test + typecheck**

Run (desde `web/`): `npx vitest run src/api/corridas.estados.test.ts` → PASS.
Run (desde `web/`): `npx tsc --noEmit` → sin errores.

- [ ] **Step 6: Commit**

```bash
git add web/src/api/corridas.ts web/src/lib/tipos.ts web/src/api/corridas.estados.test.ts
git commit -m "feat(web): cliente congelarCorrida/activarCorrida + modo en tipos de corrida"
```

---

### Task 7: Frontend — badge + botones en `Corrida.tsx`, `readOnly` en `TablaItems`, `modo` en `MisCorridas`

**Files:**
- Modify: `web/src/pages/Corrida.tsx`, `web/src/components/corrida/TablaItems.tsx`, `web/src/pages/MisCorridas.tsx`

**Interfaces:**
- Consumes: `congelarCorrida`/`activarCorrida` (Task 6); `modo` en `CorridaDetalle`/`CorridaResumen` (Task 6).
- Produces: badge Activa/Congelada + botones Congelar/Activar en `Corrida.tsx`; `TablaItems` acepta `readOnly` y deshabilita reasignar/confirmar; `MisCorridas` muestra el modo.

- [ ] **Step 1: `TablaItems.tsx` — prop `readOnly` que deshabilita las acciones**

En `web/src/components/corrida/TablaItems.tsx`:
1. En `interface TablaItemsProps`, agregar `readOnly?: boolean;`.
2. En la firma del componente, aceptarla: `export default function TablaItems({ corridaId, items, onConfirmado, readOnly = false }: TablaItemsProps)`.
3. Pasarla al detalle expandido: en el render de `<DetalleExpandido ... />`, agregar `readOnly={readOnly}`.
4. En `interface DetalleExpandidoProps`, agregar `readOnly: boolean;` y aceptarla en la firma de `DetalleExpandido`.
5. En `DetalleExpandido`, deshabilitar las acciones cuando `readOnly`:
   - En el `<BuscadorApu ... />` de "Cambiar APU": `disabled={confirmando !== null || readOnly}`.
   - En los botones "Elegir" de candidatos: `disabled={confirmando !== null || readOnly}`.
   - En el botón "Confirmar APU actual": `disabled={confirmando !== null || readOnly}`.
   - Justo antes del bloque "Cambiar APU", agregar el aviso:
     ```tsx
     {readOnly && (
       <p className="text-xs text-muted-foreground italic">
         Corrida congelada (solo lectura). Activá la corrida para modificar.
       </p>
     )}
     ```

- [ ] **Step 2: `Corrida.tsx` — badge + botones Congelar/Activar + pasar `readOnly`**

En `web/src/pages/Corrida.tsx`:
1. Imports: agregar `congelarCorrida, activarCorrida` a la línea `import { getCorrida, descargarCuadro } from "@/api/corridas";`.
2. Un handler para cambiar el modo (dentro del componente, tras los `useState`):
```tsx
  async function cambiarModo(accion: "congelar" | "activar") {
    try {
      const fn = accion === "congelar" ? congelarCorrida : activarCorrida;
      const actualizada = await fn(corridaId);
      setCorrida(actualizada);
      toast.success(accion === "congelar" ? "Corrida congelada" : "Corrida activada");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "No se pudo cambiar el modo.");
    }
  }
```
3. En el header (dentro del `{!live && (...)}` que hoy contiene el botón "Descargar cuadro"), reemplazar ese botón suelto por el grupo badge + Activar/Congelar + Descargar. `data` ya es `CorridaDetalle` tras el guard de null, así que `data.modo` es de acceso directo (sin cast):
```tsx
        {!live && (
          <div className="flex items-center gap-2">
            <span className={`text-[11px] font-semibold rounded-full px-2 py-0.5 ${
              data.modo === "congelada" ? "bg-blue-100 text-blue-800" : "bg-green-100 text-green-800"}`}>
              {data.modo === "congelada" ? "Congelada" : "Activa"}
            </span>
            <Button size="sm" variant="outline"
              onClick={() => cambiarModo(data.modo === "congelada" ? "activar" : "congelar")}>
              {data.modo === "congelada" ? "Activar" : "Congelar"}
            </Button>
            <Button size="sm" variant="outline"
              onClick={() => descargarCuadro(corridaId).catch((e) =>
                toast.error(e instanceof Error ? e.message : "No se pudo descargar el cuadro."))}>
              Descargar cuadro
            </Button>
          </div>
        )}
```
4. Pasar `readOnly` a la tabla: `<TablaItems corridaId={corridaId} items={data.items} onConfirmado={(c) => setCorrida(c)} readOnly={data.modo === "congelada"} />`.
   - Nota: el objeto `live` (armado en vivo) no tiene `modo`; usar `data.modo === "congelada"` es `false` en ese caso (el objeto live no setea modo → `undefined !== "congelada"`), lo cual es correcto (durante el armado no está congelada). Añadir `modo: "activa"` al objeto `live` que arma `Corrida.tsx` para que TypeScript no se queje (el tipo `CorridaDetalle` ahora exige `modo`).

- [ ] **Step 3: `MisCorridas.tsx` — columna Modo**

En `web/src/pages/MisCorridas.tsx`:
1. En el `<thead>`, agregar una `<th>` tras la de "Estado": `<th style={styles.th}>Modo</th>`.
2. En el `<tbody>`, tras la celda de estado, agregar:
```tsx
                  <td style={styles.td}>
                    <span style={{ ...styles.badge, ...(c.modo === "congelada"
                      ? { background: "#bee3f8", color: "#2a4365" }
                      : { background: "#c6f6d5", color: "#276749" }) }}>
                      {c.modo === "congelada" ? "Congelada" : "Activa"}
                    </span>
                  </td>
```

- [ ] **Step 4: Typecheck, tests, build**

Run (desde `web/`): `npx tsc --noEmit` → sin errores.
Run (desde `web/`): `npx vitest run` → verde (incluye el test de Task 6 y los preexistentes).
Run (desde `web/`): `npm run build` → OK.

- [ ] **Step 5: Manual smoke** (out-of-scope para un subagente; lo coordina el controlador con el usuario)

Abrir una corrida: ver el badge "Activa"; **Congelar** → badge "Congelada" + acciones de reasignación deshabilitadas + aviso; editar el APU en la biblioteca → la corrida congelada no cambia; **Activar** → vuelve a seguir; en "Mis corridas" se ve el modo.

- [ ] **Step 6: Commit**

```bash
git add web/src/pages/Corrida.tsx web/src/components/corrida/TablaItems.tsx web/src/pages/MisCorridas.tsx
git commit -m "feat(web): badge/botones Activa-Congelada, solo-lectura en congelada, modo en Mis corridas"
```

---

## Verificación final

- [ ] Backend: `python -m pytest tests/ -q` → verde (incl. `test_servicio_privacidad`, migración, corridas).
- [ ] (Opcional con Postgres) `TEST_DATABASE_URL=... python -m pytest tests/test_repositorios_contrato.py tests/test_corridas_db.py -q` — la migración PG vía `ALTER ... IF NOT EXISTS` corre en `init_schema`.
- [ ] Web (desde `web/`): `npx tsc --noEmit`, `npx vitest run`, `npm run build` → verde/OK.
- [ ] Invariante #1: `snapshot_json` (con dinero) nunca se pasa a la IA; `servicio/` no importa `ai_assist`.
- [ ] Smoke manual de congelar/activar (coordinar server local, como en features anteriores).
- [ ] Despliegue: el `ALTER ... ADD COLUMN IF NOT EXISTS` migra la tabla de prod en el arranque; corridas existentes → `activa`, sin pérdida. NO merge/push a prod sin OK explícito del usuario.
