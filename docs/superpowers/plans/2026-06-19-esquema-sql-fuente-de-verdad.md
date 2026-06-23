# Esquema SQL como fuente de verdad — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mover el DDL del esquema (hoy embebido como string en `apu_tool/db.py`) a un archivo `db/schema.sql` versionado y canónico, añadiendo integridad referencial (FOREIGN KEYs + PK) sin cambiar el modelo de datos.

**Architecture:** `db/schema.sql` se vuelve la única definición del esquema. `apu_tool/db.py` lo lee desde `config.PROJECT_ROOT / "db" / "schema.sql"` en `init_schema()` y `reset()`. Se añaden FKs seguras (precios→insumos, componentes→apus) y PK en `apu_componentes`; `apu_componentes.insumo_codigo` queda como enlace blando (sin FK). `reset()` borra en orden hijos→padres para respetar las FKs.

**Tech Stack:** Python 3, `sqlite3` (stdlib), `pytest`.

## Global Constraints

- **Invariante #1 (NO romper):** la IA nunca ve dinero. Este trabajo no toca la frontera de privacidad (`privacy.py`) ni añade campos monetarios a vistas `DePriced*`.
- **Persistencia aislada en `db.py`:** no meter SQL crudo en otros módulos. El esquema vive en `db/schema.sql`; las rutas se resuelven vía `config.PROJECT_ROOT`.
- **SQL portable:** el `.sql` corre en SQLite hoy, estructurado para migrar a Postgres; las diferencias de dialecto se anotan en comentarios.
- **Contrato `repository.py` intacto:** firmas de `init_schema()` y `reset()` sin cambios.
- **Sin git:** el proyecto NO es repositorio git. Donde un plan normal diría "Commit", aquí el checkpoint de cada tarea es **correr la suite completa** (`python -m pytest tests/ -q`) y verla pasar.
- **Español** en nombres de dominio, comentarios y mensajes.

---

## File Structure

- **Crear:** `db/schema.sql` — DDL canónico, portable, comentado. Única definición del esquema.
- **Modificar:** `apu_tool/db.py` — eliminar la constante `SCHEMA`; leer el `.sql`; reordenar los `DELETE` de `reset()`; añadir FKs/PK (vía el `.sql`).
- **Crear:** `tests/test_schema_sql.py` — pruebas de carga desde archivo e integridad referencial.

---

### Task 1: Mover el esquema a `db/schema.sql` (copia fiel + carga desde archivo)

Deliverable: el esquema vive en `db/schema.sql` (contenido idéntico al actual, sin FKs todavía), `db.py` lo lee del archivo, la constante `SCHEMA` desaparece, y los 20 tests existentes siguen pasando.

**Files:**
- Create: `db/schema.sql`
- Modify: `apu_tool/db.py:34-80` (constante `SCHEMA`), `apu_tool/db.py:102-111` (`init_schema`/`reset`)
- Test: `tests/test_schema_sql.py`

**Interfaces:**
- Consumes: `apu_tool.config.PROJECT_ROOT` (Path a la raíz del proyecto).
- Produces:
  - `apu_tool.db.SCHEMA_PATH: Path` — ruta a `db/schema.sql`.
  - `apu_tool.db._load_schema() -> str` — devuelve el contenido del `.sql`.
  - `Database.init_schema()` y `Database.reset()` mantienen su firma `() -> None`.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_schema_sql.py`:

```python
"""Pruebas del esquema SQL como fuente de verdad (archivo db/schema.sql)."""
import pytest

from apu_tool import config, db as db_module
from apu_tool.db import Database

TABLAS = {"insumos", "insumo_precios", "apus", "apu_componentes", "meta"}


def test_schema_file_is_source_of_truth(tmp_path):
    # El esquema vive en db/schema.sql y ya no como constante en db.py.
    schema_path = config.PROJECT_ROOT / "db" / "schema.sql"
    assert schema_path.exists(), "db/schema.sql debe existir"
    assert not hasattr(db_module, "SCHEMA"), "la constante SCHEMA debe desaparecer"

    d = Database(tmp_path / "t.db")
    d.init_schema()
    with d.connect() as conn:
        tablas = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert TABLAS <= tablas
```

- [ ] **Step 2: Correr el test para verlo fallar**

Run: `python -m pytest tests/test_schema_sql.py::test_schema_file_is_source_of_truth -v`
Expected: FAIL — `db/schema.sql` no existe (AssertionError "db/schema.sql debe existir").

- [ ] **Step 3: Crear `db/schema.sql` con el contenido actual (copia fiel)**

Crear `db/schema.sql` con exactamente el DDL de hoy (sin FKs aún; eso es la Task 2):

```sql
-- Esquema canónico del Armador de APUs.
-- Fuente de verdad del modelo de datos. SQL portable (SQLite hoy; Postgres luego).
-- Cargado por apu_tool/db.py en init_schema()/reset().

CREATE TABLE IF NOT EXISTS insumos (
    codigo TEXT PRIMARY KEY,
    nombre TEXT NOT NULL,
    unidad TEXT,
    grupo  TEXT
);

CREATE TABLE IF NOT EXISTS insumo_precios (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo        TEXT NOT NULL,
    precio        REAL NOT NULL,
    fuente        TEXT,
    clasificacion TEXT,          -- 'publico' | 'interno'
    fecha         TEXT,          -- ISO (YYYY-MM-DD)
    vigente       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS apus (
    codigo TEXT NOT NULL,
    shift  TEXT NOT NULL,
    nombre TEXT NOT NULL,
    unidad TEXT,
    grupo  TEXT,
    PRIMARY KEY (codigo, shift)
);

CREATE TABLE IF NOT EXISTS apu_componentes (
    apu_codigo            TEXT NOT NULL,
    shift                 TEXT NOT NULL,
    seq                   INTEGER NOT NULL,
    insumo_codigo         TEXT,
    insumo_nombre         TEXT,
    unidad                TEXT,
    rendimiento           REAL,
    precio_unitario_hist  REAL
);

CREATE TABLE IF NOT EXISTS meta (
    clave TEXT PRIMARY KEY,
    valor TEXT
);

CREATE INDEX IF NOT EXISTS idx_comp_apu     ON apu_componentes(apu_codigo, shift);
CREATE INDEX IF NOT EXISTS idx_apus_nombre  ON apus(nombre);
CREATE INDEX IF NOT EXISTS idx_precio_cod   ON insumo_precios(codigo, vigente);
```

- [ ] **Step 4: Modificar `apu_tool/db.py` para leer el archivo**

Eliminar el bloque de la constante `SCHEMA` (líneas 34-80) y reemplazarlo por la carga desde archivo. Justo después de los imports y antes de `class Database`:

```python
SCHEMA_PATH = config.PROJECT_ROOT / "db" / "schema.sql"


def _load_schema() -> str:
    """Lee el DDL canónico desde db/schema.sql (la fuente de verdad)."""
    return SCHEMA_PATH.read_text(encoding="utf-8")
```

Actualizar `init_schema` y `reset` para usar `_load_schema()` (el orden de `DELETE` se reordena en la Task 2; aquí solo se cambia la fuente del DDL):

```python
    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(_load_schema())

    def reset(self) -> None:
        """Vacía las tablas (para reingestar). No borra el archivo."""
        with self.connect() as conn:
            conn.executescript(_load_schema())
            for t in ("insumos", "insumo_precios", "apus", "apu_componentes", "meta"):
                conn.execute(f"DELETE FROM {t}")
```

Verificar que `config` ya está importado en `db.py` (lo está: `from . import config`).

- [ ] **Step 5: Correr el test nuevo y verlo pasar**

Run: `python -m pytest tests/test_schema_sql.py -v`
Expected: PASS.

- [ ] **Step 6: Checkpoint — correr la suite completa**

Run: `python -m pytest tests/ -q`
Expected: todos los tests pasan (los 20 previos + el nuevo). Sin commit (proyecto no-git).

---

### Task 2: Integridad referencial (FKs + PK) y orden de borrado en `reset()`

Deliverable: `db/schema.sql` declara FKs reales (precios→insumos, componentes→apus) y PK en `apu_componentes`; `apu_componentes.insumo_codigo` queda como enlace blando (sin FK); `reset()` borra hijos→padres. La base rechaza datos inconsistentes pero la ingesta (que cita insumos huérfanos) sigue funcionando.

**Files:**
- Modify: `db/schema.sql` (añadir FKs y PK)
- Modify: `apu_tool/db.py` (`reset()` — orden de `DELETE`; `insert_components()` — `seq` continúa desde el máximo)
- Test: `tests/test_schema_sql.py` (añadir casos)

**Interfaces:**
- Consumes: `apu_tool.db.Database`, `Database.connect()` (context manager que activa `PRAGMA foreign_keys = ON`), modelos `Insumo`, `Apu`, `ApuComponent`.
- Produces: ningún símbolo nuevo; cambia el comportamiento de integridad del esquema. `insert_components()` mantiene su firma `(Iterable[ApuComponent]) -> int`.

**Regresión a evitar (importante):** la nueva PK `(apu_codigo, shift, seq)` colisiona si `insert_components` se llama más de una vez para el mismo `(apu, shift)`, porque hoy reinicia `seq` en 0 en cada llamada. El test existente `tests/test_pricing_ingest.py::test_pricing_falls_back_to_historical` hace justo eso. Por eso el Step 4 hace que `seq` continúe desde el máximo ya almacenado.

- [ ] **Step 1: Escribir los tests que fallan**

Añadir a `tests/test_schema_sql.py`:

```python
import sqlite3

from apu_tool.models import Apu, ApuComponent, Insumo


def _seed(d):
    d.reset()
    d.insert_insumos([Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU")])
    d.insert_apus([Apu("A1", "MURO", "M2", "DIURNO")])
    d.insert_components([ApuComponent("A1", "DIURNO", "100", "CEMENTO", "KG", 3.0, 900)])
    return d


def test_precio_requiere_insumo_existente(tmp_path):
    d = Database(tmp_path / "t.db"); d.reset()
    with pytest.raises(sqlite3.IntegrityError):
        with d.connect() as conn:
            conn.execute(
                "INSERT INTO insumo_precios (codigo, precio, vigente) "
                "VALUES ('NOEXISTE', 100, 1)")


def test_componente_requiere_apu_existente(tmp_path):
    d = Database(tmp_path / "t.db"); d.reset()
    with pytest.raises(sqlite3.IntegrityError):
        with d.connect() as conn:
            conn.execute(
                "INSERT INTO apu_componentes (apu_codigo, shift, seq) "
                "VALUES ('NOEXISTE', 'DIURNO', 0)")


def test_componente_pk_rechaza_duplicado(tmp_path):
    d = _seed(Database(tmp_path / "t.db"))
    with pytest.raises(sqlite3.IntegrityError):
        with d.connect() as conn:
            conn.execute(
                "INSERT INTO apu_componentes (apu_codigo, shift, seq) "
                "VALUES ('A1', 'DIURNO', 0)")  # seq 0 ya existe


def test_componente_admite_insumo_codigo_desconocido(tmp_path):
    # Enlace blando (opción A): un componente puede citar un insumo huérfano.
    d = _seed(Database(tmp_path / "t.db"))
    d.insert_components([ApuComponent("A1", "DIURNO", "GRA-99", "GRAVA", "M3", 1.0, 50)])
    comps = d.get_components("A1", "DIURNO")
    assert any(c.insumo_codigo == "GRA-99" for c in comps)


def test_reset_con_datos_no_viola_fk(tmp_path):
    d = _seed(Database(tmp_path / "t.db"))
    d.reset()  # con FKs activas, borrar padres antes que hijos fallaría
    assert d.counts() == {"insumos": 0, "insumo_precios": 0,
                          "apus": 0, "apu_componentes": 0}
```

- [ ] **Step 2: Correr los tests nuevos para verlos fallar**

Run: `python -m pytest tests/test_schema_sql.py -v -k "precio_requiere or componente_requiere or pk_rechaza or reset_con_datos"`
Expected: FAIL — sin FKs/PK no se lanza `IntegrityError`; y `reset()` con orden actual puede fallar al borrar `insumos` antes que `insumo_precios`.

- [ ] **Step 3: Añadir FKs y PK en `db/schema.sql`**

Reemplazar las definiciones de `insumo_precios` y `apu_componentes` en `db/schema.sql` por estas versiones con integridad (las demás tablas no cambian):

```sql
CREATE TABLE IF NOT EXISTS insumo_precios (
    -- Postgres: id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo        TEXT NOT NULL,
    precio        REAL NOT NULL,
    fuente        TEXT,
    clasificacion TEXT,          -- 'publico' | 'interno'
    fecha         TEXT,          -- ISO (YYYY-MM-DD)
    vigente       INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (codigo) REFERENCES insumos(codigo)
);

CREATE TABLE IF NOT EXISTS apu_componentes (
    apu_codigo            TEXT NOT NULL,
    shift                 TEXT NOT NULL,
    seq                   INTEGER NOT NULL,
    insumo_codigo         TEXT,   -- enlace BLANDO: puede citar un insumo no listado
    insumo_nombre         TEXT,   -- nombre desnormalizado (no se pierde si falta el código)
    unidad                TEXT,
    rendimiento           REAL,
    precio_unitario_hist  REAL,
    PRIMARY KEY (apu_codigo, shift, seq),
    FOREIGN KEY (apu_codigo, shift) REFERENCES apus(codigo, shift)
);
```

Nota: NO se añade FK sobre `insumo_codigo` (decisión "opción A" del spec).

- [ ] **Step 4: Reordenar `reset()` y hacer que `insert_components` continúe el `seq`**

En `apu_tool/db.py`, borrar hijos antes que padres en `reset()` para no violar las FKs:

```python
    def reset(self) -> None:
        """Vacía las tablas (para reingestar). No borra el archivo.
        Orden hijos->padres para respetar las FKs activas."""
        with self.connect() as conn:
            conn.executescript(_load_schema())
            for t in ("apu_componentes", "insumo_precios", "apus", "insumos", "meta"):
                conn.execute(f"DELETE FROM {t}")
```

Y reemplazar `insert_components` (líneas 159-174) para que `seq` continúe desde el máximo ya almacenado por `(apu_codigo, shift)`, evitando colisiones de PK entre llamadas:

```python
    def insert_components(self, comps: Iterable[ApuComponent]) -> int:
        comps = list(comps)
        with self.connect() as conn:
            # seq continúa desde el máximo existente por (apu, shift): así varias
            # llamadas para el mismo APU no colisionan con la PK (apu_codigo, shift, seq).
            seq_by_key: dict[tuple[str, str], int] = {}
            rows = []
            for c in comps:
                key = (c.apu_codigo, c.shift)
                if key not in seq_by_key:
                    r = conn.execute(
                        "SELECT COALESCE(MAX(seq) + 1, 0) FROM apu_componentes "
                        "WHERE apu_codigo=? AND shift=?", key).fetchone()
                    seq_by_key[key] = r[0]
                seq = seq_by_key[key]
                seq_by_key[key] = seq + 1
                rows.append((c.apu_codigo, c.shift, seq, c.insumo_codigo,
                             c.insumo_nombre, c.unidad, c.rendimiento,
                             c.precio_unitario_hist))
            conn.executemany(
                "INSERT INTO apu_componentes "
                "(apu_codigo, shift, seq, insumo_codigo, insumo_nombre, unidad, "
                " rendimiento, precio_unitario_hist) VALUES (?,?,?,?,?,?,?,?)", rows)
        return len(rows)
```

- [ ] **Step 5: Correr los tests nuevos y verlos pasar**

Run: `python -m pytest tests/test_schema_sql.py -v`
Expected: PASS (todos, incluidos los de la Task 1).

- [ ] **Step 6: Checkpoint — suite completa + reconstrucción real**

Run: `python -m pytest tests/ -q`
Expected: todos los tests pasan.

Run: `python run_cli.py db rebuild`
Expected: reconstruye `data/apu.db` desde el Excel sin error (la ingesta inserta insumos→apus→componentes en orden FK-seguro, y los `insumo_codigo` huérfanos se aceptan por el enlace blando).

Run: `python run_cli.py status`
Expected: reporta conteos coherentes (mismos que antes del cambio).

---

## Self-Review

**Spec coverage:**
- Esquema en `db/schema.sql` como fuente de verdad → Task 1.
- `db.py` lee el archivo, sin constante `SCHEMA` → Task 1 (Steps 3-4, test lo verifica).
- SQL portable + comentarios de dialecto → Task 1 (encabezado) + Task 2 (comentario Postgres en `id`).
- FK precios→insumos y componentes→apus → Task 2.
- PK en `apu_componentes` → Task 2.
- `insumo_codigo` enlace blando (opción A) → Task 2 (Step 3 nota + test `admite_insumo_codigo_desconocido`).
- `reset()` orden hijos→padres → Task 2 (Step 4 + test `reset_con_datos`).
- `insert_components` robusto a la nueva PK (regresión) → Task 2 (Step 4; lo cubre el test existente `test_pricing_falls_back_to_historical`).
- Contrato `repository.py` intacto → firmas sin cambios (Task 1 Step 4).
- Verificación pytest + rebuild + status → Task 2 Step 6.

**Placeholder scan:** sin TBD/TODO; todo el código y los comandos están completos.

**Type consistency:** `SCHEMA_PATH`/`_load_schema()` definidos en Task 1 y usados consistentemente; `init_schema`/`reset` mantienen firma `() -> None`; nombres de tablas idénticos en esquema, `reset()` y tests.
