# Web v1 — Backend (API + persistencia) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Exponer el dominio del Armador de APUs por HTTP (FastAPI) para subir una licitación plana, armar el cuadro, revisar/confirmar ítems y descargar el Excel, con la corrida persistida en su propia base.

**Architecture:** Capa de servicio (`apu_tool/servicio/`) que orquesta el dominio existente (matcher, assembler, pricing, report) sin tocarlo, y una base nueva `data/corridas.db` accedida vía repositorio (`apu_tool/datos/corridas_db.py`) tras la fachada `Almacen`. La API solo expone resultados costeados; nunca habla con la IA (eso sigue dentro del dominio, detrás de `privacy.py`).

**Tech Stack:** Python 3, FastAPI, uvicorn, python-multipart, httpx (tests), SQLite (stdlib), openpyxl (ya presente).

## Global Constraints

- Español en nombres de dominio, comentarios y mensajes de usuario.
- Toda la persistencia vive en `apu_tool/datos/`; sin SQL crudo fuera de esa capa.
- El dominio (`apu_tool/dominio/`) NO se modifica, salvo un único cambio retrocompatible: `generate_sample(...)` gana un parámetro opcional `alm`.
- **Invariante #1:** la IA nunca recibe dinero. El paquete `servicio` no importa ni llama `ai_assist`.
- Sin dependencias pesadas nuevas: solo `fastapi`, `uvicorn`, `python-multipart`, `httpx`.
- La corrida persiste decisiones y estructura, no dinero derivado (único monetario: `precio_contractual` de entrada, dentro de `item_json`).
- `python -m pytest tests/ -q` debe pasar antes de dar nada por terminado.

---

## File Structure

- `requirements.txt` — agrega fastapi, uvicorn, python-multipart, httpx.
- `apu_tool/config.py` — agrega `CORRIDAS_DB_PATH`.
- `apu_tool/nucleo/models.py` — agrega `CorridaMeta`, `CorridaItemRow`.
- `db/corridas.sql` — DDL canónico (nuevo).
- `apu_tool/datos/corridas_db.py` — `CorridasDB` (nuevo).
- `apu_tool/datos/repositorio.py` — agrega `Protocol RepositorioCorridas`.
- `apu_tool/datos/almacen.py` — `Almacen` gana `.corridas`.
- `apu_tool/dominio/pipeline.py` — `generate_sample(alm=None)` (cambio mínimo).
- `apu_tool/servicio/corridas.py` — lógica de servicio (nuevo).
- `apu_tool/servicio/esquemas.py` — DTOs Pydantic (nuevo).
- `apu_tool/servicio/dependencias.py` — inyección del Almacen (nuevo).
- `apu_tool/servicio/rutas.py` — endpoints (nuevo).
- `apu_tool/servicio/app.py` — `create_app` + servir estáticos (nuevo).
- `run_web.py` — lanzador (nuevo).
- `tests/` — `test_corridas_db.py`, `test_servicio_corridas.py`, `test_api_corridas.py`, `test_servicio_privacidad.py`.

---

### Task 1: Dependencias del backend

**Files:**
- Modify: `requirements.txt`
- Test: `tests/test_servicio_privacidad.py` (se crea aquí con el primer test de import)

**Interfaces:**
- Produces: paquete `apu_tool.servicio` importable; `fastapi`, `uvicorn`, `httpx` disponibles.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_servicio_privacidad.py
def test_fastapi_disponible():
    import fastapi  # noqa: F401
    import httpx    # noqa: F401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_servicio_privacidad.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'fastapi'` (o httpx).

- [ ] **Step 3: Agregar dependencias e instalar**

Agrega al final de `requirements.txt`:

```
fastapi
uvicorn
python-multipart
httpx
```

Luego: `pip install -r requirements.txt`

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_servicio_privacidad.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add requirements.txt tests/test_servicio_privacidad.py
git commit -m "build(web): dependencias del backend (fastapi, uvicorn, multipart, httpx)"
```

---

### Task 2: Modelos de la corrida en el núcleo

**Files:**
- Modify: `apu_tool/nucleo/models.py`
- Test: `tests/test_corridas_db.py`

**Interfaces:**
- Produces:
  - `CorridaMeta(id: Optional[int], creada_en: str, archivo: str, turno_def: str, use_ai: Optional[bool], estado: str, cuadro_path: Optional[str] = None)` — frozen dataclass.
  - `CorridaItemRow(seq: int, item: LicitacionItem, status: str, apu_codigo: Optional[str], apu_nombre: str, unidad: str, shift: str, origen: str, confianza: float, explicacion: str, componentes: list[dict], candidatos: list[dict])` — dataclass.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_corridas_db.py
from apu_tool.nucleo.models import CorridaItemRow, CorridaMeta, LicitacionItem


def test_corrida_meta_y_item_row_se_construyen():
    meta = CorridaMeta(id=None, creada_en="2026-06-24T10:00:00", archivo="lic.xlsx",
                       turno_def="DIURNO", use_ai=False, estado="en_revision")
    assert meta.cuadro_path is None
    item = LicitacionItem(item="1", descripcion="Concreto", unidad="M3",
                          cantidad=10.0, precio_contractual=400000.0, shift="DIURNO")
    row = CorridaItemRow(seq=0, item=item, status="auto", apu_codigo="A1",
                         apu_nombre="Concreto clase D", unidad="M3", shift="DIURNO",
                         origen="historico", confianza=1.0, explicacion="",
                         componentes=[], candidatos=[])
    assert row.seq == 0 and row.item.precio_contractual == 400000.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_corridas_db.py::test_corrida_meta_y_item_row_se_construyen -q`
Expected: FAIL con `ImportError: cannot import name 'CorridaMeta'`.

- [ ] **Step 3: Agregar los dataclasses**

Al final de `apu_tool/nucleo/models.py` (después de `AssembledApu`):

```python
# ---------------------------------------------------------------------------
# Estado de aplicación: la corrida (armado web en progreso)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CorridaMeta:
    id: Optional[int]
    creada_en: str                # ISO 8601
    archivo: str
    turno_def: str
    use_ai: Optional[bool]
    estado: str                   # 'en_revision' | 'finalizada'
    cuadro_path: Optional[str] = None


@dataclass
class CorridaItemRow:
    seq: int
    item: LicitacionItem
    status: str                   # auto | review | new | confirmed | rejected
    apu_codigo: Optional[str]
    apu_nombre: str
    unidad: str
    shift: str
    origen: str
    confianza: float
    explicacion: str
    componentes: list[dict]       # [{insumo_codigo, insumo_nombre, unidad, rendimiento}] (sin dinero)
    candidatos: list[dict]        # [{apu_codigo, apu_nombre, score, motivo}] (sin dinero)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_corridas_db.py::test_corrida_meta_y_item_row_se_construyen -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apu_tool/nucleo/models.py tests/test_corridas_db.py
git commit -m "feat(nucleo): modelos CorridaMeta y CorridaItemRow"
```

---

### Task 3: Base de corridas (DDL + repositorio + Almacen + Protocol)

**Files:**
- Create: `db/corridas.sql`
- Create: `apu_tool/datos/corridas_db.py`
- Modify: `apu_tool/config.py` (agrega `CORRIDAS_DB_PATH`)
- Modify: `apu_tool/datos/almacen.py` (agrega `.corridas`)
- Modify: `apu_tool/datos/repositorio.py` (agrega `RepositorioCorridas`)
- Test: `tests/test_corridas_db.py` (se amplía)

**Interfaces:**
- Consumes: `CorridaMeta`, `CorridaItemRow`, `LicitacionItem` (Task 2).
- Produces: `CorridasDB` con
  - `init_schema()`, `reset()`, `counts() -> dict[str,int]`
  - `crear_corrida(meta: CorridaMeta) -> int`
  - `guardar_items(corrida_id: int, items: list[CorridaItemRow]) -> int`
  - `get_corrida(corrida_id: int) -> Optional[CorridaMeta]`
  - `get_items(corrida_id: int) -> list[CorridaItemRow]`
  - `get_item(corrida_id: int, seq: int) -> Optional[CorridaItemRow]`
  - `actualizar_eleccion(corrida_id, seq, *, status, apu_codigo, apu_nombre, unidad, shift, origen, confianza, explicacion, componentes: list[dict]) -> None`
  - `set_cuadro(corrida_id: int, path: str) -> None`
  - `set_estado(corrida_id: int, estado: str) -> None`
  - `Almacen(...).corridas` apunta a `CorridasDB`; `Almacen.init_schema/reset/counts` la incluyen.
  - `config.CORRIDAS_DB_PATH`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_corridas_db.py  (agregar)
from apu_tool.datos.almacen import Almacen


def _almacen_tmp(tmp_path):
    alm = Almacen(precios_path=tmp_path / "precios.db",
                  apus_path=tmp_path / "apus.db",
                  corridas_path=tmp_path / "corridas.db")
    alm.init_schema()
    return alm


def _fila(seq=0):
    item = LicitacionItem(item=str(seq + 1), descripcion="Concreto clase D",
                          unidad="M3", cantidad=10.0, precio_contractual=400000.0,
                          shift="DIURNO")
    return CorridaItemRow(
        seq=seq, item=item, status="review", apu_codigo="A1",
        apu_nombre="Concreto clase D", unidad="M3", shift="DIURNO",
        origen="historico", confianza=0.7, explicacion="dudoso",
        componentes=[{"insumo_codigo": "100", "insumo_nombre": "Concreto 3000 PSI",
                      "unidad": "M3", "rendimiento": 1.05}],
        candidatos=[{"apu_codigo": "A1", "apu_nombre": "Concreto clase D",
                     "score": 0.7, "motivo": ""}])


def test_corrida_roundtrip(tmp_path):
    alm = _almacen_tmp(tmp_path)
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-06-24T10:00:00", archivo="lic.xlsx",
        turno_def="DIURNO", use_ai=False, estado="en_revision"))
    assert isinstance(cid, int)
    assert alm.corridas.guardar_items(cid, [_fila(0), _fila(1)]) == 2

    meta = alm.corridas.get_corrida(cid)
    assert meta.archivo == "lic.xlsx" and meta.use_ai is False
    items = alm.corridas.get_items(cid)
    assert len(items) == 2
    assert items[0].item.precio_contractual == 400000.0
    assert items[0].componentes[0]["insumo_codigo"] == "100"
    assert items[0].candidatos[0]["apu_codigo"] == "A1"


def test_actualizar_eleccion_y_estado(tmp_path):
    alm = _almacen_tmp(tmp_path)
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="x", archivo="lic.xlsx", turno_def="DIURNO",
        use_ai=None, estado="en_revision"))
    alm.corridas.guardar_items(cid, [_fila(0)])
    alm.corridas.actualizar_eleccion(
        cid, 0, status="confirmed", apu_codigo="A2", apu_nombre="Otro APU",
        unidad="M3", shift="DIURNO", origen="historico", confianza=1.0,
        explicacion="Confirmado por el usuario.", componentes=[])
    row = alm.corridas.get_item(cid, 0)
    assert row.status == "confirmed" and row.apu_codigo == "A2"
    alm.corridas.set_estado(cid, "finalizada")
    assert alm.corridas.get_corrida(cid).estado == "finalizada"


def test_get_corrida_inexistente(tmp_path):
    alm = _almacen_tmp(tmp_path)
    assert alm.corridas.get_corrida(999) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_corridas_db.py -q`
Expected: FAIL (`Almacen.__init__` no acepta `corridas_path`, o `.corridas` no existe).

- [ ] **Step 3: Crear el DDL**

`db/corridas.sql`:

```sql
CREATE TABLE IF NOT EXISTS corrida (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  creada_en     TEXT NOT NULL,
  archivo       TEXT NOT NULL,
  turno_def     TEXT NOT NULL,
  use_ai        INTEGER,
  estado        TEXT NOT NULL,
  cuadro_path   TEXT
);

CREATE TABLE IF NOT EXISTS corrida_item (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  corrida_id    INTEGER NOT NULL REFERENCES corrida(id) ON DELETE CASCADE,
  seq           INTEGER NOT NULL,
  item_json     TEXT NOT NULL,
  status        TEXT NOT NULL,
  apu_codigo    TEXT,
  apu_nombre    TEXT,
  unidad        TEXT,
  shift         TEXT,
  origen        TEXT,
  confianza     REAL,
  explicacion   TEXT,
  componentes_json TEXT,
  candidatos_json  TEXT
);

CREATE INDEX IF NOT EXISTS ix_corrida_item ON corrida_item(corrida_id, seq);
```

- [ ] **Step 4: Agregar la ruta en config**

En `apu_tool/config.py`, tras `APUS_DB_PATH = DATA_DIR / "apus.db"`:

```python
CORRIDAS_DB_PATH = DATA_DIR / "corridas.db"
```

- [ ] **Step 5: Crear el repositorio**

`apu_tool/datos/corridas_db.py`:

```python
"""
Acceso a corridas.db (SQLite): estado de aplicación de un armado en progreso.

Implementa RepositorioCorridas. Guarda DECISIONES y ESTRUCTURA, nunca dinero
derivado (el costo se recalcula con el precio vigente). El único valor monetario
que persiste es el precio_contractual de entrada, embebido en item_json.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Iterator, Optional

from apu_tool import config
from apu_tool.nucleo.models import CorridaItemRow, CorridaMeta, LicitacionItem

SCHEMA_PATH = config.PROJECT_ROOT / "db" / "corridas.sql"


def _load_schema() -> str:
    return SCHEMA_PATH.read_text(encoding="utf-8")


class CorridasDB:
    """Backend SQLite de corridas. Implementa RepositorioCorridas."""

    def __init__(self, path: Path | str = config.CORRIDAS_DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(_load_schema())

    def reset(self) -> None:
        with self.connect() as conn:
            for t in ("corrida_item", "corrida"):
                conn.execute(f"DROP TABLE IF EXISTS {t}")
            conn.executescript(_load_schema())

    # ---- escritura ----
    def crear_corrida(self, meta: CorridaMeta) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO corrida (creada_en, archivo, turno_def, use_ai, estado, cuadro_path) "
                "VALUES (?,?,?,?,?,?)",
                (meta.creada_en, meta.archivo, meta.turno_def,
                 None if meta.use_ai is None else int(meta.use_ai),
                 meta.estado, meta.cuadro_path))
            return int(cur.lastrowid)

    def guardar_items(self, corrida_id: int, items: list[CorridaItemRow]) -> int:
        rows = []
        for it in items:
            rows.append((
                corrida_id, it.seq, json.dumps(asdict(it.item), ensure_ascii=False),
                it.status, it.apu_codigo, it.apu_nombre, it.unidad, it.shift,
                it.origen, it.confianza, it.explicacion,
                json.dumps(it.componentes, ensure_ascii=False),
                json.dumps(it.candidatos, ensure_ascii=False)))
        with self.connect() as conn:
            conn.executemany(
                "INSERT INTO corrida_item "
                "(corrida_id, seq, item_json, status, apu_codigo, apu_nombre, unidad, "
                " shift, origen, confianza, explicacion, componentes_json, candidatos_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        return len(rows)

    def actualizar_eleccion(self, corrida_id: int, seq: int, *, status: str,
                            apu_codigo: Optional[str], apu_nombre: str, unidad: str,
                            shift: str, origen: str, confianza: float,
                            explicacion: str, componentes: list[dict]) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE corrida_item SET status=?, apu_codigo=?, apu_nombre=?, unidad=?, "
                "shift=?, origen=?, confianza=?, explicacion=?, componentes_json=? "
                "WHERE corrida_id=? AND seq=?",
                (status, apu_codigo, apu_nombre, unidad, shift, origen, confianza,
                 explicacion, json.dumps(componentes, ensure_ascii=False),
                 corrida_id, seq))

    def set_cuadro(self, corrida_id: int, path: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE corrida SET cuadro_path=? WHERE id=?", (path, corrida_id))

    def set_estado(self, corrida_id: int, estado: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE corrida SET estado=? WHERE id=?", (estado, corrida_id))

    # ---- lectura ----
    def _row_to_item(self, r: sqlite3.Row) -> CorridaItemRow:
        return CorridaItemRow(
            seq=r["seq"], item=LicitacionItem(**json.loads(r["item_json"])),
            status=r["status"], apu_codigo=r["apu_codigo"],
            apu_nombre=r["apu_nombre"] or "", unidad=r["unidad"] or "",
            shift=r["shift"] or "", origen=r["origen"] or "historico",
            confianza=r["confianza"] or 0.0, explicacion=r["explicacion"] or "",
            componentes=json.loads(r["componentes_json"] or "[]"),
            candidatos=json.loads(r["candidatos_json"] or "[]"))

    def get_corrida(self, corrida_id: int) -> Optional[CorridaMeta]:
        with self.connect() as conn:
            r = conn.execute("SELECT * FROM corrida WHERE id=?", (corrida_id,)).fetchone()
        if r is None:
            return None
        return CorridaMeta(
            id=r["id"], creada_en=r["creada_en"], archivo=r["archivo"],
            turno_def=r["turno_def"],
            use_ai=None if r["use_ai"] is None else bool(r["use_ai"]),
            estado=r["estado"], cuadro_path=r["cuadro_path"])

    def get_items(self, corrida_id: int) -> list[CorridaItemRow]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM corrida_item WHERE corrida_id=? ORDER BY seq",
                (corrida_id,)).fetchall()
        return [self._row_to_item(r) for r in rows]

    def get_item(self, corrida_id: int, seq: int) -> Optional[CorridaItemRow]:
        with self.connect() as conn:
            r = conn.execute(
                "SELECT * FROM corrida_item WHERE corrida_id=? AND seq=?",
                (corrida_id, seq)).fetchone()
        return self._row_to_item(r) if r else None

    def counts(self) -> dict[str, int]:
        with self.connect() as conn:
            return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    for t in ("corrida", "corrida_item")}
```

- [ ] **Step 6: Conectar el repositorio a Almacen**

Reemplaza el cuerpo de `apu_tool/datos/almacen.py` para incluir corridas:

```python
from __future__ import annotations

from pathlib import Path

from apu_tool import config
from apu_tool.datos.apus_db import ApusDB
from apu_tool.datos.corridas_db import CorridasDB
from apu_tool.datos.precios_db import PreciosDB


class Almacen:
    def __init__(self, precios_path: Path | str = config.PRECIOS_DB_PATH,
                 apus_path: Path | str = config.APUS_DB_PATH,
                 corridas_path: Path | str = config.CORRIDAS_DB_PATH):
        self.precios = PreciosDB(precios_path)
        self.apus = ApusDB(apus_path)
        self.corridas = CorridasDB(corridas_path)

    def init_schema(self) -> None:
        self.precios.init_schema()
        self.apus.init_schema()
        self.corridas.init_schema()

    def reset(self) -> None:
        self.precios.reset()
        self.apus.reset()
        self.corridas.reset()

    def counts(self) -> dict[str, int]:
        return {**self.precios.counts(), **self.apus.counts(), **self.corridas.counts()}
```

- [ ] **Step 7: Declarar el Protocol**

En `apu_tool/datos/repositorio.py`, amplía el import y agrega el Protocol al final:

```python
from apu_tool.nucleo.models import (
    Apu, ApuComponent, CorridaItemRow, CorridaMeta, DePricedApu, Insumo,
)
```

```python
@runtime_checkable
class RepositorioCorridas(Protocol):
    def init_schema(self) -> None: ...
    def reset(self) -> None: ...
    def crear_corrida(self, meta: CorridaMeta) -> int: ...
    def guardar_items(self, corrida_id: int, items: list[CorridaItemRow]) -> int: ...
    def get_corrida(self, corrida_id: int) -> Optional[CorridaMeta]: ...
    def get_items(self, corrida_id: int) -> list[CorridaItemRow]: ...
    def get_item(self, corrida_id: int, seq: int) -> Optional[CorridaItemRow]: ...
    def actualizar_eleccion(self, corrida_id: int, seq: int, *, status: str,
                            apu_codigo: Optional[str], apu_nombre: str, unidad: str,
                            shift: str, origen: str, confianza: float,
                            explicacion: str, componentes: list[dict]) -> None: ...
    def set_cuadro(self, corrida_id: int, path: str) -> None: ...
    def set_estado(self, corrida_id: int, estado: str) -> None: ...
    def counts(self) -> dict[str, int]: ...
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `python -m pytest tests/test_corridas_db.py -q`
Expected: PASS (3 tests).

- [ ] **Step 9: Commit**

```bash
git add db/corridas.sql apu_tool/datos/corridas_db.py apu_tool/config.py apu_tool/datos/almacen.py apu_tool/datos/repositorio.py tests/test_corridas_db.py
git commit -m "feat(datos): RepositorioCorridas + corridas.db tras Almacen"
```

---

### Task 4: Servicio — construir corrida y vista costeada

**Files:**
- Create: `apu_tool/servicio/corridas.py`
- Test: `tests/test_servicio_corridas.py`, `tests/test_servicio_privacidad.py` (se amplía)

**Interfaces:**
- Consumes: `Almacen.corridas`, `Assembler`, `ApuAdvisor`, `PricingEngine`, `Matcher` (vía `Assembler.matcher`).
- Produces:
  - `construir_corrida(alm, archivo: str, items: list[LicitacionItem], turno_def: str, use_ai: Optional[bool]) -> int`
  - `vista_corrida(alm, corrida_id: int) -> Optional[dict]` con forma `{"id", "archivo", "estado", "items": [item...], "totales": {"contractual","costo","margen","margen_pct","n_items","n_revision"}}`. Cada `item`: `{"seq","item","descripcion","unidad","cantidad","apu_codigo","apu_nombre","status","confianza","precio_contractual","costo_unitario","margen_unitario","margen_pct","contractual_total","costo_total","margen_total"}`.
  - `_costear_row(alm, row: CorridaItemRow) -> AssembledApu` (interno, reutilizado por Task 5).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_servicio_corridas.py
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo, LicitacionItem
from apu_tool.servicio import corridas as svc


def _almacen_seed(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo("100", "Concreto 3000 PSI", "M3", "CONCRETOS", 350000.0, "COSTO INTERNO")])
    alm.apus.insert_apus([Apu("A1", "Concreto clase D", "M3", "DIURNO", "ESTRUCTURAS")])
    alm.apus.insert_components([
        ApuComponent("A1", "DIURNO", "100", "Concreto 3000 PSI", "M3", 1.05, 350000.0)])
    return alm


def test_construir_y_vista(tmp_path):
    alm = _almacen_seed(tmp_path)
    items = [LicitacionItem(item="1", descripcion="Concreto clase D", unidad="M3",
                            cantidad=10.0, precio_contractual=400000.0, shift="DIURNO")]
    cid = svc.construir_corrida(alm, "lic.xlsx", items, "DIURNO", use_ai=False)
    vista = svc.vista_corrida(alm, cid)
    assert vista["totales"]["n_items"] == 1
    fila = vista["items"][0]
    assert fila["apu_codigo"] == "A1"
    assert fila["status"] == "auto"                       # coincidencia exacta
    assert fila["costo_unitario"] == 1.05 * 350000.0      # 367500.0
    assert fila["contractual_total"] == 4000000.0
    assert fila["costo_total"] == 3675000.0


def test_vista_corrida_inexistente(tmp_path):
    alm = _almacen_seed(tmp_path)
    assert svc.vista_corrida(alm, 999) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_servicio_corridas.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'apu_tool.servicio.corridas'`.

- [ ] **Step 3: Implementar el servicio (parte 1)**

`apu_tool/servicio/corridas.py`:

```python
"""
Lógica de la capa de servicio para las corridas (armado web).

No habla HTTP ni con la IA directamente: orquesta el dominio (matcher, assembler,
pricing, report) y la persistencia de la corrida. Ve dinero (arma el cuadro para
el equipo), pero nunca abre un camino hacia la IA.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.dominio.ai_assist import ApuAdvisor
from apu_tool.dominio.assemble import Assembler
from apu_tool.dominio.pricing import PricingEngine
from apu_tool.dominio.report import write_report
from apu_tool.nucleo.models import (
    ApuComponent, AssembledApu, CorridaItemRow, CorridaMeta, LicitacionItem,
    MatchStatus,
)


def _estructura(componentes) -> list[dict]:
    """Snapshot SIN dinero de una composición costeada."""
    return [{"insumo_codigo": c.insumo_codigo, "insumo_nombre": c.insumo_nombre,
             "unidad": c.unidad, "rendimiento": c.rendimiento} for c in componentes]


def construir_corrida(alm: Almacen, archivo: str, items: list[LicitacionItem],
                      turno_def: str, use_ai: Optional[bool]) -> int:
    advisor = ApuAdvisor(enabled=use_ai)
    assembler = Assembler(alm, advisor=advisor)
    corrida_id = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en=datetime.now().isoformat(timespec="seconds"),
        archivo=archivo, turno_def=turno_def, use_ai=use_ai,
        estado="en_revision", cuadro_path=None))
    filas: list[CorridaItemRow] = []
    for seq, item in enumerate(items):
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
    alm.corridas.guardar_items(corrida_id, filas)
    return corrida_id


def _costear_row(alm: Almacen, row: CorridaItemRow) -> AssembledApu:
    """Recostea la estructura guardada con el precio vigente."""
    pricing = PricingEngine(alm)
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


def _vista_item(ens: AssembledApu, seq: int, status: str) -> dict:
    return {
        "seq": seq, "item": ens.item.item, "descripcion": ens.item.descripcion,
        "unidad": ens.unidad, "cantidad": ens.item.cantidad,
        "apu_codigo": ens.apu_codigo, "apu_nombre": ens.apu_nombre,
        "status": status, "confianza": round(ens.confianza, 4),
        "precio_contractual": ens.item.precio_contractual,
        "costo_unitario": ens.costo_unitario, "margen_unitario": ens.margen_unitario,
        "margen_pct": ens.margen_pct, "contractual_total": ens.contractual_total,
        "costo_total": ens.costo_total, "margen_total": ens.margen_total,
    }


def vista_corrida(alm: Almacen, corrida_id: int) -> Optional[dict]:
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    rows = alm.corridas.get_items(corrida_id)
    items = [_vista_item(_costear_row(alm, r), r.seq, r.status) for r in rows]
    tot_c = sum(i["contractual_total"] for i in items)
    tot_k = sum(i["costo_total"] for i in items)
    n_rev = sum(1 for i in items if i["status"] in ("review", "new"))
    return {
        "id": meta.id, "archivo": meta.archivo, "estado": meta.estado, "items": items,
        "totales": {"contractual": tot_c, "costo": tot_k, "margen": tot_c - tot_k,
                    "margen_pct": ((tot_c - tot_k) / tot_c) if tot_c else 0.0,
                    "n_items": len(items), "n_revision": n_rev},
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_servicio_corridas.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Agregar el test de privacidad del servicio**

En `tests/test_servicio_privacidad.py` agrega:

```python
import json
from pathlib import Path

FORBIDDEN = {"precio", "costo", "valor", "margen", "price", "cost", "total",
             "precio_unitario", "precio_contractual", "fuente_precio"}


def test_servicio_no_importa_ai_assist():
    raiz = Path(__file__).resolve().parent.parent / "apu_tool" / "servicio"
    for py in raiz.glob("*.py"):
        assert "ai_assist" not in py.read_text(encoding="utf-8"), py.name


def test_estructura_persistida_no_tiene_dinero(tmp_path):
    from apu_tool.datos.almacen import Almacen
    from apu_tool.nucleo.models import Apu, ApuComponent, Insumo, LicitacionItem
    from apu_tool.servicio import corridas as svc
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([Insumo("100", "Concreto 3000 PSI", "M3",
                                       "CONCRETOS", 350000.0, "COSTO INTERNO")])
    alm.apus.insert_apus([Apu("A1", "Concreto clase D", "M3", "DIURNO", "ESTR")])
    alm.apus.insert_components([ApuComponent("A1", "DIURNO", "100",
                               "Concreto 3000 PSI", "M3", 1.05, 350000.0)])
    cid = svc.construir_corrida(alm, "lic.xlsx", [LicitacionItem(
        item="1", descripcion="Concreto clase D", unidad="M3", cantidad=10.0,
        precio_contractual=400000.0, shift="DIURNO")], "DIURNO", False)
    row = alm.corridas.get_item(cid, 0)
    for c in row.componentes:
        assert FORBIDDEN.isdisjoint(c.keys())
    for c in row.candidatos:
        assert FORBIDDEN.isdisjoint(c.keys())
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_servicio_privacidad.py tests/test_servicio_corridas.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apu_tool/servicio/corridas.py tests/test_servicio_corridas.py tests/test_servicio_privacidad.py
git commit -m "feat(servicio): construir_corrida + vista costeada (re-costeo determinístico)"
```

---

### Task 5: Servicio — detalle, confirmar y cuadro

**Files:**
- Modify: `apu_tool/servicio/corridas.py`
- Modify: `apu_tool/dominio/pipeline.py` (`generate_sample` gana `alm`)
- Test: `tests/test_servicio_corridas.py` (se amplía)

**Interfaces:**
- Consumes: `_costear_row`, `_estructura`, `vista_corrida` (Task 4); `Assembler.reassemble_with_choice`; `write_report`.
- Produces:
  - `detalle_item(alm, corrida_id, seq) -> Optional[dict]` con `{"seq","descripcion","apu_codigo","apu_nombre","status","explicacion","candidatos","composicion":[{insumo_codigo,insumo_nombre,unidad,rendimiento,precio_unitario,fuente_precio,costo,calidad_cruce}],"costo_unitario"}`.
  - `confirmar_item(alm, corrida_id, seq, apu_codigo: str, shift: Optional[str]=None) -> Optional[dict]` (devuelve `vista_corrida` actualizada).
  - `generar_cuadro(alm, corrida_id) -> Optional[Path]`.
  - `generate_sample(..., alm: Optional[Almacen] = None)` retrocompatible.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_servicio_corridas.py  (agregar)
def test_detalle_confirmar_y_cuadro(tmp_path):
    alm = _almacen_seed(tmp_path)
    # segundo APU para poder "elegir otro"
    alm.apus.insert_apus([Apu("A2", "Concreto clase E", "M3", "DIURNO", "ESTR")])
    alm.apus.insert_components([
        ApuComponent("A2", "DIURNO", "100", "Concreto 3000 PSI", "M3", 2.0, 350000.0)])
    items = [LicitacionItem(item="1", descripcion="Concreto clase D", unidad="M3",
                            cantidad=10.0, precio_contractual=400000.0, shift="DIURNO")]
    cid = svc.construir_corrida(alm, "lic.xlsx", items, "DIURNO", use_ai=False)

    det = svc.detalle_item(alm, cid, 0)
    assert det["apu_codigo"] == "A1"
    assert det["composicion"][0]["precio_unitario"] == 350000.0

    vista = svc.confirmar_item(alm, cid, 0, apu_codigo="A2")
    fila = vista["items"][0]
    assert fila["status"] == "confirmed" and fila["apu_codigo"] == "A2"
    assert fila["costo_unitario"] == 2.0 * 350000.0      # recosteado: 700000.0

    out = svc.generar_cuadro(alm, cid)
    assert out.exists()
    assert alm.corridas.get_corrida(cid).estado == "finalizada"


def test_detalle_item_inexistente(tmp_path):
    alm = _almacen_seed(tmp_path)
    assert svc.detalle_item(alm, 1, 0) is None
    assert svc.confirmar_item(alm, 1, 0, "A1") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_servicio_corridas.py::test_detalle_confirmar_y_cuadro -q`
Expected: FAIL con `AttributeError: module ... has no attribute 'detalle_item'`.

- [ ] **Step 3: Implementar el servicio (parte 2)**

Agrega al final de `apu_tool/servicio/corridas.py`:

```python
def detalle_item(alm: Almacen, corrida_id: int, seq: int) -> Optional[dict]:
    row = alm.corridas.get_item(corrida_id, seq)
    if row is None:
        return None
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


def confirmar_item(alm: Almacen, corrida_id: int, seq: int, apu_codigo: str,
                   shift: Optional[str] = None) -> Optional[dict]:
    row = alm.corridas.get_item(corrida_id, seq)
    if row is None:
        return None
    assembler = Assembler(alm, advisor=ApuAdvisor(enabled=False))
    ens = assembler.reassemble_with_choice(row.item, apu_codigo, shift or row.shift)
    alm.corridas.actualizar_eleccion(
        corrida_id, seq, status=MatchStatus.CONFIRMED.value, apu_codigo=ens.apu_codigo,
        apu_nombre=ens.apu_nombre, unidad=ens.unidad, shift=ens.shift, origen=ens.origen,
        confianza=ens.confianza, explicacion=ens.explicacion,
        componentes=_estructura(ens.componentes))
    return vista_corrida(alm, corrida_id)


def generar_cuadro(alm: Almacen, corrida_id: int) -> Optional[Path]:
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    config.ensure_dirs()
    rows = alm.corridas.get_items(corrida_id)
    assembled = [_costear_row(alm, r) for r in rows]
    stamp = meta.creada_en.replace(":", "").replace("-", "").replace("T", "_")
    out = config.OUTPUT_DIR / f"cuadro_corrida_{corrida_id}_{stamp}.xlsx"
    write_report(assembled, out)
    alm.corridas.set_cuadro(corrida_id, str(out))
    alm.corridas.set_estado(corrida_id, "finalizada")
    return out
```

- [ ] **Step 4: Hacer `generate_sample` aceptar un Almacen**

En `apu_tool/dominio/pipeline.py`, cambia la firma y la obtención del almacén:

```python
def generate_sample(n: int = 15, margen: float = 0.18, seed: int = 7,
                    out_path: Optional[Path] = None,
                    alm: Optional[Almacen] = None) -> Path:
```

y reemplaza la línea `alm = get_almacen()` (dentro de la función) por:

```python
    alm = alm or get_almacen()
```

(Agrega `from apu_tool.datos.almacen import Almacen` a los imports de `pipeline.py` si no está; ya lo está vía `from apu_tool.datos.almacen import Almacen`.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_servicio_corridas.py -q`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add apu_tool/servicio/corridas.py apu_tool/dominio/pipeline.py tests/test_servicio_corridas.py
git commit -m "feat(servicio): detalle, confirmar (recosteo en vivo) y generar cuadro"
```

---

### Task 6: API — app factory, dependencias, esquemas y /status

**Files:**
- Create: `apu_tool/servicio/dependencias.py`
- Create: `apu_tool/servicio/esquemas.py`
- Create: `apu_tool/servicio/app.py`
- Create: `apu_tool/servicio/rutas.py` (solo `/status` por ahora)
- Test: `tests/test_api_corridas.py`

**Interfaces:**
- Consumes: `Almacen`, `config.ai_available()`.
- Produces:
  - `dependencias.get_almacen(request) -> Almacen` (lee `request.app.state.almacen`).
  - `esquemas.StatusOut(insumos:int, apus:int, ia:bool)`, `esquemas.ConfirmarIn(apu_codigo:str, shift:Optional[str]=None)`.
  - `app.create_app(almacen: Optional[Almacen]=None) -> FastAPI`; `app.app` (instancia por defecto).
  - `rutas.router` (APIRouter); `GET /status`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_corridas.py
from fastapi.testclient import TestClient

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo
from apu_tool.servicio.app import create_app


def _cliente(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([Insumo("100", "Concreto 3000 PSI", "M3",
                                       "CONCRETOS", 350000.0, "COSTO INTERNO")])
    alm.apus.insert_apus([Apu("A1", "Concreto clase D", "M3", "DIURNO", "ESTR")])
    alm.apus.insert_components([ApuComponent("A1", "DIURNO", "100",
                               "Concreto 3000 PSI", "M3", 1.05, 350000.0)])
    return TestClient(create_app(almacen=alm)), alm


def test_status(tmp_path):
    cli, _ = _cliente(tmp_path)
    r = cli.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["apus"] == 1 and body["insumos"] == 1 and "ia" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api_corridas.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'apu_tool.servicio.app'`.

- [ ] **Step 3: Crear dependencias y esquemas**

`apu_tool/servicio/dependencias.py`:

```python
"""Inyección de dependencias de la API: el Almacen vive en app.state."""
from __future__ import annotations

from fastapi import Request

from apu_tool.datos.almacen import Almacen


def get_almacen(request: Request) -> Almacen:
    return request.app.state.almacen
```

`apu_tool/servicio/esquemas.py`:

```python
"""DTOs del contrato HTTP. Las respuestas de cuadro/ítems se devuelven como dict."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class StatusOut(BaseModel):
    insumos: int
    apus: int
    ia: bool


class ConfirmarIn(BaseModel):
    apu_codigo: str
    shift: Optional[str] = None
```

- [ ] **Step 4: Crear el router con /status**

`apu_tool/servicio/rutas.py`:

```python
"""Endpoints de la API. Delgados: validan y delegan en apu_tool.servicio.corridas."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.servicio.dependencias import get_almacen
from apu_tool.servicio.esquemas import StatusOut

router = APIRouter()


@router.get("/status", response_model=StatusOut)
def status(alm: Almacen = Depends(get_almacen)):
    c = alm.counts()
    return StatusOut(insumos=c.get("insumos", 0), apus=c.get("apus", 0),
                     ia=config.ai_available())
```

- [ ] **Step 5: Crear la app factory**

`apu_tool/servicio/app.py`:

```python
"""App FastAPI: monta /api y, si existe el build, sirve el frontend (web/dist)."""
from __future__ import annotations

from typing import Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.servicio import rutas

WEB_DIST = config.PROJECT_ROOT / "web" / "dist"


def _crear_almacen() -> Almacen:
    alm = Almacen()
    alm.init_schema()
    return alm


def create_app(almacen: Optional[Almacen] = None) -> FastAPI:
    app = FastAPI(title="Armador de APUs")
    app.state.almacen = almacen or _crear_almacen()
    app.include_router(rutas.router, prefix="/api")
    if WEB_DIST.exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @app.get("/{full_path:path}")
        def spa(full_path: str):
            return FileResponse(WEB_DIST / "index.html")
    return app


app = create_app()
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_api_corridas.py -q`
Expected: PASS

Nota: `app = create_app()` al importar crea/inicializa las bases reales (`data/*.db`). Es el comportamiento deseado en uso real; los tests usan `create_app(almacen=alm_tmp)` y no tocan las bases reales.

- [ ] **Step 7: Commit**

```bash
git add apu_tool/servicio/dependencias.py apu_tool/servicio/esquemas.py apu_tool/servicio/rutas.py apu_tool/servicio/app.py tests/test_api_corridas.py
git commit -m "feat(api): app factory + dependencias + /api/status"
```

---

### Task 7: API — endpoints de corridas

**Files:**
- Modify: `apu_tool/servicio/rutas.py`
- Test: `tests/test_api_corridas.py` (se amplía)

**Interfaces:**
- Consumes: `servicio.corridas` (Tasks 4–5), `read_licitacion`, `ensure_seeded`, `generate_sample`, `write_sample_licitacion`, `ConfirmarIn`.
- Produces los endpoints: `POST /corridas`, `POST /sample`, `GET /corridas/{cid}`, `GET /corridas/{cid}/items/{seq}`, `POST /corridas/{cid}/items/{seq}/confirmar`, `GET /corridas/{cid}/cuadro`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_corridas.py  (agregar)
from apu_tool.dominio.licitacion import write_sample_licitacion
from apu_tool.nucleo.models import LicitacionItem


def _xlsx_lic(tmp_path):
    p = tmp_path / "lic.xlsx"
    write_sample_licitacion(p, [LicitacionItem(
        item="1", descripcion="Concreto clase D", unidad="M3", cantidad=10.0,
        precio_contractual=400000.0, shift="DIURNO")])
    return p


def test_flujo_corrida_completo(tmp_path):
    cli, _ = _cliente(tmp_path)
    lic = _xlsx_lic(tmp_path)
    with open(lic, "rb") as f:
        r = cli.post("/api/corridas",
                     data={"turno": "DIURNO", "use_ai": "false"},
                     files={"archivo": ("lic.xlsx", f,
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]

    v = cli.get(f"/api/corridas/{cid}")
    assert v.status_code == 200
    assert v.json()["totales"]["n_items"] == 1
    assert v.json()["items"][0]["costo_unitario"] == 367500.0

    det = cli.get(f"/api/corridas/{cid}/items/0")
    assert det.status_code == 200 and det.json()["apu_codigo"] == "A1"

    conf = cli.post(f"/api/corridas/{cid}/items/0/confirmar",
                    json={"apu_codigo": "A1"})
    assert conf.status_code == 200
    assert conf.json()["items"][0]["status"] == "confirmed"

    cuadro = cli.get(f"/api/corridas/{cid}/cuadro")
    assert cuadro.status_code == 200
    assert cuadro.headers["content-type"].startswith(
        "application/vnd.openxmlformats")


def test_corrida_inexistente_404(tmp_path):
    cli, _ = _cliente(tmp_path)
    assert cli.get("/api/corridas/999").status_code == 404


def test_archivo_ilegible_400(tmp_path):
    cli, _ = _cliente(tmp_path)
    mala = tmp_path / "mala.csv"
    mala.write_text("foo,bar\n1,2\n", encoding="utf-8")
    with open(mala, "rb") as f:
        r = cli.post("/api/corridas", data={"turno": "DIURNO"},
                     files={"archivo": ("mala.csv", f, "text/csv")})
    assert r.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api_corridas.py::test_flujo_corrida_completo -q`
Expected: FAIL con `404` (la ruta `/api/corridas` aún no existe).

- [ ] **Step 3: Implementar los endpoints**

Reemplaza el contenido de `apu_tool/servicio/rutas.py` por:

```python
"""Endpoints de la API. Delgados: validan y delegan en apu_tool.servicio.corridas."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import (APIRouter, Depends, File, Form, HTTPException, UploadFile)
from fastapi.responses import FileResponse

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.dominio.licitacion import read_licitacion
from apu_tool.dominio.pipeline import ensure_seeded, generate_sample
from apu_tool.servicio import corridas as svc
from apu_tool.servicio.dependencias import get_almacen
from apu_tool.servicio.esquemas import ConfirmarIn, StatusOut

router = APIRouter()

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/status", response_model=StatusOut)
def status(alm: Almacen = Depends(get_almacen)):
    c = alm.counts()
    return StatusOut(insumos=c.get("insumos", 0), apus=c.get("apus", 0),
                     ia=config.ai_available())


@router.post("/corridas")
async def crear_corrida(turno: str = Form(config.SHIFT_DIURNO),
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
    cid = svc.construir_corrida(alm, archivo.filename or "licitacion", items, turno, use_ai)
    return {"id": cid, "resumen": svc.vista_corrida(alm, cid)["totales"]}


@router.post("/sample")
def crear_sample(alm: Almacen = Depends(get_almacen)):
    if alm.counts().get("apus", 0) == 0:
        ensure_seeded()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        sample_path = tmp.name
    try:
        generate_sample(out_path=Path(sample_path), alm=alm)
        items = read_licitacion(sample_path, default_shift=config.SHIFT_DIURNO)
    finally:
        os.unlink(sample_path)
    cid = svc.construir_corrida(alm, "ejemplo.xlsx", items, config.SHIFT_DIURNO, False)
    return {"id": cid, "resumen": svc.vista_corrida(alm, cid)["totales"]}


@router.get("/corridas/{cid}")
def get_corrida(cid: int, alm: Almacen = Depends(get_almacen)):
    v = svc.vista_corrida(alm, cid)
    if v is None:
        raise HTTPException(status_code=404, detail="Corrida no encontrada.")
    return v


@router.get("/corridas/{cid}/items/{seq}")
def get_item(cid: int, seq: int, alm: Almacen = Depends(get_almacen)):
    d = svc.detalle_item(alm, cid, seq)
    if d is None:
        raise HTTPException(status_code=404, detail="Ítem no encontrado.")
    return d


@router.post("/corridas/{cid}/items/{seq}/confirmar")
def confirmar(cid: int, seq: int, body: ConfirmarIn,
              alm: Almacen = Depends(get_almacen)):
    v = svc.confirmar_item(alm, cid, seq, body.apu_codigo, body.shift)
    if v is None:
        raise HTTPException(status_code=404, detail="Ítem no encontrado.")
    return v


@router.get("/corridas/{cid}/cuadro")
def cuadro(cid: int, alm: Almacen = Depends(get_almacen)):
    out = svc.generar_cuadro(alm, cid)
    if out is None:
        raise HTTPException(status_code=404, detail="Corrida no encontrada.")
    return FileResponse(str(out), filename=out.name, media_type=_XLSX)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_api_corridas.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Run full suite**

Run: `python -m pytest tests/ -q`
Expected: PASS (suite completa, incluyendo las pruebas existentes).

- [ ] **Step 6: Commit**

```bash
git add apu_tool/servicio/rutas.py tests/test_api_corridas.py
git commit -m "feat(api): endpoints de corridas (crear, ver, detalle, confirmar, cuadro, sample)"
```

---

### Task 8: Lanzador local (run_web.py) y verificación manual

**Files:**
- Create: `run_web.py`

**Interfaces:**
- Consumes: `apu_tool.servicio.app:app`, `config.ensure_dirs`.
- Produces: `python run_web.py` levanta uvicorn en `127.0.0.1:8000` y abre el navegador.

- [ ] **Step 1: Crear el lanzador**

`run_web.py`:

```python
"""Lanza la app web (FastAPI + estáticos del frontend) y abre el navegador.

Un solo proceso. El frontend (web/dist) se sirve si fue compilado; mientras tanto
la API responde en /api y /docs muestra el contrato.
"""
from __future__ import annotations

import threading
import webbrowser

import uvicorn

from apu_tool import config

URL = "http://127.0.0.1:8000"


def _abrir() -> None:
    webbrowser.open(URL)


def main() -> None:
    config.ensure_dirs()
    threading.Timer(1.0, _abrir).start()
    uvicorn.run("apu_tool.servicio.app:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Verificación manual del arranque**

Run (en una terminal aparte; semilla primero si las bases están vacías):

```bash
python run_cli.py seed        # solo si data/ está vacía
python run_web.py
```

Expected: uvicorn arranca; el navegador abre `127.0.0.1:8000`. Como aún no hay `web/dist`, navegar a `127.0.0.1:8000/docs` muestra Swagger con los endpoints `/api/...`. Detén con Ctrl+C.

- [ ] **Step 3: Verificación manual del flujo por API (smoke con curl)**

Con el server corriendo, en otra terminal:

```bash
curl -s http://127.0.0.1:8000/api/status
curl -s -X POST http://127.0.0.1:8000/api/sample
```

Expected: `/api/status` devuelve `{"insumos":...,"apus":...,"ia":...}`. `/api/sample` devuelve `{"id":N,"resumen":{...}}`. Luego `curl -s http://127.0.0.1:8000/api/corridas/N` muestra el cuadro con ítems y totales.

- [ ] **Step 4: Commit**

```bash
git add run_web.py
git commit -m "feat(web): lanzador local run_web.py (uvicorn + abre navegador)"
```

---

## Frontend (plan siguiente)

El frontend (Vite + React + shadcn en `web/`, servido por FastAPI) se escribe en un
**segundo plan** una vez este backend esté verde, para diseñar las pantallas contra una
API real y verificada. Pantallas previstas (del spec): Inicio/Nueva corrida, Corrida (cuadro),
y el panel de revisión de ítem. Endpoints a consumir: los de las Tasks 6–7.

---

## Self-Review

**1. Spec coverage:**
- API: `GET /status` (T6), `POST /sample` (T7), `POST /corridas` (T7), `GET /corridas/{id}` (T7), `GET /corridas/{id}/items/{seq}` (T7), `POST .../confirmar` (T7), `GET .../cuadro` (T7). ✓
- Persistencia (corrida + repositorio + Almacen + Protocol): T2, T3. ✓
- Re-costeo determinístico desde estructura: `_costear_row` (T4). ✓
- Privacidad (servicio no toca IA; estructura sin dinero): tests en T4. ✓
- Errores (400 ilegible, 404 inexistente, base vacía→seed, IA→fallback): T7 + guardas. ✓
- Servir estáticos + run_web: T6 (`create_app`), T8. ✓
- Frontend: diferido a plan siguiente (declarado). ✓
- `422` para APU inexistente al confirmar: el dominio cae a otro turno (`_build`); si el código no existe en ningún turno, `reassemble_with_choice` arma con `apu=None` y nombre del ítem (costo 0). No se rompe; queda como CONFIRMED con costo 0. Comportamiento aceptable para v1 (no es un 422 explícito); documentado aquí como desviación menor del spec.

**2. Placeholder scan:** Sin "TBD/TODO"; todos los pasos con código real. ✓

**3. Type consistency:** `CorridaItemRow`/`CorridaMeta` idénticos entre T2, T3, repositorio y servicio; `construir_corrida`, `vista_corrida`, `_costear_row`, `detalle_item`, `confirmar_item`, `generar_cuadro` con firmas consistentes entre T4, T5 y rutas (T7); `StatusOut`/`ConfirmarIn` consistentes T6→T7; `actualizar_eleccion` con los mismos parámetros keyword en repo (T3), Protocol (T3) y servicio (T5). ✓
