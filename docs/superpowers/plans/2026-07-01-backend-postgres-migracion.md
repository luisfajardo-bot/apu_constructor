# Backend Postgres + Migración de Catálogo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Añadir un backend de persistencia Postgres (Supabase) que implemente los mismos `Protocol` que hoy cumplen los repos SQLite, seleccionable por config, y migrar el catálogo (insumos + historial de precios + APUs) desde las SQLite locales — sin romper la lógica existente ni la invariante #1.

**Architecture:** Enfoque A — tres clases nuevas (`PreciosPg`, `ApusPg`, `CorridasPg`) en `apu_tool/datos/pg/` implementan `RepositorioPrecios/Apus/Corridas` con **psycopg v3** sobre un pool de conexiones. `Almacen` elige backend según config (`sqlite` por defecto; `postgres` si hay `DATABASE_URL`). Las tres SQLite se unifican en un Postgres separado por **schemas** (`precios`, `apus`, `corridas`) para evitar la colisión de la tabla `meta`. SQLite se conserva intacto para desarrollo y tests rápidos. Un test de contrato parametrizado corre la misma batería contra ambos backends y es el oráculo de no-regresión.

**Tech Stack:** Python 3.10+, psycopg[binary] v3, psycopg_pool, Supabase Postgres (pooler Supavisor en modo transacción), openpyxl (existente), pytest.

## Global Constraints

- **Invariante #1 (NO romper):** la IA nunca ve dinero. Este plan NO toca `apu_tool/dominio/privacy.py`, `ai_assist.py` ni las vistas `DePriced*`. Los repos Postgres exponen exactamente los mismos tipos que los SQLite.
- **Persistencia aislada en `apu_tool/datos/`:** ningún SQL crudo fuera de esa capa. Los repos Postgres viven en `apu_tool/datos/pg/`.
- **Español** en nombres de dominio, comentarios y mensajes de usuario.
- **Sin dependencias pesadas:** `psycopg` (v3) y `psycopg_pool` son livianas y son el driver estándar de Postgres; se aceptan. No se introduce ORM.
- **Los 161 tests actuales deben seguir verdes** tras cada tarea. SQLite sigue siendo el backend por defecto (sin `DATABASE_URL`, todo corre igual que hoy).
- **SQL parametrizado siempre** (placeholders `%s`); cero concatenación de input de usuario.
- **Identidad de insumo = (codigo, nombre_norm)**; el código NO es único. El precio cuelga del `id` interno.
- **Turno** (DIURNO/NOCTURNO) es parte de la clave de un APU y su composición.
- TDD, commits frecuentes. Rama: `feat/produccion-multiusuario`.

---

### Task 1: Dependencias, capa de conexión Postgres y switch de backend en config

**Files:**
- Modify: `requirements.txt`
- Create: `apu_tool/datos/pg/__init__.py`
- Create: `apu_tool/datos/pg/conexion.py`
- Modify: `apu_tool/config.py` (añadir al final, antes no hay nada de backend)
- Test: `tests/test_pg_conexion.py`

**Interfaces:**
- Produces:
  - `config.db_backend() -> str` — devuelve `"postgres"` si `APU_DB_BACKEND=="postgres"` o hay `DATABASE_URL`; si no `"sqlite"`.
  - `config.database_url() -> str | None` — lee `DATABASE_URL`.
  - `apu_tool.datos.pg.conexion.Conexion(dsn: str)` con:
    - `Conexion.connection() -> ContextManager[psycopg.Connection]` — saca una conexión del pool, `row_factory=dict_row`, **commit** al salir sin excepción, **rollback** si excepción, y la devuelve al pool.
    - `Conexion.transaccion() -> ContextManager[psycopg.Connection]` — igual pero pensada como unidad de trabajo compartida (misma semántica; es el punto donde el Plan 3 enganchará auditoría). En Plan 1 los repos usan `connection()`.
    - `Conexion.cerrar() -> None` — cierra el pool.

- [ ] **Step 1: Añadir dependencias**

En `requirements.txt`, añadir al final:

```
psycopg[binary]>=3.2   # driver Postgres (backend de nube)
psycopg-pool>=3.2      # pool de conexiones para el backend Postgres
```

Instalar:

Run: `pip install -r requirements.txt`
Expected: instala psycopg y psycopg-pool sin error.

- [ ] **Step 2: Escribir el test de conexión (falla)**

Create `tests/test_pg_conexion.py`:

```python
import os
import pytest
from apu_tool import config


def test_db_backend_por_defecto_es_sqlite(monkeypatch):
    monkeypatch.delenv("APU_DB_BACKEND", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert config.db_backend() == "sqlite"


def test_db_backend_postgres_por_database_url(monkeypatch):
    monkeypatch.delenv("APU_DB_BACKEND", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://x")
    assert config.db_backend() == "postgres"


def test_db_backend_postgres_explicito(monkeypatch):
    monkeypatch.setenv("APU_DB_BACKEND", "postgres")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert config.db_backend() == "postgres"


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"),
                    reason="sin TEST_DATABASE_URL: se omite la prueba contra Postgres real")
def test_conexion_hace_ping():
    from apu_tool.datos.pg.conexion import Conexion
    cx = Conexion(os.environ["TEST_DATABASE_URL"])
    try:
        with cx.connection() as conn:
            r = conn.execute("SELECT 1 AS uno").fetchone()
            assert r["uno"] == 1
    finally:
        cx.cerrar()
```

- [ ] **Step 3: Verificar que falla**

Run: `python -m pytest tests/test_pg_conexion.py -v`
Expected: FAIL (`config.db_backend` no existe / `apu_tool.datos.pg` no existe).

- [ ] **Step 4: Añadir el switch de backend a `config.py`**

Añadir al final de `apu_tool/config.py`:

```python
# ---------------------------------------------------------------------------
# Selección de backend de persistencia. Por defecto SQLite (local/dev/tests).
# En producción se usa Postgres (Supabase) si hay DATABASE_URL o se fuerza con
# APU_DB_BACKEND=postgres.
# ---------------------------------------------------------------------------
def database_url() -> str | None:
    return os.environ.get("DATABASE_URL") or None


def db_backend() -> str:
    """'postgres' | 'sqlite'. Postgres si se fuerza por env o hay DATABASE_URL."""
    if os.environ.get("APU_DB_BACKEND", "").strip().lower() == "postgres":
        return "postgres"
    return "postgres" if database_url() else "sqlite"
```

- [ ] **Step 5: Crear el paquete pg y la capa de conexión**

Create `apu_tool/datos/pg/__init__.py` (vacío):

```python
```

Create `apu_tool/datos/pg/conexion.py`:

```python
"""Pool de conexiones Postgres (Supabase) para el backend de nube.

Una instancia de Conexion envuelve un ConnectionPool de psycopg. Los repos
Postgres (PreciosPg, ApusPg, CorridasPg) comparten UNA Conexion (un pool).

Notas Supabase: se usa el pooler en modo transacción (Supavisor), por lo que
se desactivan los prepared statements server-side (prepare_threshold=None).
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


class Conexion:
    def __init__(self, dsn: str, min_size: int = 1, max_size: int = 10):
        self._pool = ConnectionPool(
            conninfo=dsn,
            min_size=min_size,
            max_size=max_size,
            open=True,
            kwargs={"row_factory": dict_row, "prepare_threshold": None},
        )

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        """Conexión por operación: commit al salir OK, rollback si excepción."""
        with self._pool.connection() as conn:
            yield conn  # psycopg_pool ya hace commit/rollback y devuelve al pool

    @contextmanager
    def transaccion(self) -> Iterator[psycopg.Connection]:
        """Unidad de trabajo (mismo comportamiento). Seam para auditoría (Plan 3)."""
        with self._pool.connection() as conn:
            yield conn

    def cerrar(self) -> None:
        self._pool.close()
```

- [ ] **Step 6: Verificar que pasa**

Run: `python -m pytest tests/test_pg_conexion.py -v`
Expected: PASS (los 3 tests de `db_backend`; el `ping` se omite salvo que exista `TEST_DATABASE_URL`).

- [ ] **Step 7: Verificar no-regresión**

Run: `python -m pytest tests/ -q`
Expected: 161+ passed (sin `DATABASE_URL` todo sigue igual).

- [ ] **Step 8: Commit**

```bash
git add requirements.txt apu_tool/datos/pg/__init__.py apu_tool/datos/pg/conexion.py apu_tool/config.py tests/test_pg_conexion.py
git commit -m "feat(datos): pool de conexión Postgres y switch de backend por config"
```

---

### Task 2: Esquema Postgres (DDL con schemas) + migraciones Supabase

**Files:**
- Create: `db/pg/precios.sql`
- Create: `db/pg/apus.sql`
- Create: `db/pg/corridas.sql`
- Create: `supabase/migrations/0001_esquema_inicial.sql`
- Test: `tests/test_pg_esquema.py`

**Interfaces:**
- Produces: tres schemas Postgres (`precios`, `apus`, `corridas`) con tablas calificadas: `precios.insumos`, `precios.insumo_precios`, `precios.meta`, `apus.apus`, `apus.apu_componentes`, `apus.meta`, `corridas.corrida`, `corridas.corrida_item`. El texto DDL se lee desde `db/pg/*.sql` (igual que los repos SQLite leen `db/*.sql`).

**Notas de traducción SQLite→Postgres aplicadas aquí:**
- `INTEGER PRIMARY KEY` / `AUTOINCREMENT` → `BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY`.
- `REAL` → `DOUBLE PRECISION`. `TEXT` se mantiene.
- Se añade `ON DELETE CASCADE` al FK `insumo_precios→insumos` (hoy falta en SQLite).
- Se añade la columna `creado_por TEXT` (nullable) a `insumo_precios` y `corrida` (la usarán auditoría/roles en Planes 2–3; incluirla ahora evita un ALTER posterior y permite que la migración la rellene).
- `corrida_item.*_json` se mantiene `TEXT` (guarda strings JSON; el código hace `json.loads`).

- [ ] **Step 1: Escribir el test de esquema (falla)**

Create `tests/test_pg_esquema.py`:

```python
import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="sin TEST_DATABASE_URL: se omite la prueba contra Postgres real")


def _aplicar_todo(conn):
    from apu_tool import config
    for archivo in ("precios.sql", "apus.sql", "corridas.sql"):
        sql = (config.PROJECT_ROOT / "db" / "pg" / archivo).read_text(encoding="utf-8")
        conn.execute(sql)


def test_esquema_crea_tablas_calificadas():
    from apu_tool.datos.pg.conexion import Conexion
    cx = Conexion(os.environ["TEST_DATABASE_URL"])
    try:
        with cx.connection() as conn:
            _aplicar_todo(conn)
            r = conn.execute(
                "SELECT count(*) AS n FROM information_schema.tables "
                "WHERE table_schema IN ('precios','apus','corridas')").fetchone()
            assert r["n"] >= 8
    finally:
        cx.cerrar()
```

- [ ] **Step 2: Verificar que falla**

Run: `python -m pytest tests/test_pg_esquema.py -v`
Expected: FAIL o SKIP. Con `TEST_DATABASE_URL`: FAIL (faltan `db/pg/*.sql`). Sin él: SKIP — está bien, continúa.

- [ ] **Step 3: Escribir `db/pg/precios.sql`**

```sql
-- Esquema Postgres de precios (Supabase). Equivalente a db/precios.sql.
CREATE SCHEMA IF NOT EXISTS precios;

CREATE TABLE IF NOT EXISTS precios.insumos (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    codigo      TEXT NOT NULL,
    nombre      TEXT NOT NULL,
    nombre_norm TEXT NOT NULL,
    unidad      TEXT,
    grupo       TEXT,
    UNIQUE (codigo, nombre_norm)
);
CREATE INDEX IF NOT EXISTS idx_insumo_cod ON precios.insumos(codigo);

CREATE TABLE IF NOT EXISTS precios.insumo_precios (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    insumo_id     BIGINT NOT NULL REFERENCES precios.insumos(id) ON DELETE CASCADE,
    precio        DOUBLE PRECISION NOT NULL,
    fuente        TEXT,
    clasificacion TEXT,
    fecha         TEXT,
    vigente       INTEGER NOT NULL DEFAULT 1,
    creado_por    TEXT
);
CREATE INDEX IF NOT EXISTS idx_precio_ins ON precios.insumo_precios(insumo_id, vigente);

CREATE TABLE IF NOT EXISTS precios.meta (
    clave TEXT PRIMARY KEY,
    valor TEXT
);
```

- [ ] **Step 4: Escribir `db/pg/apus.sql`**

```sql
-- Esquema Postgres de apus (Supabase). Equivalente a db/apus.sql.
CREATE SCHEMA IF NOT EXISTS apus;

CREATE TABLE IF NOT EXISTS apus.apus (
    codigo TEXT NOT NULL,
    shift  TEXT NOT NULL,
    nombre TEXT NOT NULL,
    unidad TEXT,
    grupo  TEXT,
    PRIMARY KEY (codigo, shift)
);
CREATE INDEX IF NOT EXISTS idx_apus_nombre ON apus.apus(nombre);

CREATE TABLE IF NOT EXISTS apus.apu_componentes (
    apu_codigo            TEXT NOT NULL,
    shift                 TEXT NOT NULL,
    seq                   INTEGER NOT NULL,
    insumo_codigo         TEXT,
    insumo_nombre         TEXT,
    unidad                TEXT,
    rendimiento           DOUBLE PRECISION,
    precio_unitario_hist  DOUBLE PRECISION,
    PRIMARY KEY (apu_codigo, shift, seq),
    FOREIGN KEY (apu_codigo, shift) REFERENCES apus.apus(codigo, shift)
);
CREATE INDEX IF NOT EXISTS idx_comp_apu ON apus.apu_componentes(apu_codigo, shift);

CREATE TABLE IF NOT EXISTS apus.meta (
    clave TEXT PRIMARY KEY,
    valor TEXT
);
```

- [ ] **Step 5: Escribir `db/pg/corridas.sql`**

```sql
-- Esquema Postgres de corridas (Supabase). Equivalente a db/corridas.sql.
CREATE SCHEMA IF NOT EXISTS corridas;

CREATE TABLE IF NOT EXISTS corridas.corrida (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    creada_en     TEXT NOT NULL,
    archivo       TEXT NOT NULL,
    turno_def     TEXT NOT NULL,
    use_ai        SMALLINT,
    estado        TEXT NOT NULL,
    cuadro_path   TEXT,
    duracion_ms   INTEGER,
    creado_por    TEXT
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
    candidatos_json  TEXT
);
CREATE INDEX IF NOT EXISTS ix_corrida_item ON corridas.corrida_item(corrida_id, seq);
```

- [ ] **Step 6: Crear la migración Supabase (copia consolidada del DDL)**

Create `supabase/migrations/0001_esquema_inicial.sql` con el contenido concatenado de los tres archivos anteriores (precios, luego apus, luego corridas), en ese orden. Es la fuente de verdad para el deploy gestionado; `db/pg/*.sql` es lo que aplica `init_schema()` en runtime/tests. (Mantener ambos idénticos; la Task 8 los verifica por conteo de tablas.)

- [ ] **Step 7: Verificar que pasa**

Run: `python -m pytest tests/test_pg_esquema.py -v`
Expected: PASS con `TEST_DATABASE_URL`; SKIP sin él.

- [ ] **Step 8: Commit**

```bash
git add db/pg/ supabase/migrations/0001_esquema_inicial.sql tests/test_pg_esquema.py
git commit -m "feat(datos): esquema Postgres con schemas precios/apus/corridas + migración Supabase"
```

---

### Task 3: `PreciosPg` — implementación Postgres de `RepositorioPrecios`

**Files:**
- Create: `apu_tool/datos/pg/precios_pg.py`
- Test: cubierto por el contrato parametrizado (Task 6). Aquí se añade un smoke test directo.

**Interfaces:**
- Consumes: `Conexion` (Task 1); DDL `db/pg/precios.sql` (Task 2); `nucleo.models.Insumo`; `nucleo.texto.normalizar`; `config.classify_price_source`.
- Produces: `PreciosPg(cx: Conexion)` que cumple `RepositorioPrecios` — mismos métodos y firmas que `PreciosDB` (ver `apu_tool/datos/precios_db.py` y `apu_tool/datos/repositorio.py`).

**Reglas de port (SQLite→Postgres) aplicadas:** placeholders `?`→`%s`; nombres de tabla calificados (`precios.insumos`, `precios.insumo_precios`, `precios.meta`); `INSERT OR IGNORE … ` → `INSERT … ON CONFLICT (codigo, nombre_norm) DO NOTHING RETURNING id` (si `fetchone()` es `None`, existía → no duplicar precio); `cur.lastrowid` → `RETURNING id` + `fetchone()["id"]`; `INSERT OR REPLACE INTO meta` → `ON CONFLICT (clave) DO UPDATE SET valor=EXCLUDED.valor`. La lógica de negocio (identidad, precio vigente, historial, filtros) es idéntica a `PreciosDB`; el contrato de la Task 6 es el oráculo.

- [ ] **Step 1: Escribir el smoke test (falla)**

Create `tests/test_precios_pg_smoke.py`:

```python
import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="sin TEST_DATABASE_URL")


@pytest.fixture()
def precios_pg():
    from apu_tool import config
    from apu_tool.datos.pg.conexion import Conexion
    from apu_tool.datos.pg.precios_pg import PreciosPg
    cx = Conexion(os.environ["TEST_DATABASE_URL"])
    with cx.connection() as conn:
        conn.execute("DROP SCHEMA IF EXISTS precios CASCADE")
        conn.execute((config.PROJECT_ROOT / "db" / "pg" / "precios.sql").read_text("utf-8"))
    repo = PreciosPg(cx)
    yield repo
    cx.cerrar()


def test_insert_y_candidato(precios_pg):
    from apu_tool.nucleo.models import Insumo
    n = precios_pg.insert_insumos([
        Insumo("6140", "ACERO 60000 PSI", "KG", "MATERIAL", 3500.0, "PRECIO IDU")])
    assert n == 1
    cands = precios_pg.get_candidatos("6140")
    assert len(cands) == 1
    assert cands[0].precio == 3500.0
```

- [ ] **Step 2: Verificar que falla**

Run: `python -m pytest tests/test_precios_pg_smoke.py -v`
Expected: FAIL (no existe `precios_pg`) o SKIP sin `TEST_DATABASE_URL`.

- [ ] **Step 3: Escribir `apu_tool/datos/pg/precios_pg.py`**

```python
"""Backend Postgres de precios. Implementa RepositorioPrecios.

Port 1:1 de apu_tool/datos/precios_db.py a Postgres (psycopg v3). Misma lógica
de negocio; cambian dialecto SQL (%s, ON CONFLICT, RETURNING) y tablas
calificadas por schema. NO toca dinero de cara a la IA (fuera de su alcance).
"""
from __future__ import annotations

from datetime import date
from typing import Iterable, Optional

from apu_tool import config
from apu_tool.datos.pg.conexion import Conexion
from apu_tool.nucleo.models import Insumo
from apu_tool.nucleo.texto import normalizar

SCHEMA_PATH = config.PROJECT_ROOT / "db" / "pg" / "precios.sql"


class PreciosPg:
    def __init__(self, cx: Conexion):
        self.cx = cx

    def init_schema(self) -> None:
        with self.cx.connection() as conn:
            conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))

    def reset(self) -> None:
        with self.cx.connection() as conn:
            conn.execute("DROP SCHEMA IF EXISTS precios CASCADE")
            conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))

    # ---- escritura ----
    def insert_insumos(self, insumos: Iterable[Insumo]) -> int:
        hoy = date.today().isoformat()
        n = 0
        with self.cx.connection() as conn:
            for i in insumos:
                nombre_norm = normalizar(i.nombre)
                cur = conn.execute(
                    "INSERT INTO precios.insumos "
                    "(codigo, nombre, nombre_norm, unidad, grupo) VALUES (%s,%s,%s,%s,%s) "
                    "ON CONFLICT (codigo, nombre_norm) DO NOTHING RETURNING id",
                    (i.codigo, i.nombre, nombre_norm, i.unidad, i.grupo))
                row = cur.fetchone()
                if row is None:
                    continue  # identidad ya existía; no duplicar precio
                iid = row["id"]
                conn.execute(
                    "INSERT INTO precios.insumo_precios "
                    "(insumo_id, precio, fuente, clasificacion, fecha, vigente) "
                    "VALUES (%s,%s,%s,%s,%s,1)",
                    (iid, i.precio, i.fuente_precio,
                     config.classify_price_source(i.fuente_precio), hoy))
                n += 1
        return n

    def crear_insumo(self, insumo: Insumo) -> int:
        if not str(insumo.codigo or "").strip() or not str(insumo.nombre or "").strip():
            raise ValueError("El insumo necesita código y nombre.")
        nombre_norm = normalizar(insumo.nombre)
        hoy = date.today().isoformat()
        with self.cx.connection() as conn:
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
            self._insertar_precio_vigente(conn, iid, insumo.precio, insumo.fuente_precio, hoy)
            return iid

    def _ids_de(self, conn, codigo: str, nombre: Optional[str]) -> list[int]:
        if nombre is None:
            rows = conn.execute("SELECT id FROM precios.insumos WHERE codigo=%s",
                                (str(codigo),)).fetchall()
        else:
            rows = conn.execute(
                "SELECT id FROM precios.insumos WHERE codigo=%s AND nombre_norm=%s",
                (str(codigo), normalizar(nombre))).fetchall()
        return [r["id"] for r in rows]

    def _insertar_precio_vigente(self, conn, insumo_id: int, precio: float,
                                 fuente: str, fecha: str) -> None:
        conn.execute("UPDATE precios.insumo_precios SET vigente=0 WHERE insumo_id=%s",
                     (int(insumo_id),))
        conn.execute(
            "INSERT INTO precios.insumo_precios "
            "(insumo_id, precio, fuente, clasificacion, fecha, vigente) "
            "VALUES (%s,%s,%s,%s,%s,1)",
            (int(insumo_id), float(precio), fuente,
             config.classify_price_source(fuente), fecha))

    def set_precio(self, codigo: str, precio: float, fuente: str = "",
                   fecha: Optional[str] = None, nombre: Optional[str] = None) -> None:
        fecha = fecha or date.today().isoformat()
        with self.cx.connection() as conn:
            ids = self._ids_de(conn, codigo, nombre)
            if len(ids) != 1:
                raise ValueError(
                    f"Código {codigo} resuelve a {len(ids)} insumos; "
                    f"especifica el nombre exacto para desambiguar.")
            self._insertar_precio_vigente(conn, ids[0], precio, fuente, fecha)

    def set_precio_por_id(self, insumo_id: int, precio: float, fuente: str = "",
                          fecha: Optional[str] = None) -> None:
        fecha = fecha or date.today().isoformat()
        with self.cx.connection() as conn:
            r = conn.execute("SELECT id FROM precios.insumos WHERE id=%s",
                             (int(insumo_id),)).fetchone()
            if r is None:
                raise ValueError(f"No existe el insumo id={insumo_id}.")
            self._insertar_precio_vigente(conn, int(insumo_id), precio, fuente, fecha)

    def set_meta(self, clave: str, valor: str) -> None:
        with self.cx.connection() as conn:
            conn.execute(
                "INSERT INTO precios.meta (clave, valor) VALUES (%s,%s) "
                "ON CONFLICT (clave) DO UPDATE SET valor=EXCLUDED.valor",
                (clave, str(valor)))

    # ---- lectura ----
    def _fila_a_insumo(self, r) -> Insumo:
        return Insumo(codigo=r["codigo"], nombre=r["nombre"], unidad=r["unidad"] or "",
                      grupo=r["grupo"] or "", precio=r["precio"] or 0.0,
                      fuente_precio=r["fuente"] or "", id=r["id"])

    def get_candidatos(self, codigo: str) -> list[Insumo]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT i.id, i.codigo, i.nombre, i.unidad, i.grupo, p.precio, p.fuente "
                "FROM precios.insumos i LEFT JOIN precios.insumo_precios p "
                "  ON p.insumo_id = i.id AND p.vigente = 1 "
                "WHERE i.codigo = %s ORDER BY i.id", (str(codigo),)).fetchall()
        return [self._fila_a_insumo(r) for r in rows]

    def get_insumo_por_id(self, insumo_id: int) -> Optional[Insumo]:
        with self.cx.connection() as conn:
            r = conn.execute(
                "SELECT i.id, i.codigo, i.nombre, i.unidad, i.grupo, p.precio, p.fuente "
                "FROM precios.insumos i LEFT JOIN precios.insumo_precios p "
                "  ON p.insumo_id = i.id AND p.vigente = 1 "
                "WHERE i.id = %s", (int(insumo_id),)).fetchone()
        return self._fila_a_insumo(r) if r else None

    def price_history(self, codigo: str, nombre: Optional[str] = None) -> list[dict]:
        with self.cx.connection() as conn:
            q = ("SELECT p.precio, p.fuente, p.clasificacion, p.fecha, p.vigente "
                 "FROM precios.insumo_precios p JOIN precios.insumos i ON i.id = p.insumo_id "
                 "WHERE i.codigo = %s")
            params: list = [str(codigo)]
            if nombre is not None:
                q += " AND i.nombre_norm = %s"
                params.append(normalizar(nombre))
            q += " ORDER BY p.id"
            rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]

    def list_insumos(self, q=None, grupo=None, fuente=None,
                     clasificacion: Optional[str] = None,
                     limit: int = 100, offset: int = 0) -> tuple[list[Insumo], int]:
        base = ("FROM precios.insumos i LEFT JOIN precios.insumo_precios p "
                "ON p.insumo_id = i.id AND p.vigente = 1")
        where, params = [], []
        if q:
            where.append("(i.nombre ILIKE %s OR i.codigo ILIKE %s)")
            like = f"%{q.strip()}%"
            params += [like, like]
        if grupo:
            where.append("i.grupo = %s")
            params.append(grupo)
        if fuente:
            where.append("p.fuente = %s")
            params.append(fuente)
        if clasificacion == "publico":
            placeholders = ",".join(["%s"] * len(config.PUBLIC_PRICE_SOURCES))
            where.append(f"UPPER(p.fuente) IN ({placeholders})")
            params += [s.upper() for s in config.PUBLIC_PRICE_SOURCES]
        elif clasificacion == "interno":
            placeholders = ",".join(["%s"] * len(config.PUBLIC_PRICE_SOURCES))
            where.append(f"(p.fuente IS NULL OR UPPER(p.fuente) NOT IN ({placeholders}))")
            params += [s.upper() for s in config.PUBLIC_PRICE_SOURCES]
        wsql = (" WHERE " + " AND ".join(where)) if where else ""
        with self.cx.connection() as conn:
            total = conn.execute(f"SELECT COUNT(*) AS n {base}{wsql}", params).fetchone()["n"]
            rows = conn.execute(
                f"SELECT i.id, i.codigo, i.nombre, i.unidad, i.grupo, p.precio, p.fuente "
                f"{base}{wsql} ORDER BY i.codigo, i.id LIMIT %s OFFSET %s",
                params + [int(limit), int(offset)]).fetchall()
        return [self._fila_a_insumo(r) for r in rows], int(total)

    def grupos(self) -> list[str]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT grupo FROM precios.insumos "
                "WHERE grupo IS NOT NULL AND grupo <> '' ORDER BY grupo").fetchall()
        return [r["grupo"] for r in rows]

    def fuentes(self) -> list[str]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT fuente FROM precios.insumo_precios "
                "WHERE vigente = 1 AND fuente IS NOT NULL AND fuente <> '' "
                "ORDER BY fuente").fetchall()
        return [r["fuente"] for r in rows]

    def search_insumos(self, texto: str, limit: int = 20) -> list[Insumo]:
        like = f"%{texto.strip()}%"
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT id FROM precios.insumos WHERE nombre ILIKE %s OR codigo ILIKE %s LIMIT %s",
                (like, like, limit)).fetchall()
        return [self.get_insumo_por_id(r["id"]) for r in rows]

    def search_insumos_por_palabras(self, palabras: list[str], limit: int = 60) -> list[Insumo]:
        palabras = [p for p in palabras if p]
        if not palabras:
            return []
        clauses = " OR ".join(["nombre ILIKE %s"] * len(palabras))
        params = [f"%{p}%" for p in palabras] + [limit]
        with self.cx.connection() as conn:
            rows = conn.execute(
                f"SELECT id FROM precios.insumos WHERE {clauses} LIMIT %s", params).fetchall()
        return [self.get_insumo_por_id(r["id"]) for r in rows]

    def counts(self) -> dict[str, int]:
        with self.cx.connection() as conn:
            return {t: conn.execute(f"SELECT COUNT(*) AS n FROM precios.{t}").fetchone()["n"]
                    for t in ("insumos", "insumo_precios")}

    def get_meta(self) -> dict[str, str]:
        with self.cx.connection() as conn:
            return {r["clave"]: r["valor"]
                    for r in conn.execute("SELECT clave, valor FROM precios.meta").fetchall()}
```

Nota: la búsqueda `LIKE` de SQLite se traduce a `ILIKE` en Postgres para conservar el comportamiento insensible a mayúsculas que el resto de la app asume.

- [ ] **Step 4: Verificar que pasa**

Run: `python -m pytest tests/test_precios_pg_smoke.py -v`
Expected: PASS con `TEST_DATABASE_URL`; SKIP sin él.

- [ ] **Step 5: Verificar no-regresión**

Run: `python -m pytest tests/ -q`
Expected: 161+ passed.

- [ ] **Step 6: Commit**

```bash
git add apu_tool/datos/pg/precios_pg.py tests/test_precios_pg_smoke.py
git commit -m "feat(datos): PreciosPg (backend Postgres de RepositorioPrecios)"
```

---

### Task 4: `ApusPg` — implementación Postgres de `RepositorioApus`

**Files:**
- Create: `apu_tool/datos/pg/apus_pg.py`

**Interfaces:**
- Consumes: `Conexion`; DDL `db/pg/apus.sql`; `nucleo.models.{Apu, ApuComponent, DePricedApu, DePricedComponent}`.
- Produces: `ApusPg(cx: Conexion)` que cumple `RepositorioApus` (mismas firmas que `ApusDB`).

**Reglas de port:** placeholders `%s`; tablas calificadas `apus.apus`, `apus.apu_componentes`, `apus.meta`; `INSERT OR REPLACE INTO apus` → `ON CONFLICT (codigo, shift) DO UPDATE SET nombre=EXCLUDED.nombre, unidad=EXCLUDED.unidad, grupo=EXCLUDED.grupo`; `INSERT OR REPLACE INTO meta` → `ON CONFLICT (clave) DO UPDATE SET valor=EXCLUDED.valor`; `executemany` → `cur.executemany`; `LIKE`→`ILIKE`. La lógica de `insert_components` (numeración `seq` con `COALESCE(MAX(seq)+1,0)`) y `crear_apu` (identidad (codigo,shift)) es idéntica a `ApusDB`.

- [ ] **Step 1: Escribir `apu_tool/datos/pg/apus_pg.py`**

```python
"""Backend Postgres de APUs. Implementa RepositorioApus. Port 1:1 de apus_db.py."""
from __future__ import annotations

from typing import Iterable, Optional

from apu_tool import config
from apu_tool.datos.pg.conexion import Conexion
from apu_tool.nucleo.models import Apu, ApuComponent, DePricedApu, DePricedComponent

SCHEMA_PATH = config.PROJECT_ROOT / "db" / "pg" / "apus.sql"


class ApusPg:
    def __init__(self, cx: Conexion):
        self.cx = cx

    def init_schema(self) -> None:
        with self.cx.connection() as conn:
            conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))

    def reset(self) -> None:
        with self.cx.connection() as conn:
            conn.execute("DROP SCHEMA IF EXISTS apus CASCADE")
            conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))

    # ---- escritura ----
    def insert_apus(self, apus: Iterable[Apu]) -> int:
        rows = [(a.codigo, a.shift, a.nombre, a.unidad, a.grupo) for a in apus]
        with self.cx.connection() as conn:
            conn.executemany(
                "INSERT INTO apus.apus (codigo, shift, nombre, unidad, grupo) "
                "VALUES (%s,%s,%s,%s,%s) "
                "ON CONFLICT (codigo, shift) DO UPDATE SET "
                "nombre=EXCLUDED.nombre, unidad=EXCLUDED.unidad, grupo=EXCLUDED.grupo", rows)
        return len(rows)

    def insert_components(self, comps: Iterable[ApuComponent]) -> int:
        comps = list(comps)
        with self.cx.connection() as conn:
            seq_by_key: dict[tuple[str, str], int] = {}
            rows = []
            for c in comps:
                key = (c.apu_codigo, c.shift)
                if key not in seq_by_key:
                    r = conn.execute(
                        "SELECT COALESCE(MAX(seq) + 1, 0) AS s FROM apus.apu_componentes "
                        "WHERE apu_codigo=%s AND shift=%s", key).fetchone()
                    seq_by_key[key] = r["s"]
                seq = seq_by_key[key]
                seq_by_key[key] = seq + 1
                rows.append((c.apu_codigo, c.shift, seq, c.insumo_codigo,
                             c.insumo_nombre, c.unidad, c.rendimiento,
                             c.precio_unitario_hist))
            conn.executemany(
                "INSERT INTO apus.apu_componentes "
                "(apu_codigo, shift, seq, insumo_codigo, insumo_nombre, unidad, "
                " rendimiento, precio_unitario_hist) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", rows)
        return len(rows)

    def crear_apu(self, apu: Apu, componentes: list[ApuComponent]) -> None:
        if not str(apu.codigo or "").strip() or not str(apu.nombre or "").strip():
            raise ValueError("El APU necesita código y nombre.")
        with self.cx.connection() as conn:
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

    def set_meta(self, clave: str, valor: str) -> None:
        with self.cx.connection() as conn:
            conn.execute(
                "INSERT INTO apus.meta (clave, valor) VALUES (%s,%s) "
                "ON CONFLICT (clave) DO UPDATE SET valor=EXCLUDED.valor",
                (clave, str(valor)))

    # ---- lectura ----
    def all_apus(self) -> list[Apu]:
        with self.cx.connection() as conn:
            rows = conn.execute("SELECT * FROM apus.apus").fetchall()
        return [Apu(r["codigo"], r["nombre"], r["unidad"], r["shift"], r["grupo"]) for r in rows]

    def apu_index(self) -> list[tuple[str, str, str]]:
        with self.cx.connection() as conn:
            rows = conn.execute("SELECT codigo, nombre, shift FROM apus.apus").fetchall()
        return [(r["codigo"], r["nombre"], r["shift"]) for r in rows]

    def list_apus(self, q: Optional[str] = None, grupo: Optional[str] = None,
                  shift: Optional[str] = None, limit: int = 100,
                  offset: int = 0) -> tuple[list[Apu], int]:
        where, params = [], []
        if q:
            where.append("(nombre ILIKE %s OR codigo ILIKE %s)")
            like = f"%{q.strip()}%"
            params += [like, like]
        if grupo:
            where.append("grupo = %s")
            params.append(grupo)
        if shift:
            where.append("shift = %s")
            params.append(shift)
        wsql = (" WHERE " + " AND ".join(where)) if where else ""
        with self.cx.connection() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS n FROM apus.apus{wsql}", params).fetchone()["n"]
            rows = conn.execute(
                f"SELECT codigo, nombre, unidad, shift, grupo FROM apus.apus{wsql} "
                f"ORDER BY codigo, shift LIMIT %s OFFSET %s",
                params + [int(limit), int(offset)]).fetchall()
        return ([Apu(r["codigo"], r["nombre"], r["unidad"], r["shift"], r["grupo"])
                 for r in rows], int(total))

    def search_apus(self, texto: str, limit: int = 20) -> list[Apu]:
        like = f"%{texto.strip()}%"
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM apus.apus WHERE nombre ILIKE %s OR codigo ILIKE %s LIMIT %s",
                (like, like, limit)).fetchall()
        return [Apu(r["codigo"], r["nombre"], r["unidad"], r["shift"], r["grupo"]) for r in rows]

    def get_apu(self, codigo: str, shift: str) -> Optional[Apu]:
        with self.cx.connection() as conn:
            r = conn.execute("SELECT * FROM apus.apus WHERE codigo=%s AND shift=%s",
                             (str(codigo), shift)).fetchone()
        return Apu(r["codigo"], r["nombre"], r["unidad"], r["shift"], r["grupo"]) if r else None

    def get_components(self, apu_codigo: str, shift: str) -> list[ApuComponent]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM apus.apu_componentes WHERE apu_codigo=%s AND shift=%s ORDER BY seq",
                (str(apu_codigo), shift)).fetchall()
        return [ApuComponent(
            apu_codigo=r["apu_codigo"], shift=r["shift"], insumo_codigo=r["insumo_codigo"],
            insumo_nombre=r["insumo_nombre"], unidad=r["unidad"],
            rendimiento=r["rendimiento"] or 0.0,
            precio_unitario_hist=r["precio_unitario_hist"] or 0.0) for r in rows]

    def get_depriced_apu(self, codigo: str, shift: str) -> Optional[DePricedApu]:
        apu = self.get_apu(codigo, shift)
        if apu is None:
            return None
        comps = self.get_components(codigo, shift)
        return DePricedApu(
            codigo=apu.codigo, nombre=apu.nombre, unidad=apu.unidad,
            shift=apu.shift, grupo=apu.grupo,
            componentes=tuple(
                DePricedComponent(c.insumo_codigo, c.insumo_nombre, c.unidad, c.rendimiento)
                for c in comps))

    def component_counts(self) -> dict[tuple[str, str], int]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT apu_codigo, shift, COUNT(*) AS n FROM apus.apu_componentes "
                "GROUP BY apu_codigo, shift").fetchall()
        return {(r["apu_codigo"], r["shift"]): r["n"] for r in rows}

    def counts(self) -> dict[str, int]:
        with self.cx.connection() as conn:
            return {t: conn.execute(f"SELECT COUNT(*) AS n FROM apus.{t}").fetchone()["n"]
                    for t in ("apus", "apu_componentes")}

    def get_meta(self) -> dict[str, str]:
        with self.cx.connection() as conn:
            return {r["clave"]: r["valor"]
                    for r in conn.execute("SELECT clave, valor FROM apus.meta").fetchall()}
```

- [ ] **Step 2: Verificar no-regresión**

Run: `python -m pytest tests/ -q`
Expected: 161+ passed (ApusPg aún no se ejercita salvo por el contrato de la Task 6).

- [ ] **Step 3: Commit**

```bash
git add apu_tool/datos/pg/apus_pg.py
git commit -m "feat(datos): ApusPg (backend Postgres de RepositorioApus)"
```

---

### Task 5: `CorridasPg` — implementación Postgres de `RepositorioCorridas`

**Files:**
- Create: `apu_tool/datos/pg/corridas_pg.py`

**Interfaces:**
- Consumes: `Conexion`; DDL `db/pg/corridas.sql`; `datos.repositorio.CorridaEliminada`; `nucleo.models.{CorridaItemRow, CorridaMeta, LicitacionItem}`.
- Produces: `CorridasPg(cx: Conexion)` que cumple `RepositorioCorridas` (mismas firmas que `CorridasDB`).

**Reglas de port:** placeholders `%s`; tablas calificadas `corridas.corrida`, `corridas.corrida_item`; `cur.lastrowid` → `RETURNING id`; el FK viola-> `psycopg.errors.ForeignKeyViolation` (subclase de `IntegrityError`) se traduce a `CorridaEliminada` (como en SQLite con `sqlite3.IntegrityError`). NO hay hack de `ALTER` para `duracion_ms` (la columna ya está en el DDL).

- [ ] **Step 1: Escribir `apu_tool/datos/pg/corridas_pg.py`**

```python
"""Backend Postgres de corridas. Implementa RepositorioCorridas. Port de corridas_db.py."""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Optional

import psycopg

from apu_tool import config
from apu_tool.datos.pg.conexion import Conexion
from apu_tool.datos.repositorio import CorridaEliminada
from apu_tool.nucleo.models import CorridaItemRow, CorridaMeta, LicitacionItem

SCHEMA_PATH = config.PROJECT_ROOT / "db" / "pg" / "corridas.sql"


class CorridasPg:
    def __init__(self, cx: Conexion):
        self.cx = cx

    def init_schema(self) -> None:
        with self.cx.connection() as conn:
            conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))

    def reset(self) -> None:
        with self.cx.connection() as conn:
            conn.execute("DROP SCHEMA IF EXISTS corridas CASCADE")
            conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))

    _INSERT_ITEM_SQL = (
        "INSERT INTO corridas.corrida_item "
        "(corrida_id, seq, item_json, status, apu_codigo, apu_nombre, unidad, "
        " shift, origen, confianza, explicacion, componentes_json, candidatos_json) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)")

    @staticmethod
    def _item_tuple(corrida_id: int, it: CorridaItemRow) -> tuple:
        return (corrida_id, it.seq, json.dumps(asdict(it.item), ensure_ascii=False),
                it.status, it.apu_codigo, it.apu_nombre, it.unidad, it.shift,
                it.origen, it.confianza, it.explicacion,
                json.dumps(it.componentes, ensure_ascii=False),
                json.dumps(it.candidatos, ensure_ascii=False))

    def _insert_corrida(self, conn, meta: CorridaMeta) -> int:
        cur = conn.execute(
            "INSERT INTO corridas.corrida (creada_en, archivo, turno_def, use_ai, estado, "
            "cuadro_path, duracion_ms) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (meta.creada_en, meta.archivo, meta.turno_def,
             None if meta.use_ai is None else int(meta.use_ai),
             meta.estado, meta.cuadro_path, meta.duracion_ms))
        return int(cur.fetchone()["id"])

    def crear_corrida(self, meta: CorridaMeta) -> int:
        with self.cx.connection() as conn:
            return self._insert_corrida(conn, meta)

    def guardar_items(self, corrida_id: int, items: list[CorridaItemRow]) -> int:
        rows = [self._item_tuple(corrida_id, it) for it in items]
        with self.cx.connection() as conn:
            conn.executemany(self._INSERT_ITEM_SQL, rows)
        return len(rows)

    def agregar_item(self, corrida_id: int, fila: CorridaItemRow) -> None:
        try:
            with self.cx.connection() as conn:
                conn.execute(self._INSERT_ITEM_SQL, self._item_tuple(corrida_id, fila))
        except psycopg.errors.ForeignKeyViolation as e:
            raise CorridaEliminada(corrida_id) from e

    def actualizar_eleccion(self, corrida_id: int, seq: int, *, status: str,
                            apu_codigo: Optional[str], apu_nombre: str, unidad: str,
                            shift: str, origen: str, confianza: float,
                            explicacion: str, componentes: list[dict]) -> None:
        with self.cx.connection() as conn:
            conn.execute(
                "UPDATE corridas.corrida_item SET status=%s, apu_codigo=%s, apu_nombre=%s, "
                "unidad=%s, shift=%s, origen=%s, confianza=%s, explicacion=%s, "
                "componentes_json=%s WHERE corrida_id=%s AND seq=%s",
                (status, apu_codigo, apu_nombre, unidad, shift, origen, confianza,
                 explicacion, json.dumps(componentes, ensure_ascii=False),
                 corrida_id, seq))

    def set_cuadro(self, corrida_id: int, path: str) -> None:
        with self.cx.connection() as conn:
            conn.execute("UPDATE corridas.corrida SET cuadro_path=%s WHERE id=%s",
                         (path, corrida_id))

    def set_estado(self, corrida_id: int, estado: str) -> None:
        with self.cx.connection() as conn:
            conn.execute("UPDATE corridas.corrida SET estado=%s WHERE id=%s",
                         (estado, corrida_id))

    def set_duracion(self, corrida_id: int, duracion_ms: int) -> None:
        with self.cx.connection() as conn:
            conn.execute("UPDATE corridas.corrida SET duracion_ms=%s WHERE id=%s",
                         (int(duracion_ms), int(corrida_id)))

    # ---- lectura ----
    def _row_to_item(self, r) -> CorridaItemRow:
        return CorridaItemRow(
            seq=r["seq"], item=LicitacionItem(**json.loads(r["item_json"])),
            status=r["status"], apu_codigo=r["apu_codigo"],
            apu_nombre=r["apu_nombre"] or "", unidad=r["unidad"] or "",
            shift=r["shift"] or "", origen=r["origen"] or "historico",
            confianza=r["confianza"] or 0.0, explicacion=r["explicacion"] or "",
            componentes=json.loads(r["componentes_json"] or "[]"),
            candidatos=json.loads(r["candidatos_json"] or "[]"))

    def _row_to_meta(self, r) -> CorridaMeta:
        return CorridaMeta(
            id=r["id"], creada_en=r["creada_en"], archivo=r["archivo"],
            turno_def=r["turno_def"],
            use_ai=None if r["use_ai"] is None else bool(r["use_ai"]),
            estado=r["estado"], cuadro_path=r["cuadro_path"],
            duracion_ms=r["duracion_ms"])

    def get_corrida(self, corrida_id: int) -> Optional[CorridaMeta]:
        with self.cx.connection() as conn:
            r = conn.execute("SELECT * FROM corridas.corrida WHERE id=%s",
                             (corrida_id,)).fetchone()
        return self._row_to_meta(r) if r else None

    def listar_corridas(self) -> list[CorridaMeta]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM corridas.corrida ORDER BY creada_en DESC, id DESC").fetchall()
        return [self._row_to_meta(r) for r in rows]

    def eliminar_corrida(self, corrida_id: int) -> bool:
        with self.cx.connection() as conn:
            cur = conn.execute("DELETE FROM corridas.corrida WHERE id=%s", (int(corrida_id),))
            return cur.rowcount > 0

    def get_items(self, corrida_id: int) -> list[CorridaItemRow]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM corridas.corrida_item WHERE corrida_id=%s ORDER BY seq",
                (corrida_id,)).fetchall()
        return [self._row_to_item(r) for r in rows]

    def get_item(self, corrida_id: int, seq: int) -> Optional[CorridaItemRow]:
        with self.cx.connection() as conn:
            r = conn.execute(
                "SELECT * FROM corridas.corrida_item WHERE corrida_id=%s AND seq=%s",
                (corrida_id, seq)).fetchone()
        return self._row_to_item(r) if r else None

    def counts(self) -> dict[str, int]:
        with self.cx.connection() as conn:
            return {t: conn.execute(f"SELECT COUNT(*) AS n FROM corridas.{t}").fetchone()["n"]
                    for t in ("corrida", "corrida_item")}
```

- [ ] **Step 2: Verificar no-regresión**

Run: `python -m pytest tests/ -q`
Expected: 161+ passed.

- [ ] **Step 3: Commit**

```bash
git add apu_tool/datos/pg/corridas_pg.py
git commit -m "feat(datos): CorridasPg (backend Postgres de RepositorioCorridas)"
```

---

### Task 6: Selección de backend en `Almacen` + test de contrato parametrizado

**Files:**
- Modify: `apu_tool/datos/almacen.py`
- Modify: `tests/test_repositorios_contrato.py` (hoy trivial; se amplía)

**Interfaces:**
- Consumes: `config.db_backend()`, `config.database_url()` (Task 1); `PreciosPg/ApusPg/CorridasPg` (Tasks 3–5); `Conexion` (Task 1).
- Produces: `Almacen()` que, si `config.db_backend()=="postgres"`, instancia los repos Postgres compartiendo una `Conexion`; si no, los SQLite de siempre. Firma pública sin cambios.

- [ ] **Step 1: Escribir el contrato parametrizado (falla)**

Reemplazar todo el contenido de `tests/test_repositorios_contrato.py` por:

```python
"""Contrato de almacenamiento: la MISMA batería corre contra ambos backends.

SQLite corre siempre (temp files). Postgres solo si hay TEST_DATABASE_URL.
Es el oráculo de no-regresión del port a Postgres (Enfoque A).
"""
import os
import pytest

from apu_tool.nucleo.models import Apu, ApuComponent, Insumo
from apu_tool.datos.repositorio import RepositorioPrecios, RepositorioApus


def _repos_sqlite(tmp_path):
    from apu_tool.datos.precios_db import PreciosDB
    from apu_tool.datos.apus_db import ApusDB
    p = PreciosDB(tmp_path / "precios.db")
    a = ApusDB(tmp_path / "apus.db")
    p.init_schema()
    a.init_schema()
    return p, a, None


def _repos_postgres(tmp_path):
    from apu_tool.datos.pg.conexion import Conexion
    from apu_tool.datos.pg.precios_pg import PreciosPg
    from apu_tool.datos.pg.apus_pg import ApusPg
    cx = Conexion(os.environ["TEST_DATABASE_URL"])
    p, a = PreciosPg(cx), ApusPg(cx)
    p.reset()  # esquema limpio
    a.reset()
    return p, a, cx


_BACKENDS = ["sqlite"]
if os.environ.get("TEST_DATABASE_URL"):
    _BACKENDS.append("postgres")


@pytest.fixture(params=_BACKENDS)
def repos(request, tmp_path):
    if request.param == "sqlite":
        p, a, cx = _repos_sqlite(tmp_path)
    else:
        p, a, cx = _repos_postgres(tmp_path)
    yield p, a
    if cx is not None:
        cx.cerrar()


def test_protocols_existen():
    assert hasattr(RepositorioPrecios, "get_candidatos")
    assert hasattr(RepositorioApus, "get_depriced_apu")


def test_insumo_insert_y_candidato_vigente(repos):
    precios, _ = repos
    assert precios.insert_insumos([
        Insumo("6140", "ACERO 60000 PSI", "KG", "MATERIAL", 3500.0, "PRECIO IDU")]) == 1
    cands = precios.get_candidatos("6140")
    assert len(cands) == 1 and cands[0].precio == 3500.0
    assert cands[0].fuente_precio == "PRECIO IDU"


def test_insumo_identidad_no_duplica(repos):
    precios, _ = repos
    ins = Insumo("6140", "ACERO 60000 PSI", "KG", "MATERIAL", 3500.0, "PRECIO IDU")
    precios.insert_insumos([ins])
    precios.insert_insumos([ins])  # misma identidad (codigo, nombre_norm)
    assert precios.counts()["insumos"] == 1


def test_crear_insumo_duplicado_lanza(repos):
    precios, _ = repos
    ins = Insumo("9", "CEMENTO GRIS", "KG", "MATERIAL", 900.0, "COSTO INTERNO")
    precios.crear_insumo(ins)
    with pytest.raises(ValueError):
        precios.crear_insumo(ins)


def test_set_precio_marca_vigente_y_guarda_historial(repos):
    precios, _ = repos
    iid = precios.crear_insumo(
        Insumo("9", "CEMENTO GRIS", "KG", "MATERIAL", 900.0, "COSTO INTERNO"))
    precios.set_precio_por_id(iid, 1000.0, "COMPRAS 2026")
    assert precios.get_insumo_por_id(iid).precio == 1000.0
    hist = precios.price_history("9")
    assert len(hist) == 2
    assert sum(1 for h in hist if h["vigente"]) == 1


def test_list_insumos_filtra_por_clasificacion(repos):
    precios, _ = repos
    precios.insert_insumos([
        Insumo("1", "ARENA", "M3", "MATERIAL", 10.0, "PRECIO IDU"),
        Insumo("2", "CUADRILLA", "HC", "MANO OBRA", 20.0, "COSTO INTERNO")])
    pub, npub = precios.list_insumos(clasificacion="publico", limit=50, offset=0)
    assert {i.codigo for i in pub} == {"1"}
    intr, _ = precios.list_insumos(clasificacion="interno", limit=50, offset=0)
    assert {i.codigo for i in intr} == {"2"}


def test_apu_crear_get_components_orden_y_depriced(repos):
    _, apus = repos
    comps = [
        ApuComponent("A1", "DIURNO", "1", "ARENA", "M3", 0.5, 10.0),
        ApuComponent("A1", "DIURNO", "2", "CUADRILLA", "HC", 1.2, 20.0)]
    apus.crear_apu(Apu("A1", "EXCAVACION", "M3", "DIURNO", "MOV TIERRAS"), comps)
    got = apus.get_components("A1", "DIURNO")
    assert [c.insumo_codigo for c in got] == ["1", "2"]
    dep = apus.get_depriced_apu("A1", "DIURNO")
    # invariante #1: la vista DePriced no expone dinero
    assert not hasattr(dep.componentes[0], "precio_unitario_hist")
    assert dep.componentes[0].rendimiento == 0.5


def test_apu_crear_duplicado_lanza(repos):
    _, apus = repos
    apus.crear_apu(Apu("A1", "EXCAVACION", "M3", "DIURNO"), [])
    with pytest.raises(ValueError):
        apus.crear_apu(Apu("A1", "OTRA", "M3", "DIURNO"), [])
```

- [ ] **Step 2: Verificar que falla parcialmente**

Run: `python -m pytest tests/test_repositorios_contrato.py -v`
Expected: los tests SQLite pasan; si aún no está el wiring de Almacen no importa (el contrato no usa Almacen). Si algo del contrato SQLite falla, corregir el test (debe reflejar el comportamiento real de los repos SQLite existentes).

- [ ] **Step 3: Wire de backend en `Almacen`**

Reemplazar `apu_tool/datos/almacen.py` por:

```python
"""Fachada de persistencia. Agrupa los tres repositorios y elige backend.

Backend por config: 'sqlite' (local/dev/tests, por defecto) o 'postgres'
(Supabase, cuando hay DATABASE_URL). Los repos Postgres comparten una Conexion.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from apu_tool import config
from apu_tool.datos.apus_db import ApusDB
from apu_tool.datos.corridas_db import CorridasDB
from apu_tool.datos.precios_db import PreciosDB


class Almacen:
    def __init__(self, precios_path: Path | str = config.PRECIOS_DB_PATH,
                 apus_path: Path | str = config.APUS_DB_PATH,
                 corridas_path: Path | str = config.CORRIDAS_DB_PATH):
        self._cx = None
        if config.db_backend() == "postgres":
            from apu_tool.datos.pg.conexion import Conexion
            from apu_tool.datos.pg.precios_pg import PreciosPg
            from apu_tool.datos.pg.apus_pg import ApusPg
            from apu_tool.datos.pg.corridas_pg import CorridasPg
            self._cx = Conexion(config.database_url())
            self.precios = PreciosPg(self._cx)
            self.apus = ApusPg(self._cx)
            self.corridas = CorridasPg(self._cx)
        else:
            self.precios = PreciosDB(precios_path)
            self.apus = ApusDB(apus_path)
            self.corridas = CorridasDB(corridas_path)

    def init_schema(self) -> None:
        self.precios.init_schema()
        self.apus.init_schema()
        self.corridas.init_schema()

    def reset(self) -> None:
        """Reseteo COMPLETO de las tres áreas (uso explícito; borra también corridas)."""
        self.precios.reset()
        self.apus.reset()
        self.corridas.reset()

    def reset_catalogo(self) -> None:
        """Resetea solo el catálogo (precios + apus), preservando las corridas."""
        self.precios.reset()
        self.apus.reset()

    def counts(self) -> dict[str, int]:
        return {**self.precios.counts(), **self.apus.counts(), **self.corridas.counts()}

    def cerrar(self) -> None:
        """Cierra el pool si es backend Postgres (no-op en SQLite)."""
        if self._cx is not None:
            self._cx.cerrar()
```

- [ ] **Step 4: Verificar contrato + no-regresión**

Run: `python -m pytest tests/test_repositorios_contrato.py -v`
Expected: PASS en SQLite (y en Postgres si hay `TEST_DATABASE_URL`).

Run: `python -m pytest tests/ -q`
Expected: 161+ passed (Almacen en SQLite se comporta igual que antes).

- [ ] **Step 5: Commit**

```bash
git add apu_tool/datos/almacen.py tests/test_repositorios_contrato.py
git commit -m "feat(datos): Almacen elige backend por config + contrato parametrizado sqlite/postgres"
```

---

### Task 7: Cierre del pool en el ciclo de vida de la app web

**Files:**
- Modify: `apu_tool/servicio/app.py`
- Test: `tests/test_app_lifespan.py`

**Interfaces:**
- Consumes: `Almacen.cerrar()` (Task 6).
- Produces: la app FastAPI cierra el pool Postgres al apagarse (lifespan). En SQLite es no-op.

- [ ] **Step 1: Escribir el test (falla)**

Create `tests/test_app_lifespan.py`:

```python
from apu_tool.servicio.app import create_app


def test_app_arranca_y_expone_almacen():
    app = create_app()
    assert app.state.almacen is not None
    # el lifespan de cierre no debe reventar con SQLite (cx es None -> no-op)
    app.state.almacen.cerrar()
```

- [ ] **Step 2: Verificar que falla**

Run: `python -m pytest tests/test_app_lifespan.py -v`
Expected: FAIL si `Almacen.cerrar` no existiera; como ya se añadió en Task 6, verificar que PASA aquí y seguir. Si PASA, continuar al Step 3 igual (añadimos el lifespan).

- [ ] **Step 3: Añadir lifespan de cierre a `create_app`**

Modificar `apu_tool/servicio/app.py` — reemplazar la función `create_app` por:

```python
def create_app(almacen: Optional[Almacen] = None) -> FastAPI:
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        app.state.almacen.cerrar()  # cierra el pool Postgres (no-op en SQLite)

    app = FastAPI(title="Armador de APUs", lifespan=lifespan)
    app.state.almacen = almacen or _crear_almacen()
    app.include_router(rutas.router, prefix="/api")
    if WEB_DIST.exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @app.get("/{full_path:path}")
        def spa(full_path: str):
            return FileResponse(WEB_DIST / "index.html")
    return app
```

- [ ] **Step 4: Verificar**

Run: `python -m pytest tests/test_app_lifespan.py tests/ -q`
Expected: 162+ passed.

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/app.py tests/test_app_lifespan.py
git commit -m "feat(web): cerrar el pool Postgres en el lifespan de la app"
```

---

### Task 8: Script de migración de catálogo (SQLite → Postgres) + verificación

**Files:**
- Create: `apu_tool/datos/migracion_pg.py`
- Modify: `apu_tool/interfaz/cli.py` (añadir subcomando `migrate-pg`)
- Test: `tests/test_migracion_pg.py`

**Interfaces:**
- Consumes: SQLite `precios.db`/`apus.db` (lectura directa vía `sqlite3`); `Conexion` (Task 1); DDL `db/pg/*.sql`.
- Produces:
  - `migracion_pg.migrar_catalogo(sqlite_precios: Path, sqlite_apus: Path, cx: Conexion) -> dict` — migra insumos + historial de precios + APUs + componentes + `meta`, preservando ids y linkage. Corridas NO se migran. Devuelve `{"insumos": n, "precios": n, "apus": n, "componentes": n}`.
  - `migracion_pg.verificar(sqlite_precios, sqlite_apus, cx) -> dict` — compara conteos origen vs destino; devuelve `{"ok": bool, "detalle": {...}}`.

**Detalle técnico:** los ids se insertan explícitos con `OVERRIDING SYSTEM VALUE` para preservar el linkage `insumo_precios.insumo_id`; luego se resincroniza la secuencia IDENTITY con `setval(pg_get_serial_sequence(...), MAX(id))`. Las filas de precio migradas llevan `creado_por='migración'`.

- [ ] **Step 1: Escribir el test (falla)**

Create `tests/test_migracion_pg.py`:

```python
import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="sin TEST_DATABASE_URL")


def _sembrar_sqlite(tmp_path):
    from apu_tool.datos.precios_db import PreciosDB
    from apu_tool.datos.apus_db import ApusDB
    from apu_tool.nucleo.models import Apu, ApuComponent, Insumo
    p = PreciosDB(tmp_path / "precios.db"); p.init_schema()
    a = ApusDB(tmp_path / "apus.db"); a.init_schema()
    iid = p.crear_insumo(Insumo("6140", "ACERO", "KG", "MAT", 3500.0, "PRECIO IDU"))
    p.set_precio_por_id(iid, 3700.0, "COMPRAS 2026")  # genera historial (2 filas)
    a.crear_apu(Apu("A1", "EXCAVACION", "M3", "DIURNO", "MT"),
                [ApuComponent("A1", "DIURNO", "6140", "ACERO", "KG", 0.5, 3500.0)])
    return tmp_path / "precios.db", tmp_path / "apus.db"


def test_migracion_traslada_y_verifica(tmp_path):
    from apu_tool.datos.pg.conexion import Conexion
    from apu_tool.datos import migracion_pg
    sp, sa = _sembrar_sqlite(tmp_path)
    cx = Conexion(os.environ["TEST_DATABASE_URL"])
    try:
        with cx.connection() as conn:
            for f in ("precios.sql", "apus.sql", "corridas.sql"):
                from apu_tool import config
                conn.execute("DROP SCHEMA IF EXISTS precios CASCADE")
                conn.execute("DROP SCHEMA IF EXISTS apus CASCADE")
                conn.execute("DROP SCHEMA IF EXISTS corridas CASCADE")
            for f in ("precios.sql", "apus.sql", "corridas.sql"):
                conn.execute((config.PROJECT_ROOT / "db" / "pg" / f).read_text("utf-8"))
        res = migracion_pg.migrar_catalogo(sp, sa, cx)
        assert res["insumos"] == 1
        assert res["precios"] == 2      # historial preservado
        assert res["apus"] == 1
        assert res["componentes"] == 1
        ver = migracion_pg.verificar(sp, sa, cx)
        assert ver["ok"] is True
        # el precio vigente y el linkage se conservan
        from apu_tool.datos.pg.precios_pg import PreciosPg
        cand = PreciosPg(cx).get_candidatos("6140")
        assert cand[0].precio == 3700.0
    finally:
        cx.cerrar()
```

- [ ] **Step 2: Verificar que falla**

Run: `python -m pytest tests/test_migracion_pg.py -v`
Expected: FAIL (no existe `migracion_pg`) o SKIP sin `TEST_DATABASE_URL`.

- [ ] **Step 3: Escribir `apu_tool/datos/migracion_pg.py`**

```python
"""Migración de catálogo SQLite → Postgres (Supabase). Corridas NO se migran.

Lee las SQLite locales directo y escribe en Postgres preservando ids y el
linkage insumo_precios.insumo_id. Idempotente sobre esquema limpio.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from apu_tool.datos.pg.conexion import Conexion


def _sqlite(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _resync_identity(conn, tabla: str, col: str = "id") -> None:
    conn.execute(
        f"SELECT setval(pg_get_serial_sequence('{tabla}', '{col}'), "
        f"COALESCE((SELECT MAX({col}) FROM {tabla}), 1))")


def migrar_catalogo(sqlite_precios: Path, sqlite_apus: Path, cx: Conexion) -> dict:
    sp = _sqlite(sqlite_precios)
    sa = _sqlite(sqlite_apus)
    n = {"insumos": 0, "precios": 0, "apus": 0, "componentes": 0}
    try:
        with cx.connection() as conn:
            # insumos (id explícito para preservar linkage)
            for r in sp.execute("SELECT id, codigo, nombre, nombre_norm, unidad, grupo "
                                "FROM insumos").fetchall():
                conn.execute(
                    "INSERT INTO precios.insumos (id, codigo, nombre, nombre_norm, unidad, grupo) "
                    "OVERRIDING SYSTEM VALUE VALUES (%s,%s,%s,%s,%s,%s)",
                    (r["id"], r["codigo"], r["nombre"], r["nombre_norm"], r["unidad"], r["grupo"]))
                n["insumos"] += 1
            # historial de precios (con creado_por='migración')
            for r in sp.execute("SELECT id, insumo_id, precio, fuente, clasificacion, fecha, "
                                "vigente FROM insumo_precios").fetchall():
                conn.execute(
                    "INSERT INTO precios.insumo_precios "
                    "(id, insumo_id, precio, fuente, clasificacion, fecha, vigente, creado_por) "
                    "OVERRIDING SYSTEM VALUE VALUES (%s,%s,%s,%s,%s,%s,%s,'migración')",
                    (r["id"], r["insumo_id"], r["precio"], r["fuente"],
                     r["clasificacion"], r["fecha"], r["vigente"]))
                n["precios"] += 1
            _resync_identity(conn, "precios.insumos")
            _resync_identity(conn, "precios.insumo_precios")
            # meta de precios
            for r in sp.execute("SELECT clave, valor FROM meta").fetchall():
                conn.execute("INSERT INTO precios.meta (clave, valor) VALUES (%s,%s) "
                             "ON CONFLICT (clave) DO UPDATE SET valor=EXCLUDED.valor",
                             (r["clave"], r["valor"]))
            # apus
            for r in sa.execute("SELECT codigo, shift, nombre, unidad, grupo FROM apus").fetchall():
                conn.execute("INSERT INTO apus.apus (codigo, shift, nombre, unidad, grupo) "
                             "VALUES (%s,%s,%s,%s,%s)",
                             (r["codigo"], r["shift"], r["nombre"], r["unidad"], r["grupo"]))
                n["apus"] += 1
            # componentes
            for r in sa.execute("SELECT apu_codigo, shift, seq, insumo_codigo, insumo_nombre, "
                                "unidad, rendimiento, precio_unitario_hist "
                                "FROM apu_componentes").fetchall():
                conn.execute(
                    "INSERT INTO apus.apu_componentes (apu_codigo, shift, seq, insumo_codigo, "
                    "insumo_nombre, unidad, rendimiento, precio_unitario_hist) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (r["apu_codigo"], r["shift"], r["seq"], r["insumo_codigo"],
                     r["insumo_nombre"], r["unidad"], r["rendimiento"], r["precio_unitario_hist"]))
                n["componentes"] += 1
            # meta de apus
            for r in sa.execute("SELECT clave, valor FROM meta").fetchall():
                conn.execute("INSERT INTO apus.meta (clave, valor) VALUES (%s,%s) "
                             "ON CONFLICT (clave) DO UPDATE SET valor=EXCLUDED.valor",
                             (r["clave"], r["valor"]))
    finally:
        sp.close()
        sa.close()
    return n


def verificar(sqlite_precios: Path, sqlite_apus: Path, cx: Conexion) -> dict:
    sp = _sqlite(sqlite_precios)
    sa = _sqlite(sqlite_apus)
    try:
        origen = {
            "insumos": sp.execute("SELECT COUNT(*) FROM insumos").fetchone()[0],
            "insumo_precios": sp.execute("SELECT COUNT(*) FROM insumo_precios").fetchone()[0],
            "apus": sa.execute("SELECT COUNT(*) FROM apus").fetchone()[0],
            "apu_componentes": sa.execute("SELECT COUNT(*) FROM apu_componentes").fetchone()[0],
        }
    finally:
        sp.close()
        sa.close()
    with cx.connection() as conn:
        destino = {
            "insumos": conn.execute("SELECT COUNT(*) AS n FROM precios.insumos").fetchone()["n"],
            "insumo_precios": conn.execute(
                "SELECT COUNT(*) AS n FROM precios.insumo_precios").fetchone()["n"],
            "apus": conn.execute("SELECT COUNT(*) AS n FROM apus.apus").fetchone()["n"],
            "apu_componentes": conn.execute(
                "SELECT COUNT(*) AS n FROM apus.apu_componentes").fetchone()["n"],
        }
    return {"ok": origen == destino, "detalle": {"origen": origen, "destino": destino}}
```

- [ ] **Step 4: Añadir el subcomando CLI `migrate-pg`**

En `apu_tool/interfaz/cli.py`, localizar el dispatcher de subcomandos (donde se manejan `seed`, `build`, `status`, `db`) y añadir un subcomando `migrate-pg` que:

```python
# dentro del parser de subcomandos (imitando el estilo de los existentes):
def _cmd_migrate_pg(args) -> int:
    from apu_tool import config
    from apu_tool.datos.pg.conexion import Conexion
    from apu_tool.datos import migracion_pg
    dsn = config.database_url()
    if not dsn:
        print("Falta DATABASE_URL (destino Postgres/Supabase).")
        return 2
    cx = Conexion(dsn)
    try:
        # aplicar esquema destino
        with cx.connection() as conn:
            for f in ("precios.sql", "apus.sql", "corridas.sql"):
                conn.execute((config.PROJECT_ROOT / "db" / "pg" / f).read_text("utf-8"))
        n = migracion_pg.migrar_catalogo(config.PRECIOS_DB_PATH, config.APUS_DB_PATH, cx)
        ver = migracion_pg.verificar(config.PRECIOS_DB_PATH, config.APUS_DB_PATH, cx)
        print(f"Migrado: {n}")
        print(f"Verificación: {'OK' if ver['ok'] else 'DISCREPANCIA'} -> {ver['detalle']}")
        return 0 if ver["ok"] else 1
    finally:
        cx.cerrar()
```

Registrar el subparser `migrate-pg` con `set_defaults(func=_cmd_migrate_pg)` siguiendo el mismo patrón que los subcomandos existentes en el archivo (revisar cómo se añade `status` o `seed` y replicar exactamente ese estilo).

- [ ] **Step 5: Verificar**

Run: `python -m pytest tests/test_migracion_pg.py -q`
Expected: PASS con `TEST_DATABASE_URL`; SKIP sin él.

Run: `python -m pytest tests/ -q`
Expected: todos verdes.

Run (humo del CLI, sin BD): `python run_cli.py migrate-pg`
Expected: imprime "Falta DATABASE_URL…" y sale con código 2 (no revienta).

- [ ] **Step 6: Commit**

```bash
git add apu_tool/datos/migracion_pg.py apu_tool/interfaz/cli.py tests/test_migracion_pg.py
git commit -m "feat(datos): migración de catálogo SQLite→Postgres + subcomando migrate-pg"
```

---

## Notas de ejecución

- **Para correr los tests contra Postgres real** (recomendado antes de dar el plan por cerrado): exportar `TEST_DATABASE_URL` apuntando a una BD Supabase de prueba (o un Postgres local/Docker), y correr `python -m pytest tests/ -q`. Sin esa variable, todos los tests Postgres se **omiten** (SKIP) y los 161 originales siguen verdes — el trabajo no bloquea el desarrollo local.
- **Aplicar migraciones en Supabase**: usar el MCP/CLI de Supabase con `supabase/migrations/0001_esquema_inicial.sql` (apoyarse en la skill `supabase:supabase` en ejecución).
- **Este plan NO expone Postgres a la app en producción por sí solo** hasta que se configure `DATABASE_URL` en el entorno del PaaS (eso ocurre en el Plan 4 — despliegue). En local, sin `DATABASE_URL`, todo sigue en SQLite.

## Self-Review

**Cobertura del spec (secciones 2, 4, 8 del design):**
- Repos Postgres que implementan los Protocol → Tasks 3, 4, 5. ✅
- Switch de backend por config; SQLite conservado → Tasks 1, 6. ✅
- Una base, tres schemas; pool único; pooler transacción (`prepare_threshold=None`) → Tasks 1, 2. ✅
- Traducción de dialecto (ON CONFLICT, RETURNING, IDENTITY, %s) → Tasks 2–5. ✅
- FK `insumo_precios→insumos` con `ON DELETE CASCADE` → Task 2. ✅
- Esquema como migraciones Supabase → Task 2. ✅
- Contract tests parametrizados sobre ambos backends → Task 6. ✅
- Migración de catálogo (historial de precios; corridas NO) + verificación → Task 8. ✅
- Cierre de recursos (pool) en la app → Task 7. ✅
- Invariante #1 intacta (no se toca dominio; test lo verifica en Task 6) → ✅

**Placeholder scan:** sin TODO/TBD; todo paso con código tiene código completo. La única indirección es en Task 8 Step 4 (registrar el subparser "siguiendo el patrón existente"), inevitable sin ver el dispatcher de `cli.py`; el cuerpo del comando sí está completo.

**Type consistency:** `Conexion.connection()`/`transaccion()`/`cerrar()` usados igual en repos, Almacen y tests. `PreciosPg/ApusPg/CorridasPg(cx)` firma consistente. `migrar_catalogo`/`verificar` firmas usadas igual en test y CLI. Repos devuelven los mismos tipos de dominio que los SQLite (verificado contra `precios_db.py`/`apus_db.py`/`corridas_db.py`).

**Riesgo abierto conocido:** `cli.py` no fue leído en detalle; Task 8 Step 4 pide replicar el patrón de subcomando existente. Es el único punto que el implementador debe adaptar leyendo el archivo.
