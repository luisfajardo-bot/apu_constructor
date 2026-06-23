# Dos bases separadas, fuente de verdad — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganizar el proyecto a la estructura por capas y partir el almacenamiento en dos bases SQLite canónicas (`precios.db`, `apus.db`) que pasan a ser la fuente de verdad, semilladas una vez desde el Excel, con la corrección del código 4613 persistida y un chequeo de integridad.

**Architecture:** Enfoque A (dos repositorios + fachada `Almacen`). Primero una reorganización mecánica a `datos/ · dominio/ · servicio/ · interfaz/` sin cambiar lógica; luego se parte `db.py` en `PreciosDB`/`ApusDB`, se crea la fachada, y los consumidores pasan de `Database` a `Almacen`. El Excel se importa con un `seed` guardado.

**Tech Stack:** Python 3, `sqlite3` (stdlib), `openpyxl`, `pytest`.

## Global Constraints

- **Invariante #1 (NO romper):** la IA nunca ve dinero. No se tocan la frontera de `privacy.py` ni las vistas `DePriced*`.
- **Capas como fronteras:** `datos/` NO importa de `dominio/`, `servicio/` ni `interfaz/`. El `dominio/` no importa de `servicio/` ni `interfaz/`. Esto se vigila en el código.
- **Fuente de verdad = las bases.** El Excel es semilla de una sola vez; el `seed` es **guardado** (se niega a sobrescribir datos mantenidos salvo `--force`).
- **Precio contractual / costo nunca van a la IA.** Solo `pricing` toca dinero.
- **SQL portable** (SQLite hoy, Postgres después): DDL en `db/*.sql` con comentarios de dialecto.
- **Sin git:** el proyecto NO es repositorio git. Donde un plan normal diría "Commit", el checkpoint de cada tarea es **correr la suite completa** (`python -m pytest tests/ -q`) y verla pasar.
- **Español** en identificadores de dominio, comentarios y mensajes de usuario (los nombres de archivo se conservan en su forma actual).
- Entorno Windows; tests con `python -m pytest tests/ -q`.

---

## File Structure (objetivo tras el plan)

```
apu_tool/
  config.py
  nucleo/     models.py          # kernel compartido (dataclasses puras): datos y dominio lo importan
  datos/      repositorio.py  precios_db.py  apus_db.py  almacen.py
              seed.py  correcciones.py  integridad.py
  dominio/    licitacion.py presupuesto.py matching.py privacy.py
              ai_assist.py compose.py assemble.py pricing.py report.py
              report_categorizado.py pipeline.py
  servicio/   (vacío)
  interfaz/   cli.py  gui.py
db/           precios.sql  apus.sql
data/         precios.db  apus.db
```

> **Nota (decisión post-Task 1):** los modelos (`Insumo`, `Apu`, `ApuComponent`, `DePriced*`)
> son un **núcleo compartido** en `apu_tool/nucleo/models.py` — los importan tanto `datos`
> como `dominio`. La regla de capas se entiende así: `datos/` no importa **lógica** de
> `dominio/` (matching, pricing…), pero ambos pueden importar `nucleo/`. El movimiento de
> `dominio/models.py` → `nucleo/models.py` se hace como cierre de la Task 1.

---

### Task 1: Reorganización a la estructura por capas (mecánica, sin cambio de lógica)

Deliverable: todos los módulos viven en `datos/ · dominio/ · servicio/ · interfaz/`, los imports y lanzadores quedan arreglados, y la suite (44) sigue verde. Cero cambios de comportamiento. En esta tarea `db.py`, `repository.py` e `ingest.py` SOLO se mueven a `datos/` con su nombre actual (se parten/renombran en tareas posteriores).

**Files:**
- Crear: `apu_tool/datos/__init__.py`, `apu_tool/dominio/__init__.py`, `apu_tool/servicio/__init__.py`, `apu_tool/interfaz/__init__.py`
- Mover (sin cambiar lógica):
  - → `datos/`: `db.py`, `repository.py`, `ingest.py`
  - → `dominio/`: `models.py`, `licitacion.py`, `presupuesto.py`, `matching.py`, `privacy.py`, `ai_assist.py`, `compose.py`, `assemble.py`, `pricing.py`, `report.py`, `report_categorizado.py`, `pipeline.py`
  - → `interfaz/`: `cli.py`, `gui.py`
- Modificar: imports internos de todos los módulos; `run_cli.py`, `run_gui.py`; imports de `tests/`.

**Interfaces:**
- Convención de imports: **absolutos** desde la raíz del paquete, p. ej. `from apu_tool.nucleo.models import Insumo`, `from apu_tool.datos.db import Database`, `from apu_tool import config`. (Reemplazan a los relativos `from .x`.) Esto evita contar puntos al mover.
- `run_cli.py` → `from apu_tool.interfaz.cli import main`; `run_gui.py` → `from apu_tool.interfaz.gui import main`.

- [ ] **Step 1: Crear los paquetes de capa**

Crear los cuatro `__init__.py` vacíos: `apu_tool/datos/__init__.py`, `apu_tool/dominio/__init__.py`, `apu_tool/servicio/__init__.py`, `apu_tool/interfaz/__init__.py`.

- [ ] **Step 2: Mover los archivos a sus carpetas**

Mover cada archivo a la carpeta indicada en **Files** (mantener nombres). Tras mover, `apu_tool/` solo debe contener `__init__.py`, `config.py` y las cuatro carpetas.

- [ ] **Step 3: Reescribir los imports internos a absolutos**

En cada módulo movido, cambiar los imports relativos por absolutos según la capa destino. Mapa de módulo → ruta nueva (usar para reescribir cada `from .X`):

| módulo | import nuevo |
|--------|--------------|
| config | `from apu_tool import config` |
| models, licitacion, presupuesto, matching, privacy, ai_assist, compose, assemble, pricing, report, report_categorizado, pipeline | `from apu_tool.dominio.<mod> import …` |
| db, repository, ingest | `from apu_tool.datos.<mod> import …` |
| cli, gui | `from apu_tool.interfaz.<mod> import …` |

Ejemplos concretos de los cambios (no exhaustivo; aplicar el mapa a todos):
- `dominio/assemble.py`: `from apu_tool.dominio.ai_assist import ApuAdvisor, ComposeResult`; `from apu_tool.dominio.compose import InsumoRetriever`; `from apu_tool.datos.db import Database`; `from apu_tool.dominio.matching import Matcher`; `from apu_tool.nucleo.models import (...)`; `from apu_tool.dominio.pricing import PricingEngine`.
- `dominio/pipeline.py`: `from apu_tool import config`; `from apu_tool.dominio.ai_assist import ApuAdvisor`; `from apu_tool.dominio.assemble import Assembler`; `from apu_tool.datos.db import Database`; `from apu_tool.datos.ingest import IngestReport, ingest`; `from apu_tool.dominio.licitacion import read_licitacion, write_sample_licitacion`; `from apu_tool.nucleo.models import AssembledApu, LicitacionItem`; `from apu_tool.dominio.presupuesto import read_presupuesto`; `from apu_tool.dominio.pricing import PricingEngine`; `from apu_tool.dominio.report import write_report`; `from apu_tool.dominio.report_categorizado import write_report_categorizado`.
- `datos/db.py`: `from apu_tool import config`; `from apu_tool.nucleo.models import (...)`.
- `datos/ingest.py`: `from apu_tool import config`; `from apu_tool.datos.db import Database`; `from apu_tool.nucleo.models import Apu, ApuComponent, Insumo`.
- `interfaz/cli.py`: `from apu_tool import config`; `from apu_tool.nucleo.models import MatchStatus`; `from apu_tool.dominio.pipeline import (...)`.
- `interfaz/gui.py`: idem con `apu_tool.dominio.*`, `apu_tool.datos.ingest`.
- `datos/db.py` (búsqueda por tokens): la línea `from .matching import _tokens` (dentro de `search_insumos_by_tokens`) queda **temporalmente** como `from apu_tool.dominio.matching import _tokens`. (Se elimina en la Task 4, que rompe esa dependencia datos→dominio.)

Nota: `datos/repository.py` solo importa `models` → `from apu_tool.nucleo.models import Apu, ApuComponent, DePricedApu, Insumo`.

- [ ] **Step 4: Actualizar los lanzadores**

`run_cli.py`:
```python
"""Atajo a la CLI.  Ej:  python run_cli.py demo"""
from apu_tool.interfaz.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
```
`run_gui.py`:
```python
"""Lanza la interfaz gráfica.  Uso:  python run_gui.py"""
from apu_tool.interfaz.gui import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Actualizar los imports de los tests**

En cada archivo de `tests/`, reescribir los imports de `apu_tool.X` a su nueva ruta de capa (mismo mapa del Step 3). Ej.: `from apu_tool.db import Database` → `from apu_tool.datos.db import Database`; `from apu_tool.models import ...` → `from apu_tool.nucleo.models import ...`; `from apu_tool.pricing import PricingEngine` → `from apu_tool.dominio.pricing import PricingEngine`; `from apu_tool.config import ...` → `from apu_tool import config` (o `from apu_tool.config import ...`).

- [ ] **Step 6: Checkpoint — suite completa + arranque**

Run: `python -m pytest tests/ -q`
Expected: 44 passing, sin cambios de conteo (solo se movió código).

Run: `python run_cli.py status`
Expected: imprime el estado de la base sin error (verifica que los lanzadores y los imports resuelven).

---

### Task 2: Esquemas separados `db/precios.sql` y `db/apus.sql` + rutas en config

Deliverable: dos DDL canónicos (uno por base) y las rutas `PRECIOS_DB_PATH`/`APUS_DB_PATH` en config. Aún no se usan; se validan cargándolos en bases temporales.

**Files:**
- Crear: `db/precios.sql`, `db/apus.sql`
- Modificar: `apu_tool/config.py` (añadir rutas)
- Test: `tests/test_esquemas_separados.py`

**Interfaces:**
- Produces: `config.PRECIOS_DB_PATH: Path` (= `DATA_DIR/"precios.db"`), `config.APUS_DB_PATH: Path` (= `DATA_DIR/"apus.db"`).
- `db/precios.sql` crea tablas `insumos`, `insumo_precios`, `meta`. `db/apus.sql` crea `apus`, `apu_componentes`, `meta`.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_esquemas_separados.py`:
```python
"""Los dos esquemas SQL separados existen y crean sus tablas."""
import sqlite3
from apu_tool import config

def _tablas(sql_path, tmp):
    con = sqlite3.connect(tmp)
    con.executescript(sql_path.read_text(encoding="utf-8"))
    t = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    return t

def test_esquema_precios(tmp_path):
    p = config.PROJECT_ROOT / "db" / "precios.sql"
    assert p.exists()
    assert {"insumos", "insumo_precios", "meta"} <= _tablas(p, tmp_path / "p.db")

def test_esquema_apus(tmp_path):
    p = config.PROJECT_ROOT / "db" / "apus.sql"
    assert p.exists()
    assert {"apus", "apu_componentes", "meta"} <= _tablas(p, tmp_path / "a.db")

def test_rutas_config():
    assert config.PRECIOS_DB_PATH.name == "precios.db"
    assert config.APUS_DB_PATH.name == "apus.db"
```

- [ ] **Step 2: Correr el test y verlo fallar**

Run: `python -m pytest tests/test_esquemas_separados.py -v`
Expected: FAIL — los `.sql` no existen y `config` no tiene las rutas.

- [ ] **Step 3: Crear `db/precios.sql`**
```sql
-- Esquema canónico de precios.db — catálogo de insumos y libro de precios.
-- SQL portable (SQLite hoy; Postgres luego). Cargado por apu_tool/datos/precios_db.py.

CREATE TABLE IF NOT EXISTS insumos (
    codigo TEXT PRIMARY KEY,
    nombre TEXT NOT NULL,
    unidad TEXT,
    grupo  TEXT
);

CREATE TABLE IF NOT EXISTS insumo_precios (
    -- SQLite autollena un INTEGER PRIMARY KEY (rowid); sin AUTOINCREMENT para portar limpio.
    -- Postgres: id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY
    id            INTEGER PRIMARY KEY,
    codigo        TEXT NOT NULL,
    precio        REAL NOT NULL,
    fuente        TEXT,
    clasificacion TEXT,          -- 'publico' | 'interno'
    fecha         TEXT,          -- ISO (YYYY-MM-DD)
    vigente       INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (codigo) REFERENCES insumos(codigo)
);

CREATE TABLE IF NOT EXISTS meta (
    clave TEXT PRIMARY KEY,
    valor TEXT
);

CREATE INDEX IF NOT EXISTS idx_precio_cod ON insumo_precios(codigo, vigente);
```

- [ ] **Step 4: Crear `db/apus.sql`**
```sql
-- Esquema canónico de apus.db — biblioteca histórica de APUs.
-- SQL portable (SQLite hoy; Postgres luego). Cargado por apu_tool/datos/apus_db.py.

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
    insumo_codigo         TEXT,   -- enlace BLANDO a precios.db: se valida en la app, sin FK
    insumo_nombre         TEXT,   -- nombre desnormalizado (respaldo si falta el código)
    unidad                TEXT,
    rendimiento           REAL,
    precio_unitario_hist  REAL,
    PRIMARY KEY (apu_codigo, shift, seq),
    FOREIGN KEY (apu_codigo, shift) REFERENCES apus(codigo, shift)
);

CREATE TABLE IF NOT EXISTS meta (
    clave TEXT PRIMARY KEY,
    valor TEXT
);

CREATE INDEX IF NOT EXISTS idx_comp_apu    ON apu_componentes(apu_codigo, shift);
CREATE INDEX IF NOT EXISTS idx_apus_nombre ON apus(nombre);
```

- [ ] **Step 5: Añadir rutas en `apu_tool/config.py`**

Junto a `DB_PATH` (línea ~22), añadir:
```python
# Bases canónicas separadas (fuente de verdad). DB_PATH queda obsoleto.
PRECIOS_DB_PATH = DATA_DIR / "precios.db"
APUS_DB_PATH = DATA_DIR / "apus.db"
```

- [ ] **Step 6: Correr el test y la suite**

Run: `python -m pytest tests/test_esquemas_separados.py -v` → PASS.
Run: `python -m pytest tests/ -q` → todo verde.

---

### Task 3: `datos/repositorio.py` — dos contratos (Protocol)

Deliverable: `RepositorioPrecios` y `RepositorioApus` definidos como Protocols (reemplazan a `repository.py`). Aún no hay implementación nueva; se valida que importan.

**Files:**
- Crear: `apu_tool/datos/repositorio.py`
- Test: `tests/test_repositorios_contrato.py`

**Interfaces:**
- Produces: `RepositorioPrecios` y `RepositorioApus` (Protocols runtime-checkable) con las firmas listadas abajo.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_repositorios_contrato.py`:
```python
from apu_tool.datos.repositorio import RepositorioPrecios, RepositorioApus

def test_protocols_existen():
    # son Protocols con métodos esperados
    assert hasattr(RepositorioPrecios, "get_insumo")
    assert hasattr(RepositorioPrecios, "set_precio")
    assert hasattr(RepositorioApus, "get_components")
    assert hasattr(RepositorioApus, "get_depriced_apu")
```

- [ ] **Step 2: Correr y ver fallar**

Run: `python -m pytest tests/test_repositorios_contrato.py -v`
Expected: FAIL — `ModuleNotFoundError: apu_tool.datos.repositorio`.

- [ ] **Step 3: Crear `apu_tool/datos/repositorio.py`**
```python
"""
Contratos de almacenamiento, separados por dominio.

Hoy los implementan PreciosDB y ApusDB (SQLite). Mañana, un backend de nube
(p. ej. Postgres) implementa estos mismos Protocols y el resto del programa no cambia.
"""
from __future__ import annotations

from typing import Iterable, Optional, Protocol, runtime_checkable

from apu_tool.nucleo.models import Apu, ApuComponent, DePricedApu, Insumo


@runtime_checkable
class RepositorioPrecios(Protocol):
    def init_schema(self) -> None: ...
    def reset(self) -> None: ...
    def insert_insumos(self, insumos: Iterable[Insumo]) -> int: ...
    def get_insumo(self, codigo: str) -> Optional[Insumo]: ...
    def set_precio(self, codigo: str, precio: float, fuente: str = "",
                   fecha: Optional[str] = None) -> None: ...
    def price_history(self, codigo: str) -> list[dict]: ...
    def search_insumos(self, texto: str, limit: int = 20) -> list[Insumo]: ...
    def search_insumos_por_palabras(self, palabras: list[str],
                                    limit: int = 60) -> list[Insumo]: ...
    def counts(self) -> dict[str, int]: ...
    def set_meta(self, clave: str, valor: str) -> None: ...
    def get_meta(self) -> dict[str, str]: ...


@runtime_checkable
class RepositorioApus(Protocol):
    def init_schema(self) -> None: ...
    def reset(self) -> None: ...
    def insert_apus(self, apus: Iterable[Apu]) -> int: ...
    def insert_components(self, comps: Iterable[ApuComponent]) -> int: ...
    def all_apus(self) -> list[Apu]: ...
    def apu_index(self) -> list[tuple[str, str, str]]: ...
    def get_apu(self, codigo: str, shift: str) -> Optional[Apu]: ...
    def search_apus(self, texto: str, limit: int = 20) -> list[Apu]: ...
    def get_components(self, apu_codigo: str, shift: str) -> list[ApuComponent]: ...
    def get_depriced_apu(self, codigo: str, shift: str) -> Optional[DePricedApu]: ...
    def counts(self) -> dict[str, int]: ...
    def set_meta(self, clave: str, valor: str) -> None: ...
    def get_meta(self) -> dict[str, str]: ...
```

- [ ] **Step 4: Correr y ver pasar; suite**

Run: `python -m pytest tests/test_repositorios_contrato.py -v` → PASS.
Run: `python -m pytest tests/ -q` → verde.

---

### Task 4: `datos/precios_db.py` — `PreciosDB`

Deliverable: `PreciosDB` (SQLite sobre `precios.db`) implementa `RepositorioPrecios`. Sin dependencia de `dominio` salvo los modelos (datos de dominio) — la búsqueda por palabras recibe tokens ya hechos.

**Files:**
- Crear: `apu_tool/datos/precios_db.py`
- Test: `tests/test_precios_db.py`

**Interfaces:**
- Consumes: `config.PRECIOS_DB_PATH`, `config.classify_price_source`, `db/precios.sql`, `Insumo`.
- Produces: `PreciosDB(path=config.PRECIOS_DB_PATH)` con los métodos de `RepositorioPrecios`. `search_insumos_por_palabras(palabras: list[str], limit=60) -> list[Insumo]` (recibe palabras ya tokenizadas; no importa de `dominio`).

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_precios_db.py`:
```python
import sqlite3
import pytest
from apu_tool import config
from apu_tool.datos.precios_db import PreciosDB
from apu_tool.datos.repositorio import RepositorioPrecios
from apu_tool.nucleo.models import Insumo


@pytest.fixture()
def precios(tmp_path):
    d = PreciosDB(tmp_path / "precios.db")
    d.reset()
    d.insert_insumos([
        Insumo("100", "CEMENTO GRIS", "KG", "MAT", 1000, "PRECIO IDU"),
        Insumo("200", "ACERO FIGURADO", "KG", "MAT", 5000, "COSTO INTERNO"),
    ])
    return d


def test_cumple_contrato(precios):
    assert isinstance(precios, RepositorioPrecios)

def test_precio_y_clasificacion(precios):
    assert precios.get_insumo("100").precio == 1000
    assert precios.get_insumo("100").es_confidencial is False
    assert precios.get_insumo("200").es_confidencial is True

def test_set_precio_vigente_e_historial(precios):
    precios.set_precio("100", 1500, fuente="COMPRAS 2026")
    assert precios.get_insumo("100").precio == 1500
    hist = precios.price_history("100")
    assert sum(h["vigente"] for h in hist) == 1 and len(hist) == 2

def test_fk_precio_requiere_insumo(precios):
    with pytest.raises(sqlite3.IntegrityError):
        with precios.connect() as c:
            c.execute("INSERT INTO insumo_precios (codigo, precio, vigente) "
                      "VALUES ('NOEXISTE', 1, 1)")

def test_busqueda(precios):
    assert any(i.codigo == "100" for i in precios.search_insumos("CEMENTO"))
    assert any(i.codigo == "200" for i in precios.search_insumos_por_palabras(["ACERO"]))

def test_counts(precios):
    c = precios.counts()
    assert c["insumos"] == 2 and c["insumo_precios"] == 2
```

- [ ] **Step 2: Correr y ver fallar**

Run: `python -m pytest tests/test_precios_db.py -v`
Expected: FAIL — `ModuleNotFoundError: apu_tool.datos.precios_db`.

- [ ] **Step 3: Crear `apu_tool/datos/precios_db.py`**
```python
"""
Acceso a precios.db (SQLite): catálogo de insumos y libro de precios.

Toda la lectura/escritura de precios pasa por aquí. Implementa RepositorioPrecios.
No importa nada de `dominio` salvo el modelo `Insumo`: la búsqueda por palabras recibe
los tokens ya hechos (la tokenización vive en el dominio), respetando la frontera de capas.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterable, Iterator, Optional

from apu_tool import config
from apu_tool.nucleo.models import Insumo

SCHEMA_PATH = config.PROJECT_ROOT / "db" / "precios.sql"


def _load_schema() -> str:
    return SCHEMA_PATH.read_text(encoding="utf-8")


class PreciosDB:
    """Backend SQLite de precios. Implementa RepositorioPrecios."""

    def __init__(self, path: Path | str = config.PRECIOS_DB_PATH):
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
        """Reconstruye el esquema desde cero (descarta y recrea desde db/precios.sql)."""
        with self.connect() as conn:
            for t in ("insumo_precios", "insumos", "meta"):
                conn.execute(f"DROP TABLE IF EXISTS {t}")
            conn.executescript(_load_schema())

    # ---- escritura ----
    def insert_insumos(self, insumos: Iterable[Insumo]) -> int:
        identidad, precios, seen = [], [], set()
        hoy = date.today().isoformat()
        for i in insumos:
            if i.codigo in seen:
                continue
            seen.add(i.codigo)
            identidad.append((i.codigo, i.nombre, i.unidad, i.grupo))
            precios.append((i.codigo, i.precio, i.fuente_precio,
                            config.classify_price_source(i.fuente_precio), hoy, 1))
        with self.connect() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO insumos (codigo, nombre, unidad, grupo) "
                "VALUES (?,?,?,?)", identidad)
            conn.executemany(
                "INSERT INTO insumo_precios "
                "(codigo, precio, fuente, clasificacion, fecha, vigente) "
                "VALUES (?,?,?,?,?,?)", precios)
        return len(identidad)

    def set_precio(self, codigo: str, precio: float, fuente: str = "",
                   fecha: Optional[str] = None) -> None:
        fecha = fecha or date.today().isoformat()
        with self.connect() as conn:
            conn.execute("UPDATE insumo_precios SET vigente=0 WHERE codigo=?", (str(codigo),))
            conn.execute(
                "INSERT INTO insumo_precios "
                "(codigo, precio, fuente, clasificacion, fecha, vigente) "
                "VALUES (?,?,?,?,?,1)",
                (str(codigo), float(precio), fuente,
                 config.classify_price_source(fuente), fecha))

    def set_meta(self, clave: str, valor: str) -> None:
        with self.connect() as conn:
            conn.execute("INSERT OR REPLACE INTO meta (clave, valor) VALUES (?,?)",
                         (clave, str(valor)))

    # ---- lectura ----
    def get_insumo(self, codigo: str) -> Optional[Insumo]:
        with self.connect() as conn:
            r = conn.execute(
                "SELECT i.codigo, i.nombre, i.unidad, i.grupo, p.precio, p.fuente "
                "FROM insumos i LEFT JOIN insumo_precios p "
                "  ON p.codigo = i.codigo AND p.vigente = 1 "
                "WHERE i.codigo = ?", (str(codigo),)).fetchone()
        if not r:
            return None
        return Insumo(codigo=r["codigo"], nombre=r["nombre"], unidad=r["unidad"] or "",
                      grupo=r["grupo"] or "", precio=r["precio"] or 0.0,
                      fuente_precio=r["fuente"] or "")

    def price_history(self, codigo: str) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT precio, fuente, clasificacion, fecha, vigente "
                "FROM insumo_precios WHERE codigo=? ORDER BY id", (str(codigo),)).fetchall()
        return [dict(r) for r in rows]

    def search_insumos(self, texto: str, limit: int = 20) -> list[Insumo]:
        like = f"%{texto.strip()}%"
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT codigo FROM insumos WHERE nombre LIKE ? OR codigo LIKE ? LIMIT ?",
                (like, like, limit)).fetchall()
        return [self.get_insumo(r["codigo"]) for r in rows]

    def search_insumos_por_palabras(self, palabras: list[str], limit: int = 60) -> list[Insumo]:
        """Insumos cuyo nombre contiene alguna de las `palabras` (ya tokenizadas por el dominio)."""
        palabras = [p for p in palabras if p]
        if not palabras:
            return []
        clauses = " OR ".join(["nombre LIKE ?"] * len(palabras))
        params = [f"%{p}%" for p in palabras] + [limit]
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT codigo FROM insumos WHERE {clauses} LIMIT ?", params).fetchall()
        return [self.get_insumo(r["codigo"]) for r in rows]

    def counts(self) -> dict[str, int]:
        with self.connect() as conn:
            return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    for t in ("insumos", "insumo_precios")}

    def get_meta(self) -> dict[str, str]:
        with self.connect() as conn:
            return {r["clave"]: r["valor"]
                    for r in conn.execute("SELECT clave, valor FROM meta").fetchall()}
```

- [ ] **Step 4: Correr y ver pasar; suite**

Run: `python -m pytest tests/test_precios_db.py -v` → PASS.
Run: `python -m pytest tests/ -q` → verde.

---

### Task 5: `datos/apus_db.py` — `ApusDB`

Deliverable: `ApusDB` (SQLite sobre `apus.db`) implementa `RepositorioApus`, incluyendo `get_depriced_apu` (vista sin dinero) y `insert_components` con continuación de `seq`.

**Files:**
- Crear: `apu_tool/datos/apus_db.py`
- Test: `tests/test_apus_db.py`

**Interfaces:**
- Consumes: `config.APUS_DB_PATH`, `db/apus.sql`, `Apu`, `ApuComponent`, `DePricedApu`, `DePricedComponent`.
- Produces: `ApusDB(path=config.APUS_DB_PATH)` con los métodos de `RepositorioApus`.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_apus_db.py`:
```python
import sqlite3
import pytest
from apu_tool.datos.apus_db import ApusDB
from apu_tool.datos.repositorio import RepositorioApus
from apu_tool.nucleo.models import Apu, ApuComponent


@pytest.fixture()
def apus(tmp_path):
    d = ApusDB(tmp_path / "apus.db")
    d.reset()
    d.insert_apus([Apu("A1", "MURO", "M2", "DIURNO")])
    d.insert_components([ApuComponent("A1", "DIURNO", "100", "CEMENTO", "KG", 3.0, 900)])
    return d


def test_cumple_contrato(apus):
    assert isinstance(apus, RepositorioApus)

def test_componentes_y_apu(apus):
    assert apus.get_apu("A1", "DIURNO").nombre == "MURO"
    comps = apus.get_components("A1", "DIURNO")
    assert len(comps) == 1 and comps[0].insumo_codigo == "100"

def test_seq_continua_entre_llamadas(apus):
    apus.insert_components([ApuComponent("A1", "DIURNO", "200", "ARENA", "M3", 1.0, 50)])
    assert len(apus.get_components("A1", "DIURNO")) == 2  # sin choque de PK

def test_componente_admite_insumo_huerfano(apus):
    apus.insert_components([ApuComponent("A1", "DIURNO", "GRA-99", "GRAVA", "M3", 1.0, 50)])
    assert any(c.insumo_codigo == "GRA-99" for c in apus.get_components("A1", "DIURNO"))

def test_depriced_no_tiene_dinero(apus):
    dp = apus.get_depriced_apu("A1", "DIURNO")
    assert not any(hasattr(c, "precio") or hasattr(c, "precio_unitario_hist")
                   for c in dp.componentes)

def test_fk_componente_requiere_apu(apus):
    with pytest.raises(sqlite3.IntegrityError):
        with apus.connect() as c:
            c.execute("INSERT INTO apu_componentes (apu_codigo, shift, seq) "
                      "VALUES ('NOEXISTE', 'DIURNO', 0)")
```

- [ ] **Step 2: Correr y ver fallar**

Run: `python -m pytest tests/test_apus_db.py -v`
Expected: FAIL — `ModuleNotFoundError: apu_tool.datos.apus_db`.

- [ ] **Step 3: Crear `apu_tool/datos/apus_db.py`**
```python
"""
Acceso a apus.db (SQLite): biblioteca histórica de APUs (composición + rendimiento + turno).

Implementa RepositorioApus. NO toca dinero (precio_unitario_hist es un respaldo embebido,
no se expone a la IA). get_depriced_apu devuelve la vista SIN dinero para la IA.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator, Optional

from apu_tool import config
from apu_tool.nucleo.models import (
    Apu, ApuComponent, DePricedApu, DePricedComponent,
)

SCHEMA_PATH = config.PROJECT_ROOT / "db" / "apus.sql"


def _load_schema() -> str:
    return SCHEMA_PATH.read_text(encoding="utf-8")


class ApusDB:
    """Backend SQLite de APUs. Implementa RepositorioApus."""

    def __init__(self, path: Path | str = config.APUS_DB_PATH):
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
        """Reconstruye el esquema desde cero (descarta y recrea desde db/apus.sql)."""
        with self.connect() as conn:
            for t in ("apu_componentes", "apus", "meta"):
                conn.execute(f"DROP TABLE IF EXISTS {t}")
            conn.executescript(_load_schema())

    # ---- escritura ----
    def insert_apus(self, apus: Iterable[Apu]) -> int:
        rows = [(a.codigo, a.shift, a.nombre, a.unidad, a.grupo) for a in apus]
        with self.connect() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO apus (codigo, shift, nombre, unidad, grupo) "
                "VALUES (?,?,?,?,?)", rows)
        return len(rows)

    def insert_components(self, comps: Iterable[ApuComponent]) -> int:
        comps = list(comps)
        with self.connect() as conn:
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

    def set_meta(self, clave: str, valor: str) -> None:
        with self.connect() as conn:
            conn.execute("INSERT OR REPLACE INTO meta (clave, valor) VALUES (?,?)",
                         (clave, str(valor)))

    # ---- lectura ----
    def all_apus(self) -> list[Apu]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM apus").fetchall()
        return [Apu(r["codigo"], r["nombre"], r["unidad"], r["shift"], r["grupo"]) for r in rows]

    def apu_index(self) -> list[tuple[str, str, str]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT codigo, nombre, shift FROM apus").fetchall()
        return [(r["codigo"], r["nombre"], r["shift"]) for r in rows]

    def search_apus(self, texto: str, limit: int = 20) -> list[Apu]:
        like = f"%{texto.strip()}%"
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM apus WHERE nombre LIKE ? OR codigo LIKE ? LIMIT ?",
                (like, like, limit)).fetchall()
        return [Apu(r["codigo"], r["nombre"], r["unidad"], r["shift"], r["grupo"]) for r in rows]

    def get_apu(self, codigo: str, shift: str) -> Optional[Apu]:
        with self.connect() as conn:
            r = conn.execute("SELECT * FROM apus WHERE codigo=? AND shift=?",
                             (str(codigo), shift)).fetchone()
        return Apu(r["codigo"], r["nombre"], r["unidad"], r["shift"], r["grupo"]) if r else None

    def get_components(self, apu_codigo: str, shift: str) -> list[ApuComponent]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM apu_componentes WHERE apu_codigo=? AND shift=? ORDER BY seq",
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

    def counts(self) -> dict[str, int]:
        with self.connect() as conn:
            return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    for t in ("apus", "apu_componentes")}

    def get_meta(self) -> dict[str, str]:
        with self.connect() as conn:
            return {r["clave"]: r["valor"]
                    for r in conn.execute("SELECT clave, valor FROM meta").fetchall()}
```

- [ ] **Step 4: Correr y ver pasar; suite**

Run: `python -m pytest tests/test_apus_db.py -v` → PASS.
Run: `python -m pytest tests/ -q` → verde.

---

### Task 6: `datos/almacen.py` — fachada `Almacen`

Deliverable: `Almacen` agrupa los dos repos (`.precios`, `.apus`) y ofrece `init_schema`/`counts` sobre ambos. Es lo que el resto de la app recibirá.

**Files:**
- Crear: `apu_tool/datos/almacen.py`
- Test: `tests/test_almacen.py`

**Interfaces:**
- Consumes: `PreciosDB`, `ApusDB`, `config`.
- Produces: `Almacen(precios_path=config.PRECIOS_DB_PATH, apus_path=config.APUS_DB_PATH)` con atributos `.precios: PreciosDB` y `.apus: ApusDB`; métodos `init_schema() -> None`, `reset() -> None`, `counts() -> dict[str, int]` (unión de ambos).

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_almacen.py`:
```python
from apu_tool.datos.almacen import Almacen
from apu_tool.datos.precios_db import PreciosDB
from apu_tool.datos.apus_db import ApusDB
from apu_tool.nucleo.models import Apu, Insumo


def test_fachada_expone_repos(tmp_path):
    alm = Almacen(tmp_path / "precios.db", tmp_path / "apus.db")
    alm.reset()
    assert isinstance(alm.precios, PreciosDB)
    assert isinstance(alm.apus, ApusDB)
    alm.precios.insert_insumos([Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU")])
    alm.apus.insert_apus([Apu("A1", "MURO", "M2", "DIURNO")])
    c = alm.counts()
    assert c["insumos"] == 1 and c["apus"] == 1
```

- [ ] **Step 2: Correr y ver fallar**

Run: `python -m pytest tests/test_almacen.py -v`
Expected: FAIL — `ModuleNotFoundError: apu_tool.datos.almacen`.

- [ ] **Step 3: Crear `apu_tool/datos/almacen.py`**
```python
"""
Fachada de almacenamiento: agrupa las dos bases (precios + APUs).

El resto de la app recibe un Almacen y usa el repo correcto:
    almacen.precios.get_insumo(...)      # precios.db
    almacen.apus.get_components(...)      # apus.db
Cambiar a un backend de nube = cambiar lo que se instancia aquí, sin tocar el dominio.
"""
from __future__ import annotations

from pathlib import Path

from apu_tool import config
from apu_tool.datos.apus_db import ApusDB
from apu_tool.datos.precios_db import PreciosDB


class Almacen:
    def __init__(self, precios_path: Path | str = config.PRECIOS_DB_PATH,
                 apus_path: Path | str = config.APUS_DB_PATH):
        self.precios = PreciosDB(precios_path)
        self.apus = ApusDB(apus_path)

    def init_schema(self) -> None:
        self.precios.init_schema()
        self.apus.init_schema()

    def reset(self) -> None:
        self.precios.reset()
        self.apus.reset()

    def counts(self) -> dict[str, int]:
        return {**self.precios.counts(), **self.apus.counts()}
```

- [ ] **Step 4: Correr y ver pasar; suite**

Run: `python -m pytest tests/test_almacen.py -v` → PASS.
Run: `python -m pytest tests/ -q` → verde.

---

### Task 7: Adaptar el dominio y la interfaz a `Almacen`

Deliverable: `pricing`, `compose`, `assemble`, `pipeline` y la interfaz (`cli`, `gui`) usan `Almacen` en vez del `Database` único. Se eliminan `datos/db.py` y `datos/repository.py`. Los tests que usaban `Database` migran a los repos/`Almacen`. Suite verde.

**Files:**
- Modificar: `apu_tool/dominio/pricing.py`, `apu_tool/dominio/compose.py`, `apu_tool/dominio/assemble.py`, `apu_tool/dominio/pipeline.py`, `apu_tool/interfaz/cli.py`, `apu_tool/interfaz/gui.py`
- Eliminar: `apu_tool/datos/repository.py` (tras migrar su test). **`db.py` NO se elimina aquí**: `ingest.py` aún lo usa; ambos se retiran juntos en la Task 8.
- Modificar tests: `tests/test_pricing_ingest.py`, `tests/test_db_repository.py`, `tests/test_assemble.py`, `tests/test_compose.py`, `tests/test_assemble_codigo.py`, `tests/test_schema_sql.py`

**Interfaces:**
- Consumes: `Almacen` (`.precios`, `.apus`) de la Task 6; `RepositorioApus.apu_index`.
- Produces:
  - `PricingEngine(almacen: Almacen)` — usa `almacen.apus.get_components` y `almacen.precios.get_insumo`. Firma de `cost_apu`/`cost_components`/`cost_component` sin cambios.
  - `InsumoRetriever(almacen: Almacen, matcher=None)` — usa `almacen.apus` y `almacen.precios.search_insumos_por_palabras`.
  - `Assembler(almacen: Almacen, advisor=None)` — `matcher = Matcher(almacen.apus.apu_index())`, `_codigos_apu` desde `almacen.apus.apu_index()`.
  - `pipeline.get_almacen() -> Almacen` (reemplaza `get_db`).

- [ ] **Step 1: Adaptar `dominio/pricing.py`**

Reemplazar el uso de `Database` por `Almacen` (solo cambia el origen de datos):
```python
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import ApuComponent, CostedComponent


class PricingEngine:
    def __init__(self, almacen: Almacen):
        self.alm = almacen
        self._cache: dict[str, Optional[tuple[float, str]]] = {}

    def _insumo_price(self, codigo: str) -> Optional[tuple[float, str]]:
        if not codigo:
            return None
        if codigo in self._cache:
            return self._cache[codigo]
        ins = self.alm.precios.get_insumo(codigo)
        result = (ins.precio, ins.fuente_precio) if ins else None
        self._cache[codigo] = result
        return result

    # cost_component / cost_components SIN cambios

    def cost_apu(self, apu_codigo: str, shift: str) -> tuple[list[CostedComponent], float]:
        comps = self.alm.apus.get_components(apu_codigo, shift)
        return self.cost_components(comps)
```

- [ ] **Step 2: Adaptar `dominio/compose.py`**

`InsumoRetriever` recibe `Almacen`; usa `almacen.apus.get_depriced_apu` y la búsqueda por palabras del dominio. Cambios:
```python
from apu_tool.datos.almacen import Almacen
from apu_tool.dominio.matching import Matcher, similarity, _tokens
from apu_tool.nucleo.models import DePricedApu, DePricedComponent

class InsumoRetriever:
    def __init__(self, almacen: Almacen, matcher: Matcher | None = None):
        self.alm = almacen
        self.matcher = matcher or Matcher(almacen.apus.apu_index())
    ...
    # en retrieve(): reemplazar self.db.get_depriced_apu(...) por self.alm.apus.get_depriced_apu(...)
    # y el bloque de búsqueda por nombre:
        palabras = [t for t in _tokens(descripcion) if len(t) >= 4]
        for ins in self.alm.precios.search_insumos_por_palabras(palabras, limit=60):
            if ins.codigo not in insumos:
                insumos[ins.codigo] = CandidateInsumo(ins.codigo, ins.nombre, ins.unidad)
```

- [ ] **Step 3: Adaptar `dominio/assemble.py`**

`Assembler` recibe `Almacen`:
```python
from apu_tool.datos.almacen import Almacen

class Assembler:
    def __init__(self, almacen: Almacen, advisor: Optional[ApuAdvisor] = None):
        self.alm = almacen
        self.matcher = Matcher(almacen.apus.apu_index())
        self.pricing = PricingEngine(almacen)
        self.advisor = advisor or ApuAdvisor()
        self.retriever = InsumoRetriever(almacen, self.matcher)
        self._codigos_apu = {cod for cod, _, _ in almacen.apus.apu_index()}
```
En `assemble_item`, `_try_generate` y `_build`, reemplazar cada `self.db.X` por el repo correcto:
- `self.db.get_depriced_apu(...)` → `self.alm.apus.get_depriced_apu(...)`
- `self.db.get_insumo(...)` (en `_try_generate`) → `self.alm.precios.get_insumo(...)`
- `self.db.get_apu(...)` y `self.db.all_apus()` (en `_build`) → `self.alm.apus.get_apu(...)` / `self.alm.apus.all_apus()`

- [ ] **Step 4: Adaptar `dominio/pipeline.py`**

Reemplazar `get_db`/`Database` por `get_almacen`/`Almacen`:
```python
from apu_tool.datos.almacen import Almacen

def get_almacen() -> Almacen:
    alm = Almacen()
    alm.init_schema()
    return alm

def db_is_empty(alm: Optional[Almacen] = None) -> bool:
    alm = alm or get_almacen()
    return alm.counts()["apus"] == 0
```
En `run_pipeline`, `build_desde_presupuesto`, `generate_sample`: construir el motor con `alm = get_almacen()`, `Assembler(alm, advisor=...)`, `PricingEngine(alm)`.

**Importante (cutover):** NO tocar `ensure_ingested`, `get_db` ni `ingest` en esta tarea — siguen existiendo y funcionando sobre `db.py` (apu.db) hasta la Task 8, donde `seed` los reemplaza. Es decir, en la Task 7 conviven `get_db()` (viejo, para ensure_ingested) y `get_almacen()` (nuevo, para el motor). Mantén ambos imports en `pipeline.py`. Consecuencia esperada: tras la Task 7 los **tests** pasan (usan fixtures con `Almacen`), pero el CLI real contra datos (`build-ppto`) no tendrá datos en precios.db/apus.db hasta semillar en la Task 8 — eso es correcto a mitad de migración.

- [ ] **Step 5: Adaptar `interfaz/cli.py` e `interfaz/gui.py`**

- `cli.py`: `from apu_tool.dominio.pipeline import build_desde_presupuesto, ensure_ingested, generate_sample, get_almacen, run_pipeline`. En `cmd_status`/`cmd_db_price`/`cmd_db_update_price` usar `alm = get_almacen()` y `alm.precios`/`alm.apus`. `_summary` no cambia (usa AssembledApu).
- `gui.py`: `from apu_tool.dominio.pipeline import db_is_empty, generate_sample, get_almacen`; cualquier `get_db()` → `get_almacen()`.

- [ ] **Step 6: Eliminar `datos/repository.py`**

Borrar `datos/repository.py` (su único uso era `tests/test_db_repository.py`, migrado en el Step 7). Verificar que nada lo importa: `grep -rn "datos.repository\|import Repository" apu_tool tests` no debe arrojar resultados. **`datos/db.py` se conserva** (aún lo usa `datos/ingest.py` y `ensure_ingested`); se elimina en la Task 8.

- [ ] **Step 7: Migrar los tests que usaban `Database`**

Reescribir las fixtures: donde antes había `d = Database(tmp); d.reset(); d.insert_insumos(...); d.insert_apus(...); d.insert_components(...)`, ahora:
```python
from apu_tool.datos.almacen import Almacen

@pytest.fixture()
def alm(tmp_path):
    a = Almacen(tmp_path / "precios.db", tmp_path / "apus.db")
    a.reset()
    a.precios.insert_insumos([...])
    a.apus.insert_apus([...])
    a.apus.insert_components([...])
    return a
```
Y los usos: `PricingEngine(alm)`, `Assembler(alm, advisor=...)`, `alm.precios.get_insumo(...)`, `alm.apus.get_components(...)`, `alm.apus.get_depriced_apu(...)`.
- `tests/test_db_repository.py` → renombrar conceptualmente a precios+apus: mover sus asserts de protocolo a los repos (o eliminar los que ya cubren `test_precios_db.py`/`test_apus_db.py`); conservar los de pricing/meta/búsqueda adaptados a `alm`.
- `tests/test_schema_sql.py`: las pruebas del esquema único ya no aplican (hay dos esquemas, cubiertos por `test_esquemas_separados.py` + `test_precios_db.py` + `test_apus_db.py`). Eliminar este archivo.
- Los demás (`test_pricing_ingest`, `test_assemble`, `test_compose`, `test_assemble_codigo`): adaptar fixture a `Almacen` como arriba.

- [ ] **Step 8: Checkpoint — suite completa**

Run: `python -m pytest tests/ -q`
Expected: verde (con los tests migrados; el conteo total cambia por las altas/bajas de archivos de test).

---

### Task 8: `seed` guardado + correcciones (4613→3017) + integridad + CLI

Deliverable: importación semilla desde el Excel hacia las dos bases (guardada), con la corrección de código aplicada y un chequeo de integridad; comandos `seed`, `db check`, y `status`/`build`/`build-ppto` adaptados. Se retiran `ingest`/`db rebuild`. Verificación real.

**Files:**
- Crear: `apu_tool/datos/correcciones.py`, `apu_tool/datos/integridad.py`, `apu_tool/datos/seed.py`
- Eliminar: `apu_tool/datos/ingest.py` **y** `apu_tool/datos/db.py` (ya nadie los usa tras reemplazar `ensure_ingested`→`ensure_seeded` y quitar `get_db`)
- Modificar: `apu_tool/dominio/pipeline.py` (ensure_seeded), `apu_tool/interfaz/cli.py` (comandos), `apu_tool/interfaz/gui.py` (si llamaba ingest)
- Test: `tests/test_seed_correcciones.py`, `tests/test_integridad.py`

**Interfaces:**
- Consumes: `Almacen`, `openpyxl`, la config de pestañas de la ingesta actual (reutilizar el parser de `ingest.py`).
- Produces:
  - `correcciones.CORRECCIONES_CODIGO: dict[str, str]` (= `{"4613": "3017"}`) y `correcciones.aplicar(comps: list[ApuComponent]) -> list[ApuComponent]` (remapea `insumo_codigo`).
  - `integridad.revisar(almacen) -> dict` con `{"huerfanos": int, "descalces": list[dict]}`.
  - `seed.seed(almacen=None, xlsx_path=None, force=False) -> dict` (reporte de conteos); lanza `SeedExistente` si ya hay datos y no `force`.
  - `pipeline.ensure_seeded()` (reemplaza `ensure_ingested`).

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_seed_correcciones.py`:
```python
from apu_tool.datos.correcciones import CORRECCIONES_CODIGO, aplicar
from apu_tool.nucleo.models import ApuComponent

def test_remapea_4613_a_3017():
    assert CORRECCIONES_CODIGO["4613"] == "3017"
    comps = [ApuComponent("A", "DIURNO", "4613", "TRANSPORTE", "M3", 6.0, 0),
             ApuComponent("A", "DIURNO", "100", "CEMENTO", "KG", 1.0, 0)]
    out = aplicar(comps)
    assert out[0].insumo_codigo == "3017"   # remapeado
    assert out[1].insumo_codigo == "100"    # intacto
```
Crear `tests/test_integridad.py`:
```python
from apu_tool.datos.almacen import Almacen
from apu_tool.datos import integridad
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo

def test_detecta_huerfano(tmp_path):
    a = Almacen(tmp_path / "p.db", tmp_path / "a.db")
    a.reset()
    a.precios.insert_insumos([Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU")])
    a.apus.insert_apus([Apu("A1", "MURO", "M2", "DIURNO")])
    a.apus.insert_components([ApuComponent("A1", "DIURNO", "999", "X", "UN", 1.0, 0)])
    rep = integridad.revisar(a)
    assert rep["huerfanos"] == 1   # código 999 no está en precios
```

- [ ] **Step 2: Correr y ver fallar**

Run: `python -m pytest tests/test_seed_correcciones.py tests/test_integridad.py -v`
Expected: FAIL — módulos inexistentes.

- [ ] **Step 3: Crear `apu_tool/datos/correcciones.py`**
```python
"""
Correcciones de código aplicadas al semillar (normalización mínima).

El histórico cita códigos de insumo que en el catálogo significan otra cosa. Aquí se
remapean al código correcto del catálogo. Arranca con el descalce confirmado del 4613:
la composición lo usa como "transporte y disposición final", pero 4613 en precios es
"UNIÓN PVC D=10"; el código correcto del transporte (diurno) es 3017.
"""
from __future__ import annotations

from dataclasses import replace
from apu_tool.nucleo.models import ApuComponent

CORRECCIONES_CODIGO: dict[str, str] = {
    "4613": "3017",   # transporte y disposición final (diurno)
}


def aplicar(comps: list[ApuComponent]) -> list[ApuComponent]:
    """Devuelve la lista con insumo_codigo remapeado según CORRECCIONES_CODIGO."""
    out = []
    for c in comps:
        nuevo = CORRECCIONES_CODIGO.get(c.insumo_codigo)
        out.append(replace(c, insumo_codigo=nuevo) if nuevo else c)
    return out
```
(Nota: `ApuComponent` es `@dataclass(frozen=True)`, por eso `dataclasses.replace`.)

- [ ] **Step 4: Crear `apu_tool/datos/integridad.py`**
```python
"""
Chequeo de integridad del vínculo APU→insumo (que cruza las dos bases).

Sustituye la FK que ya no existe entre archivos: reporta componentes cuyo código no
existe en precios (huérfanos) y descalces de nombre (el nombre embebido en el APU no
coincide con el del código en el catálogo) — la clase del problema del 4613.
"""
from __future__ import annotations

import unicodedata
from difflib import SequenceMatcher

from apu_tool.datos.almacen import Almacen


def _norm(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", str(s or ""))
                if unicodedata.category(c) != "Mn")
    return " ".join(s.upper().split())


def _coincide(a: str, b: str) -> bool:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return True
    if na == nb or na.startswith(nb) or nb.startswith(na):
        return True
    return SequenceMatcher(None, na, nb).ratio() >= 0.60


def revisar(almacen: Almacen) -> dict:
    """Devuelve {'huerfanos': int, 'descalces': [{codigo, apu_nom, cat_nom, n}]}."""
    huerfanos = 0
    descalces: dict[tuple, dict] = {}
    with almacen.apus.connect() as ca:
        comps = ca.execute(
            "SELECT insumo_codigo AS cod, insumo_nombre AS nom "
            "FROM apu_componentes WHERE insumo_codigo IS NOT NULL AND insumo_codigo <> ''"
        ).fetchall()
    for r in comps:
        ins = almacen.precios.get_insumo(r["cod"])
        if ins is None:
            huerfanos += 1
            continue
        if not _coincide(r["nom"], ins.nombre):
            key = (r["cod"], _norm(r["nom"]))
            d = descalces.setdefault(key, {"codigo": r["cod"], "apu_nom": r["nom"],
                                           "cat_nom": ins.nombre, "n": 0})
            d["n"] += 1
    return {"huerfanos": huerfanos, "descalces": list(descalces.values())}
```

- [ ] **Step 5: Crear `apu_tool/datos/seed.py`**

Reutiliza el parser del Excel del `ingest.py` actual (mover ese parsing aquí). El `seed` es guardado y aplica correcciones a los componentes antes de insertarlos en `apus.db`:
```python
"""
Semillado (fuente de verdad): importa el Excel UNA vez a precios.db + apus.db.

Es guardado: si las bases ya tienen datos mantenidos, se niega salvo force=True.
Aplica las correcciones de código (4613→3017) a la composición antes de insertarla.
Reutiliza el parser de pestañas del histórico (antes en ingest.py).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

import openpyxl

from apu_tool import config
from apu_tool.datos import correcciones
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo
# Reutilizar los lectores de pestañas que estaban en ingest.py:
# _read_insumos, _read_apus, INSUMO_SHEETS, APUS_SHEET/APUS_COLS, _num/_code/_text/_looks_like_code
# (mover esas funciones/constantes a este módulo tal cual, sin cambiar su lógica).


class SeedExistente(Exception):
    """Las bases ya tienen datos mantenidos; usar force=True para sobrescribir."""


def seed(almacen: Optional[Almacen] = None, xlsx_path: Optional[Path] = None,
         force: bool = False) -> dict:
    config.ensure_dirs()
    alm = almacen or Almacen()
    alm.init_schema()
    c = alm.counts()
    if (c.get("apus", 0) or c.get("insumos", 0)) and not force:
        raise SeedExistente(
            "precios.db/apus.db ya tienen datos. Usa --force para re-semillar "
            "(¡borra correcciones mantenidas!).")

    xlsx_path = Path(xlsx_path) if xlsx_path else config.detect_source_xlsx()
    if not xlsx_path or not xlsx_path.exists():
        raise FileNotFoundError(
            "No se encontró el Excel histórico. Define APU_SOURCE_XLSX o coloca el .xlsx.")

    alm.reset()
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    try:
        insumos: dict[str, Insumo] = {}
        for sheet in INSUMO_SHEETS:                      # noqa: F821 (movido desde ingest.py)
            for ins in _read_insumos(wb, sheet):          # noqa: F821
                insumos.setdefault(ins.codigo, ins)
        alm.precios.insert_insumos(insumos.values())

        apus, comps = _read_apus(wb)                      # noqa: F821
        alm.apus.insert_apus(apus)
        alm.apus.insert_components(correcciones.aplicar(comps))   # ← corrección aquí
    finally:
        wb.close()

    counts = alm.counts()
    alm.precios.set_meta("fuente", xlsx_path.name)
    alm.precios.set_meta("fecha_seed", date.today().isoformat())
    alm.apus.set_meta("fuente", xlsx_path.name)
    alm.apus.set_meta("fecha_seed", date.today().isoformat())
    return counts
```
Mover desde `ingest.py` a `seed.py` (sin cambiar su lógica): `_num`, `_code`, `_text`, `_looks_like_code`, `InsumoSheet`, `INSUMO_SHEETS`, `APUS_SHEET`, `APUS_COLS`, `_read_insumos`, `_read_apus`. Luego eliminar `ingest.py`.

- [ ] **Step 6: Adaptar `pipeline.py` (ensure_seeded) y `cli.py`**

`pipeline.py`:
```python
from apu_tool.datos.seed import seed, SeedExistente

def ensure_seeded() -> dict:
    """Semilla si las bases están vacías; si no, devuelve los conteos actuales."""
    alm = get_almacen()
    if alm.counts()["apus"] == 0:
        return seed(alm)
    return alm.counts()
```
Reemplazar las llamadas a `ensure_ingested()` por `ensure_seeded()` en `run_pipeline`, `build_desde_presupuesto`, `generate_sample`; **eliminar `ensure_ingested`, `get_db` y los imports de `ingest`/`db`** de `pipeline.py`. Luego borrar `datos/ingest.py` y `datos/db.py`. Verificar: `grep -rn "datos.db\|datos.ingest\|get_db\|ensure_ingested\|import Database" apu_tool tests` sin resultados.

`cli.py` — reemplazar `cmd_db_rebuild`/`cmd_ingest` por:
```python
def cmd_seed(args) -> int:
    from apu_tool.datos.seed import seed, SeedExistente
    from apu_tool.datos.almacen import Almacen
    try:
        counts = seed(Almacen(), force=args.force)
    except SeedExistente as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    print("Semillado OK:", counts)
    return 0

def cmd_db_check(args) -> int:
    from apu_tool.datos import integridad
    rep = integridad.revisar(get_almacen())
    print(f"Huérfanos: {rep['huerfanos']}")
    print(f"Descalces de nombre: {len(rep['descalces'])}")
    for d in sorted(rep["descalces"], key=lambda x: -x["n"])[:25]:
        print(f"  {d['codigo']:>7}  x{d['n']:<3}  {d['apu_nom'][:26]} -> {d['cat_nom'][:30]}")
    return 0
```
Registrar subparsers: `seed` (con `--force`) y `db check`. Quitar `db rebuild` y `ingest`. `cmd_status` usa `get_almacen().counts()` y `get_meta()` de ambos repos.

- [ ] **Step 7: Correr los tests nuevos y la suite**

Run: `python -m pytest tests/test_seed_correcciones.py tests/test_integridad.py -v` → PASS.
Run: `python -m pytest tests/ -q` → verde.

- [ ] **Step 8: Verificación real**

Run: `python run_cli.py seed`
Expected: crea `data/precios.db` y `data/apus.db`; imprime conteos (~7505 insumos / 1098 APUs / 4879 componentes).

Run: `python run_cli.py seed`
Expected: se **niega** (SeedExistente), porque ya hay datos.

Run: `python run_cli.py db check`
Expected: `Huérfanos: 0` y los descalces restantes (9164, 4513 menores; 4613 ya NO aparece porque se corrigió al semillar).

Run: `python run_cli.py build-ppto`
Expected: genera el cuadro; el ítem **13.601** ahora da **margen positivo (~+12%)** — confirma que la corrección del 4613 persiste y se aplica.

Run: `python run_cli.py status`
Expected: conteos de ambas bases + fuente/fecha de seed.

---

## Self-Review

**Spec coverage:**
- Reorganización completa por capas → Task 1.
- `db/precios.sql`, `db/apus.sql` + rutas config → Task 2.
- `RepositorioPrecios`/`RepositorioApus` → Task 3.
- `PreciosDB` → Task 4 (incl. `search_insumos_por_palabras` sin dep. de dominio).
- `ApusDB` (get_depriced_apu, seq-continuation) → Task 5.
- `Almacen` fachada → Task 6.
- Consumidores a `Almacen`, eliminar `db.py`/`repository.py`, migrar tests → Task 7.
- `seed` guardado + correcciones 4613→3017 + integridad + CLI (`seed`, `db check`), retirar `ingest`/`db rebuild` → Task 8.
- Invariante #1 → no se toca `privacy.py`/`ai_assist`; el costo solo en `pricing`; verificado por construcción.
- Verificación real (seed guardado, db check, 13.601 positivo) → Task 8 Step 8.

**Placeholder scan:** sin TBD/TODO. Los `# noqa (movido desde ingest.py)` referencian funciones cuyo traslado literal está indicado explícitamente en la Task 8 Step 5.

**Type consistency:** `Almacen.precios`/`.apus`, `PricingEngine(almacen)`, `Assembler(almacen, advisor)`, `InsumoRetriever(almacen, matcher)`, `search_insumos_por_palabras(palabras, limit)`, `get_almacen()`, `seed(almacen, xlsx_path, force)`, `integridad.revisar(almacen)`, `correcciones.aplicar(comps)` usados con nombres y firmas idénticas entre tareas. Las firmas de los Protocols (Task 3) coinciden con los métodos implementados en Tasks 4–5.
