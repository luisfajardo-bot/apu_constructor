# Carpetas para organizar corridas — Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agrupar las corridas en carpetas anidadas de hasta 2 niveles (globales) para separar subproyectos; toda corrida vive dentro de una carpeta.

**Architecture:** Nueva tabla `carpeta` autoreferenciada (nivel 1 = `parent_id NULL`, nivel 2 = `parent_id` a una de nivel 1). `corrida` gana `carpeta_id`. Persistencia aislada en un repo nuevo (`RepositorioCarpetas`, backends SQLite + Postgres) siguiendo el contrato de `repositorio.py`. Reglas (profundidad, unicidad de hermanas, borrado bloqueado si no vacía) y auditoría en `servicio/carpetas.py`. API delgada en `rutas.py`. Frontend: navegación tipo explorador en `MisCorridas.tsx` + selector de carpeta al crear.

**Tech Stack:** Python 3, FastAPI, SQLite (`sqlite3`), Postgres (`psycopg`), pytest; React + TypeScript + Vite + Vitest.

**Referencia de diseño:** `docs/superpowers/specs/2026-07-09-carpetas-corridas-design.md`

**Reglas de rol:** crear carpeta = `consulta`+; renombrar / mover / borrar carpeta y mover corrida = `editor`+.

---

## Estructura de archivos

**Backend — crear:**
- `apu_tool/datos/carpetas_db.py` — repo SQLite (`CarpetasDB`).
- `apu_tool/datos/pg/carpetas_pg.py` — repo Postgres (`CarpetasPg`).
- `apu_tool/servicio/carpetas.py` — reglas + auditoría.
- `tests/test_carpetas_db.py`, `tests/test_servicio_carpetas.py`, `tests/test_api_carpetas.py`.

**Backend — modificar:**
- `db/corridas.sql` — tabla `carpeta` + `corrida.carpeta_id` + índice único de hermanas.
- `db/pg/corridas.sql` — equivalente Postgres + bootstrap/backfill "Sin clasificar".
- `apu_tool/nucleo/models.py` — dataclass `Carpeta`; `CorridaMeta.carpeta_id`.
- `apu_tool/datos/repositorio.py` — `Protocol` `RepositorioCarpetas`; `set_carpeta` en `RepositorioCorridas`.
- `apu_tool/datos/corridas_db.py` — persistir/leer `carpeta_id`; ALTER + bootstrap/backfill "Sin clasificar"; `set_carpeta`.
- `apu_tool/datos/pg/corridas_pg.py` — persistir/leer `carpeta_id`; `set_carpeta`.
- `apu_tool/datos/almacen.py` — cablear `self.carpetas` (SQLite y PG).
- `apu_tool/servicio/corridas.py` — `carpeta_id` en `construir_corrida[_stream]`, `listar_corridas`, `vista_corrida`.
- `apu_tool/servicio/rutas.py` — endpoints `/carpetas*`, `carpeta_id` en creación, `/corridas/{cid}/mover`.
- `supabase/migrations/0004_carpetas_rls.sql` — RLS de `carpetas.carpeta`.

**Frontend — crear:**
- `web/src/api/carpetas.ts` — CRUD del árbol + `moverCorrida`.

**Frontend — modificar:**
- `web/src/lib/tipos.ts` — `Carpeta`, `CarpetaNodo`; `carpeta_id` en `CorridaResumen`.
- `web/src/pages/MisCorridas.tsx` — navegación por carpetas (breadcrumb + subcarpetas + tabla).
- `web/src/pages/CorridasInicio.tsx` — selector/creación de carpeta antes de armar.

---

## Fase A — Modelo de datos y repo SQLite

### Task A1: Dataclass `Carpeta` y `CorridaMeta.carpeta_id`

**Files:**
- Modify: `apu_tool/nucleo/models.py:208-218`
- Test: `tests/test_carpetas_db.py`

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_carpetas_db.py`:

```python
from apu_tool.nucleo.models import Carpeta, CorridaMeta


def test_carpeta_dataclass_defaults():
    c = Carpeta(id=None, nombre="Calle 13", parent_id=None, creada_en="2026-07-09")
    assert c.parent_id is None
    assert c.creado_por is None


def test_corrida_meta_tiene_carpeta_id():
    m = CorridaMeta(id=None, creada_en="2026-07-09", archivo="x.xlsx",
                    turno_def="DIURNO", use_ai=False, estado="armando")
    assert m.carpeta_id is None
```

- [ ] **Step 2: Correr para ver que falla**

Run: `python -m pytest tests/test_carpetas_db.py -q`
Expected: FAIL con `ImportError: cannot import name 'Carpeta'`.

- [ ] **Step 3: Implementación mínima**

En `apu_tool/nucleo/models.py`, tras la clase `Perfil` (línea ~70) agregar:

```python
@dataclass(frozen=True)
class Carpeta:
    """Carpeta para agrupar corridas. parent_id None = nivel 1; con valor = nivel 2."""
    id: Optional[int]
    nombre: str
    parent_id: Optional[int]
    creada_en: str                # ISO 8601
    creado_por: Optional[str] = None
```

En `CorridaMeta` (línea ~209-218) agregar el campo al final:

```python
    modo: str = "activa"
    carpeta_id: Optional[int] = None
```

- [ ] **Step 4: Correr para ver que pasa**

Run: `python -m pytest tests/test_carpetas_db.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add apu_tool/nucleo/models.py tests/test_carpetas_db.py
git commit -m "feat(models): dataclass Carpeta y CorridaMeta.carpeta_id"
```

---

### Task A2: Esquema SQLite — tabla `carpeta` + `corrida.carpeta_id`

**Files:**
- Modify: `db/corridas.sql`
- Modify: `apu_tool/datos/corridas_db.py:46-62` (init_schema/reset)
- Test: `tests/test_carpetas_db.py`

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_carpetas_db.py`:

```python
from apu_tool.datos.almacen import Almacen


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def test_schema_crea_tabla_carpeta_y_columna(tmp_path):
    alm = _alm(tmp_path)
    with alm.corridas.connect() as conn:
        tablas = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "carpeta" in tablas
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(corrida)").fetchall()}
        assert "carpeta_id" in cols
```

- [ ] **Step 2: Correr para ver que falla**

Run: `python -m pytest tests/test_carpetas_db.py::test_schema_crea_tabla_carpeta_y_columna -q`
Expected: FAIL (`assert 'carpeta' in tablas`).

- [ ] **Step 3: Implementación**

Reemplazar el contenido de `db/corridas.sql` (la tabla `carpeta` va PRIMERO para que la FK de `corrida` la referencie):

```sql
CREATE TABLE IF NOT EXISTS carpeta (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  nombre        TEXT NOT NULL,
  parent_id     INTEGER REFERENCES carpeta(id) ON DELETE RESTRICT,
  creada_en     TEXT NOT NULL,
  creado_por    TEXT
);
-- Unicidad de hermanas: no dos carpetas con el mismo nombre bajo el mismo padre
-- (incluida la raíz; NULL se normaliza a 0 porque UNIQUE trata los NULL como distintos).
CREATE UNIQUE INDEX IF NOT EXISTS ux_carpeta_hermanas
  ON carpeta(COALESCE(parent_id, 0), nombre);

CREATE TABLE IF NOT EXISTS corrida (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  creada_en     TEXT NOT NULL,
  archivo       TEXT NOT NULL,
  turno_def     TEXT NOT NULL,
  use_ai        INTEGER,
  estado        TEXT NOT NULL,
  cuadro_path   TEXT,
  duracion_ms   INTEGER,
  modo          TEXT NOT NULL DEFAULT 'activa',
  carpeta_id    INTEGER REFERENCES carpeta(id) ON DELETE RESTRICT
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
  candidatos_json  TEXT,
  snapshot_json    TEXT
);

CREATE INDEX IF NOT EXISTS ix_corrida_item ON corrida_item(corrida_id, seq);
```

En `apu_tool/datos/corridas_db.py`, dentro de `init_schema` (tras el bloque de `corrida_item`, antes de cerrar el `with`), agregar el ALTER para bases existentes:

```python
            if "carpeta_id" not in cols:
                conn.execute("ALTER TABLE corrida ADD COLUMN carpeta_id INTEGER "
                             "REFERENCES carpeta(id) ON DELETE RESTRICT")
```

(Colócalo junto a los otros `if ... not in cols` que ya existen; `cols` es el set de columnas de `corrida` ya leído en línea 49.)

En `reset` (línea 58-62) agregar `carpeta` a la lista de tablas a dropear, respetando el orden (primero las que dependen):

```python
    def reset(self) -> None:
        with self.connect() as conn:
            for t in ("corrida_item", "corrida", "carpeta"):
                conn.execute(f"DROP TABLE IF EXISTS {t}")
            conn.executescript(_load_schema())
```

- [ ] **Step 4: Correr para ver que pasa**

Run: `python -m pytest tests/test_carpetas_db.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add db/corridas.sql apu_tool/datos/corridas_db.py tests/test_carpetas_db.py
git commit -m "feat(db): esquema SQLite de carpeta + corrida.carpeta_id"
```

---

### Task A3: `CarpetasDB` (repo SQLite) — CRUD

**Files:**
- Create: `apu_tool/datos/carpetas_db.py`
- Modify: `apu_tool/datos/repositorio.py` (nuevo `Protocol`)
- Modify: `apu_tool/datos/almacen.py:38-49,51-55` (cablear `self.carpetas`)
- Test: `tests/test_carpetas_db.py`

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_carpetas_db.py`:

```python
import sqlite3
import pytest


def test_crud_carpeta_sqlite(tmp_path):
    alm = _alm(tmp_path)
    cid = alm.carpetas.crear("Calle 13", parent_id=None, creado_por="u1")
    c = alm.carpetas.get(cid)
    assert c.nombre == "Calle 13" and c.parent_id is None
    sub = alm.carpetas.crear("Lote 3", parent_id=cid, creado_por="u1")
    assert alm.carpetas.contar_hijas(cid) == 1
    alm.carpetas.renombrar(cid, "Calle 13 SL5")
    assert alm.carpetas.get(cid).nombre == "Calle 13 SL5"
    assert {c.id for c in alm.carpetas.listar()} == {cid, sub}
    assert alm.carpetas.eliminar(sub) is True
    assert alm.carpetas.contar_hijas(cid) == 0


def test_unicidad_hermanas_sqlite(tmp_path):
    alm = _alm(tmp_path)
    alm.carpetas.crear("Obra", parent_id=None)
    with pytest.raises(sqlite3.IntegrityError):
        alm.carpetas.crear("Obra", parent_id=None)
```

- [ ] **Step 2: Correr para ver que falla**

Run: `python -m pytest tests/test_carpetas_db.py::test_crud_carpeta_sqlite -q`
Expected: FAIL (`AttributeError: 'Almacen' object has no attribute 'carpetas'`).

- [ ] **Step 3: Implementación**

Crear `apu_tool/datos/carpetas_db.py`:

```python
"""Acceso a la tabla `carpeta` (vive en corridas.db). Implementa RepositorioCarpetas.

Guarda solo estructura (nombre + jerarquía de 2 niveles). Las reglas de negocio
(profundidad, borrado bloqueado si no vacía) viven en servicio/carpetas.py; aquí
solo CRUD y conteos. La unicidad de hermanas la garantiza el índice ux_carpeta_hermanas.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from apu_tool import config
from apu_tool.nucleo.models import Carpeta


class CarpetasDB:
    """Backend SQLite de carpetas. Comparte el archivo corridas.db con CorridasDB."""

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

    def _fila(self, r: sqlite3.Row) -> Carpeta:
        return Carpeta(id=r["id"], nombre=r["nombre"], parent_id=r["parent_id"],
                       creada_en=r["creada_en"], creado_por=r["creado_por"])

    def crear(self, nombre: str, parent_id: Optional[int] = None,
              creado_por: Optional[str] = None, conn: Optional[sqlite3.Connection] = None) -> int:
        import datetime as _dt
        creada_en = _dt.datetime.now().isoformat(timespec="seconds")
        sql = ("INSERT INTO carpeta (nombre, parent_id, creada_en, creado_por) "
               "VALUES (?,?,?,?)")
        params = (nombre, parent_id, creada_en, creado_por)
        if conn is not None:
            return int(conn.execute(sql, params).lastrowid)
        with self.connect() as c:
            return int(c.execute(sql, params).lastrowid)

    def get(self, carpeta_id: int) -> Optional[Carpeta]:
        with self.connect() as conn:
            r = conn.execute("SELECT * FROM carpeta WHERE id=?", (int(carpeta_id),)).fetchone()
        return self._fila(r) if r else None

    def listar(self) -> list[Carpeta]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM carpeta ORDER BY parent_id IS NOT NULL, nombre").fetchall()
        return [self._fila(r) for r in rows]

    def renombrar(self, carpeta_id: int, nombre: str,
                  conn: Optional[sqlite3.Connection] = None) -> None:
        sql = "UPDATE carpeta SET nombre=? WHERE id=?"
        params = (nombre, int(carpeta_id))
        if conn is not None:
            conn.execute(sql, params); return
        with self.connect() as c:
            c.execute(sql, params)

    def mover(self, carpeta_id: int, parent_id: Optional[int],
              conn: Optional[sqlite3.Connection] = None) -> None:
        sql = "UPDATE carpeta SET parent_id=? WHERE id=?"
        params = (parent_id, int(carpeta_id))
        if conn is not None:
            conn.execute(sql, params); return
        with self.connect() as c:
            c.execute(sql, params)

    def eliminar(self, carpeta_id: int, conn: Optional[sqlite3.Connection] = None) -> bool:
        sql = "DELETE FROM carpeta WHERE id=?"
        if conn is not None:
            return conn.execute(sql, (int(carpeta_id),)).rowcount > 0
        with self.connect() as c:
            return c.execute(sql, (int(carpeta_id),)).rowcount > 0

    def contar_hijas(self, carpeta_id: int) -> int:
        with self.connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM carpeta WHERE parent_id=?",
                                (int(carpeta_id),)).fetchone()[0]

    def contar_corridas(self, carpeta_id: int) -> int:
        with self.connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM corrida WHERE carpeta_id=?",
                                (int(carpeta_id),)).fetchone()[0]
```

En `apu_tool/datos/repositorio.py`, tras `RepositorioCorridas` agregar el import de `Carpeta` a la línea de imports (línea 11-13) y el nuevo Protocol:

```python
from apu_tool.nucleo.models import (
    Apu, ApuComponent, Carpeta, CorridaItemRow, CorridaMeta, DePricedApu,
    EventoAuditoria, Insumo, Perfil,
)
```

```python
@runtime_checkable
class RepositorioCarpetas(Protocol):
    def crear(self, nombre: str, parent_id: Optional[int] = None,
              creado_por: Optional[str] = None, conn=None) -> int: ...
    def get(self, carpeta_id: int) -> Optional[Carpeta]: ...
    def listar(self) -> list[Carpeta]: ...
    def renombrar(self, carpeta_id: int, nombre: str, conn=None) -> None: ...
    def mover(self, carpeta_id: int, parent_id: Optional[int], conn=None) -> None: ...
    def eliminar(self, carpeta_id: int, conn=None) -> bool: ...
    def contar_hijas(self, carpeta_id: int) -> int: ...
    def contar_corridas(self, carpeta_id: int) -> int: ...
```

En `apu_tool/datos/almacen.py`:
- rama Postgres (tras línea 33 `self.corridas = CorridasPg(...)`): añadir `from apu_tool.datos.pg.carpetas_pg import CarpetasPg` al bloque de imports (línea 24-29) y `self.carpetas = CarpetasPg(self._cx)`.
- rama SQLite (tras línea 45 `self.corridas = CorridasDB(corridas_path)`): `from apu_tool.datos.carpetas_db import CarpetasDB` (arriba con los otros imports) y `self.carpetas = CarpetasDB(corridas_path)`.

(No se agrega `carpetas.init_schema()` a `Almacen.init_schema`: el esquema de `carpeta` lo crea `corridas.init_schema()`, con el que comparte base.)

- [ ] **Step 4: Correr para ver que pasa**

Run: `python -m pytest tests/test_carpetas_db.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apu_tool/datos/carpetas_db.py apu_tool/datos/repositorio.py apu_tool/datos/almacen.py tests/test_carpetas_db.py
git commit -m "feat(datos): CarpetasDB (SQLite) + RepositorioCarpetas + cableado en Almacen"
```

---

### Task A4: Migración "Sin clasificar" (SQLite) + `set_carpeta` en corridas

**Files:**
- Modify: `apu_tool/datos/corridas_db.py` (init_schema backfill + `set_carpeta`)
- Modify: `apu_tool/datos/repositorio.py` (`set_carpeta` en `RepositorioCorridas`)
- Test: `tests/test_carpetas_db.py`

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_carpetas_db.py`:

```python
from apu_tool.nucleo.models import CorridaMeta


def test_backfill_sin_clasificar(tmp_path):
    # Simula una base vieja: crea una corrida sin carpeta_id insertándola directo.
    alm = _alm(tmp_path)
    with alm.corridas.connect() as conn:
        conn.execute("INSERT INTO corrida (creada_en, archivo, turno_def, estado) "
                     "VALUES ('2026-01-01', 'vieja.xlsx', 'DIURNO', 'finalizada')")
    # Re-init: debe crear "Sin clasificar" y backfillear.
    alm.corridas.init_schema()
    with alm.corridas.connect() as conn:
        sc = conn.execute("SELECT id FROM carpeta WHERE nombre='Sin clasificar' "
                          "AND parent_id IS NULL").fetchone()
        assert sc is not None
        row = conn.execute("SELECT carpeta_id FROM corrida WHERE archivo='vieja.xlsx'").fetchone()
        assert row["carpeta_id"] == sc["id"]


def test_set_carpeta(tmp_path):
    alm = _alm(tmp_path)
    dest = alm.carpetas.crear("Destino", parent_id=None)
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-07-09", archivo="x.xlsx", turno_def="DIURNO",
        use_ai=False, estado="armando", carpeta_id=dest))
    otra = alm.carpetas.crear("Otra", parent_id=None)
    alm.corridas.set_carpeta(cid, otra)
    assert alm.corridas.get_corrida(cid).carpeta_id == otra
```

- [ ] **Step 2: Correr para ver que falla**

Run: `python -m pytest tests/test_carpetas_db.py::test_backfill_sin_clasificar tests/test_carpetas_db.py::test_set_carpeta -q`
Expected: FAIL (no existe "Sin clasificar"; y `set_carpeta` no existe).

- [ ] **Step 3: Implementación**

En `apu_tool/datos/corridas_db.py`:

En `init_schema`, al final del `with` (después del ALTER de `carpeta_id` de Task A2) agregar el bootstrap + backfill:

```python
            sc = conn.execute("SELECT id FROM carpeta WHERE nombre='Sin clasificar' "
                              "AND parent_id IS NULL").fetchone()
            if sc is None:
                import datetime as _dt
                cur = conn.execute(
                    "INSERT INTO carpeta (nombre, parent_id, creada_en) VALUES (?, NULL, ?)",
                    ("Sin clasificar", _dt.datetime.now().isoformat(timespec="seconds")))
                sc_id = int(cur.lastrowid)
            else:
                sc_id = int(sc["id"])
            conn.execute("UPDATE corrida SET carpeta_id=? WHERE carpeta_id IS NULL", (sc_id,))
```

Persistir `carpeta_id` al crear la corrida — modificar `_insert_corrida` (línea 79-86):

```python
    def _insert_corrida(self, conn: sqlite3.Connection, meta: CorridaMeta) -> int:
        cur = conn.execute(
            "INSERT INTO corrida (creada_en, archivo, turno_def, use_ai, estado, "
            "cuadro_path, duracion_ms, modo, carpeta_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (meta.creada_en, meta.archivo, meta.turno_def,
             None if meta.use_ai is None else int(meta.use_ai),
             meta.estado, meta.cuadro_path, meta.duracion_ms, meta.modo, meta.carpeta_id))
        return int(cur.lastrowid)
```

Leer `carpeta_id` — modificar `_row_to_meta` (línea 165-171), agregar al constructor:

```python
            modo=(r["modo"] or "activa"),
            carpeta_id=(r["carpeta_id"] if "carpeta_id" in r.keys() else None))
```

Agregar `set_carpeta` (junto a `set_modo`):

```python
    def set_carpeta(self, corrida_id: int, carpeta_id: int) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE corrida SET carpeta_id=? WHERE id=?",
                         (int(carpeta_id), int(corrida_id)))
```

En `apu_tool/datos/repositorio.py`, dentro de `RepositorioCorridas` agregar:

```python
    def set_carpeta(self, corrida_id: int, carpeta_id: int) -> None: ...
```

- [ ] **Step 4: Correr para ver que pasa**

Run: `python -m pytest tests/test_carpetas_db.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apu_tool/datos/corridas_db.py apu_tool/datos/repositorio.py tests/test_carpetas_db.py
git commit -m "feat(db): backfill 'Sin clasificar' + set_carpeta (SQLite)"
```

---

## Fase B — Capa de servicio (reglas + auditoría)

### Task B1: `servicio/carpetas.py` — crear, listar_arbol, validaciones

**Files:**
- Create: `apu_tool/servicio/carpetas.py`
- Test: `tests/test_servicio_carpetas.py`

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_servicio_carpetas.py`:

```python
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.servicio import carpetas as svc
from apu_tool.servicio.carpetas import CarpetaInvalida, CarpetaNoVacia


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def test_crear_y_arbol(tmp_path):
    alm = _alm(tmp_path)
    obra = svc.crear_carpeta(alm, "Calle 13", parent_id=None, actor=None)
    svc.crear_carpeta(alm, "Lote 3", parent_id=obra["id"], actor=None)
    arbol = svc.listar_arbol(alm)
    # "Sin clasificar" + "Calle 13" en la raíz
    nombres_raiz = {n["nombre"] for n in arbol}
    assert {"Sin clasificar", "Calle 13"} <= nombres_raiz
    calle = next(n for n in arbol if n["nombre"] == "Calle 13")
    assert [h["nombre"] for h in calle["hijas"]] == ["Lote 3"]


def test_no_permite_tercer_nivel(tmp_path):
    alm = _alm(tmp_path)
    obra = svc.crear_carpeta(alm, "Obra", parent_id=None, actor=None)
    lote = svc.crear_carpeta(alm, "Lote", parent_id=obra["id"], actor=None)
    with pytest.raises(CarpetaInvalida):
        svc.crear_carpeta(alm, "Sub", parent_id=lote["id"], actor=None)


def test_nombre_duplicado_hermanas(tmp_path):
    alm = _alm(tmp_path)
    svc.crear_carpeta(alm, "Obra", parent_id=None, actor=None)
    with pytest.raises(CarpetaInvalida):
        svc.crear_carpeta(alm, "Obra", parent_id=None, actor=None)


def test_nombre_vacio(tmp_path):
    alm = _alm(tmp_path)
    with pytest.raises(CarpetaInvalida):
        svc.crear_carpeta(alm, "   ", parent_id=None, actor=None)
```

- [ ] **Step 2: Correr para ver que falla**

Run: `python -m pytest tests/test_servicio_carpetas.py -q`
Expected: FAIL (`ModuleNotFoundError` / `ImportError`).

- [ ] **Step 3: Implementación**

Crear `apu_tool/servicio/carpetas.py`:

```python
"""Servicio de carpetas: reglas de negocio (profundidad máx. 2, unicidad de
hermanas, borrado bloqueado si no vacía) + auditoría. No ve dinero ni la IA.

Roles (los aplica la API en rutas.py): crear = consulta+; renombrar/mover/borrar
y mover corridas = editor+.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Carpeta
from apu_tool.servicio.auditoria import registrar_auditoria


class CarpetaInvalida(Exception):
    """Nombre vacío, duplicado entre hermanas, padre inexistente o profundidad > 2."""


class CarpetaNoVacia(Exception):
    """Se intentó borrar una carpeta con subcarpetas o corridas dentro."""
    def __init__(self, carpeta_id: int):
        super().__init__(f"La carpeta {carpeta_id} no está vacía.")
        self.carpeta_id = carpeta_id


def _dto(c: Carpeta) -> dict:
    return {"id": c.id, "nombre": c.nombre, "parent_id": c.parent_id,
            "creada_en": c.creada_en}


def _es_duplicado(e: Exception) -> bool:
    """True si la excepción de integridad es por el índice de hermanas."""
    return isinstance(e, sqlite3.IntegrityError) or "ux_carpeta_hermanas" in str(e) \
        or "unique" in str(e).lower()


def crear_carpeta(alm: Almacen, nombre: str, parent_id: Optional[int],
                  actor=None) -> dict:
    nombre = (nombre or "").strip()
    if not nombre:
        raise CarpetaInvalida("El nombre de la carpeta no puede estar vacío.")
    if parent_id is not None:
        padre = alm.carpetas.get(parent_id)
        if padre is None:
            raise CarpetaInvalida("La carpeta padre no existe.")
        if padre.parent_id is not None:
            raise CarpetaInvalida("No se permiten más de 2 niveles de carpetas.")
    try:
        with alm.transaccion("corridas") as conn:
            new_id = alm.carpetas.crear(nombre, parent_id, creado_por=_email(actor), conn=conn)
            registrar_auditoria(alm, conn, actor, "carpeta.crear", "carpeta", new_id,
                                antes=None, despues={"nombre": nombre, "parent_id": parent_id})
    except Exception as e:
        if _es_duplicado(e):
            raise CarpetaInvalida("Ya existe una carpeta con ese nombre en el mismo nivel.") from e
        raise
    return _dto(alm.carpetas.get(new_id))


def listar_arbol(alm: Almacen) -> list[dict]:
    """Árbol de 2 niveles con conteo de corridas por carpeta."""
    todas = alm.carpetas.listar()
    por_padre: dict[Optional[int], list[Carpeta]] = {}
    for c in todas:
        por_padre.setdefault(c.parent_id, []).append(c)

    def nodo(c: Carpeta) -> dict:
        hijas = [nodo(h) for h in por_padre.get(c.id, [])]
        return {"id": c.id, "nombre": c.nombre, "parent_id": c.parent_id,
                "n_corridas": alm.carpetas.contar_corridas(c.id), "hijas": hijas}

    return [nodo(c) for c in por_padre.get(None, [])]


def _email(actor) -> Optional[str]:
    return getattr(actor, "email", None) if actor is not None else None
```

- [ ] **Step 4: Correr para ver que pasa**

Run: `python -m pytest tests/test_servicio_carpetas.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/carpetas.py tests/test_servicio_carpetas.py
git commit -m "feat(servicio): crear_carpeta + listar_arbol con validaciones"
```

---

### Task B2: `servicio/carpetas.py` — renombrar, mover, eliminar, mover_corrida

**Files:**
- Modify: `apu_tool/servicio/carpetas.py`
- Test: `tests/test_servicio_carpetas.py`

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_servicio_carpetas.py`:

```python
from apu_tool.nucleo.models import CorridaMeta


def _corrida_en(alm, carpeta_id):
    return alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-07-09", archivo="x.xlsx", turno_def="DIURNO",
        use_ai=False, estado="armando", carpeta_id=carpeta_id))


def test_renombrar_y_mover(tmp_path):
    alm = _alm(tmp_path)
    obra = svc.crear_carpeta(alm, "Obra", parent_id=None, actor=None)
    obra2 = svc.crear_carpeta(alm, "Obra 2", parent_id=None, actor=None)
    sub = svc.crear_carpeta(alm, "Sub", parent_id=obra["id"], actor=None)
    svc.renombrar_carpeta(alm, obra["id"], "Obra A", actor=None)
    assert alm.carpetas.get(obra["id"]).nombre == "Obra A"
    svc.mover_carpeta(alm, sub["id"], nuevo_parent_id=obra2["id"], actor=None)
    assert alm.carpetas.get(sub["id"]).parent_id == obra2["id"]


def test_mover_carpeta_con_hijas_no_puede_ser_nivel2(tmp_path):
    alm = _alm(tmp_path)
    obra = svc.crear_carpeta(alm, "Obra", parent_id=None, actor=None)
    otra = svc.crear_carpeta(alm, "Otra", parent_id=None, actor=None)
    svc.crear_carpeta(alm, "Hija", parent_id=obra["id"], actor=None)
    with pytest.raises(CarpetaInvalida):
        svc.mover_carpeta(alm, obra["id"], nuevo_parent_id=otra["id"], actor=None)


def test_eliminar_bloqueado_si_no_vacia(tmp_path):
    alm = _alm(tmp_path)
    obra = svc.crear_carpeta(alm, "Obra", parent_id=None, actor=None)
    sub = svc.crear_carpeta(alm, "Sub", parent_id=obra["id"], actor=None)
    with pytest.raises(CarpetaNoVacia):
        svc.eliminar_carpeta(alm, obra["id"], actor=None)      # tiene subcarpeta
    cid = _corrida_en(alm, sub["id"])
    with pytest.raises(CarpetaNoVacia):
        svc.eliminar_carpeta(alm, sub["id"], actor=None)       # tiene corrida
    # vaciamos de abajo hacia arriba: corrida -> sub -> obra
    alm.corridas.eliminar_corrida(cid)
    assert svc.eliminar_carpeta(alm, sub["id"], actor=None) is True    # sub ya vacía
    assert svc.eliminar_carpeta(alm, obra["id"], actor=None) is True   # obra ya vacía


def test_eliminar_carpeta_inexistente_devuelve_false(tmp_path):
    alm = _alm(tmp_path)
    assert svc.eliminar_carpeta(alm, 9999, actor=None) is False


def test_mover_corrida(tmp_path):
    alm = _alm(tmp_path)
    a = svc.crear_carpeta(alm, "A", parent_id=None, actor=None)
    b = svc.crear_carpeta(alm, "B", parent_id=None, actor=None)
    cid = _corrida_en(alm, a["id"])
    assert svc.mover_corrida(alm, cid, b["id"], actor=None) is True
    assert alm.corridas.get_corrida(cid).carpeta_id == b["id"]
    with pytest.raises(CarpetaInvalida):
        svc.mover_corrida(alm, cid, 9999, actor=None)          # carpeta destino inexistente
```

> Nota: en `test_eliminar_bloqueado_si_no_vacia`, `eliminar_carpeta` lanza `CarpetaNoVacia` cuando hay contenido; el `assert ... is False` cubre el caso en que la carpeta no existe (nunca se alcanza con contenido). Ajusta si tu implementación devuelve algo distinto para "no existe".

- [ ] **Step 2: Correr para ver que falla**

Run: `python -m pytest tests/test_servicio_carpetas.py -q`
Expected: FAIL (`AttributeError: module ... has no attribute 'renombrar_carpeta'`).

- [ ] **Step 3: Implementación**

Agregar a `apu_tool/servicio/carpetas.py`:

```python
def renombrar_carpeta(alm: Almacen, carpeta_id: int, nombre: str, actor=None) -> dict:
    nombre = (nombre or "").strip()
    if not nombre:
        raise CarpetaInvalida("El nombre de la carpeta no puede estar vacío.")
    c = alm.carpetas.get(carpeta_id)
    if c is None:
        raise CarpetaInvalida("La carpeta no existe.")
    try:
        with alm.transaccion("corridas") as conn:
            alm.carpetas.renombrar(carpeta_id, nombre, conn=conn)
            registrar_auditoria(alm, conn, actor, "carpeta.renombrar", "carpeta", carpeta_id,
                                antes={"nombre": c.nombre}, despues={"nombre": nombre})
    except Exception as e:
        if _es_duplicado(e):
            raise CarpetaInvalida("Ya existe una carpeta con ese nombre en el mismo nivel.") from e
        raise
    return _dto(alm.carpetas.get(carpeta_id))


def mover_carpeta(alm: Almacen, carpeta_id: int, nuevo_parent_id: Optional[int],
                  actor=None) -> dict:
    c = alm.carpetas.get(carpeta_id)
    if c is None:
        raise CarpetaInvalida("La carpeta no existe.")
    if nuevo_parent_id is not None:
        if nuevo_parent_id == carpeta_id:
            raise CarpetaInvalida("Una carpeta no puede ser su propio padre.")
        padre = alm.carpetas.get(nuevo_parent_id)
        if padre is None:
            raise CarpetaInvalida("La carpeta padre no existe.")
        if padre.parent_id is not None:
            raise CarpetaInvalida("No se permiten más de 2 niveles de carpetas.")
        if alm.carpetas.contar_hijas(carpeta_id) > 0:
            raise CarpetaInvalida("Una carpeta con subcarpetas no puede volverse subcarpeta.")
    try:
        with alm.transaccion("corridas") as conn:
            alm.carpetas.mover(carpeta_id, nuevo_parent_id, conn=conn)
            registrar_auditoria(alm, conn, actor, "carpeta.mover", "carpeta", carpeta_id,
                                antes={"parent_id": c.parent_id},
                                despues={"parent_id": nuevo_parent_id})
    except Exception as e:
        if _es_duplicado(e):
            raise CarpetaInvalida("Ya existe una carpeta con ese nombre en el destino.") from e
        raise
    return _dto(alm.carpetas.get(carpeta_id))


def eliminar_carpeta(alm: Almacen, carpeta_id: int, actor=None) -> bool:
    c = alm.carpetas.get(carpeta_id)
    if c is None:
        return False
    if alm.carpetas.contar_hijas(carpeta_id) > 0 or alm.carpetas.contar_corridas(carpeta_id) > 0:
        raise CarpetaNoVacia(carpeta_id)
    with alm.transaccion("corridas") as conn:
        ok = alm.carpetas.eliminar(carpeta_id, conn=conn)
        if ok:
            registrar_auditoria(alm, conn, actor, "carpeta.eliminar", "carpeta", carpeta_id,
                                antes={"nombre": c.nombre, "parent_id": c.parent_id},
                                despues=None)
    return ok


def mover_corrida(alm: Almacen, corrida_id: int, carpeta_id: int, actor=None) -> bool:
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return False
    if alm.carpetas.get(carpeta_id) is None:
        raise CarpetaInvalida("La carpeta destino no existe.")
    with alm.transaccion("corridas") as conn:
        # set_carpeta abre su propia conexión; para mantener la mutación + auditoría
        # en la misma transacción, hazlo con SQL directo sobre `conn`:
        conn.execute("UPDATE corrida SET carpeta_id=? WHERE id=?", (int(carpeta_id), int(corrida_id)))
        registrar_auditoria(alm, conn, actor, "corrida.mover", "corrida", corrida_id,
                            antes={"carpeta_id": meta.carpeta_id},
                            despues={"carpeta_id": carpeta_id})
    return True
```

> Nota sobre `mover_corrida`: en Postgres el placeholder es `%s`, no `?`. Para no acoplar el servicio al dialecto, en la Task D3 se reemplaza este `conn.execute(...)` por una llamada al repo. De momento (solo SQLite) el `?` es correcto; la Task D3 lo generaliza.

- [ ] **Step 4: Correr para ver que pasa**

Run: `python -m pytest tests/test_servicio_carpetas.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/carpetas.py tests/test_servicio_carpetas.py
git commit -m "feat(servicio): renombrar/mover/eliminar carpeta + mover corrida"
```

---

## Fase C — Corridas con carpeta + API

### Task C1: `carpeta_id` en construcción y listado de corridas

**Files:**
- Modify: `apu_tool/servicio/corridas.py` (`construir_corrida_stream`, `construir_corrida`, `listar_corridas`, `vista_corrida`)
- Test: `tests/test_servicio_corridas.py`

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_servicio_corridas.py`:

```python
def test_construir_corrida_guarda_carpeta(tmp_path):
    alm = _almacen_seed(tmp_path)
    from apu_tool.servicio import carpetas as csvc
    carp = csvc.crear_carpeta(alm, "Obra", parent_id=None, actor=None)
    items = [LicitacionItem(item="1", descripcion="Concreto clase D", unidad="M3",
                            cantidad=10.0, precio_contractual=400000.0, shift="DIURNO")]
    cid = corridas.construir_corrida(alm, "lic.xlsx", items, "DIURNO", use_ai=False,
                                     carpeta_id=carp["id"])
    assert alm.corridas.get_corrida(cid).carpeta_id == carp["id"]
    fila = next(f for f in corridas.listar_corridas(alm) if f["id"] == cid)
    assert fila["carpeta_id"] == carp["id"]
    assert corridas.vista_corrida(alm, cid)["carpeta_id"] == carp["id"]
```

- [ ] **Step 2: Correr para ver que falla**

Run: `python -m pytest tests/test_servicio_corridas.py::test_construir_corrida_guarda_carpeta -q`
Expected: FAIL (`construir_corrida() got an unexpected keyword argument 'carpeta_id'`).

- [ ] **Step 3: Implementación**

En `apu_tool/servicio/corridas.py`:

`construir_corrida_stream` (línea 43-44) — agregar parámetro y pasarlo a `CorridaMeta`:

```python
def construir_corrida_stream(alm: Almacen, archivo: str, items: list[LicitacionItem],
                             turno_def: str, use_ai: Optional[bool],
                             carpeta_id: Optional[int] = None):
```

En la creación de `CorridaMeta` (línea 58-61) agregar `carpeta_id=carpeta_id`:

```python
    corrida_id = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en=datetime.now().isoformat(timespec="seconds"),
        archivo=archivo, turno_def=turno_def, use_ai=use_ai,
        estado="armando", cuadro_path=None, carpeta_id=carpeta_id))
```

`construir_corrida` (línea 96-103) — propagar:

```python
def construir_corrida(alm: Almacen, archivo: str, items: list[LicitacionItem],
                      turno_def: str, use_ai: Optional[bool],
                      carpeta_id: Optional[int] = None) -> int:
    corrida_id = -1
    for evento, payload in construir_corrida_stream(alm, archivo, items, turno_def,
                                                    use_ai, carpeta_id):
        if evento == "done":
            corrida_id = payload["id"]
    return corrida_id
```

`vista_corrida` (línea 198-202) — incluir `carpeta_id` en el dict de salida:

```python
    return {
        "id": meta.id, "archivo": meta.archivo, "estado": meta.estado, "modo": meta.modo,
        "carpeta_id": meta.carpeta_id,
        "duracion_ms": meta.duracion_ms, "items": items,
        "totales": _totales(ensambles, rows),
    }
```

`listar_corridas` (línea 288-291) — incluir `carpeta_id` en cada fila:

```python
        fila = {"id": meta.id, "archivo": meta.archivo, "creada_en": meta.creada_en,
                "estado": meta.estado, "modo": meta.modo, "duracion_ms": meta.duracion_ms,
                "carpeta_id": meta.carpeta_id,
                "n_items": len(rows), "n_revision": n_rev,
                "contractual": None, "costo": None, "margen": None, "margen_pct": None}
```

- [ ] **Step 4: Correr para ver que pasa**

Run: `python -m pytest tests/test_servicio_corridas.py -q`
Expected: PASS (todos, incluidos los previos).

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/corridas.py tests/test_servicio_corridas.py
git commit -m "feat(servicio): carpeta_id en construir/listar/vista de corridas"
```

---

### Task C2: Endpoints `/carpetas` (GET, POST, PATCH, DELETE) + `/corridas/{cid}/mover`

**Files:**
- Modify: `apu_tool/servicio/rutas.py`
- Test: `tests/test_api_carpetas.py`

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_api_carpetas.py`:

```python
from apu_tool.datos.almacen import Almacen
from apu_tool.servicio.app import create_app
from tests.conftest import cliente


def _cli(tmp_path, rol="admin"):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return cliente(create_app(almacen=alm), rol=rol), alm


def test_crud_carpetas_api(tmp_path):
    cli, _ = _cli(tmp_path)
    r = cli.post("/api/carpetas", json={"nombre": "Calle 13"})
    assert r.status_code == 200, r.text
    obra = r.json()
    r = cli.post("/api/carpetas", json={"nombre": "Lote 3", "parent_id": obra["id"]})
    assert r.status_code == 200
    arbol = cli.get("/api/carpetas").json()
    assert any(n["nombre"] == "Calle 13" and n["hijas"] for n in arbol)
    # renombrar
    r = cli.patch(f"/api/carpetas/{obra['id']}", json={"nombre": "Calle 13 SL5"})
    assert r.status_code == 200 and r.json()["nombre"] == "Calle 13 SL5"


def test_borrar_carpeta_no_vacia_409(tmp_path):
    cli, _ = _cli(tmp_path)
    obra = cli.post("/api/carpetas", json={"nombre": "Obra"}).json()
    cli.post("/api/carpetas", json={"nombre": "Sub", "parent_id": obra["id"]})
    r = cli.delete(f"/api/carpetas/{obra['id']}")
    assert r.status_code == 409


def test_nombre_duplicado_409(tmp_path):
    cli, _ = _cli(tmp_path)
    cli.post("/api/carpetas", json={"nombre": "Obra"})
    r = cli.post("/api/carpetas", json={"nombre": "Obra"})
    assert r.status_code == 409


def test_consulta_puede_crear_pero_no_renombrar(tmp_path):
    cli, _ = _cli(tmp_path, rol="consulta")
    r = cli.post("/api/carpetas", json={"nombre": "X"})
    assert r.status_code == 200
    r = cli.patch(f"/api/carpetas/{r.json()['id']}", json={"nombre": "Y"})
    assert r.status_code == 403
```

- [ ] **Step 2: Correr para ver que falla**

Run: `python -m pytest tests/test_api_carpetas.py -q`
Expected: FAIL (404 en `/api/carpetas`).

- [ ] **Step 3: Implementación**

En `apu_tool/servicio/rutas.py`:

Agregar imports (junto a `from apu_tool.servicio import corridas as svc`):

```python
from apu_tool.servicio import carpetas as carpetas_svc
from apu_tool.servicio.carpetas import CarpetaInvalida, CarpetaNoVacia
```

Definir los modelos Pydantic de entrada (junto a `ConfirmarIn`, en la zona de modelos del archivo):

```python
class CarpetaIn(BaseModel):
    nombre: str
    parent_id: Optional[int] = None

class CarpetaPatchIn(BaseModel):
    nombre: Optional[str] = None
    parent_id: Optional[int] = None
    mover: bool = False          # True => interpretar parent_id como cambio de padre

class MoverCorridaIn(BaseModel):
    carpeta_id: int
```

> `BaseModel` ya se importa en `rutas.py` para `ConfirmarIn`; reutilízalo. Si no, agrega `from pydantic import BaseModel`.

Agregar los endpoints (después del bloque de corridas):

```python
@router.get("/carpetas")
def listar_carpetas(alm: Almacen = Depends(get_almacen),
                    _: object = Depends(requiere_rol("consulta"))):
    return carpetas_svc.listar_arbol(alm)


@router.post("/carpetas")
def crear_carpeta(body: CarpetaIn, alm: Almacen = Depends(get_almacen),
                  actor=Depends(requiere_rol("consulta"))):
    try:
        return carpetas_svc.crear_carpeta(alm, body.nombre, body.parent_id, actor=actor)
    except CarpetaInvalida as e:
        # nombre duplicado -> 409; el resto (vacío/padre/profundidad) -> 400
        code = 409 if "Ya existe" in str(e) else 400
        raise HTTPException(status_code=code, detail=str(e))


@router.patch("/carpetas/{carpeta_id}")
def editar_carpeta(carpeta_id: int, body: CarpetaPatchIn,
                   alm: Almacen = Depends(get_almacen),
                   actor=Depends(requiere_rol("editor"))):
    try:
        if body.mover:
            return carpetas_svc.mover_carpeta(alm, carpeta_id, body.parent_id, actor=actor)
        if body.nombre is not None:
            return carpetas_svc.renombrar_carpeta(alm, carpeta_id, body.nombre, actor=actor)
        raise HTTPException(status_code=400, detail="Nada que actualizar.")
    except CarpetaInvalida as e:
        code = 409 if "Ya existe" in str(e) else 400
        raise HTTPException(status_code=code, detail=str(e))


@router.delete("/carpetas/{carpeta_id}")
def borrar_carpeta(carpeta_id: int, alm: Almacen = Depends(get_almacen),
                   actor=Depends(requiere_rol("editor"))):
    try:
        if not carpetas_svc.eliminar_carpeta(alm, carpeta_id, actor=actor):
            raise HTTPException(status_code=404, detail="Carpeta no encontrada.")
    except CarpetaNoVacia:
        raise HTTPException(status_code=409, detail="La carpeta no está vacía.")
    return {"eliminada": carpeta_id}


@router.post("/corridas/{cid}/mover")
def mover_corrida(cid: int, body: MoverCorridaIn, alm: Almacen = Depends(get_almacen),
                  actor=Depends(requiere_rol("editor"))):
    try:
        if not carpetas_svc.mover_corrida(alm, cid, body.carpeta_id, actor=actor):
            raise HTTPException(status_code=404, detail="Corrida no encontrada.")
    except CarpetaInvalida as e:
        raise HTTPException(status_code=400, detail=str(e))
    return svc.vista_corrida(alm, cid)
```

- [ ] **Step 4: Correr para ver que pasa**

Run: `python -m pytest tests/test_api_carpetas.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/rutas.py tests/test_api_carpetas.py
git commit -m "feat(api): endpoints /carpetas (CRUD) + /corridas/{cid}/mover"
```

---

### Task C3: `carpeta_id` obligatorio al crear corrida; sample usa "Sin clasificar"

**Files:**
- Modify: `apu_tool/servicio/rutas.py` (`crear_corrida`, `crear_corrida_stream`, `crear_sample`, `crear_sample_stream`)
- Modify: `apu_tool/servicio/carpetas.py` (helper `carpeta_sin_clasificar_id`)
- Test: `tests/test_api_corridas.py`, `tests/test_api_carpetas.py`

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_api_carpetas.py`:

```python
from apu_tool.dominio.licitacion import write_sample_licitacion
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo, LicitacionItem


def _cli_seed(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([Insumo("100", "Concreto", "M3", "C", 350000.0, "COSTO INTERNO")])
    alm.apus.insert_apus([Apu("A1", "Concreto clase D", "M3", "DIURNO", "E")])
    alm.apus.insert_components([ApuComponent("A1", "DIURNO", "100", "Concreto", "M3", 1.05, 350000.0)])
    return cliente(create_app(almacen=alm), rol="admin"), alm


def test_crear_corrida_exige_carpeta(tmp_path):
    cli, alm = _cli_seed(tmp_path)
    obra = cli.post("/api/carpetas", json={"nombre": "Obra"}).json()
    lic = tmp_path / "lic.xlsx"
    write_sample_licitacion(lic, [LicitacionItem(
        item="1", descripcion="Concreto clase D", unidad="M3", cantidad=10.0,
        precio_contractual=400000.0, shift="DIURNO")])
    with open(lic, "rb") as f:
        r = cli.post("/api/corridas",
                     data={"turno": "DIURNO", "use_ai": "false", "carpeta_id": str(obra["id"])},
                     files={"archivo": ("lic.xlsx", f, "application/octet-stream")})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    assert alm.corridas.get_corrida(cid).carpeta_id == obra["id"]


def test_crear_corrida_carpeta_invalida_400(tmp_path):
    cli, _ = _cli_seed(tmp_path)
    lic = tmp_path / "lic.xlsx"
    write_sample_licitacion(lic, [LicitacionItem(
        item="1", descripcion="Concreto clase D", unidad="M3", cantidad=10.0,
        precio_contractual=400000.0, shift="DIURNO")])
    with open(lic, "rb") as f:
        r = cli.post("/api/corridas",
                     data={"turno": "DIURNO", "use_ai": "false", "carpeta_id": "9999"},
                     files={"archivo": ("lic.xlsx", f, "application/octet-stream")})
    assert r.status_code == 400


def test_sample_va_a_sin_clasificar(tmp_path):
    cli, alm = _cli_seed(tmp_path)
    r = cli.post("/api/sample")
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    sc = alm.corridas.get_corrida(cid).carpeta_id
    assert alm.carpetas.get(sc).nombre == "Sin clasificar"
```

> Los tests existentes en `tests/test_api_corridas.py` que crean corridas sin `carpeta_id` ahora deben fallar con 400. Actualízalos: crea primero una carpeta y pasa `carpeta_id` en el `data=`. Repite el patrón `obra = cli.post("/api/carpetas", json={"nombre": "Obra"}).json()` en `test_flujo_corrida_completo` y los demás que llamen a `/api/corridas` o `/api/corridas/stream`.

- [ ] **Step 2: Correr para ver que falla**

Run: `python -m pytest tests/test_api_carpetas.py -q`
Expected: FAIL (crear corrida aún no exige/lee `carpeta_id`).

- [ ] **Step 3: Implementación**

En `apu_tool/servicio/carpetas.py` agregar el helper:

```python
def carpeta_sin_clasificar_id(alm: Almacen) -> int:
    """Id de la carpeta raíz 'Sin clasificar' (la crea init_schema; fallback defensivo)."""
    for c in alm.carpetas.listar():
        if c.parent_id is None and c.nombre == "Sin clasificar":
            return c.id
    return alm.carpetas.crear("Sin clasificar", parent_id=None)
```

En `apu_tool/servicio/rutas.py`:

`crear_corrida` (línea 103-126) — agregar `carpeta_id: int = Form(...)`, validar y pasar:

```python
@router.post("/corridas")
async def crear_corrida(turno: str = Form(config.SHIFT_DIURNO),
                        use_ai: Optional[bool] = Form(None),
                        carpeta_id: int = Form(...),
                        archivo: UploadFile = File(...),
                        alm: Almacen = Depends(get_almacen),
                        _: object = Depends(requiere_rol("consulta"))):
    if alm.carpetas.get(carpeta_id) is None:
        raise HTTPException(status_code=400, detail="La carpeta indicada no existe.")
    if alm.counts().get("apus", 0) == 0:
        ensure_seeded()
    # ... (resto igual hasta la llamada al servicio) ...
    cid = svc.construir_corrida(alm, archivo.filename or "licitacion", items, turno,
                                use_ai, carpeta_id=carpeta_id)
    return {"id": cid, "resumen": svc.vista_corrida(alm, cid)["totales"]}
```

`crear_corrida_stream` (línea 159-183) — mismo cambio: `carpeta_id: int = Form(...)`, validar existencia (400 si no), y pasar `carpeta_id=carpeta_id` a `svc.construir_corrida_stream(...)`.

`crear_sample` (línea 129-146) y `crear_sample_stream` (línea 186-204) — asignar "Sin clasificar":

```python
    sc = carpetas_svc.carpeta_sin_clasificar_id(alm)
    cid = svc.construir_corrida(alm, "ejemplo.xlsx", items, config.SHIFT_DIURNO, False,
                                carpeta_id=sc)
```

y en el stream: `gen = svc.construir_corrida_stream(alm, "ejemplo.xlsx", items, config.SHIFT_DIURNO, False, carpeta_id=sc)`.

- [ ] **Step 4: Correr para ver que pasa**

Run: `python -m pytest tests/test_api_carpetas.py tests/test_api_corridas.py -q`
Expected: PASS (tras actualizar los tests viejos de `test_api_corridas.py`).

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/rutas.py apu_tool/servicio/carpetas.py tests/test_api_carpetas.py tests/test_api_corridas.py
git commit -m "feat(api): carpeta_id obligatorio al crear corrida; sample -> Sin clasificar"
```

---

## Fase D — Paridad Postgres + RLS

### Task D1: Esquema Postgres — `carpeta` + `corrida.carpeta_id` + backfill

**Files:**
- Modify: `db/pg/corridas.sql`

- [ ] **Step 1: Editar el esquema**

Reescribir `db/pg/corridas.sql` para incluir `carpeta` (antes de `corrida`), la columna `carpeta_id`, el índice de hermanas y el bootstrap/backfill idempotente:

```sql
-- Esquema Postgres de corridas (Supabase). Equivalente a db/corridas.sql.
CREATE SCHEMA IF NOT EXISTS corridas;

CREATE TABLE IF NOT EXISTS corridas.carpeta (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre        TEXT NOT NULL,
    parent_id     BIGINT REFERENCES corridas.carpeta(id) ON DELETE RESTRICT,
    creada_en     TEXT NOT NULL,
    creado_por    TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_carpeta_hermanas
    ON corridas.carpeta(COALESCE(parent_id, 0), nombre);

CREATE TABLE IF NOT EXISTS corridas.corrida (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    creada_en     TEXT NOT NULL,
    archivo       TEXT NOT NULL,
    turno_def     TEXT NOT NULL,
    use_ai        SMALLINT,
    estado        TEXT NOT NULL,
    cuadro_path   TEXT,
    duracion_ms   INTEGER,
    creado_por    TEXT,
    modo          TEXT NOT NULL DEFAULT 'activa',
    carpeta_id    BIGINT REFERENCES corridas.carpeta(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS corridas.corrida_item (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    corrida_id    BIGINT NOT NULL REFERENCES corridas.corrida(id) ON DELETE CASCADE,
    seq           INTEGER NOT NULL,
    item_json     TEXT NOT NULL,
    status        TEXT NOT NULL,
    apu_codigo    TEXT,
    apu_nombre    TEXT,
    unidad        TEXT,
    shift         TEXT,
    origen        TEXT,
    confianza     DOUBLE PRECISION,
    explicacion   TEXT,
    componentes_json TEXT,
    candidatos_json  TEXT,
    snapshot_json    TEXT
);
CREATE INDEX IF NOT EXISTS ix_corrida_item ON corridas.corrida_item(corrida_id, seq);

-- Migración idempotente para bases existentes.
ALTER TABLE corridas.corrida ADD COLUMN IF NOT EXISTS modo TEXT NOT NULL DEFAULT 'activa';
ALTER TABLE corridas.corrida_item ADD COLUMN IF NOT EXISTS snapshot_json TEXT;
ALTER TABLE corridas.corrida ADD COLUMN IF NOT EXISTS carpeta_id BIGINT
    REFERENCES corridas.carpeta(id) ON DELETE RESTRICT;

-- Bootstrap "Sin clasificar" + backfill de corridas sin carpeta (idempotente).
INSERT INTO corridas.carpeta (nombre, creada_en)
    SELECT 'Sin clasificar', to_char(now(), 'YYYY-MM-DD"T"HH24:MI:SS')
    WHERE NOT EXISTS (SELECT 1 FROM corridas.carpeta
                      WHERE nombre = 'Sin clasificar' AND parent_id IS NULL);
UPDATE corridas.corrida SET carpeta_id =
    (SELECT id FROM corridas.carpeta WHERE nombre='Sin clasificar' AND parent_id IS NULL)
    WHERE carpeta_id IS NULL;
```

- [ ] **Step 2: Verificar sintaxis (sin base PG en local es opcional)**

Si hay `DATABASE_URL` de una base de prueba: `python -c "from apu_tool.datos.pg.conexion import Conexion, ejecutar_script; import os; c=Conexion(os.environ['DATABASE_URL']); from pathlib import Path; [ejecutar_script(conn, Path('db/pg/corridas.sql').read_text()) for conn in [c.connection().__enter__()]]"`
Expected: sin error. (Si no hay PG local, saltar — se valida en Task D4.)

- [ ] **Step 3: Commit**

```bash
git add db/pg/corridas.sql
git commit -m "feat(pg): esquema carpeta + carpeta_id + backfill Sin clasificar"
```

---

### Task D2: `CarpetasPg` (repo Postgres)

**Files:**
- Create: `apu_tool/datos/pg/carpetas_pg.py`

- [ ] **Step 1: Implementación (port de CarpetasDB con placeholders `%s`)**

Crear `apu_tool/datos/pg/carpetas_pg.py`:

```python
"""Backend Postgres de carpetas. Implementa RepositorioCarpetas. Port de carpetas_db.py."""
from __future__ import annotations

import datetime as _dt
from typing import Optional

from apu_tool.datos.pg.conexion import Conexion
from apu_tool.nucleo.models import Carpeta


class CarpetasPg:
    def __init__(self, cx: Conexion):
        self.cx = cx

    def _fila(self, r) -> Carpeta:
        return Carpeta(id=r["id"], nombre=r["nombre"], parent_id=r["parent_id"],
                       creada_en=r["creada_en"], creado_por=r["creado_por"])

    def crear(self, nombre: str, parent_id: Optional[int] = None,
              creado_por: Optional[str] = None, conn=None) -> int:
        creada_en = _dt.datetime.now().isoformat(timespec="seconds")
        sql = ("INSERT INTO corridas.carpeta (nombre, parent_id, creada_en, creado_por) "
               "VALUES (%s,%s,%s,%s) RETURNING id")
        params = (nombre, parent_id, creada_en, creado_por)
        if conn is not None:
            return int(conn.execute(sql, params).fetchone()["id"])
        with self.cx.connection() as c:
            return int(c.execute(sql, params).fetchone()["id"])

    def get(self, carpeta_id: int) -> Optional[Carpeta]:
        with self.cx.connection() as conn:
            r = conn.execute("SELECT * FROM corridas.carpeta WHERE id=%s",
                             (int(carpeta_id),)).fetchone()
        return self._fila(r) if r else None

    def listar(self) -> list[Carpeta]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM corridas.carpeta ORDER BY parent_id IS NOT NULL, nombre").fetchall()
        return [self._fila(r) for r in rows]

    def renombrar(self, carpeta_id: int, nombre: str, conn=None) -> None:
        sql = "UPDATE corridas.carpeta SET nombre=%s WHERE id=%s"
        params = (nombre, int(carpeta_id))
        if conn is not None:
            conn.execute(sql, params); return
        with self.cx.connection() as c:
            c.execute(sql, params)

    def mover(self, carpeta_id: int, parent_id: Optional[int], conn=None) -> None:
        sql = "UPDATE corridas.carpeta SET parent_id=%s WHERE id=%s"
        params = (parent_id, int(carpeta_id))
        if conn is not None:
            conn.execute(sql, params); return
        with self.cx.connection() as c:
            c.execute(sql, params)

    def eliminar(self, carpeta_id: int, conn=None) -> bool:
        sql = "DELETE FROM corridas.carpeta WHERE id=%s"
        if conn is not None:
            return conn.execute(sql, (int(carpeta_id),)).rowcount > 0
        with self.cx.connection() as c:
            return c.execute(sql, (int(carpeta_id),)).rowcount > 0

    def contar_hijas(self, carpeta_id: int) -> int:
        with self.cx.connection() as conn:
            return conn.execute("SELECT COUNT(*) AS n FROM corridas.carpeta WHERE parent_id=%s",
                                (int(carpeta_id),)).fetchone()["n"]

    def contar_corridas(self, carpeta_id: int) -> int:
        with self.cx.connection() as conn:
            return conn.execute("SELECT COUNT(*) AS n FROM corridas.corrida WHERE carpeta_id=%s",
                                (int(carpeta_id),)).fetchone()["n"]
```

- [ ] **Step 2: Commit**

```bash
git add apu_tool/datos/pg/carpetas_pg.py
git commit -m "feat(pg): CarpetasPg (repo Postgres)"
```

---

### Task D3: `CorridasPg` — `carpeta_id` + `set_carpeta`; servicio usa repo para mover

**Files:**
- Modify: `apu_tool/datos/pg/corridas_pg.py` (`_insert_corrida`, `_row_to_meta`, `set_carpeta`)
- Modify: `apu_tool/servicio/carpetas.py` (`mover_corrida` usa `alm.corridas.set_carpeta` en vez de SQL crudo)

- [ ] **Step 1: Implementación**

En `apu_tool/datos/pg/corridas_pg.py`:

`_insert_corrida` (línea 45-52) — agregar `carpeta_id`:

```python
    def _insert_corrida(self, conn, meta: CorridaMeta) -> int:
        cur = conn.execute(
            "INSERT INTO corridas.corrida (creada_en, archivo, turno_def, use_ai, estado, "
            "cuadro_path, duracion_ms, modo, carpeta_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (meta.creada_en, meta.archivo, meta.turno_def,
             None if meta.use_ai is None else int(meta.use_ai),
             meta.estado, meta.cuadro_path, meta.duracion_ms, meta.modo, meta.carpeta_id))
        return int(cur.fetchone()["id"])
```

`_row_to_meta` (línea 128-134) — agregar `carpeta_id`:

```python
            modo=(r["modo"] or "activa"),
            carpeta_id=r.get("carpeta_id") if hasattr(r, "get") else r["carpeta_id"])
```

> `psycopg` devuelve filas tipo dict-row; `r["carpeta_id"]` funciona. Usa `r["carpeta_id"]` directamente si tu row factory no soporta `.get`.

Agregar `set_carpeta` (junto a `set_modo`):

```python
    def set_carpeta(self, corrida_id: int, carpeta_id: int) -> None:
        with self.cx.connection() as conn:
            conn.execute("UPDATE corridas.corrida SET carpeta_id=%s WHERE id=%s",
                         (int(carpeta_id), int(corrida_id)))
```

En `apu_tool/servicio/carpetas.py`, `mover_corrida` — reemplazar el `conn.execute("UPDATE corrida ...")` crudo por el repo (agnóstico de dialecto). Como necesitamos la mutación + auditoría en la misma transacción, agregar un método de repo que acepte `conn`. **Cambio requerido:** en `RepositorioCorridas`, `CorridasDB` y `CorridasPg`, la firma de `set_carpeta` pasa a aceptar `conn=None`:

`repositorio.py`:
```python
    def set_carpeta(self, corrida_id: int, carpeta_id: int, conn=None) -> None: ...
```

`corridas_db.py`:
```python
    def set_carpeta(self, corrida_id: int, carpeta_id: int, conn=None) -> None:
        sql = "UPDATE corrida SET carpeta_id=? WHERE id=?"
        params = (int(carpeta_id), int(corrida_id))
        if conn is not None:
            conn.execute(sql, params); return
        with self.connect() as c:
            c.execute(sql, params)
```

`corridas_pg.py`:
```python
    def set_carpeta(self, corrida_id: int, carpeta_id: int, conn=None) -> None:
        sql = "UPDATE corridas.corrida SET carpeta_id=%s WHERE id=%s"
        params = (int(carpeta_id), int(corrida_id))
        if conn is not None:
            conn.execute(sql, params); return
        with self.cx.connection() as c:
            c.execute(sql, params)
```

`carpetas.py` `mover_corrida` — reemplazar el bloque de la transacción:
```python
    with alm.transaccion("corridas") as conn:
        alm.corridas.set_carpeta(corrida_id, carpeta_id, conn=conn)
        registrar_auditoria(alm, conn, actor, "corrida.mover", "corrida", corrida_id,
                            antes={"carpeta_id": meta.carpeta_id},
                            despues={"carpeta_id": carpeta_id})
    return True
```

- [ ] **Step 2: Correr las pruebas SQLite (regresión)**

Run: `python -m pytest tests/test_servicio_carpetas.py tests/test_carpetas_db.py tests/test_api_carpetas.py -q`
Expected: PASS (el cambio de firma no rompe SQLite).

- [ ] **Step 3: Commit**

```bash
git add apu_tool/datos/pg/corridas_pg.py apu_tool/datos/corridas_db.py apu_tool/datos/repositorio.py apu_tool/servicio/carpetas.py
git commit -m "feat(pg): carpeta_id en CorridasPg; mover_corrida vía repo (agnóstico de dialecto)"
```

---

### Task D4: RLS de `carpetas.carpeta` + prueba de esquema PG

**Files:**
- Create: `supabase/migrations/0004_carpetas_rls.sql`
- Test: `tests/test_pg_esquema.py` (extender si aplica)

- [ ] **Step 1: Revisar el patrón de RLS existente**

Leer `supabase/migrations/0003_rls.sql` para calcar cómo se expresa "lectura para autenticados, escritura según rol" en las tablas de corridas.

- [ ] **Step 2: Escribir la migración RLS**

Crear `supabase/migrations/0004_carpetas_rls.sql` siguiendo el patrón de `0003_rls.sql` (ajusta los nombres de función/claim a los que use ese archivo — p. ej. una función `auth_rol()` o lectura del JWT):

```sql
-- RLS para corridas.carpeta: lectura global (autenticados), escritura por rol.
ALTER TABLE corridas.carpeta ENABLE ROW LEVEL SECURITY;

-- Lectura: cualquier usuario autenticado (carpetas globales).
CREATE POLICY carpeta_select ON corridas.carpeta
    FOR SELECT TO authenticated USING (true);

-- Inserción: consulta+ (todos los autenticados con perfil activo pueden crear).
CREATE POLICY carpeta_insert ON corridas.carpeta
    FOR INSERT TO authenticated WITH CHECK (true);

-- Update/Delete: editor o admin (calcar el predicado de rol de 0003_rls.sql).
CREATE POLICY carpeta_update ON corridas.carpeta
    FOR UPDATE TO authenticated USING (true) WITH CHECK (true);
CREATE POLICY carpeta_delete ON corridas.carpeta
    FOR DELETE TO authenticated USING (true);
```

> **Importante:** el RBAC efectivo lo aplica la API (`requiere_rol`), no la RLS, porque la app usa la service-role key desde el backend. La RLS aquí replica el patrón de `0003_rls.sql` para coherencia/defensa en profundidad. Ajusta los predicados `USING/WITH CHECK` de update/delete al mismo esquema de roles que usan las políticas de `corrida` en `0003_rls.sql` (si allí se restringe por rol, hazlo igual).

- [ ] **Step 3: (Si hay PG de prueba) correr la suite PG**

Run: `python -m pytest tests/test_pg_esquema.py tests/test_migracion_pg.py -q`
Expected: PASS (o SKIP si no hay `DATABASE_URL`).

- [ ] **Step 4: Commit**

```bash
git add supabase/migrations/0004_carpetas_rls.sql
git commit -m "feat(rls): políticas de carpetas.carpeta (lectura global, escritura por rol)"
```

---

## Fase E — Frontend: tipos y cliente API

### Task E1: Tipos `Carpeta`/`CarpetaNodo` + `carpeta_id` en `CorridaResumen`

**Files:**
- Modify: `web/src/lib/tipos.ts`

- [ ] **Step 1: Implementación**

En `web/src/lib/tipos.ts`, agregar los tipos y el campo en `CorridaResumen` (línea 109-122):

```typescript
export interface Carpeta {
  id: number;
  nombre: string;
  parent_id: number | null;
}

export interface CarpetaNodo {
  id: number;
  nombre: string;
  parent_id: number | null;
  n_corridas: number;
  hijas: CarpetaNodo[];
}
```

En `CorridaResumen` agregar:

```typescript
  carpeta_id: number | null;
```

En `CorridaDetalle` (línea 137-145) agregar también:

```typescript
  carpeta_id: number | null;
```

- [ ] **Step 2: Verificar tipos**

Run: `cd web && npx tsc --noEmit`
Expected: sin errores nuevos por estos tipos.

- [ ] **Step 3: Commit**

```bash
git add web/src/lib/tipos.ts
git commit -m "feat(web): tipos Carpeta/CarpetaNodo y carpeta_id en corridas"
```

---

### Task E2: Cliente API `web/src/api/carpetas.ts`

**Files:**
- Create: `web/src/api/carpetas.ts`
- Test: `web/src/api/carpetas.test.ts`

- [ ] **Step 1: Escribir el test que falla**

Crear `web/src/api/carpetas.test.ts` (calcar el estilo de mock de `web/src/api/corridas.*.test.ts`; ajusta el mock de `@/api/client` a como lo hacen esos tests):

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import * as client from "@/api/client";
import { listarCarpetas, crearCarpeta, borrarCarpeta } from "@/api/carpetas";

vi.mock("@/api/client");

beforeEach(() => vi.resetAllMocks());

describe("api/carpetas", () => {
  it("listarCarpetas hace GET /carpetas", async () => {
    (client.apiGet as any).mockResolvedValue([]);
    await listarCarpetas();
    expect(client.apiGet).toHaveBeenCalledWith("/carpetas");
  });

  it("crearCarpeta hace POST con nombre y parent_id", async () => {
    (client.apiPost as any).mockResolvedValue({ id: 1, nombre: "Obra", parent_id: null });
    await crearCarpeta("Obra", null);
    expect(client.apiPost).toHaveBeenCalledWith("/carpetas", { nombre: "Obra", parent_id: null });
  });

  it("borrarCarpeta hace DELETE /carpetas/:id", async () => {
    (client.apiDelete as any).mockResolvedValue(undefined);
    await borrarCarpeta(5);
    expect(client.apiDelete).toHaveBeenCalledWith("/carpetas/5");
  });
});
```

- [ ] **Step 2: Correr para ver que falla**

Run: `cd web && npx vitest run src/api/carpetas.test.ts`
Expected: FAIL (módulo inexistente).

- [ ] **Step 3: Implementación**

Crear `web/src/api/carpetas.ts`:

```typescript
import { apiGet, apiPost, apiPatch, apiDelete } from "@/api/client";
import type { Carpeta, CarpetaNodo, CorridaDetalle } from "@/lib/tipos";

export function listarCarpetas(): Promise<CarpetaNodo[]> {
  return apiGet<CarpetaNodo[]>("/carpetas");
}

export function crearCarpeta(nombre: string, parent_id: number | null): Promise<Carpeta> {
  return apiPost<Carpeta>("/carpetas", { nombre, parent_id });
}

export function renombrarCarpeta(id: number, nombre: string): Promise<Carpeta> {
  return apiPatch<Carpeta>(`/carpetas/${id}`, { nombre });
}

export function moverCarpeta(id: number, parent_id: number | null): Promise<Carpeta> {
  return apiPatch<Carpeta>(`/carpetas/${id}`, { parent_id, mover: true });
}

export function borrarCarpeta(id: number): Promise<void> {
  return apiDelete(`/carpetas/${id}`);
}

export function moverCorrida(corridaId: number, carpeta_id: number): Promise<CorridaDetalle> {
  return apiPost<CorridaDetalle>(`/corridas/${corridaId}/mover`, { carpeta_id });
}
```

> Si `apiPatch` no existe en `web/src/api/client.ts`, agrégalo calcando `apiPost`/`apiDelete` (mismo manejo de `authHeader`/errores) con método `PATCH`. Hazlo en este mismo task y commitea junto.

- [ ] **Step 4: Correr para ver que pasa**

Run: `cd web && npx vitest run src/api/carpetas.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/api/carpetas.ts web/src/api/carpetas.test.ts web/src/api/client.ts
git commit -m "feat(web): cliente API de carpetas + moverCorrida"
```

---

## Fase F — Frontend: navegación y creación

### Task F1: Navegación por carpetas en `MisCorridas.tsx`

**Files:**
- Modify: `web/src/pages/MisCorridas.tsx`
- Test: `web/src/pages/MisCorridas.test.tsx`

- [ ] **Step 1: Escribir el test que falla**

Extender `web/src/pages/MisCorridas.test.tsx` (calcar el render/mocks existentes del archivo). Añadir:

```typescript
// Mockear listarCarpetas junto a listarCorridas (ajusta a los mocks ya presentes).
// Árbol: [{id:1, nombre:"Calle 13", parent_id:null, n_corridas:0,
//          hijas:[{id:2, nombre:"Lote 3", parent_id:1, n_corridas:1, hijas:[]}]}]
// Corridas: una con carpeta_id=2.

it("muestra carpetas de nivel 1 en la raíz y entra al hacer clic", async () => {
  // render con MemoryRouter en "/corridas"
  // espera ver "Calle 13" como carpeta navegable
  // al hacer clic, la URL pasa a ?carpeta=1 y se ve la subcarpeta "Lote 3"
  // (usar screen.findByText / userEvent.click)
});

it("dentro de una subcarpeta lista solo sus corridas", async () => {
  // navegar a ?carpeta=2 y verificar que la corrida con carpeta_id=2 aparece
});
```

> Completa el cuerpo con el patrón de render ya usado en el archivo (probablemente `render(<MemoryRouter initialEntries={["/corridas"]}>...</MemoryRouter>)` + mocks de `@/api/corridas` y `@/api/carpetas`).

- [ ] **Step 2: Correr para ver que falla**

Run: `cd web && npx vitest run src/pages/MisCorridas.test.tsx`
Expected: FAIL (aún no hay navegación por carpetas).

- [ ] **Step 3: Implementación**

Reescribir `MisCorridas.tsx` para: (a) cargar el árbol con `listarCarpetas()` y las corridas con `listarCorridas()`; (b) leer la carpeta actual de la query `?carpeta=ID` (usar `useSearchParams`); (c) renderizar breadcrumb + subcarpetas del nivel actual + tabla de corridas cuyo `carpeta_id` == carpeta actual.

Núcleo de la lógica (mantén la tabla y estilos existentes; agrega la capa de navegación encima):

```tsx
import { useSearchParams } from "react-router-dom";
import { listarCarpetas, crearCarpeta } from "@/api/carpetas";
import type { CarpetaNodo } from "@/lib/tipos";

// ...dentro del componente:
const [sp, setSp] = useSearchParams();
const carpetaActual = sp.get("carpeta") ? Number(sp.get("carpeta")) : null;
const [arbol, setArbol] = useState<CarpetaNodo[]>([]);

// cargar árbol junto a las corridas en `cargar()`:
//   Promise.all([listarCorridas(), listarCarpetas()]).then(([cs, arb]) => {...})

// aplanar el árbol para buscar por id y construir breadcrumb
function planos(nodos: CarpetaNodo[], acc: CarpetaNodo[] = []): CarpetaNodo[] {
  for (const n of nodos) { acc.push(n); planos(n.hijas, acc); }
  return acc;
}
const todas = planos(arbol);
const actual = todas.find((c) => c.id === carpetaActual) || null;
const subcarpetas = carpetaActual === null
  ? arbol
  : (actual?.hijas ?? []);
const corridasVisibles = corridas.filter((c) =>
  carpetaActual === null ? false : c.carpeta_id === carpetaActual);

function irA(id: number | null) {
  if (id === null) setSp({});
  else setSp({ carpeta: String(id) });
}
```

Render:
- **Breadcrumb:** `Todas` → (si `actual.parent_id`) padre → `actual`. Cada segmento llama `irA(...)`.
- **Subcarpetas:** lista/tarjetas con nombre + `n_corridas`, clic → `irA(sub.id)`. En la raíz se muestran las de nivel 1; dentro de una de nivel 1, sus hijas.
- **Corridas:** la tabla actual, pero filtrada a `corridasVisibles` (solo cuando `carpetaActual !== null`; en la raíz se muestran solo carpetas, no corridas, porque toda corrida vive dentro de una carpeta).
- **Botón "Nueva carpeta":** visible siempre (`consulta`+); pide nombre (`window.prompt` o modal simple) y llama `crearCarpeta(nombre, carpetaActual)` — si estás en una carpeta de nivel 1 crea subcarpeta; en la raíz crea nivel 1. Tras crear, recargar el árbol.

> Mantener columnas/totales de la tabla intactos (ya existen). Solo cambia qué filas se muestran y se añade la capa de carpetas.

- [ ] **Step 4: Correr para ver que pasa**

Run: `cd web && npx vitest run src/pages/MisCorridas.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/MisCorridas.tsx web/src/pages/MisCorridas.test.tsx
git commit -m "feat(web): navegacion por carpetas en Mis corridas (breadcrumb + subcarpetas)"
```

---

### Task F2: Selector/creación de carpeta al crear corrida

**Files:**
- Modify: `web/src/pages/CorridasInicio.tsx`
- Modify: `web/src/api/corridas.ts` (pasar `carpeta_id` en el FormData) — o donde se arme el `FormData` de creación.
- Test: extender el test de `CorridasInicio` si existe, o `web/src/pages/CorridasInicio` render test.

- [ ] **Step 1: Escribir el test que falla**

Añadir un test que verifique que el botón de armar está deshabilitado hasta elegir carpeta, y que al enviar se incluye `carpeta_id` en el `FormData`. Calcar mocks de `crearCorridaStream`/`crearSampleStream` ya usados.

```typescript
it("exige elegir carpeta antes de armar", async () => {
  // render CorridasInicio con árbol mockeado (listarCarpetas)
  // el botón "Armar"/"Crear corrida" está deshabilitado sin carpeta
  // tras elegir una carpeta del selector, se habilita
});
```

- [ ] **Step 2: Correr para ver que falla**

Run: `cd web && npx vitest run src/pages/CorridasInicio`
Expected: FAIL.

- [ ] **Step 3: Implementación**

En `CorridasInicio.tsx`:
- Cargar el árbol con `listarCarpetas()`.
- Añadir dos `<select>` encadenados: nivel 1 (carpetas raíz) y nivel 2 (hijas de la seleccionada, opcional). La carpeta destino = la de nivel 2 si se eligió, si no la de nivel 1. Debajo, un botón "Crear carpeta nueva" que llama `crearCarpeta(nombre, parentSeleccionado)` y refresca.
- El botón de armar queda deshabilitado (`disabled`) hasta que haya `carpetaDestino`.
- Al armar, incluir `carpeta_id` en el `FormData`:

```tsx
const fd = new FormData();
fd.append("archivo", file);
fd.append("turno", turno);
fd.append("use_ai", String(useAi));
fd.append("carpeta_id", String(carpetaDestino));   // obligatorio
```

Ajustar la firma de `crearCorridaStream` / la construcción del `FormData` para que `carpeta_id` viaje (el backend lo exige; sin él responde 400).

> El `sample` no necesita carpeta en el front (el backend lo manda a "Sin clasificar").

- [ ] **Step 4: Correr para ver que pasa**

Run: `cd web && npx vitest run src/pages/CorridasInicio`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/CorridasInicio.tsx web/src/api/corridas.ts
git commit -m "feat(web): elegir/crear carpeta obligatoria al armar una corrida"
```

---

## Fase G — Verificación final

### Task G1: Suite completa backend + frontend

- [ ] **Step 1: Backend**

Run: `python -m pytest tests/ -q`
Expected: PASS (toda la suite; sin regresiones en corridas/api).

- [ ] **Step 2: Frontend**

Run: `cd web && npx vitest run && npx tsc --noEmit`
Expected: PASS y sin errores de tipos.

- [ ] **Step 3: Humo manual (opcional pero recomendado)**

Run: `python run_gui.py` o levantar la web; crear una carpeta `Calle 13`, una subcarpeta `Lote 3`, armar una corrida dentro, verificar que aparece al navegar y que borrar `Calle 13` da error por no estar vacía.

- [ ] **Step 4: Commit final / merge**

Usar la skill `superpowers:finishing-a-development-branch` para decidir merge/PR.

---

## Notas de decisión (para el implementador)

- **Profundidad y unicidad** se validan en servicio; el índice `ux_carpeta_hermanas` es la última línea de defensa (por eso el servicio traduce `IntegrityError` a `CarpetaInvalida`).
- **`carpeta_id` es nullable en la base** por practicidad de migración SQLite, pero **la API lo exige** al crear corridas y la migración backfilea las viejas a "Sin clasificar". Nunca debería quedar una corrida con `carpeta_id NULL` tras `init_schema`.
- **RBAC lo aplica la API** (`requiere_rol`), no la RLS (el backend usa service-role). La RLS es defensa en profundidad y debe calcar `0003_rls.sql`.
- **DRY:** la construcción del árbol y las validaciones viven solo en `servicio/carpetas.py`; la API y el front no reimplementan reglas.
