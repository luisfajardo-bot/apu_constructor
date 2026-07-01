# Auditoría Transaccional — Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Registrar en un log append-only —en la MISMA transacción que la mutación— quién cambió qué y cuándo sobre precios, catálogo, corridas y usuarios, con endpoint y visor solo-Admin.

**Architecture:** Una unidad de trabajo en `Almacen.transaccion(dominio)` cede UNA conexión que ve tanto la tabla del dominio mutado como `auditoria`. En Postgres es una conexión del pool (schemas `precios/apus/corridas/seguridad`); en SQLite es una conexión sobre el archivo del dominio con `ATTACH` de `seguridad.db` (la tabla `auditoria` resuelve sin calificar). Los métodos de escritura auditados ganan un `conn` opcional: si viene, ejecutan sobre esa conexión sin commit (camino nuevo, transaccional); si es `None`, abren su propia conexión como hoy (camino intacto). La capa de servicio envuelve mutación + `registrar_auditoria(...)` en la UdT.

**Tech Stack:** Python 3, FastAPI, psycopg v3 (+ `psycopg.types.json.Jsonb`), SQLite (stdlib `sqlite3`, modo rollback-journal), React 19 + Vite + Tailwind + shadcn/ui, vitest.

## Global Constraints

- **Invariante #1 (NO romper):** la IA nunca ve dinero. NO tocar `apu_tool/dominio/privacy.py`, `apu_tool/dominio/ai_assist.py`, ni las vistas `DePriced*`. Auditoría vive SOLO en `apu_tool/servicio/` y `apu_tool/datos/`.
- **Repos DUALES:** todo cambio de esquema/método va en SQLite (`apu_tool/datos/*_db.py`, `db/*.sql`) **y** Postgres (`apu_tool/datos/pg/*_pg.py`, `db/pg/*.sql`), y en el Protocol de `apu_tool/datos/repositorio.py`.
- **`conn=None` preserva el camino actual:** cuando no se pasa conexión, cada método se comporta EXACTAMENTE como hoy (los 204 tests backend siguen verdes).
- **Atomicidad "sin best-effort":** la fila de auditoría se confirma en la misma transacción que la mutación; si una falla, ambas revierten. NO cambiar el `journal_mode` de SQLite a WAL (rompería el commit atómico multi-archivo vía `ATTACH`).
- **Granularidad por-entidad + `lote_id`:** una fila por entidad; las operaciones por lote comparten un `lote_id` (uuid4 hex) en `contexto`. **Transacción POR ÍTEM** en los bucles → se preserva el *partial-success* actual.
- **Postgres no se prueba localmente** (la máquina bloquea el egreso a la BD): los tests de contrato dual corren SQLite y hacen `skip` de Postgres sin `TEST_DATABASE_URL` (patrón de `tests/test_perfiles_contrato.py`). Aplicar la migración Supabase es un paso de ops vía MCP.
- **Español** en dominio, comentarios y mensajes de usuario.
- **DISCIPLINA DE COMMIT:** `git add` SOLO los archivos de cada tarea, por ruta explícita. NUNCA `-A`/`.`/`-u`. Cruft ignorado: `node_modules/` raíz, `.env`; y `ejemplos/licitacion_ejemplo.xlsx` está modificado fuera de alcance — NO lo incluyas.
- **Comandos de prueba:** backend `python -m pytest tests/ -q` (desde la raíz). Frontend, dentro de `web/`: `npm test` (vitest run) y `npm run build`.

---

### Task 1: Modelo `EventoAuditoria` + tabla `auditoria` (dual) + Protocol

**Files:**
- Modify: `apu_tool/nucleo/models.py` (añadir dataclass al final de la sección "Catálogos")
- Modify: `db/seguridad.sql` (añadir tabla + índices)
- Modify: `db/pg/seguridad.sql` (añadir tabla + índices)
- Create: `supabase/migrations/0003_auditoria.sql`
- Modify: `apu_tool/datos/repositorio.py` (añadir Protocol `RepositorioAuditoria` + import)
- Test: `tests/test_auditoria_esquema.py`

**Interfaces:**
- Produces: `EventoAuditoria(ts, rol, accion, entidad_tipo, entidad_id, user_id=None, user_email=None, antes=None, despues=None, contexto=None)` (dataclass frozen). Tabla `auditoria` con columnas `id, ts, user_id, user_email, rol, accion, entidad_tipo, entidad_id, antes, despues, contexto`. Protocol `RepositorioAuditoria` con `registrar(conn, evento) -> None` y `listar(*, user_id, accion, entidad_tipo, desde, hasta, lote_id, limit, offset) -> tuple[list[dict], int]`.

- [ ] **Step 1: Write the failing test**

Crea `tests/test_auditoria_esquema.py`:

```python
import sqlite3

from apu_tool import config
from apu_tool.nucleo.models import EventoAuditoria


def test_seguridad_sql_crea_tabla_auditoria(tmp_path):
    db = tmp_path / "seg.db"
    conn = sqlite3.connect(db)
    conn.executescript((config.PROJECT_ROOT / "db" / "seguridad.sql").read_text(encoding="utf-8"))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(auditoria)").fetchall()}
    conn.close()
    assert cols == {"id", "ts", "user_id", "user_email", "rol", "accion",
                    "entidad_tipo", "entidad_id", "antes", "despues", "contexto"}


def test_evento_auditoria_campos():
    ev = EventoAuditoria(ts="2026-07-01T00:00:00+00:00", rol="admin",
                         accion="precio.editar", entidad_tipo="insumo", entidad_id="42")
    assert ev.user_id is None and ev.rol == "admin" and ev.entidad_id == "42"
    assert ev.antes is None and ev.despues is None and ev.contexto is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_auditoria_esquema.py -q`
Expected: FAIL (`ImportError: cannot import name 'EventoAuditoria'`).

- [ ] **Step 3: Añadir el dataclass a `models.py`**

En `apu_tool/nucleo/models.py`, justo después de la clase `Perfil` (línea ~68), añade:

```python
@dataclass(frozen=True)
class EventoAuditoria:
    """Un evento de auditoría (tabla seguridad.auditoria). SIN dinero directo:
    los precios viajan dentro de antes/despues como parte del estado, nunca hacia la IA."""
    ts: str                                  # ISO 8601 UTC
    rol: str                                 # rol del actor; "sistema" si no hay actor
    accion: str                              # taxonomía objeto.verbo (p.ej. "precio.editar")
    entidad_tipo: str                        # insumo | apu | corrida | usuario
    entidad_id: str
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    antes: Optional[dict] = None
    despues: Optional[dict] = None
    contexto: Optional[dict] = None
```

- [ ] **Step 4: Añadir la tabla `auditoria` a `db/seguridad.sql`**

Añade al final de `db/seguridad.sql` (después de la tabla `perfiles`):

```sql

CREATE TABLE IF NOT EXISTS auditoria (
    id           INTEGER PRIMARY KEY,     -- rowid SQLite; sin AUTOINCREMENT (porta a Postgres)
    ts           TEXT NOT NULL,           -- ISO 8601 UTC
    user_id      TEXT,                    -- actor; NULL = sistema (CLI/seed)
    user_email   TEXT,
    rol          TEXT NOT NULL,
    accion       TEXT NOT NULL,
    entidad_tipo TEXT NOT NULL,
    entidad_id   TEXT,
    antes        TEXT,                    -- JSON (estado previo)
    despues      TEXT,                    -- JSON (estado nuevo)
    contexto     TEXT                     -- JSON ({origen, lote_id, archivo, ...})
);
CREATE INDEX IF NOT EXISTS idx_auditoria_ts ON auditoria(ts);
CREATE INDEX IF NOT EXISTS idx_auditoria_entidad ON auditoria(entidad_tipo, entidad_id);
CREATE INDEX IF NOT EXISTS idx_auditoria_user ON auditoria(user_id);
```

- [ ] **Step 5: Añadir la tabla a `db/pg/seguridad.sql`**

Añade al final de `db/pg/seguridad.sql`:

```sql

CREATE TABLE IF NOT EXISTS seguridad.auditoria (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts           TEXT NOT NULL,           -- ISO 8601 UTC (TEXT como el resto de fechas del proyecto)
    user_id      TEXT,
    user_email   TEXT,
    rol          TEXT NOT NULL,
    accion       TEXT NOT NULL,
    entidad_tipo TEXT NOT NULL,
    entidad_id   TEXT,
    antes        JSONB,
    despues      JSONB,
    contexto     JSONB
);
CREATE INDEX IF NOT EXISTS idx_auditoria_ts ON seguridad.auditoria(ts);
CREATE INDEX IF NOT EXISTS idx_auditoria_entidad ON seguridad.auditoria(entidad_tipo, entidad_id);
CREATE INDEX IF NOT EXISTS idx_auditoria_user ON seguridad.auditoria(user_id);
```

- [ ] **Step 6: Crear la migración Supabase**

Crea `supabase/migrations/0003_auditoria.sql`:

```sql
-- Registro de auditoría append-only. Vive en el schema seguridad (junto a perfiles).
CREATE SCHEMA IF NOT EXISTS seguridad;

CREATE TABLE IF NOT EXISTS seguridad.auditoria (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts           TEXT NOT NULL,
    user_id      TEXT,
    user_email   TEXT,
    rol          TEXT NOT NULL,
    accion       TEXT NOT NULL,
    entidad_tipo TEXT NOT NULL,
    entidad_id   TEXT,
    antes        JSONB,
    despues      JSONB,
    contexto     JSONB
);
CREATE INDEX IF NOT EXISTS idx_auditoria_ts ON seguridad.auditoria(ts);
CREATE INDEX IF NOT EXISTS idx_auditoria_entidad ON seguridad.auditoria(entidad_tipo, entidad_id);
CREATE INDEX IF NOT EXISTS idx_auditoria_user ON seguridad.auditoria(user_id);

-- Defensa en profundidad: RLS habilitada SIN policies (FastAPI usa service_role, que hace bypass).
ALTER TABLE seguridad.auditoria ENABLE ROW LEVEL SECURITY;
```

> **Ops (fuera de tests):** aplicar esta migración a Supabase vía el MCP (`execute_sql` con el contenido, o `supabase db push`). No se prueba localmente (egreso a la BD bloqueado).

- [ ] **Step 7: Añadir el Protocol `RepositorioAuditoria`**

En `apu_tool/datos/repositorio.py`, añade `EventoAuditoria` al import de modelos (línea ~11):

```python
from apu_tool.nucleo.models import (
    Apu, ApuComponent, CorridaItemRow, CorridaMeta, DePricedApu, EventoAuditoria, Insumo, Perfil,
)
```

Y añade al final del archivo:

```python
@runtime_checkable
class RepositorioAuditoria(Protocol):
    def registrar(self, conn, evento: EventoAuditoria) -> None:
        """Inserta un evento SOBRE la conexión dada (transaccional con la mutación).
        NUNCA abre su propia conexión."""
        ...

    def listar(self, *, user_id: Optional[str] = None, accion: Optional[str] = None,
               entidad_tipo: Optional[str] = None, desde: Optional[str] = None,
               hasta: Optional[str] = None, lote_id: Optional[str] = None,
               limit: int = 100, offset: int = 0) -> tuple[list[dict], int]:
        """Lectura paginada (abre su propia conexión). antes/despues/contexto ya
        parseados a objetos Python (dict/None). Orden ts desc."""
        ...
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `python -m pytest tests/test_auditoria_esquema.py -q`
Expected: PASS (2 passed).

- [ ] **Step 9: Commit**

```bash
git add apu_tool/nucleo/models.py db/seguridad.sql db/pg/seguridad.sql supabase/migrations/0003_auditoria.sql apu_tool/datos/repositorio.py tests/test_auditoria_esquema.py
git commit -m "feat(auditoria): modelo EventoAuditoria + tabla auditoria (dual) + Protocol"
```

---

### Task 2: Repos duales `AuditoriaDB` / `AuditoriaPg` + `Almacen.auditoria` + reset

**Files:**
- Create: `apu_tool/datos/auditoria_db.py`
- Create: `apu_tool/datos/pg/auditoria_pg.py`
- Modify: `apu_tool/datos/perfiles_db.py` (reset borra también `auditoria`)
- Modify: `apu_tool/datos/almacen.py` (añadir `self.auditoria`; guardar rutas para la UdT)
- Test: `tests/test_auditoria_contrato.py`

**Interfaces:**
- Consumes: `EventoAuditoria` (Task 1), tabla `auditoria` (Task 1).
- Produces: `AuditoriaDB(path)` y `AuditoriaPg(cx)` con `registrar(conn, evento)` y `listar(...)`. `Almacen.auditoria` (repo), `Almacen._paths` (dict dominio→Path SQLite) y `Almacen._seg_path`. `perfiles.reset()` deja `auditoria` vacía.

- [ ] **Step 1: Write the failing test**

Crea `tests/test_auditoria_contrato.py` (patrón dual de `test_perfiles_contrato.py`):

```python
import os
import sqlite3
import pytest

from apu_tool import config
from apu_tool.nucleo.models import EventoAuditoria


def _ev(accion="precio.editar", entidad_id="1", lote=None):
    return EventoAuditoria(
        ts="2026-07-01T10:00:00+00:00", rol="admin", accion=accion,
        entidad_tipo="insumo", entidad_id=entidad_id, user_id="u1",
        user_email="a@obra.co", antes={"precio": 10.0}, despues={"precio": 20.0},
        contexto={"origen": "edicion", "lote_id": lote} if lote else {"origen": "edicion"})


def _sqlite(tmp_path):
    from apu_tool.datos.auditoria_db import AuditoriaDB
    seg = tmp_path / "seg.db"
    conn = sqlite3.connect(seg)
    conn.executescript((config.PROJECT_ROOT / "db" / "seguridad.sql").read_text(encoding="utf-8"))
    conn.commit(); conn.close()
    return AuditoriaDB(seg), None


def _postgres(tmp_path):
    from apu_tool.datos.pg.conexion import Conexion
    from apu_tool.datos.pg.auditoria_pg import AuditoriaPg
    from apu_tool.datos.pg.perfiles_pg import PerfilesPg
    cx = Conexion(os.environ["TEST_DATABASE_URL"])
    PerfilesPg(cx).reset()  # recrea schema seguridad con perfiles + auditoria
    return AuditoriaPg(cx), cx


_BACKENDS = ["sqlite"] + (["postgres"] if os.environ.get("TEST_DATABASE_URL") else [])


@pytest.fixture(params=_BACKENDS)
def repo_conn(request, tmp_path):
    if request.param == "sqlite":
        repo, _ = _sqlite(tmp_path)
        conn = sqlite3.connect(repo.path)
        conn.row_factory = sqlite3.Row
        yield repo, conn
        conn.commit(); conn.close()
    else:
        repo, cx = _postgres(tmp_path)
        with cx.transaccion() as conn:
            yield repo, conn
        cx.cerrar()


def test_registrar_y_listar(repo_conn):
    repo, conn = repo_conn
    repo.registrar(conn, _ev(entidad_id="7"))
    conn.commit() if hasattr(conn, "commit") else None
    items, total = repo.listar()
    assert total == 1
    assert items[0]["entidad_id"] == "7"
    assert items[0]["antes"] == {"precio": 10.0}          # JSON parseado a dict
    assert items[0]["contexto"]["origen"] == "edicion"
    assert items[0]["rol"] == "admin"


def test_listar_filtra_por_accion_y_lote(repo_conn):
    repo, conn = repo_conn
    repo.registrar(conn, _ev(accion="precio.editar", lote="L1"))
    repo.registrar(conn, _ev(accion="usuario.invitar", entidad_id="u9"))
    conn.commit() if hasattr(conn, "commit") else None
    solo_precio, n = repo.listar(accion="precio.editar")
    assert n == 1 and solo_precio[0]["accion"] == "precio.editar"
    por_lote, nl = repo.listar(lote_id="L1")
    assert nl == 1 and por_lote[0]["contexto"]["lote_id"] == "L1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_auditoria_contrato.py -q`
Expected: FAIL (`ModuleNotFoundError: apu_tool.datos.auditoria_db`).

- [ ] **Step 3: Crear `apu_tool/datos/auditoria_db.py`**

```python
"""Acceso SQLite a la tabla `auditoria` (vive en seguridad.db, junto a perfiles).

Implementa RepositorioAuditoria. `registrar` NUNCA abre su propia conexión: escribe
sobre la conexión de la unidad de trabajo (transaccional con la mutación auditada).
La tabla se nombra sin calificar; cuando la UdT ATTACHea seguridad.db a la conexión
de otro dominio, `auditoria` resuelve a la única base que la contiene.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from apu_tool import config
from apu_tool.nucleo.models import EventoAuditoria

_CAMPOS = ("id", "ts", "user_id", "user_email", "rol", "accion",
           "entidad_tipo", "entidad_id", "antes", "despues", "contexto")


def _dumps(x) -> Optional[str]:
    return None if x is None else json.dumps(x, ensure_ascii=False)


def _loads(x):
    return None if x is None else json.loads(x)


class AuditoriaDB:
    def __init__(self, path: Path | str = config.DATA_DIR / "seguridad.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def registrar(self, conn: sqlite3.Connection, ev: EventoAuditoria) -> None:
        conn.execute(
            "INSERT INTO auditoria "
            "(ts, user_id, user_email, rol, accion, entidad_tipo, entidad_id, antes, despues, contexto) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ev.ts, ev.user_id, ev.user_email, ev.rol, ev.accion, ev.entidad_tipo,
             str(ev.entidad_id), _dumps(ev.antes), _dumps(ev.despues), _dumps(ev.contexto)))

    def _fila(self, r) -> dict:
        return {"id": r["id"], "ts": r["ts"], "user_id": r["user_id"],
                "user_email": r["user_email"], "rol": r["rol"], "accion": r["accion"],
                "entidad_tipo": r["entidad_tipo"], "entidad_id": r["entidad_id"],
                "antes": _loads(r["antes"]), "despues": _loads(r["despues"]),
                "contexto": _loads(r["contexto"])}

    def listar(self, *, user_id: Optional[str] = None, accion: Optional[str] = None,
               entidad_tipo: Optional[str] = None, desde: Optional[str] = None,
               hasta: Optional[str] = None, lote_id: Optional[str] = None,
               limit: int = 100, offset: int = 0) -> tuple[list[dict], int]:
        where, params = [], []
        if user_id:
            where.append("user_id = ?"); params.append(user_id)
        if accion:
            where.append("accion = ?"); params.append(accion)
        if entidad_tipo:
            where.append("entidad_tipo = ?"); params.append(entidad_tipo)
        if desde:
            where.append("ts >= ?"); params.append(desde)
        if hasta:
            where.append("ts <= ?"); params.append(hasta)
        if lote_id:
            where.append("json_extract(contexto, '$.lote_id') = ?"); params.append(lote_id)
        wsql = (" WHERE " + " AND ".join(where)) if where else ""
        with self.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM auditoria{wsql}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM auditoria{wsql} ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?",
                params + [int(limit), int(offset)]).fetchall()
        return [self._fila(r) for r in rows], int(total)
```

- [ ] **Step 4: Crear `apu_tool/datos/pg/auditoria_pg.py`**

```python
"""Backend Postgres de auditoría (seguridad.auditoria). Implementa RepositorioAuditoria.

`registrar` escribe sobre la conexión de la unidad de trabajo (compartida con la
mutación). Las columnas JSON son jsonb (se adaptan con psycopg Jsonb / se leen como dict).
"""
from __future__ import annotations

from typing import Optional

from psycopg.types.json import Jsonb

from apu_tool.datos.pg.conexion import Conexion
from apu_tool.nucleo.models import EventoAuditoria


def _jb(x):
    return None if x is None else Jsonb(x)


class AuditoriaPg:
    def __init__(self, cx: Conexion):
        self.cx = cx

    def registrar(self, conn, ev: EventoAuditoria) -> None:
        conn.execute(
            "INSERT INTO seguridad.auditoria "
            "(ts, user_id, user_email, rol, accion, entidad_tipo, entidad_id, antes, despues, contexto) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (ev.ts, ev.user_id, ev.user_email, ev.rol, ev.accion, ev.entidad_tipo,
             str(ev.entidad_id), _jb(ev.antes), _jb(ev.despues), _jb(ev.contexto)))

    def _fila(self, r) -> dict:
        # psycopg (dict_row) ya devuelve jsonb como dict/None y ts como str (columna TEXT).
        return {"id": r["id"], "ts": r["ts"], "user_id": r["user_id"],
                "user_email": r["user_email"], "rol": r["rol"], "accion": r["accion"],
                "entidad_tipo": r["entidad_tipo"], "entidad_id": r["entidad_id"],
                "antes": r["antes"], "despues": r["despues"], "contexto": r["contexto"]}

    def listar(self, *, user_id: Optional[str] = None, accion: Optional[str] = None,
               entidad_tipo: Optional[str] = None, desde: Optional[str] = None,
               hasta: Optional[str] = None, lote_id: Optional[str] = None,
               limit: int = 100, offset: int = 0) -> tuple[list[dict], int]:
        where, params = [], []
        if user_id:
            where.append("user_id = %s"); params.append(user_id)
        if accion:
            where.append("accion = %s"); params.append(accion)
        if entidad_tipo:
            where.append("entidad_tipo = %s"); params.append(entidad_tipo)
        if desde:
            where.append("ts >= %s"); params.append(desde)
        if hasta:
            where.append("ts <= %s"); params.append(hasta)
        if lote_id:
            where.append("contexto->>'lote_id' = %s"); params.append(lote_id)
        wsql = (" WHERE " + " AND ".join(where)) if where else ""
        with self.cx.connection() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS n FROM seguridad.auditoria{wsql}", params).fetchone()["n"]
            rows = conn.execute(
                f"SELECT * FROM seguridad.auditoria{wsql} ORDER BY ts DESC, id DESC "
                f"LIMIT %s OFFSET %s", params + [int(limit), int(offset)]).fetchall()
        return [self._fila(r) for r in rows], int(total)
```

- [ ] **Step 5: `perfiles.reset()` borra también `auditoria` (SQLite)**

En `apu_tool/datos/perfiles_db.py`, reemplaza el método `reset`:

```python
    def reset(self) -> None:
        with self.connect() as conn:
            # auditoria comparte este archivo con perfiles: un reset completo la limpia también.
            for t in ("auditoria", "perfiles"):
                conn.execute(f"DROP TABLE IF EXISTS {t}")
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
```

(El `PerfilesPg.reset` ya hace `DROP SCHEMA seguridad CASCADE` + recrea desde `db/pg/seguridad.sql`, que ahora incluye `auditoria` — no requiere cambios.)

- [ ] **Step 6: `Almacen` expone `self.auditoria` y guarda rutas para la UdT**

En `apu_tool/datos/almacen.py`, reemplaza el bloque de `__init__` (líneas 20-38) por:

```python
        self._cx = None
        if config.db_backend() == "postgres":
            from apu_tool.datos.pg.conexion import Conexion
            from apu_tool.datos.pg.precios_pg import PreciosPg
            from apu_tool.datos.pg.apus_pg import ApusPg
            from apu_tool.datos.pg.corridas_pg import CorridasPg
            from apu_tool.datos.pg.perfiles_pg import PerfilesPg
            from apu_tool.datos.pg.auditoria_pg import AuditoriaPg
            self._cx = Conexion(config.database_url())
            self.precios = PreciosPg(self._cx)
            self.apus = ApusPg(self._cx)
            self.corridas = CorridasPg(self._cx)
            self.perfiles = PerfilesPg(self._cx)
            self.auditoria = AuditoriaPg(self._cx)
            self._paths = None
            self._seg_path = None
        else:
            from apu_tool.datos.auditoria_db import AuditoriaDB
            from apu_tool.datos.perfiles_db import PerfilesDB
            self._seg_path = (Path(precios_path).parent / "seguridad.db"
                              if isinstance(precios_path, Path) else config.DATA_DIR / "seguridad.db")
            self.precios = PreciosDB(precios_path)
            self.apus = ApusDB(apus_path)
            self.corridas = CorridasDB(corridas_path)
            self.perfiles = PerfilesDB(self._seg_path)
            self.auditoria = AuditoriaDB(self._seg_path)
            self._paths = {"precios": Path(precios_path), "apus": Path(apus_path),
                           "corridas": Path(corridas_path), "seguridad": Path(self._seg_path)}
```

(No cambies `init_schema`/`reset`/`reset_catalogo`: `auditoria` se crea y se limpia a través de `perfiles`, que posee el esquema `seguridad`.)

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_auditoria_contrato.py tests/test_almacen.py -q`
Expected: PASS (contrato SQLite + almacén verdes; Postgres skip sin `TEST_DATABASE_URL`).

- [ ] **Step 8: Commit**

```bash
git add apu_tool/datos/auditoria_db.py apu_tool/datos/pg/auditoria_pg.py apu_tool/datos/perfiles_db.py apu_tool/datos/almacen.py tests/test_auditoria_contrato.py
git commit -m "feat(auditoria): repos duales AuditoriaDB/AuditoriaPg + Almacen.auditoria"
```

---

### Task 3: `Almacen.transaccion(dominio)` — unidad de trabajo (ATTACH) + atomicidad

**Files:**
- Modify: `apu_tool/datos/almacen.py` (añadir `transaccion` + import `contextmanager`)
- Test: `tests/test_uow_atomicidad.py`

**Interfaces:**
- Consumes: `Almacen._paths`, `Almacen._seg_path`, `Almacen._cx` (Task 2); `Conexion.transaccion()` (ya existe).
- Produces: `Almacen.transaccion(dominio: str)` context manager que cede UNA conexión (SQLite con `ATTACH` de seguridad si `dominio != "seguridad"`; Postgres del pool). Commit único al salir OK; rollback ante excepción.

- [ ] **Step 1: Write the failing test**

Crea `tests/test_uow_atomicidad.py`:

```python
import sqlite3
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Insumo


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def _cuenta_auditoria(alm):
    with alm.auditoria.connect() as c:
        return c.execute("SELECT COUNT(*) FROM auditoria").fetchone()[0]


def _precios_de(alm, iid):
    with alm.precios.connect() as c:
        return c.execute("SELECT COUNT(*) FROM insumo_precios WHERE insumo_id=?", (iid,)).fetchone()[0]


def test_transaccion_precios_commit_escribe_ambas_tablas(tmp_path):
    alm = _alm(tmp_path)
    iid = alm.precios.crear_insumo(Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU"))
    n_precio0 = _precios_de(alm, iid)
    with alm.transaccion("precios") as conn:
        conn.execute("UPDATE insumo_precios SET vigente=0 WHERE insumo_id=?", (iid,))
        conn.execute("INSERT INTO insumo_precios (insumo_id, precio, fuente, clasificacion, fecha, vigente) "
                     "VALUES (?,?,?,?,?,1)", (iid, 2000, "COSTO INTERNO", "interno", "2026-07-01"))
        conn.execute("INSERT INTO auditoria (ts, rol, accion, entidad_tipo, entidad_id) "
                     "VALUES (?,?,?,?,?)", ("2026-07-01T00:00:00+00:00", "admin", "precio.editar", "insumo", str(iid)))
    assert _precios_de(alm, iid) == n_precio0 + 1     # el precio nuevo persiste
    assert _cuenta_auditoria(alm) == 1                # la auditoría persiste (misma tx, otra base)


def test_transaccion_rollback_revierte_ambas(tmp_path):
    alm = _alm(tmp_path)
    iid = alm.precios.crear_insumo(Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU"))
    n_precio0 = _precios_de(alm, iid)
    with pytest.raises(RuntimeError):
        with alm.transaccion("precios") as conn:
            conn.execute("INSERT INTO insumo_precios (insumo_id, precio, fuente, clasificacion, fecha, vigente) "
                         "VALUES (?,?,?,?,?,1)", (iid, 2000, "X", "interno", "2026-07-01"))
            conn.execute("INSERT INTO auditoria (ts, rol, accion, entidad_tipo, entidad_id) "
                         "VALUES (?,?,?,?,?)", ("2026-07-01T00:00:00+00:00", "admin", "precio.editar", "insumo", str(iid)))
            raise RuntimeError("falla la auditoría a mitad")
    assert _precios_de(alm, iid) == n_precio0         # el precio NO persiste (rollback)
    assert _cuenta_auditoria(alm) == 0                # la auditoría NO persiste (rollback)


def test_transaccion_seguridad_sin_attach(tmp_path):
    alm = _alm(tmp_path)
    with alm.transaccion("seguridad") as conn:
        conn.execute("INSERT INTO auditoria (ts, rol, accion, entidad_tipo, entidad_id) "
                     "VALUES (?,?,?,?,?)", ("2026-07-01T00:00:00+00:00", "sistema", "usuario.invitar", "usuario", "u1"))
    assert _cuenta_auditoria(alm) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_uow_atomicidad.py -q`
Expected: FAIL (`AttributeError: 'Almacen' object has no attribute 'transaccion'`).

- [ ] **Step 3: Implementar `transaccion`**

En `apu_tool/datos/almacen.py`, añade los imports que falten al inicio (`Path` ya está importado; añade solo estos dos):

```python
import sqlite3
from contextlib import contextmanager
```

Y añade el método a la clase `Almacen` (p.ej. después de `reset_catalogo`):

```python
    @contextmanager
    def transaccion(self, dominio: str):
        """Unidad de trabajo: cede UNA conexión que ve la tabla del `dominio`
        ('precios'|'apus'|'corridas'|'seguridad') y la tabla `auditoria`, para
        escribir mutación + auditoría atómicamente. Commit único al salir OK;
        rollback ante excepción.

        Postgres: conexión del pool (todos los schemas visibles).
        SQLite: conexión sobre el archivo del dominio; si no es 'seguridad', ATTACH
        de seguridad.db (`auditoria` resuelve sin calificar por ser la única base que
        la contiene). NO usar WAL: rompería el commit atómico multi-archivo.
        """
        if self._cx is not None:  # Postgres: el pool hace commit/rollback al salir
            with self._cx.transaccion() as conn:
                yield conn
            return
        conn = sqlite3.connect(self._paths[dominio])
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if dominio != "seguridad":
            conn.execute("ATTACH DATABASE ? AS seg", (str(self._seg_path),))
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()  # SQLite hace DETACH de las bases adjuntas al cerrar
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_uow_atomicidad.py -q`
Expected: PASS (3 passed). Valida el commit atómico multi-archivo vía ATTACH y el rollback.

- [ ] **Step 5: Commit**

```bash
git add apu_tool/datos/almacen.py tests/test_uow_atomicidad.py
git commit -m "feat(auditoria): Almacen.transaccion(dominio) — UdT con ATTACH atómico"
```

---

### Task 4: `creado_por` + `conn` en repos de precios (dual)

**Files:**
- Modify: `db/precios.sql` (columna `creado_por TEXT`)
- Modify: `apu_tool/datos/precios_db.py` (`init_schema` ALTER; `_insertar_precio_vigente`, `set_precio_por_id`, `crear_insumo` con `conn`/`creado_por`)
- Modify: `apu_tool/datos/pg/precios_pg.py` (mismos métodos; `db/pg/precios.sql` ya tiene la columna)
- Modify: `apu_tool/datos/repositorio.py` (firmas de `set_precio_por_id`, `crear_insumo`)
- Test: `tests/test_precios_conn_creado_por.py`

**Interfaces:**
- Consumes: `Almacen.transaccion` (Task 3).
- Produces: `set_precio_por_id(insumo_id, precio, fuente="", fecha=None, conn=None, creado_por=None) -> None`; `crear_insumo(insumo, conn=None, creado_por=None) -> int`. `insumo_precios.creado_por` se guarda en cada precio nuevo.

- [ ] **Step 1: Write the failing test**

Crea `tests/test_precios_conn_creado_por.py`:

```python
import sqlite3
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.datos.precios_db import PreciosDB
from apu_tool.nucleo.models import Insumo


def _creado_por_vigente(repo, iid):
    with repo.connect() as c:
        r = c.execute("SELECT creado_por FROM insumo_precios WHERE insumo_id=? AND vigente=1",
                      (iid,)).fetchone()
    return r["creado_por"]


def test_set_precio_por_id_guarda_creado_por(tmp_path):
    repo = PreciosDB(tmp_path / "p.db"); repo.init_schema()
    iid = repo.crear_insumo(Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU"))
    repo.set_precio_por_id(iid, 1500, "COSTO INTERNO", creado_por="u-editor")
    assert _creado_por_vigente(repo, iid) == "u-editor"


def test_set_precio_por_id_con_conn_no_autocommite(tmp_path):
    # Con conn de la UdT, si la transacción revierte, el precio NO persiste.
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    iid = alm.precios.crear_insumo(Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU"))
    with pytest.raises(RuntimeError):
        with alm.transaccion("precios") as conn:
            alm.precios.set_precio_por_id(iid, 9999, "X", conn=conn, creado_por="u1")
            raise RuntimeError("aborta")
    with alm.precios.connect() as c:
        n = c.execute("SELECT COUNT(*) FROM insumo_precios WHERE precio=9999").fetchone()[0]
    assert n == 0


def test_crear_insumo_guarda_creado_por(tmp_path):
    repo = PreciosDB(tmp_path / "p.db"); repo.init_schema()
    iid = repo.crear_insumo(Insumo("200", "ARENA", "M3", "MAT", 500, "PRECIO IDU"),
                            creado_por="u-editor")
    assert _creado_por_vigente(repo, iid) == "u-editor"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_precios_conn_creado_por.py -q`
Expected: FAIL (`set_precio_por_id() got an unexpected keyword argument 'creado_por'`).

- [ ] **Step 3: Añadir la columna a `db/precios.sql` y migrar en `init_schema`**

En `db/precios.sql`, dentro de `CREATE TABLE ... insumo_precios`, añade la columna `creado_por` antes de la `FOREIGN KEY`:

```sql
    vigente       INTEGER NOT NULL DEFAULT 1,
    creado_por    TEXT,          -- user_id de quien fijó el precio (NULL = histórico/seed)
    FOREIGN KEY (insumo_id) REFERENCES insumos(id)
```

En `apu_tool/datos/precios_db.py`, reemplaza `init_schema` para migrar bases existentes:

```python
    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(_load_schema())
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(insumo_precios)").fetchall()}
            if "creado_por" not in cols:
                conn.execute("ALTER TABLE insumo_precios ADD COLUMN creado_por TEXT")
```

- [ ] **Step 4: `_insertar_precio_vigente` + `set_precio_por_id` + `crear_insumo` con `conn`/`creado_por` (SQLite)**

En `apu_tool/datos/precios_db.py`, reemplaza `_insertar_precio_vigente`:

```python
    def _insertar_precio_vigente(self, conn: sqlite3.Connection, insumo_id: int, precio: float,
                                fuente: str, fecha: str, creado_por: Optional[str] = None) -> None:
        conn.execute("UPDATE insumo_precios SET vigente=0 WHERE insumo_id=?", (int(insumo_id),))
        conn.execute(
            "INSERT INTO insumo_precios "
            "(insumo_id, precio, fuente, clasificacion, fecha, vigente, creado_por) "
            "VALUES (?,?,?,?,?,1,?)",
            (int(insumo_id), float(precio), fuente,
             config.classify_price_source(fuente), fecha, creado_por))
```

Reemplaza `set_precio_por_id` (líneas 136-143) por una versión con `conn`/`creado_por` que factoriza el cuerpo:

```python
    def set_precio_por_id(self, insumo_id: int, precio: float, fuente: str = "",
                          fecha: Optional[str] = None, conn: Optional[sqlite3.Connection] = None,
                          creado_por: Optional[str] = None) -> None:
        fecha = fecha or date.today().isoformat()
        if conn is not None:
            self._set_precio_por_id(conn, insumo_id, precio, fuente, fecha, creado_por)
            return
        with self.connect() as c:
            self._set_precio_por_id(c, insumo_id, precio, fuente, fecha, creado_por)

    def _set_precio_por_id(self, conn, insumo_id, precio, fuente, fecha, creado_por) -> None:
        r = conn.execute("SELECT id FROM insumos WHERE id=?", (int(insumo_id),)).fetchone()
        if r is None:
            raise ValueError(f"No existe el insumo id={insumo_id}.")
        self._insertar_precio_vigente(conn, int(insumo_id), precio, fuente, fecha, creado_por)
```

Reemplaza `crear_insumo` (líneas 79-103) por una versión con `conn`/`creado_por`:

```python
    def crear_insumo(self, insumo: Insumo, conn: Optional[sqlite3.Connection] = None,
                     creado_por: Optional[str] = None) -> int:
        """Crea un insumo NUEVO + su precio vigente; devuelve el id. Identidad
        (código, nombre_norm): si ya existe → ValueError."""
        if not str(insumo.codigo or "").strip() or not str(insumo.nombre or "").strip():
            raise ValueError("El insumo necesita código y nombre.")
        if conn is not None:
            return self._crear_insumo(conn, insumo, creado_por)
        with self.connect() as c:
            return self._crear_insumo(c, insumo, creado_por)

    def _crear_insumo(self, conn, insumo: Insumo, creado_por: Optional[str]) -> int:
        nombre_norm = normalizar(insumo.nombre)
        hoy = date.today().isoformat()
        existe = conn.execute(
            "SELECT 1 FROM insumos WHERE codigo=? AND nombre_norm=?",
            (str(insumo.codigo), nombre_norm)).fetchone()
        if existe:
            raise ValueError(
                f"Ya existe un insumo con código {insumo.codigo} y ese nombre.")
        cur = conn.execute(
            "INSERT INTO insumos (codigo, nombre, nombre_norm, unidad, grupo) "
            "VALUES (?,?,?,?,?)",
            (str(insumo.codigo), insumo.nombre, nombre_norm, insumo.unidad, insumo.grupo))
        iid = int(cur.lastrowid)
        self._insertar_precio_vigente(conn, iid, insumo.precio, insumo.fuente_precio, hoy, creado_por)
        return iid
```

- [ ] **Step 5: Mismos cambios en `apu_tool/datos/pg/precios_pg.py`**

Reemplaza `_insertar_precio_vigente` (Pg):

```python
    def _insertar_precio_vigente(self, conn, insumo_id: int, precio: float,
                                 fuente: str, fecha: str, creado_por: Optional[str] = None) -> None:
        conn.execute("UPDATE precios.insumo_precios SET vigente=0 WHERE insumo_id=%s",
                     (int(insumo_id),))
        conn.execute(
            "INSERT INTO precios.insumo_precios "
            "(insumo_id, precio, fuente, clasificacion, fecha, vigente, creado_por) "
            "VALUES (%s,%s,%s,%s,%s,1,%s)",
            (int(insumo_id), float(precio), fuente,
             config.classify_price_source(fuente), fecha, creado_por))
```

Reemplaza `set_precio_por_id` (Pg):

```python
    def set_precio_por_id(self, insumo_id: int, precio: float, fuente: str = "",
                          fecha: Optional[str] = None, conn=None,
                          creado_por: Optional[str] = None) -> None:
        fecha = fecha or date.today().isoformat()
        if conn is not None:
            self._set_precio_por_id(conn, insumo_id, precio, fuente, fecha, creado_por)
            return
        with self.cx.connection() as c:
            self._set_precio_por_id(c, insumo_id, precio, fuente, fecha, creado_por)

    def _set_precio_por_id(self, conn, insumo_id, precio, fuente, fecha, creado_por) -> None:
        r = conn.execute("SELECT id FROM precios.insumos WHERE id=%s",
                         (int(insumo_id),)).fetchone()
        if r is None:
            raise ValueError(f"No existe el insumo id={insumo_id}.")
        self._insertar_precio_vigente(conn, int(insumo_id), precio, fuente, fecha, creado_por)
```

Reemplaza `crear_insumo` (Pg):

```python
    def crear_insumo(self, insumo: Insumo, conn=None, creado_por: Optional[str] = None) -> int:
        if not str(insumo.codigo or "").strip() or not str(insumo.nombre or "").strip():
            raise ValueError("El insumo necesita código y nombre.")
        if conn is not None:
            return self._crear_insumo(conn, insumo, creado_por)
        with self.cx.connection() as c:
            return self._crear_insumo(c, insumo, creado_por)

    def _crear_insumo(self, conn, insumo: Insumo, creado_por: Optional[str]) -> int:
        nombre_norm = normalizar(insumo.nombre)
        hoy = date.today().isoformat()
        existe = conn.execute(
            "SELECT 1 FROM precios.insumos WHERE codigo=%s AND nombre_norm=%s",
            (str(insumo.codigo), nombre_norm)).fetchone()
        if existe:
            raise ValueError(
                f"Ya existe un insumo con código {insumo.codigo} y ese nombre.")
        cur = conn.execute(
            "INSERT INTO precios.insumos (codigo, nombre, nombre_norm, unidad, grupo) "
            "VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (str(insumo.codigo), insumo.nombre, nombre_norm, insumo.unidad, insumo.grupo))
        iid = int(cur.fetchone()["id"])
        self._insertar_precio_vigente(conn, iid, insumo.precio, insumo.fuente_precio, hoy, creado_por)
        return iid
```

- [ ] **Step 6: Actualizar el Protocol**

En `apu_tool/datos/repositorio.py`, reemplaza las firmas dentro de `RepositorioPrecios`:

```python
    def crear_insumo(self, insumo: Insumo, conn=None, creado_por: Optional[str] = None) -> int: ...
    ...
    def set_precio_por_id(self, insumo_id: int, precio: float, fuente: str = "",
                          fecha: Optional[str] = None, conn=None,
                          creado_por: Optional[str] = None) -> None: ...
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_precios_conn_creado_por.py tests/test_precios_db.py tests/test_insumos_db.py tests/test_migracion_pg.py -q`
Expected: PASS (nuevos + existentes de precios verdes; el ALTER hace idempotente `init_schema`).

- [ ] **Step 8: Commit**

```bash
git add db/precios.sql apu_tool/datos/precios_db.py apu_tool/datos/pg/precios_pg.py apu_tool/datos/repositorio.py tests/test_precios_conn_creado_por.py
git commit -m "feat(auditoria): insumo_precios.creado_por + conn opcional en repos de precios"
```

---

### Task 5: `conn` opcional en repos de apus / corridas / perfiles (dual)

**Files:**
- Modify: `apu_tool/datos/apus_db.py` + `apu_tool/datos/pg/apus_pg.py` (`crear_apu(conn=None)`)
- Modify: `apu_tool/datos/corridas_db.py` + `apu_tool/datos/pg/corridas_pg.py` (`eliminar_corrida(conn=None)`)
- Modify: `apu_tool/datos/perfiles_db.py` + `apu_tool/datos/pg/perfiles_pg.py` (`set_rol/set_estado/upsert(conn=None)`)
- Modify: `apu_tool/datos/repositorio.py` (firmas)
- Test: `tests/test_repos_conn_opcional.py`

**Interfaces:**
- Produces: `crear_apu(apu, componentes, conn=None) -> None`; `eliminar_corrida(corrida_id, conn=None) -> bool`; `set_rol(user_id, rol, conn=None)`; `set_estado(user_id, estado, conn=None)`; `upsert(perfil, conn=None)`.

- [ ] **Step 1: Write the failing test**

Crea `tests/test_repos_conn_opcional.py`:

```python
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, CorridaMeta, Perfil


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def test_crear_apu_con_conn_rollback(tmp_path):
    alm = _alm(tmp_path)
    with pytest.raises(RuntimeError):
        with alm.transaccion("apus") as conn:
            alm.apus.crear_apu(Apu("A1", "MURO", "M2", "DIURNO"), [], conn=conn)
            raise RuntimeError("aborta")
    assert alm.apus.get_apu("A1", "DIURNO") is None       # rollback


def test_eliminar_corrida_con_conn_commit(tmp_path):
    alm = _alm(tmp_path)
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="x", archivo="lic.xlsx", turno_def="DIURNO",
        use_ai=False, estado="en_revision"))
    with alm.transaccion("corridas") as conn:
        ok = alm.corridas.eliminar_corrida(cid, conn=conn)
    assert ok is True and alm.corridas.get_corrida(cid) is None


def test_set_rol_con_conn_rollback(tmp_path):
    alm = _alm(tmp_path)
    alm.perfiles.upsert(Perfil("u1", "a@obra.co", "consulta", "activo"))
    with pytest.raises(RuntimeError):
        with alm.transaccion("seguridad") as conn:
            alm.perfiles.set_rol("u1", "admin", conn=conn)
            raise RuntimeError("aborta")
    assert alm.perfiles.get("u1").rol == "consulta"       # rollback
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_repos_conn_opcional.py -q`
Expected: FAIL (`crear_apu() got an unexpected keyword argument 'conn'`).

- [ ] **Step 3: `crear_apu(conn=None)` — SQLite**

En `apu_tool/datos/apus_db.py`, reemplaza `crear_apu` (líneas 87-110) por:

```python
    def crear_apu(self, apu: Apu, componentes: list[ApuComponent], conn=None) -> None:
        """Crea un APU NUEVO con su composición, atómico. Identidad (código, turno):
        si ya existe → ValueError."""
        if not str(apu.codigo or "").strip() or not str(apu.nombre or "").strip():
            raise ValueError("El APU necesita código y nombre.")
        if conn is not None:
            return self._crear_apu(conn, apu, componentes)
        with self.connect() as c:
            return self._crear_apu(c, apu, componentes)

    def _crear_apu(self, conn, apu: Apu, componentes: list[ApuComponent]) -> None:
        existe = conn.execute("SELECT 1 FROM apus WHERE codigo=? AND shift=?",
                              (str(apu.codigo), apu.shift)).fetchone()
        if existe:
            raise ValueError(
                f"Ya existe un APU con código {apu.codigo} en turno {apu.shift}.")
        conn.execute(
            "INSERT INTO apus (codigo, shift, nombre, unidad, grupo) VALUES (?,?,?,?,?)",
            (str(apu.codigo), apu.shift, apu.nombre, apu.unidad, apu.grupo))
        rows = [(str(apu.codigo), apu.shift, seq, c.insumo_codigo, c.insumo_nombre,
                 c.unidad, c.rendimiento, c.precio_unitario_hist)
                for seq, c in enumerate(componentes)]
        if rows:
            conn.executemany(
                "INSERT INTO apu_componentes "
                "(apu_codigo, shift, seq, insumo_codigo, insumo_nombre, unidad, "
                " rendimiento, precio_unitario_hist) VALUES (?,?,?,?,?,?,?,?)", rows)
```

- [ ] **Step 4: `crear_apu(conn=None)` — Postgres**

En `apu_tool/datos/pg/apus_pg.py`, reemplaza `crear_apu` (líneas 65-85) por:

```python
    def crear_apu(self, apu: Apu, componentes: list[ApuComponent], conn=None) -> None:
        if not str(apu.codigo or "").strip() or not str(apu.nombre or "").strip():
            raise ValueError("El APU necesita código y nombre.")
        if conn is not None:
            return self._crear_apu(conn, apu, componentes)
        with self.cx.connection() as c:
            return self._crear_apu(c, apu, componentes)

    def _crear_apu(self, conn, apu: Apu, componentes: list[ApuComponent]) -> None:
        existe = conn.execute("SELECT 1 FROM apus.apus WHERE codigo=%s AND shift=%s",
                              (str(apu.codigo), apu.shift)).fetchone()
        if existe:
            raise ValueError(
                f"Ya existe un APU con código {apu.codigo} en turno {apu.shift}.")
        conn.execute(
            "INSERT INTO apus.apus (codigo, shift, nombre, unidad, grupo) "
            "VALUES (%s,%s,%s,%s,%s)",
            (str(apu.codigo), apu.shift, apu.nombre, apu.unidad, apu.grupo))
        rows = [(str(apu.codigo), apu.shift, seq, c.insumo_codigo, c.insumo_nombre,
                 c.unidad, c.rendimiento, c.precio_unitario_hist)
                for seq, c in enumerate(componentes)]
        if rows:
            conn.executemany(
                "INSERT INTO apus.apu_componentes "
                "(apu_codigo, shift, seq, insumo_codigo, insumo_nombre, unidad, "
                " rendimiento, precio_unitario_hist) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", rows)
```

- [ ] **Step 5: `eliminar_corrida(conn=None)` — SQLite y Postgres**

En `apu_tool/datos/corridas_db.py`, reemplaza `eliminar_corrida` (líneas 162-165):

```python
    def eliminar_corrida(self, corrida_id: int, conn=None) -> bool:
        if conn is not None:
            cur = conn.execute("DELETE FROM corrida WHERE id=?", (int(corrida_id),))
            return cur.rowcount > 0
        with self.connect() as c:
            cur = c.execute("DELETE FROM corrida WHERE id=?", (int(corrida_id),))
            return cur.rowcount > 0
```

En `apu_tool/datos/pg/corridas_pg.py`, reemplaza `eliminar_corrida` (líneas 130-133):

```python
    def eliminar_corrida(self, corrida_id: int, conn=None) -> bool:
        if conn is not None:
            cur = conn.execute("DELETE FROM corridas.corrida WHERE id=%s", (int(corrida_id),))
            return cur.rowcount > 0
        with self.cx.connection() as c:
            cur = c.execute("DELETE FROM corridas.corrida WHERE id=%s", (int(corrida_id),))
            return cur.rowcount > 0
```

- [ ] **Step 6: `set_rol/set_estado/upsert(conn=None)` — SQLite**

En `apu_tool/datos/perfiles_db.py`, reemplaza `upsert`, `set_rol`, `set_estado`:

```python
    def upsert(self, p: Perfil, conn=None) -> None:
        sql = ("INSERT INTO perfiles (user_id,email,rol,estado,nombre,creado_en) "
               "VALUES (?,?,?,?,?,?) "
               "ON CONFLICT(user_id) DO UPDATE SET email=excluded.email, rol=excluded.rol, "
               "estado=excluded.estado, nombre=excluded.nombre")
        params = (p.user_id, p.email, p.rol, p.estado, p.nombre, p.creado_en)
        if conn is not None:
            conn.execute(sql, params); return
        with self.connect() as c:
            c.execute(sql, params)

    def set_rol(self, user_id: str, rol: str, conn=None) -> None:
        if conn is not None:
            conn.execute("UPDATE perfiles SET rol=? WHERE user_id=?", (rol, user_id)); return
        with self.connect() as c:
            c.execute("UPDATE perfiles SET rol=? WHERE user_id=?", (rol, user_id))

    def set_estado(self, user_id: str, estado: str, conn=None) -> None:
        if conn is not None:
            conn.execute("UPDATE perfiles SET estado=? WHERE user_id=?", (estado, user_id)); return
        with self.connect() as c:
            c.execute("UPDATE perfiles SET estado=? WHERE user_id=?", (estado, user_id))
```

- [ ] **Step 7: `set_rol/set_estado/upsert(conn=None)` — Postgres**

En `apu_tool/datos/pg/perfiles_pg.py`, reemplaza `upsert`, `set_rol`, `set_estado`:

```python
    def upsert(self, p: Perfil, conn=None) -> None:
        sql = ("INSERT INTO seguridad.perfiles (user_id,email,rol,estado,nombre,creado_en) "
               "VALUES (%s,%s,%s,%s,%s,%s) "
               "ON CONFLICT (user_id) DO UPDATE SET email=EXCLUDED.email, rol=EXCLUDED.rol, "
               "estado=EXCLUDED.estado, nombre=EXCLUDED.nombre")
        params = (p.user_id, p.email, p.rol, p.estado, p.nombre, p.creado_en)
        if conn is not None:
            conn.execute(sql, params); return
        with self.cx.connection() as c:
            c.execute(sql, params)

    def set_rol(self, user_id: str, rol: str, conn=None) -> None:
        if conn is not None:
            conn.execute("UPDATE seguridad.perfiles SET rol=%s WHERE user_id=%s", (rol, user_id)); return
        with self.cx.connection() as c:
            c.execute("UPDATE seguridad.perfiles SET rol=%s WHERE user_id=%s", (rol, user_id))

    def set_estado(self, user_id: str, estado: str, conn=None) -> None:
        if conn is not None:
            conn.execute("UPDATE seguridad.perfiles SET estado=%s WHERE user_id=%s", (estado, user_id)); return
        with self.cx.connection() as c:
            c.execute("UPDATE seguridad.perfiles SET estado=%s WHERE user_id=%s", (estado, user_id))
```

- [ ] **Step 8: Actualizar el Protocol**

En `apu_tool/datos/repositorio.py`, actualiza las firmas:

```python
    # RepositorioApus:
    def crear_apu(self, apu: Apu, componentes: list[ApuComponent], conn=None) -> None: ...
    # RepositorioCorridas:
    def eliminar_corrida(self, corrida_id: int, conn=None) -> bool: ...
    # RepositorioPerfiles:
    def upsert(self, perfil: Perfil, conn=None) -> None: ...
    def set_rol(self, user_id: str, rol: str, conn=None) -> None: ...
    def set_estado(self, user_id: str, estado: str, conn=None) -> None: ...
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `python -m pytest tests/test_repos_conn_opcional.py tests/test_apus_db.py tests/test_corridas_db.py tests/test_perfiles_contrato.py -q`
Expected: PASS (nuevos + existentes verdes).

- [ ] **Step 10: Commit**

```bash
git add apu_tool/datos/apus_db.py apu_tool/datos/pg/apus_pg.py apu_tool/datos/corridas_db.py apu_tool/datos/pg/corridas_pg.py apu_tool/datos/perfiles_db.py apu_tool/datos/pg/perfiles_pg.py apu_tool/datos/repositorio.py tests/test_repos_conn_opcional.py
git commit -m "feat(auditoria): conn opcional en repos de apus/corridas/perfiles"
```

---

### Task 6: Helper de servicio `registrar_auditoria` + `listar`

**Files:**
- Create: `apu_tool/servicio/auditoria.py`
- Test: `tests/test_servicio_auditoria.py`

**Interfaces:**
- Consumes: `Almacen.transaccion`, `Almacen.auditoria` (Tasks 2-3), `EventoAuditoria`, `Perfil`.
- Produces: `registrar_auditoria(alm, conn, actor, accion, entidad_tipo, entidad_id, antes=None, despues=None, contexto=None) -> None`; `nuevo_lote() -> str`; `listar(alm, *, user_id=None, accion=None, entidad_tipo=None, desde=None, hasta=None, lote_id=None, limit=100, offset=0) -> dict`.

- [ ] **Step 1: Write the failing test**

Crea `tests/test_servicio_auditoria.py`:

```python
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Perfil
from apu_tool.servicio import auditoria as svc


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def test_registrar_con_actor(tmp_path):
    alm = _alm(tmp_path)
    actor = Perfil("u1", "a@obra.co", "editor", "activo")
    with alm.transaccion("seguridad") as conn:
        svc.registrar_auditoria(alm, conn, actor, "usuario.invitar", "usuario", "u9",
                                despues={"rol": "consulta"})
    items, total = alm.auditoria.listar()
    assert total == 1
    ev = items[0]
    assert ev["user_id"] == "u1" and ev["user_email"] == "a@obra.co" and ev["rol"] == "editor"
    assert ev["accion"] == "usuario.invitar" and ev["entidad_id"] == "u9"
    assert ev["despues"] == {"rol": "consulta"} and ev["ts"]  # ts no vacío


def test_registrar_sin_actor_es_sistema(tmp_path):
    alm = _alm(tmp_path)
    with alm.transaccion("seguridad") as conn:
        svc.registrar_auditoria(alm, conn, None, "insumo.crear", "insumo", "5")
    ev = alm.auditoria.listar()[0][0]
    assert ev["user_id"] is None and ev["rol"] == "sistema"


def test_listar_devuelve_paginacion(tmp_path):
    alm = _alm(tmp_path)
    with alm.transaccion("seguridad") as conn:
        svc.registrar_auditoria(alm, conn, None, "insumo.crear", "insumo", "1")
    out = svc.listar(alm, limit=10, offset=0)
    assert out["total"] == 1 and out["limit"] == 10 and len(out["items"]) == 1


def test_nuevo_lote_unico():
    assert svc.nuevo_lote() != svc.nuevo_lote()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_servicio_auditoria.py -q`
Expected: FAIL (`ModuleNotFoundError: apu_tool.servicio.auditoria`).

- [ ] **Step 3: Crear `apu_tool/servicio/auditoria.py`**

```python
"""Servicio de auditoría: helper transaccional para registrar eventos y lectura paginada.

`registrar_auditoria` escribe la fila de auditoría SOBRE la conexión de la unidad de
trabajo (misma transacción que la mutación → sin best-effort). NO ve la IA (Invariante #1).
"""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Optional

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import EventoAuditoria, Perfil


def nuevo_lote() -> str:
    """Id de lote para agrupar las filas de una misma operación por lote."""
    return uuid.uuid4().hex


def registrar_auditoria(alm: Almacen, conn, actor: Optional[Perfil], accion: str,
                        entidad_tipo: str, entidad_id, antes: Optional[dict] = None,
                        despues: Optional[dict] = None, contexto: Optional[dict] = None) -> None:
    ev = EventoAuditoria(
        ts=dt.datetime.now(dt.timezone.utc).isoformat(),
        rol=(actor.rol if actor else "sistema"),
        accion=accion, entidad_tipo=entidad_tipo, entidad_id=str(entidad_id),
        user_id=(actor.user_id if actor else None),
        user_email=(actor.email if actor else None),
        antes=antes, despues=despues, contexto=contexto)
    alm.auditoria.registrar(conn, ev)


def listar(alm: Almacen, *, user_id: Optional[str] = None, accion: Optional[str] = None,
           entidad_tipo: Optional[str] = None, desde: Optional[str] = None,
           hasta: Optional[str] = None, lote_id: Optional[str] = None,
           limit: int = 100, offset: int = 0) -> dict:
    items, total = alm.auditoria.listar(
        user_id=user_id, accion=accion, entidad_tipo=entidad_tipo, desde=desde,
        hasta=hasta, lote_id=lote_id, limit=limit, offset=offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_servicio_auditoria.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/auditoria.py tests/test_servicio_auditoria.py
git commit -m "feat(auditoria): helper de servicio registrar_auditoria + listar"
```

---

### Task 7: Instrumentar servicios de precios y autoría

**Files:**
- Modify: `apu_tool/servicio/insumos.py` (`aplicar_cambios` con `actor`)
- Modify: `apu_tool/servicio/autoria.py` (`crear_insumo`, `crear_apu`, `aplicar_importar_insumos`, `aplicar_importar_apus` con `actor`)
- Test: `tests/test_auditoria_servicios_precios.py`

**Interfaces:**
- Consumes: `registrar_auditoria`, `nuevo_lote` (Task 6); `set_precio_por_id`/`crear_insumo` con `conn`/`creado_por` (Task 4); `crear_apu(conn=)` (Task 5); `Almacen.transaccion`.
- Produces: `aplicar_cambios(alm, cambios, actor=None)`; `crear_insumo(alm, datos, actor=None)`; `crear_apu(alm, datos, actor=None)`; `aplicar_importar_insumos(alm, contenido, nombre_archivo, actor=None)`; `aplicar_importar_apus(alm, contenido, actor=None)`.

- [ ] **Step 1: Write the failing test**

Crea `tests/test_auditoria_servicios_precios.py`:

```python
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Insumo, Perfil
from apu_tool.servicio import autoria
from apu_tool.servicio import insumos as insumos_svc


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def _actor():
    return Perfil("u-ed", "ed@obra.co", "editor", "activo")


def test_aplicar_cambios_audita_por_entidad(tmp_path):
    alm = _alm(tmp_path)
    iid = alm.precios.crear_insumo(Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU"))
    out = insumos_svc.aplicar_cambios(alm, [{"insumo_id": iid, "precio": 1500, "fuente": "COSTO INTERNO"}],
                                      actor=_actor())
    assert out["aplicados"] == 1
    items, total = alm.auditoria.listar(accion="precio.editar")
    assert total == 1
    ev = items[0]
    assert ev["entidad_tipo"] == "insumo" and ev["entidad_id"] == str(iid)
    assert ev["antes"]["precio"] == 1000 and ev["despues"]["precio"] == 1500
    assert ev["contexto"]["origen"] == "edicion" and ev["contexto"]["lote_id"]
    assert ev["user_id"] == "u-ed"


def test_aplicar_cambios_partial_success_no_audita_el_malo(tmp_path):
    alm = _alm(tmp_path)
    iid = alm.precios.crear_insumo(Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU"))
    out = insumos_svc.aplicar_cambios(alm, [
        {"insumo_id": iid, "precio": 1500, "fuente": "X"},
        {"insumo_id": 99999, "precio": 10, "fuente": "Y"},   # no existe → error
    ], actor=_actor())
    assert out["aplicados"] == 1 and len(out["errores"]) == 1
    _, total = alm.auditoria.listar()
    assert total == 1                                        # solo el válido dejó auditoría


def test_crear_insumo_audita(tmp_path):
    alm = _alm(tmp_path)
    autoria.crear_insumo(alm, {"codigo": "200", "nombre": "ARENA", "unidad": "M3",
                               "grupo": "MAT", "precio": 500, "fuente": "PRECIO IDU"}, actor=_actor())
    items, total = alm.auditoria.listar(accion="insumo.crear")
    assert total == 1 and items[0]["despues"]["codigo"] == "200"


def test_crear_apu_audita(tmp_path):
    alm = _alm(tmp_path)
    autoria.crear_apu(alm, {"codigo": "AP1", "nombre": "MURO", "unidad": "M2",
                            "turno": "DIURNO", "grupo": "OC", "componentes": []}, actor=_actor())
    items, total = alm.auditoria.listar(accion="apu.crear")
    assert total == 1 and items[0]["entidad_tipo"] == "apu" and items[0]["entidad_id"] == "AP1"


def test_importar_insumos_audita_con_lote_y_origen(tmp_path):
    alm = _alm(tmp_path)
    csv = b"codigo,nombre,unidad,grupo,precio,fuente\n300,GRAVA,M3,MAT,700,PRECIO IDU\n"
    autoria.aplicar_importar_insumos(alm, csv, "insumos.csv", actor=_actor())
    items, total = alm.auditoria.listar(accion="insumo.crear")
    assert total == 1
    assert items[0]["contexto"]["origen"] == "import" and items[0]["contexto"]["lote_id"]
    assert items[0]["contexto"]["archivo"] == "insumos.csv"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_auditoria_servicios_precios.py -q`
Expected: FAIL (`aplicar_cambios() got an unexpected keyword argument 'actor'`).

- [ ] **Step 3: Instrumentar `insumos.aplicar_cambios`**

En `apu_tool/servicio/insumos.py`, añade el import (junto a los otros):

```python
from apu_tool.servicio.auditoria import nuevo_lote, registrar_auditoria
```

Reemplaza `aplicar_cambios` (líneas 44-56) por:

```python
def aplicar_cambios(alm: Almacen, cambios: list[dict], actor=None) -> dict:
    aplicados, errores = 0, []
    lote = nuevo_lote()
    for c in cambios:
        try:
            precio = float(c["precio"])
            if precio < 0:
                raise ValueError("El precio no puede ser negativo.")
            iid = int(c["insumo_id"])
            fuente = str(c.get("fuente", "") or "")
            antes_ins = alm.precios.get_insumo_por_id(iid)   # estado previo (lectura)
            with alm.transaccion("precios") as conn:
                alm.precios.set_precio_por_id(iid, precio, fuente, conn=conn,
                                              creado_por=(actor.user_id if actor else None))
                registrar_auditoria(
                    alm, conn, actor, "precio.editar", "insumo", iid,
                    antes=({"precio": antes_ins.precio, "fuente": antes_ins.fuente_precio}
                           if antes_ins else None),
                    despues={"precio": precio, "fuente": fuente},
                    contexto={"origen": "edicion", "lote_id": lote})
            aplicados += 1
        except Exception as e:
            errores.append({"insumo_id": c.get("insumo_id"), "error": str(e)})
    return {"aplicados": aplicados, "errores": errores}
```

- [ ] **Step 4: Instrumentar `autoria.crear_insumo` y `crear_apu`**

En `apu_tool/servicio/autoria.py`, añade el import:

```python
from apu_tool.servicio.auditoria import nuevo_lote, registrar_auditoria
```

Reemplaza `crear_insumo` (líneas 28-41) por:

```python
def crear_insumo(alm: Almacen, datos: dict, actor=None) -> dict:
    codigo = str(datos.get("codigo", "") or "").strip()
    nombre = str(datos.get("nombre", "") or "").strip()
    if not codigo or not nombre:
        raise ValueError("Código y nombre son obligatorios.")
    precio = _to_float(datos.get("precio"))
    if precio < 0:
        raise ValueError("El precio no puede ser negativo.")
    ins = Insumo(codigo=codigo, nombre=nombre,
                 unidad=str(datos.get("unidad", "") or ""),
                 grupo=str(datos.get("grupo", "") or ""),
                 precio=precio, fuente_precio=str(datos.get("fuente", "") or ""))
    with alm.transaccion("precios") as conn:
        iid = alm.precios.crear_insumo(ins, conn=conn,
                                       creado_por=(actor.user_id if actor else None))
        registrar_auditoria(
            alm, conn, actor, "insumo.crear", "insumo", iid, antes=None,
            despues={"codigo": ins.codigo, "nombre": ins.nombre, "unidad": ins.unidad,
                     "grupo": ins.grupo, "precio": ins.precio, "fuente": ins.fuente_precio},
            contexto={"origen": "individual"})
    return _insumo_out(alm.precios.get_insumo_por_id(iid))
```

Reemplaza `crear_apu` (líneas 67-80) por:

```python
def crear_apu(alm: Almacen, datos: dict, actor=None) -> dict:
    codigo = str(datos.get("codigo", "") or "").strip()
    nombre = str(datos.get("nombre", "") or "").strip()
    turno = str(datos.get("turno", "") or "").strip().upper()
    if not codigo or not nombre:
        raise ValueError("Código y nombre son obligatorios.")
    if turno not in (config.SHIFT_DIURNO, config.SHIFT_NOCTURNO):
        raise ValueError("El turno debe ser DIURNO o NOCTURNO.")
    comps = _componentes_de(alm, datos.get("componentes", []) or [], turno)
    apu = Apu(codigo=codigo, nombre=nombre, unidad=str(datos.get("unidad", "") or ""),
              shift=turno, grupo=str(datos.get("grupo", "") or ""))
    with alm.transaccion("apus") as conn:
        alm.apus.crear_apu(apu, comps, conn=conn)
        registrar_auditoria(
            alm, conn, actor, "apu.crear", "apu", codigo, antes=None,
            despues={"codigo": codigo, "turno": turno, "nombre": nombre,
                     "unidad": apu.unidad, "grupo": apu.grupo, "n_componentes": len(comps)},
            contexto={"origen": "individual"})
    return {"codigo": codigo, "shift": turno, "nombre": nombre,
            "unidad": apu.unidad, "grupo": apu.grupo, "n_componentes": len(comps)}
```

- [ ] **Step 5: Instrumentar `autoria.aplicar_importar_insumos` y `aplicar_importar_apus`**

Reemplaza `aplicar_importar_insumos` (líneas 144-158) por:

```python
def aplicar_importar_insumos(alm: Almacen, contenido: bytes, nombre_archivo: str,
                             actor=None) -> dict:
    creados, errores = 0, []
    lote = nuevo_lote()
    for f in _filas_insumos(contenido, nombre_archivo):
        if not f["codigo"] or not f["nombre"]:
            continue                                   # inválida: se omite
        if _existe_identidad(alm, f["codigo"], f["nombre"]):
            continue                                   # ya existe: no se pisa
        try:
            ins = Insumo(codigo=f["codigo"], nombre=f["nombre"], unidad=f["unidad"],
                         grupo=f["grupo"], precio=f["precio"], fuente_precio=f["fuente"])
            with alm.transaccion("precios") as conn:
                iid = alm.precios.crear_insumo(ins, conn=conn,
                                               creado_por=(actor.user_id if actor else None))
                registrar_auditoria(
                    alm, conn, actor, "insumo.crear", "insumo", iid, antes=None,
                    despues={"codigo": ins.codigo, "nombre": ins.nombre, "unidad": ins.unidad,
                             "grupo": ins.grupo, "precio": ins.precio, "fuente": ins.fuente_precio},
                    contexto={"origen": "import", "lote_id": lote, "archivo": nombre_archivo})
            creados += 1
        except ValueError as e:
            errores.append({"codigo": f["codigo"], "error": str(e)})
    return {"creados": creados, "errores": errores}
```

Reemplaza `aplicar_importar_apus` (líneas 190-201) por:

```python
def aplicar_importar_apus(alm: Almacen, contenido: bytes, actor=None) -> dict:
    apus, comps_por = _parse_apus(contenido)
    creados, errores = 0, []
    lote = nuevo_lote()
    for a in apus:
        if alm.apus.get_apu(a.codigo, a.shift):
            continue                                   # ya existe: no se pisa
        try:
            comps = comps_por.get((a.codigo, a.shift), [])
            with alm.transaccion("apus") as conn:
                alm.apus.crear_apu(a, comps, conn=conn)
                registrar_auditoria(
                    alm, conn, actor, "apu.crear", "apu", a.codigo, antes=None,
                    despues={"codigo": a.codigo, "turno": a.shift, "nombre": a.nombre,
                             "unidad": a.unidad, "grupo": a.grupo, "n_componentes": len(comps)},
                    contexto={"origen": "import", "lote_id": lote})
            creados += 1
        except ValueError as e:
            errores.append({"codigo": a.codigo, "turno": a.shift, "error": str(e)})
    return {"creados": creados, "errores": errores}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_auditoria_servicios_precios.py tests/test_servicio_insumos.py tests/test_servicio_autoria.py -q`
Expected: PASS (nuevos + existentes de servicio verdes; los existentes llaman sin `actor` → auditan como `sistema`, sin romper aserciones).

- [ ] **Step 7: Commit**

```bash
git add apu_tool/servicio/insumos.py apu_tool/servicio/autoria.py tests/test_auditoria_servicios_precios.py
git commit -m "feat(auditoria): instrumentar precios y autoría (por-entidad + lote_id)"
```

---

### Task 8: Instrumentar `corridas.eliminar_corrida` y `usuarios.*`

**Files:**
- Modify: `apu_tool/servicio/corridas.py` (`eliminar_corrida` con `actor`)
- Modify: `apu_tool/servicio/usuarios.py` (`invitar`, `cambiar_rol`, `cambiar_estado` con auditoría)
- Test: `tests/test_auditoria_servicios_corridas_usuarios.py`

**Interfaces:**
- Consumes: `registrar_auditoria` (Task 6); `eliminar_corrida(conn=)`, `set_rol/set_estado/upsert(conn=)` (Task 5); `Almacen.transaccion`.
- Produces: `corridas.eliminar_corrida(alm, corrida_id, actor=None) -> bool`; `usuarios.invitar(alm, admin, email, rol, nombre="", actor=None)`; `usuarios.cambiar_rol/cambiar_estado` auditan (firmas ya con `actor`).

- [ ] **Step 1: Write the failing test**

Crea `tests/test_auditoria_servicios_corridas_usuarios.py`:

```python
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import CorridaMeta, Perfil
from apu_tool.servicio import corridas as corridas_svc
from apu_tool.servicio import usuarios as usuarios_svc
from apu_tool.servicio.supabase_admin import AdminSupabaseFake


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def _admin():
    return Perfil("admin-0", "root@obra.co", "admin", "activo")


def test_eliminar_corrida_audita(tmp_path):
    alm = _alm(tmp_path)
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="x", archivo="lic.xlsx", turno_def="DIURNO",
        use_ai=False, estado="en_revision"))
    ok = corridas_svc.eliminar_corrida(alm, cid, actor=_admin())
    assert ok is True and alm.corridas.get_corrida(cid) is None
    items, total = alm.auditoria.listar(accion="corrida.eliminar")
    assert total == 1 and items[0]["antes"]["archivo"] == "lic.xlsx" and items[0]["despues"] is None


def test_eliminar_corrida_inexistente_no_audita(tmp_path):
    alm = _alm(tmp_path)
    assert corridas_svc.eliminar_corrida(alm, 999, actor=_admin()) is False
    assert alm.auditoria.listar()[1] == 0


def test_invitar_audita(tmp_path):
    alm = _alm(tmp_path)
    admin = AdminSupabaseFake(id_por_email={"nuevo@obra.co": "u-nuevo"})
    usuarios_svc.invitar(alm, admin, "nuevo@obra.co", "editor", "Nuevo", actor=_admin())
    items, total = alm.auditoria.listar(accion="usuario.invitar")
    assert total == 1 and items[0]["entidad_id"] == "u-nuevo" and items[0]["despues"]["rol"] == "editor"


def test_cambiar_rol_audita_antes_despues(tmp_path):
    alm = _alm(tmp_path)
    alm.perfiles.upsert(Perfil("u1", "a@obra.co", "consulta", "activo"))
    usuarios_svc.cambiar_rol(alm, _admin(), "u1", "editor")
    items, total = alm.auditoria.listar(accion="usuario.cambiar_rol")
    assert total == 1 and items[0]["antes"]["rol"] == "consulta" and items[0]["despues"]["rol"] == "editor"


def test_cambiar_estado_audita(tmp_path):
    alm = _alm(tmp_path)
    alm.perfiles.upsert(Perfil("u1", "a@obra.co", "admin", "activo"))
    alm.perfiles.upsert(Perfil("u2", "b@obra.co", "admin", "activo"))
    usuarios_svc.cambiar_estado(alm, _admin(), "u1", "inactivo")
    items, total = alm.auditoria.listar(accion="usuario.cambiar_estado")
    assert total == 1 and items[0]["despues"]["estado"] == "inactivo"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_auditoria_servicios_corridas_usuarios.py -q`
Expected: FAIL (`eliminar_corrida() got an unexpected keyword argument 'actor'`).

- [ ] **Step 3: Instrumentar `corridas.eliminar_corrida`**

En `apu_tool/servicio/corridas.py`, añade el import (junto a los otros de servicio):

```python
from apu_tool.servicio.auditoria import registrar_auditoria
```

Reemplaza `eliminar_corrida` (líneas 189-190) por:

```python
def eliminar_corrida(alm: Almacen, corrida_id: int, actor=None) -> bool:
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return False
    with alm.transaccion("corridas") as conn:
        ok = alm.corridas.eliminar_corrida(corrida_id, conn=conn)
        if ok:
            registrar_auditoria(
                alm, conn, actor, "corrida.eliminar", "corrida", corrida_id,
                antes={"archivo": meta.archivo, "creada_en": meta.creada_en, "estado": meta.estado},
                despues=None)
    return ok
```

- [ ] **Step 4: Instrumentar `usuarios.invitar / cambiar_rol / cambiar_estado`**

En `apu_tool/servicio/usuarios.py`, añade el import:

```python
from apu_tool.servicio.auditoria import registrar_auditoria
```

Reemplaza `invitar` (líneas 20-30) por (la llamada HTTP a Supabase ocurre ANTES de la transacción; solo el upsert local + auditoría son transaccionales):

```python
def invitar(alm: Almacen, admin: AdminSupabase, email: str, rol: str,
            nombre: str = "", actor=None) -> dict:
    email = (email or "").strip().lower()
    if not email:
        raise ValueError("El email es obligatorio.")
    if rol not in _ROLES:
        raise ValueError(f"Rol inválido: {rol}.")
    user_id = admin.invitar(email)   # efecto externo (HTTP), NO reversible → fuera de la tx
    perfil = Perfil(user_id=user_id, email=email, rol=rol, estado="activo",
                    nombre=nombre, creado_en=dt.date.today().isoformat())
    with alm.transaccion("seguridad") as conn:
        alm.perfiles.upsert(perfil, conn=conn)
        registrar_auditoria(alm, conn, actor, "usuario.invitar", "usuario", user_id,
                            antes=None, despues={"email": email, "rol": rol, "estado": "activo"})
    return {"user_id": user_id, "email": email, "rol": rol, "estado": "activo"}
```

Reemplaza `cambiar_rol` (líneas 47-54) por:

```python
def cambiar_rol(alm: Almacen, actor: Perfil, user_id: str, rol: str) -> dict:
    if rol not in _ROLES:
        raise ValueError(f"Rol inválido: {rol}.")
    objetivo = _existe(alm, user_id)
    if rol != "admin":
        _proteger_ultimo_admin(alm, objetivo)
    with alm.transaccion("seguridad") as conn:
        alm.perfiles.set_rol(user_id, rol, conn=conn)
        registrar_auditoria(alm, conn, actor, "usuario.cambiar_rol", "usuario", user_id,
                            antes={"rol": objetivo.rol}, despues={"rol": rol})
    return {"user_id": user_id, "rol": rol}
```

Reemplaza `cambiar_estado` (líneas 57-64) por:

```python
def cambiar_estado(alm: Almacen, actor: Perfil, user_id: str, estado: str) -> dict:
    if estado not in _ESTADOS:
        raise ValueError(f"Estado inválido: {estado}.")
    objetivo = _existe(alm, user_id)
    if estado == "inactivo":
        _proteger_ultimo_admin(alm, objetivo)
    with alm.transaccion("seguridad") as conn:
        alm.perfiles.set_estado(user_id, estado, conn=conn)
        registrar_auditoria(alm, conn, actor, "usuario.cambiar_estado", "usuario", user_id,
                            antes={"estado": objetivo.estado}, despues={"estado": estado})
    return {"user_id": user_id, "estado": estado}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_auditoria_servicios_corridas_usuarios.py tests/test_servicio_usuarios.py tests/test_servicio_corridas.py -q`
Expected: PASS (nuevos + existentes verdes; los existentes de usuarios llaman sin `actor` en `invitar` → `None` → `sistema`).

- [ ] **Step 6: Commit**

```bash
git add apu_tool/servicio/corridas.py apu_tool/servicio/usuarios.py tests/test_auditoria_servicios_corridas_usuarios.py
git commit -m "feat(auditoria): instrumentar borrado de corridas y gestión de usuarios"
```

---

### Task 9: `GET /api/auditoria` (solo-Admin) + propagar `actor` en endpoints

**Files:**
- Modify: `apu_tool/servicio/rutas.py` (endpoint `GET /auditoria`; `actor` en endpoints de mutación)
- Test: `tests/test_api_auditoria.py`

**Interfaces:**
- Consumes: `auditoria.listar` (Task 6); servicios instrumentados (Tasks 7-8); `requiere_rol` (devuelve el `Perfil`).
- Produces: `GET /api/auditoria` (Admin) → `{items, total, limit, offset}`. Endpoints de mutación pasan `actor=usuario_actual`.

- [ ] **Step 1: Write the failing test**

Crea `tests/test_api_auditoria.py`:

```python
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Insumo
from apu_tool.servicio.app import create_app
from tests.conftest import cliente


def _app(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return create_app(almacen=alm), alm


def test_auditoria_solo_admin(tmp_path):
    app, _ = _app(tmp_path)
    assert cliente(app, rol="consulta").get("/api/auditoria").status_code == 403
    assert cliente(app, rol="editor").get("/api/auditoria").status_code == 403
    assert cliente(app, rol="admin").get("/api/auditoria").status_code == 200


def test_cambio_precio_via_api_deja_auditoria(tmp_path):
    app, alm = _app(tmp_path)
    iid = alm.precios.crear_insumo(Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU"))
    ed = cliente(app, rol="editor")
    r = ed.post("/api/insumos/cambios",
                json={"cambios": [{"insumo_id": iid, "precio": 1500, "fuente": "COSTO INTERNO"}]})
    assert r.status_code == 200, r.text
    adm = cliente(app, rol="admin")
    data = adm.get("/api/auditoria?accion=precio.editar").json()
    assert data["total"] == 1
    assert data["items"][0]["entidad_id"] == str(iid)
    assert data["items"][0]["user_id"] == "test-editor"     # actor = usuario_actual (conftest)


def test_auditoria_filtra_por_entidad_tipo(tmp_path):
    app, alm = _app(tmp_path)
    adm = cliente(app, rol="admin")
    # sin datos → total 0, estructura correcta
    data = adm.get("/api/auditoria?entidad_tipo=usuario").json()
    assert data == {"items": [], "total": 0, "limit": 100, "offset": 0}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api_auditoria.py -q`
Expected: FAIL (404 en `/api/auditoria`; y `user_id` no coincide porque el endpoint aún no pasa `actor`).

- [ ] **Step 3: Añadir el endpoint + propagar `actor`**

En `apu_tool/servicio/rutas.py`, añade el import de servicio (junto a los otros):

```python
from apu_tool.servicio import auditoria as auditoria_svc
```

Añade el endpoint (p.ej. tras `yo`, antes de `_XLSX`):

```python
@router.get("/auditoria")
def auditoria_listar(user_id: Optional[str] = None, accion: Optional[str] = None,
                     entidad_tipo: Optional[str] = None, desde: Optional[str] = None,
                     hasta: Optional[str] = None, lote_id: Optional[str] = None,
                     limit: int = 100, offset: int = 0,
                     alm: Almacen = Depends(get_almacen),
                     _: object = Depends(requiere_rol("admin"))):
    return auditoria_svc.listar(alm, user_id=user_id, accion=accion, entidad_tipo=entidad_tipo,
                                desde=desde, hasta=hasta, lote_id=lote_id,
                                limit=limit, offset=offset)
```

Propaga `actor` en los endpoints de mutación (cambia `_: object = Depends(...)` por `actor=Depends(...)` y pásalo al servicio):

`eliminar_corrida` (líneas 59-63):
```python
@router.delete("/corridas/{cid}")
def eliminar_corrida(cid: int, alm: Almacen = Depends(get_almacen),
                     actor=Depends(requiere_rol("consulta"))):
    if not svc.eliminar_corrida(alm, cid, actor=actor):
        raise HTTPException(status_code=404, detail="Corrida no encontrada.")
    return {"eliminada": cid}
```

`insumos_cambios` (líneas 232-235):
```python
@router.post("/insumos/cambios")
def insumos_cambios(body: CambiosIn, alm: Almacen = Depends(get_almacen),
                    actor=Depends(requiere_rol("editor"))):
    return insumos_svc.aplicar_cambios(alm, [c.model_dump() for c in body.cambios], actor=actor)
```

`crear_insumo` (líneas 259-265):
```python
@router.post("/insumos/crear")
def crear_insumo(body: InsumoNuevoIn, alm: Almacen = Depends(get_almacen),
                 actor=Depends(requiere_rol("editor"))):
    try:
        return autoria.crear_insumo(alm, body.model_dump(), actor=actor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

`insumos_importar_crear` (líneas 279-287):
```python
@router.post("/insumos/importar-crear")
async def insumos_importar_crear(archivo: UploadFile = File(...),
                                 alm: Almacen = Depends(get_almacen),
                                 actor=Depends(requiere_rol("editor"))):
    contenido = await archivo.read()
    try:
        return autoria.aplicar_importar_insumos(alm, contenido, archivo.filename or "insumos.xlsx",
                                                actor=actor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

`crear_apu` (líneas 298-304):
```python
@router.post("/apus/crear")
def crear_apu(body: ApuNuevoIn, alm: Almacen = Depends(get_almacen),
             actor=Depends(requiere_rol("editor"))):
    try:
        return autoria.crear_apu(alm, body.model_dump(), actor=actor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

`apus_importar` (líneas 318-326):
```python
@router.post("/apus/importar")
async def apus_importar(archivo: UploadFile = File(...),
                        alm: Almacen = Depends(get_almacen),
                        actor=Depends(requiere_rol("editor"))):
    contenido = await archivo.read()
    try:
        return autoria.aplicar_importar_apus(alm, contenido, actor=actor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

`usuarios_invitar` (líneas 345-355) — pasar `actor` (ya hay una dep de rol admin; renómbrala a `actor`):
```python
@router.post("/usuarios/invitar")
def usuarios_invitar(body: UsuarioInvitarIn, alm: Almacen = Depends(get_almacen),
                     admin=Depends(get_admin_supabase),
                     actor=Depends(requiere_rol("admin"))):
    try:
        return usuarios_svc.invitar(alm, admin, body.email, body.rol, body.nombre, actor=actor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPStatusError:
        raise HTTPException(status_code=400,
                            detail="No se pudo invitar (¿el email ya existe?).")
```

(`usuarios_cambiar_rol` y `usuarios_cambiar_estado` ya pasan `actor` — no cambian.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_api_auditoria.py tests/test_api_insumos.py tests/test_api_autoria.py tests/test_api_corridas.py tests/test_api_usuarios.py tests/test_api_autorizacion.py -q`
Expected: PASS (nuevo + toda la suite de API verde).

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/rutas.py tests/test_api_auditoria.py
git commit -m "feat(auditoria): GET /api/auditoria (Admin) + propagar actor en endpoints"
```

---

### Task 10: Frontend — API tipada + visor `/auditoria` + navegación + vitest

**Files:**
- Create: `web/src/api/auditoria.ts`
- Create: `web/src/pages/Auditoria.tsx`
- Create: `web/src/pages/Auditoria.test.tsx`
- Modify: `web/src/App.tsx` (ruta `/auditoria` bajo `RequiereRol admin`)
- Modify: `web/src/components/Layout.tsx` (link "Auditoría" solo Admin)

**Interfaces:**
- Consumes: `GET /api/auditoria` (Task 9); `apiGet` (`web/src/api/client.ts`); componentes shadcn/ui existentes (`@/components/ui/{button,input,select,badge}`).
- Produces: `listarAuditoria(filtros)`; página `Auditoria` (tabla densa, filtros, lotes colapsables).

- [ ] **Step 1: Write the failing test**

Crea `web/src/pages/Auditoria.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";

vi.mock("@/api/auditoria", () => ({
  listarAuditoria: vi.fn(async () => ({
    items: [
      {
        id: 1, ts: "2026-07-01T10:00:00+00:00", user_id: "u1", user_email: "a@obra.co",
        rol: "editor", accion: "precio.editar", entidad_tipo: "insumo", entidad_id: "42",
        antes: { precio: 1000 }, despues: { precio: 1500 },
        contexto: { origen: "edicion", lote_id: "L1" },
      },
    ],
    total: 1, limit: 100, offset: 0,
  })),
}));

test("lista los eventos de auditoría", async () => {
  const { default: Auditoria } = await import("./Auditoria");
  render(<Auditoria />);
  await waitFor(() => expect(screen.getByText("a@obra.co")).toBeTruthy());
  expect(screen.getByText("precio.editar")).toBeTruthy();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (dentro de `web/`): `npm test -- --run Auditoria`
Expected: FAIL (no existe `./Auditoria` ni `@/api/auditoria`).

- [ ] **Step 3: Crear `web/src/api/auditoria.ts`**

```ts
import { apiGet } from "@/api/client";

export type EventoAuditoria = {
  id: number;
  ts: string;
  user_id: string | null;
  user_email: string | null;
  rol: string;
  accion: string;
  entidad_tipo: string;
  entidad_id: string;
  antes: Record<string, unknown> | null;
  despues: Record<string, unknown> | null;
  contexto: Record<string, unknown> | null;
};

export type AuditoriaFiltros = {
  user_id?: string;
  accion?: string;
  entidad_tipo?: string;
  desde?: string;
  hasta?: string;
  lote_id?: string;
  limit?: number;
  offset?: number;
};

export type AuditoriaPagina = {
  items: EventoAuditoria[];
  total: number;
  limit: number;
  offset: number;
};

export function listarAuditoria(f: AuditoriaFiltros = {}): Promise<AuditoriaPagina> {
  const qs = new URLSearchParams();
  Object.entries(f).forEach(([k, v]) => {
    if (v !== undefined && v !== "" && v !== null) qs.set(k, String(v));
  });
  const q = qs.toString();
  return apiGet<AuditoriaPagina>(`/auditoria${q ? `?${q}` : ""}`);
}
```

- [ ] **Step 4: Crear `web/src/pages/Auditoria.tsx`**

Tabla densa coherente con `Usuarios.tsx` (Tailwind + shadcn/ui). Filtros arriba; filas de un mismo `lote_id` colapsables.

```tsx
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { listarAuditoria, type EventoAuditoria } from "@/api/auditoria";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";

const ENTIDADES = ["", "insumo", "apu", "corrida", "usuario"] as const;

function fmtTs(ts: string): string {
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? ts : d.toLocaleString();
}

function resumen(v: Record<string, unknown> | null): string {
  if (!v) return "—";
  return Object.entries(v).map(([k, val]) => `${k}: ${val}`).join(", ");
}

type Fila = EventoAuditoria & { _loteId: string | null };

export default function Auditoria() {
  const [eventos, setEventos] = useState<EventoAuditoria[]>([]);
  const [cargando, setCargando] = useState(false);
  const [usuario, setUsuario] = useState("");
  const [accion, setAccion] = useState("");
  const [entidadTipo, setEntidadTipo] = useState("");
  const [desde, setDesde] = useState("");
  const [hasta, setHasta] = useState("");
  const [lotesAbiertos, setLotesAbiertos] = useState<Record<string, boolean>>({});

  const cargar = () => {
    setCargando(true);
    return listarAuditoria({
      user_id: usuario || undefined,
      accion: accion || undefined,
      entidad_tipo: entidadTipo || undefined,
      desde: desde || undefined,
      hasta: hasta || undefined,
      limit: 200,
    })
      .then((p) => setEventos(p.items))
      .catch((e) => toast.error(e instanceof Error ? e.message : "No se pudo cargar la auditoría."))
      .finally(() => setCargando(false));
  };

  useEffect(() => {
    cargar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Agrupa por lote_id: un lote con >1 fila se colapsa en una cabecera expandible.
  const filas = useMemo<Fila[]>(() => {
    const conteo = new Map<string, number>();
    eventos.forEach((e) => {
      const l = (e.contexto?.lote_id as string) || null;
      if (l) conteo.set(l, (conteo.get(l) ?? 0) + 1);
    });
    const out: Fila[] = [];
    const cabecerasVistas = new Set<string>();
    for (const e of eventos) {
      const l = (e.contexto?.lote_id as string) || null;
      const esLote = l !== null && (conteo.get(l) ?? 0) > 1;
      if (esLote && !cabecerasVistas.has(l as string)) {
        cabecerasVistas.add(l as string);
      }
      out.push({ ...e, _loteId: esLote ? (l as string) : null });
    }
    return out;
  }, [eventos]);

  const toggleLote = (l: string) =>
    setLotesAbiertos((s) => ({ ...s, [l]: !s[l] }));

  const conteoPorLote = useMemo(() => {
    const m = new Map<string, number>();
    filas.forEach((f) => {
      if (f._loteId) m.set(f._loteId, (m.get(f._loteId) ?? 0) + 1);
    });
    return m;
  }, [filas]);

  const cabecerasEmitidas = new Set<string>();

  return (
    <div className="flex flex-col h-full">
      <div className="flex flex-wrap items-center gap-2 px-4 py-2 border-b">
        <h2 className="text-sm font-semibold">Auditoría</h2>
        {cargando && <span className="text-xs text-muted-foreground animate-pulse">cargando…</span>}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Input
            value={usuario}
            onChange={(e) => setUsuario(e.target.value)}
            placeholder="user_id"
            className="h-7 w-40 text-xs"
          />
          <Input
            value={accion}
            onChange={(e) => setAccion(e.target.value)}
            placeholder="acción (p.ej. precio.editar)"
            className="h-7 w-52 text-xs"
          />
          <Select value={entidadTipo || "todas"} onValueChange={(v) => setEntidadTipo(v === "todas" ? "" : v)}>
            <SelectTrigger size="sm" className="h-7 w-32 text-xs">
              <SelectValue placeholder="entidad" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="todas">todas</SelectItem>
              {ENTIDADES.filter(Boolean).map((e) => (
                <SelectItem key={e} value={e}>{e}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input type="date" value={desde} onChange={(e) => setDesde(e.target.value)} className="h-7 text-xs" />
          <Input type="date" value={hasta} onChange={(e) => setHasta(e.target.value)} className="h-7 text-xs" />
          <Button size="xs" variant="outline" onClick={() => cargar()}>Filtrar</Button>
        </div>
      </div>

      <div className="flex-1 overflow-auto">
        <table className="w-full text-xs border-collapse">
          <thead className="sticky top-0 z-10 bg-muted/80 backdrop-blur">
            <tr>
              <th className="px-2 py-1.5 text-left font-medium text-muted-foreground border-b w-44">Fecha</th>
              <th className="px-2 py-1.5 text-left font-medium text-muted-foreground border-b w-48">Usuario</th>
              <th className="px-2 py-1.5 text-left font-medium text-muted-foreground border-b w-40">Acción</th>
              <th className="px-2 py-1.5 text-left font-medium text-muted-foreground border-b w-32">Entidad</th>
              <th className="px-2 py-1.5 text-left font-medium text-muted-foreground border-b">Antes → Después</th>
            </tr>
          </thead>
          <tbody>
            {filas.map((f) => {
              if (f._loteId) {
                const primeraDelLote = !cabecerasEmitidas.has(f._loteId);
                if (primeraDelLote) cabecerasEmitidas.add(f._loteId);
                const abierto = !!lotesAbiertos[f._loteId];
                if (primeraDelLote) {
                  return (
                    <tr key={`h-${f._loteId}`} className="bg-muted/30">
                      <td colSpan={5} className="px-2 py-1">
                        <button
                          type="button"
                          className="flex items-center gap-2 font-medium"
                          onClick={() => toggleLote(f._loteId as string)}
                        >
                          <span>{abierto ? "▾" : "▸"}</span>
                          <span>
                            {(f.contexto?.origen as string) || "lote"} — {conteoPorLote.get(f._loteId)} eventos
                          </span>
                          <Badge variant="outline">{f.accion}</Badge>
                        </button>
                        {!abierto && (
                          <span className="ml-6 text-muted-foreground">{fmtTs(f.ts)} · {f.user_email ?? "sistema"}</span>
                        )}
                      </td>
                    </tr>
                  );
                }
                if (!abierto) return null;
              }
              return (
                <tr key={f.id} className="hover:bg-muted/40 even:bg-muted/10">
                  <td className="px-2 py-1 whitespace-nowrap">{fmtTs(f.ts)}</td>
                  <td className="px-2 py-1">
                    <span className="text-foreground">{f.user_email ?? "sistema"}</span>
                    <span className="text-muted-foreground"> · {f.rol}</span>
                  </td>
                  <td className="px-2 py-1"><Badge variant="secondary">{f.accion}</Badge></td>
                  <td className="px-2 py-1 text-muted-foreground">{f.entidad_tipo} #{f.entidad_id}</td>
                  <td className="px-2 py-1 text-muted-foreground truncate max-w-0">
                    {resumen(f.antes)} → {resumen(f.despues)}
                  </td>
                </tr>
              );
            })}
            {filas.length === 0 && !cargando && (
              <tr>
                <td colSpan={5} className="px-3 py-8 text-center text-muted-foreground text-sm">
                  Sin eventos de auditoría
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Cablear ruta y navegación**

En `web/src/App.tsx`, añade el import y la ruta bajo `RequiereRol admin` (junto a `usuarios`):

```tsx
import Auditoria from "@/pages/Auditoria";
```
```tsx
            <Route element={<RequiereRol minimo="admin" />}>
              <Route path="usuarios" element={<Usuarios />} />
              <Route path="auditoria" element={<Auditoria />} />
            </Route>
```

En `web/src/components/Layout.tsx`, añade el link solo-Admin (reemplaza el array `links`, líneas 25-30):

```tsx
  const links = [
    { to: "/corridas", label: "Corridas", end: false },
    { to: "/insumos", label: "Insumos", end: true },
    { to: "/apus", label: "APUs", end: true },
    ...(puede(perfil?.rol, "admin")
      ? [
          { to: "/usuarios", label: "Usuarios", end: true },
          { to: "/auditoria", label: "Auditoría", end: true },
        ]
      : []),
  ];
```

- [ ] **Step 6: Run tests + build**

Run (dentro de `web/`): `npm test -- --run` y luego `npm run build`
Expected: vitest verde (incluye `Auditoria.test.tsx` + los 18 existentes) y build OK.

- [ ] **Step 7: Commit**

```bash
git add web/src/api/auditoria.ts web/src/pages/Auditoria.tsx web/src/pages/Auditoria.test.tsx web/src/App.tsx web/src/components/Layout.tsx
git commit -m "feat(auditoria): visor Admin /auditoria + API tipada + navegación"
```

---

## Notas de cierre (para el revisor final)

- **Suite completa:** `python -m pytest tests/ -q` (objetivo: 204 previos + nuevos, todos verdes) y, dentro de `web/`, `npm test -- --run` + `npm run build`.
- **Invariante #1:** verificar que NO se tocaron `apu_tool/dominio/privacy.py`, `apu_tool/dominio/ai_assist.py` ni las vistas `DePriced*`.
- **Ops pendiente (no es código):** aplicar `supabase/migrations/0003_auditoria.sql` a Supabase vía MCP antes de producción; el "gate" psycopg contra Postgres real sigue diferido al PaaS (Plan 4).
