> Espejo automático — no editar aquí. Fuente: `docs/superpowers/plans/2026-07-23-nombre-corridas.md`

# Nombre/alias para corridas — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Darle a cada corrida un nombre/alias editable, precargado (sin extensión) del archivo subido, con opción de renombrar corridas existentes.

**Architecture:** Se agrega una columna `nombre` a la tabla `corrida` (ambos backends, migración idempotente + backfill = `archivo`), preservando `archivo` como procedencia inmutable. El servicio calcula el nombre por defecto desde el archivo y expone `renombrar_corrida`. El frontend agrega un campo "Nombre" en el alta (con precarga) y una acción "Renombrar" en "Mis corridas" (vía `window.prompt`, igual que renombrar carpeta).

**Tech Stack:** Python 3 / FastAPI / SQLite + Postgres (psycopg) en backend; React + TypeScript + Vitest en `web/`.

## Global Constraints

- **Invariante #1 (la IA nunca ve dinero):** esta feature NO toca dinero ni la IA. No agregar payloads a la IA. `privacy.py` no se toca.
- **No romper lógica existente:** extender por adición; suite verde antes de dar por terminado (`python -m pytest tests/ -q` y los tests de `web/`).
- **Persistencia aislada en la capa de datos:** nada de SQL crudo fuera de `apu_tool/datos/`.
- **Español** en nombres de dominio, comentarios y mensajes de usuario.
- **Doble backend:** todo cambio de esquema/consulta va en SQLite (`apu_tool/datos/corridas_db.py` + `db/corridas.sql`) **y** en Postgres (`apu_tool/datos/pg/corridas_pg.py` + `db/pg/corridas.sql`).
- **Tope de longitud del nombre:** 120 caracteres. **Espacios permitidos.**
- **Commits:** terminar el mensaje con `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

## Preparación

Trabajar en una rama nueva: `git checkout -b feat/nombre-corridas` (o worktree equivalente vía superpowers:using-git-worktrees).

---

### Task 1: Dominio — `CorridaMeta.nombre` + helper `nombre_desde_archivo`

**Files:**
- Modify: `apu_tool/nucleo/models.py` (dataclass `CorridaMeta`, ~línea 218-229)
- Modify: `apu_tool/servicio/corridas.py` (agregar helper de módulo; `Path` ya está importado, línea 12)
- Test: `tests/test_nombre_corridas.py` (Create)

**Interfaces:**
- Produces:
  - `CorridaMeta.nombre: str` (campo nuevo, default `""`)
  - `apu_tool.servicio.corridas.nombre_desde_archivo(filename: str) -> str`

- [ ] **Step 1: Escribir el test que falla**

Create `tests/test_nombre_corridas.py`:

```python
from apu_tool.servicio.corridas import nombre_desde_archivo


def test_nombre_desde_archivo_quita_extension():
    assert nombre_desde_archivo("Licitacion Calle 13.xlsx") == "Licitacion Calle 13"


def test_nombre_desde_archivo_csv_y_espacios():
    assert nombre_desde_archivo("  Obra Lote SL5.csv  ") == "Obra Lote SL5"


def test_nombre_desde_archivo_sin_extension():
    assert nombre_desde_archivo("presupuesto") == "presupuesto"


def test_nombre_desde_archivo_puntos_intermedios():
    assert nombre_desde_archivo("v1.2.final.xlsx") == "v1.2.final"


def test_nombre_desde_archivo_vacio():
    assert nombre_desde_archivo("") == ""
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_nombre_corridas.py -q`
Expected: FAIL con `ImportError: cannot import name 'nombre_desde_archivo'`.

- [ ] **Step 3: Agregar el campo `nombre` a `CorridaMeta`**

En `apu_tool/nucleo/models.py`, en la dataclass `CorridaMeta`, agregar `nombre` como último campo (después de `carpeta_id`, para no alterar posiciones de constructores existentes):

```python
@dataclass(frozen=True)
class CorridaMeta:
    id: Optional[int]
    creada_en: str                # ISO 8601
    archivo: str
    turno_def: str
    use_ai: Optional[bool]
    estado: str                   # 'en_revision' | 'finalizada'
    cuadro_path: Optional[str] = None
    duracion_ms: Optional[int] = None
    modo: str = "activa"
    carpeta_id: Optional[int] = None
    nombre: str = ""              # alias editable; vacío => se deriva de `archivo`
```

- [ ] **Step 4: Implementar el helper `nombre_desde_archivo`**

En `apu_tool/servicio/corridas.py`, después de la definición de `_estructura` (o junto a los helpers de módulo, antes de `construir_corrida_stream`):

```python
def nombre_desde_archivo(filename: str) -> str:
    """Nombre por defecto de una corrida: el archivo subido SIN su última extensión.

    `Licitacion Calle 13.xlsx` -> `Licitacion Calle 13`. Es puro (sin I/O)."""
    base = (filename or "").strip()
    return Path(base).stem.strip() if base else ""
```

- [ ] **Step 5: Correr el test para verificar que pasa**

Run: `python -m pytest tests/test_nombre_corridas.py -q`
Expected: PASS (5 passed).

- [ ] **Step 6: Commit**

```bash
git add apu_tool/nucleo/models.py apu_tool/servicio/corridas.py tests/test_nombre_corridas.py
git commit -m "$(cat <<'EOF'
feat(corridas): campo nombre en CorridaMeta + helper nombre_desde_archivo

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Persistencia SQLite — columna `nombre`, migración, `set_nombre`

**Files:**
- Modify: `db/corridas.sql` (tabla `corrida`, ~línea 13-24)
- Modify: `apu_tool/datos/corridas_db.py` (`init_schema` ~46-70; `_insert_corrida` ~93-100; `_row_to_meta` ~187-194; nuevo `set_nombre`)
- Modify: `apu_tool/datos/repositorio.py` (Protocol `RepositorioCorridas`, ~110-135)
- Test: `tests/test_nombre_corridas.py` (Modify — agregar test SQLite)

**Interfaces:**
- Consumes: `CorridaMeta.nombre` (Task 1)
- Produces: `RepositorioCorridas.set_nombre(corrida_id: int, nombre: str) -> None`; `_row_to_meta` devuelve `nombre` con fallback a `archivo`.

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_nombre_corridas.py`:

```python
from apu_tool.nucleo.models import CorridaMeta
from apu_tool.datos.corridas_db import CorridasDB


def _corridas_db(tmp_path):
    db = CorridasDB(tmp_path / "c.db")
    db.init_schema()
    return db


def test_sqlite_persiste_nombre_y_set_nombre(tmp_path):
    db = _corridas_db(tmp_path)
    cid = db.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-07-23T10:00:00", archivo="lic.xlsx",
        turno_def="DIURNO", use_ai=False, estado="en_revision", nombre="Obra Norte"))
    assert db.get_corrida(cid).nombre == "Obra Norte"
    db.set_nombre(cid, "Obra Sur")
    assert db.get_corrida(cid).nombre == "Obra Sur"


def test_sqlite_nombre_vacio_cae_a_archivo(tmp_path):
    db = _corridas_db(tmp_path)
    cid = db.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-07-23T10:00:00", archivo="lic.xlsx",
        turno_def="DIURNO", use_ai=False, estado="en_revision"))  # nombre=""
    assert db.get_corrida(cid).nombre == "lic.xlsx"
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_nombre_corridas.py -q`
Expected: FAIL — `AttributeError: 'CorridasDB' object has no attribute 'set_nombre'` (o `nombre` no persiste).

- [ ] **Step 3: Agregar la columna al esquema SQLite**

En `db/corridas.sql`, tabla `corrida`, agregar la columna `nombre` (para DBs nuevas):

```sql
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
  carpeta_id    INTEGER REFERENCES carpeta(id) ON DELETE RESTRICT,
  nombre        TEXT
);
```

- [ ] **Step 4: Migración + backfill en `init_schema`**

En `apu_tool/datos/corridas_db.py::init_schema`, junto a los otros `ALTER` (después del bloque de `carpeta_id`, antes del bootstrap de "Sin clasificar"):

```python
            if "nombre" not in cols:
                conn.execute("ALTER TABLE corrida ADD COLUMN nombre TEXT")
            # Backfill idempotente: corridas viejas muestran su archivo hasta renombrarse.
            conn.execute("UPDATE corrida SET nombre = archivo "
                         "WHERE nombre IS NULL OR nombre = ''")
```

- [ ] **Step 5: Incluir `nombre` en el INSERT**

En `_insert_corrida` (~línea 93):

```python
    def _insert_corrida(self, conn: sqlite3.Connection, meta: CorridaMeta) -> int:
        cur = conn.execute(
            "INSERT INTO corrida (creada_en, archivo, turno_def, use_ai, estado, "
            "cuadro_path, duracion_ms, modo, carpeta_id, nombre) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (meta.creada_en, meta.archivo, meta.turno_def,
             None if meta.use_ai is None else int(meta.use_ai),
             meta.estado, meta.cuadro_path, meta.duracion_ms, meta.modo,
             meta.carpeta_id, meta.nombre))
        return int(cur.lastrowid)
```

- [ ] **Step 6: Leer `nombre` en `_row_to_meta` (con fallback a `archivo`)**

En `_row_to_meta` (~línea 187):

```python
    def _row_to_meta(self, r: sqlite3.Row) -> CorridaMeta:
        return CorridaMeta(
            id=r["id"], creada_en=r["creada_en"], archivo=r["archivo"],
            turno_def=r["turno_def"],
            use_ai=None if r["use_ai"] is None else bool(r["use_ai"]),
            estado=r["estado"], cuadro_path=r["cuadro_path"],
            duracion_ms=r["duracion_ms"], modo=(r["modo"] or "activa"),
            carpeta_id=(r["carpeta_id"] if "carpeta_id" in r.keys() else None),
            nombre=((r["nombre"] if "nombre" in r.keys() else None) or r["archivo"]))
```

- [ ] **Step 7: Agregar `set_nombre` al backend SQLite**

Junto a `set_modo` (~línea 151):

```python
    def set_nombre(self, corrida_id: int, nombre: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE corrida SET nombre=? WHERE id=?",
                         (nombre, int(corrida_id)))
```

- [ ] **Step 8: Declarar `set_nombre` en el Protocol**

En `apu_tool/datos/repositorio.py`, dentro de `RepositorioCorridas` (después de `set_modo`, línea 129):

```python
    def set_modo(self, corrida_id: int, modo: str) -> None: ...
    def set_nombre(self, corrida_id: int, nombre: str) -> None: ...
```

- [ ] **Step 9: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/test_nombre_corridas.py -q`
Expected: PASS (7 passed).

- [ ] **Step 10: Commit**

```bash
git add db/corridas.sql apu_tool/datos/corridas_db.py apu_tool/datos/repositorio.py tests/test_nombre_corridas.py
git commit -m "$(cat <<'EOF'
feat(corridas): columna nombre en SQLite + set_nombre + backfill

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Persistencia Postgres — columna `nombre`, migración, `set_nombre`

**Files:**
- Modify: `db/pg/corridas.sql` (tabla `corridas.corrida` ~14-26; bloque de migración idempotente ~47-51)
- Modify: `apu_tool/datos/pg/corridas_pg.py` (`_insert_corrida` ~44-52; `_row_to_meta` ~136-143; nuevo `set_nombre`)

**Interfaces:**
- Consumes: `CorridaMeta.nombre` (Task 1); contrato `set_nombre` (Task 2)
- Produces: paridad dual-backend (Postgres implementa `set_nombre` y persiste `nombre`).

> Nota: no hay Postgres en el entorno de pruebas local (los tests corren SQLite). La verificación aquí es import + inspección + suite completa verde; la migración real corre al boot en prod (`ADD COLUMN IF NOT EXISTS`, idempotente).

- [ ] **Step 1: Agregar la columna al esquema Postgres**

En `db/pg/corridas.sql`, tabla `corridas.corrida`, agregar `nombre TEXT`:

```sql
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
    carpeta_id    BIGINT REFERENCES corridas.carpeta(id) ON DELETE RESTRICT,
    nombre        TEXT
);
```

- [ ] **Step 2: Migración idempotente + backfill**

En `db/pg/corridas.sql`, en el bloque "Migración idempotente para bases existentes" (después de la línea de `carpeta_id`, ~línea 51):

```sql
ALTER TABLE corridas.corrida ADD COLUMN IF NOT EXISTS nombre TEXT;
UPDATE corridas.corrida SET nombre = archivo WHERE nombre IS NULL OR nombre = '';
```

- [ ] **Step 3: Incluir `nombre` en el INSERT**

En `apu_tool/datos/pg/corridas_pg.py::_insert_corrida` (~línea 44):

```python
    def _insert_corrida(self, conn, meta: CorridaMeta) -> int:
        cur = conn.execute(
            "INSERT INTO corridas.corrida (creada_en, archivo, turno_def, use_ai, estado, "
            "cuadro_path, duracion_ms, modo, carpeta_id, nombre) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (meta.creada_en, meta.archivo, meta.turno_def,
             None if meta.use_ai is None else int(meta.use_ai),
             meta.estado, meta.cuadro_path, meta.duracion_ms, meta.modo,
             meta.carpeta_id, meta.nombre))
        return int(cur.fetchone()["id"])
```

- [ ] **Step 4: Leer `nombre` en `_row_to_meta` (fallback a `archivo`)**

En `_row_to_meta` (~línea 136):

```python
    def _row_to_meta(self, r) -> CorridaMeta:
        return CorridaMeta(
            id=r["id"], creada_en=r["creada_en"], archivo=r["archivo"],
            turno_def=r["turno_def"],
            use_ai=None if r["use_ai"] is None else bool(r["use_ai"]),
            estado=r["estado"], cuadro_path=r["cuadro_path"],
            duracion_ms=r["duracion_ms"], modo=(r["modo"] or "activa"),
            carpeta_id=r["carpeta_id"],
            nombre=(r["nombre"] or r["archivo"]))
```

- [ ] **Step 5: Agregar `set_nombre` al backend Postgres**

Junto a `set_modo` (~línea 99):

```python
    def set_nombre(self, corrida_id: int, nombre: str) -> None:
        with self.cx.connection() as conn:
            conn.execute("UPDATE corridas.corrida SET nombre=%s WHERE id=%s",
                         (nombre, int(corrida_id)))
```

- [ ] **Step 6: Verificar import + suite completa (SQLite)**

Run: `python -c "import apu_tool.datos.pg.corridas_pg; print('ok')"`
Expected: imprime `ok` (sin errores de sintaxis/import).

Run: `python -m pytest tests/ -q`
Expected: toda la suite en verde (sin regresiones).

- [ ] **Step 7: Commit**

```bash
git add db/pg/corridas.sql apu_tool/datos/pg/corridas_pg.py
git commit -m "$(cat <<'EOF'
feat(corridas): columna nombre en Postgres + set_nombre (paridad dual-backend)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Servicio — nombre en armado, `renombrar_corrida`, exponer en vistas

**Files:**
- Modify: `apu_tool/servicio/corridas.py` (`construir_corrida_stream` ~44-63; `construir_corrida` ~98-107; `vista_corrida` ~204-209; `listar_corridas` ~295-299; nuevo `renombrar_corrida`)
- Test: `tests/test_nombre_corridas.py` (Modify)

**Interfaces:**
- Consumes: `nombre_desde_archivo` (Task 1), `set_nombre` (Tasks 2/3)
- Produces:
  - `construir_corrida_stream(alm, archivo, items, turno_def, use_ai, carpeta_id=None, nombre=None)`
  - `construir_corrida(alm, archivo, items, turno_def, use_ai, carpeta_id=None, nombre=None) -> int`
  - `renombrar_corrida(alm, corrida_id: int, nombre: str) -> Optional[dict]` (None si no existe; lanza `ValueError` si nombre vacío)
  - `vista_corrida(...)` y `listar_corridas(...)` incluyen `"nombre"`.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `tests/test_nombre_corridas.py`:

```python
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo, LicitacionItem
import apu_tool.servicio.corridas as svc
import pytest


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([Insumo("100", "CEMENTO", "KG", "MAT", 1000.0, "PRECIO IDU")])
    alm.apus.crear_apu(Apu("A1", "MURO", "M2", "DIURNO", "ESTR"),
                       [ApuComponent("A1", "DIURNO", "100", "CEMENTO", "KG", 2.0, 0.0)])
    sc = alm.carpetas.crear("Obra")
    return alm, sc


def _items():
    return [LicitacionItem(item="1", descripcion="muro", unidad="M2", cantidad=1.0,
                           precio_contractual=10000.0, shift="DIURNO")]


def test_construir_corrida_usa_nombre_explicito(tmp_path):
    alm, sc = _alm(tmp_path)
    cid = svc.construir_corrida(alm, "lic.xlsx", _items(), "DIURNO", False,
                                carpeta_id=sc, nombre="Presupuesto A")
    assert alm.corridas.get_corrida(cid).nombre == "Presupuesto A"


def test_construir_corrida_default_sin_extension(tmp_path):
    alm, sc = _alm(tmp_path)
    cid = svc.construir_corrida(alm, "Obra Lote SL5.xlsx", _items(), "DIURNO", False,
                                carpeta_id=sc)  # sin nombre
    assert alm.corridas.get_corrida(cid).nombre == "Obra Lote SL5"


def test_renombrar_corrida_ok(tmp_path):
    alm, sc = _alm(tmp_path)
    cid = svc.construir_corrida(alm, "lic.xlsx", _items(), "DIURNO", False, carpeta_id=sc)
    v = svc.renombrar_corrida(alm, cid, "  Nuevo nombre  ")
    assert v is not None and v["nombre"] == "Nuevo nombre"
    assert alm.corridas.get_corrida(cid).nombre == "Nuevo nombre"


def test_renombrar_corrida_inexistente_devuelve_none(tmp_path):
    alm, _ = _alm(tmp_path)
    assert svc.renombrar_corrida(alm, 999, "X") is None


def test_renombrar_corrida_vacio_lanza(tmp_path):
    alm, sc = _alm(tmp_path)
    cid = svc.construir_corrida(alm, "lic.xlsx", _items(), "DIURNO", False, carpeta_id=sc)
    with pytest.raises(ValueError):
        svc.renombrar_corrida(alm, cid, "   ")


def test_vista_y_listar_incluyen_nombre(tmp_path):
    alm, sc = _alm(tmp_path)
    cid = svc.construir_corrida(alm, "lic.xlsx", _items(), "DIURNO", False,
                                carpeta_id=sc, nombre="Mi corrida")
    assert svc.vista_corrida(alm, cid)["nombre"] == "Mi corrida"
    fila = next(f for f in svc.listar_corridas(alm) if f["id"] == cid)
    assert fila["nombre"] == "Mi corrida"
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/test_nombre_corridas.py -q`
Expected: FAIL — `construir_corrida()` no acepta `nombre`; `renombrar_corrida` no existe; falta clave `"nombre"`.

- [ ] **Step 3: Aceptar `nombre` en el armado (stream + wrapper)**

En `apu_tool/servicio/corridas.py`, firma y cuerpo de `construir_corrida_stream` (~línea 44):

```python
def construir_corrida_stream(alm: Almacen, archivo: str, items: list[LicitacionItem],
                             turno_def: str, use_ai: Optional[bool],
                             carpeta_id: Optional[int] = None,
                             nombre: Optional[str] = None):
```

Y dentro, al crear la `CorridaMeta` (~línea 60), calcular el nombre efectivo y pasarlo:

```python
    nombre_efectivo = (nombre or "").strip()[:120].strip() or nombre_desde_archivo(archivo)
    corrida_id = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en=datetime.now().isoformat(timespec="seconds"),
        archivo=archivo, turno_def=turno_def, use_ai=use_ai,
        estado="armando", cuadro_path=None, carpeta_id=carpeta_id,
        nombre=nombre_efectivo))
```

En el wrapper `construir_corrida` (~línea 98):

```python
def construir_corrida(alm: Almacen, archivo: str, items: list[LicitacionItem],
                      turno_def: str, use_ai: Optional[bool],
                      carpeta_id: Optional[int] = None,
                      nombre: Optional[str] = None) -> int:
    """Envoltorio no-stream: drena el generador e ignora el progreso; devuelve el id."""
    corrida_id = -1
    for evento, payload in construir_corrida_stream(alm, archivo, items, turno_def,
                                                    use_ai, carpeta_id, nombre):
        if evento == "done":
            corrida_id = payload["id"]
    return corrida_id
```

- [ ] **Step 4: Implementar `renombrar_corrida`**

En `apu_tool/servicio/corridas.py`, junto a `activar` (~línea 261):

```python
def renombrar_corrida(alm: Almacen, corrida_id: int, nombre: str) -> Optional[dict]:
    """Cambia el alias de una corrida. Devuelve la vista; None si no existe.
    Lanza ValueError si el nombre queda vacío. Permitido aun si está congelada
    (el nombre es etiqueta, no forma parte del snapshot)."""
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    limpio = (nombre or "").strip()[:120].strip()
    if not limpio:
        raise ValueError("El nombre no puede estar vacío.")
    alm.corridas.set_nombre(corrida_id, limpio)
    return vista_corrida(alm, corrida_id)
```

- [ ] **Step 5: Exponer `nombre` en `vista_corrida` y `listar_corridas`**

En `vista_corrida` (~línea 204), agregar `nombre` al dict:

```python
    return {
        "id": meta.id, "nombre": meta.nombre, "archivo": meta.archivo,
        "estado": meta.estado, "modo": meta.modo,
        "carpeta_id": meta.carpeta_id,
        "duracion_ms": meta.duracion_ms, "items": items,
        "totales": _totales(ensambles, rows),
    }
```

En `listar_corridas` (~línea 295), agregar `nombre` a la fila:

```python
        fila = {"id": meta.id, "nombre": meta.nombre, "archivo": meta.archivo,
                "creada_en": meta.creada_en,
                "estado": meta.estado, "modo": meta.modo, "duracion_ms": meta.duracion_ms,
                "carpeta_id": meta.carpeta_id,
                "n_items": len(rows), "n_revision": n_rev,
                "contractual": None, "costo": None, "margen": None, "margen_pct": None}
```

- [ ] **Step 6: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/test_nombre_corridas.py -q`
Expected: PASS (todos).

- [ ] **Step 7: Correr la suite completa (no romper nada)**

Run: `python -m pytest tests/ -q`
Expected: verde.

- [ ] **Step 8: Commit**

```bash
git add apu_tool/servicio/corridas.py tests/test_nombre_corridas.py
git commit -m "$(cat <<'EOF'
feat(corridas): nombre en armado + renombrar_corrida + exponer en vistas

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: API — `nombre` al crear + endpoint `POST /corridas/{cid}/renombrar`

**Files:**
- Modify: `apu_tool/servicio/rutas.py` (modelos ~40-51; `crear_corrida` ~121-148; `crear_corrida_stream` ~183-211; `crear_sample`/`crear_sample_stream` ~151-170 y ~214-234; nuevo endpoint tras `activar` ~284)
- Test: `tests/test_api_corridas.py` (Modify)

**Interfaces:**
- Consumes: `svc.construir_corrida(..., nombre=...)`, `svc.construir_corrida_stream(..., nombre=...)`, `svc.renombrar_corrida(...)` (Task 4)
- Produces: endpoint `POST /api/corridas/{cid}/renombrar` con body `{"nombre": str}`.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `tests/test_api_corridas.py`:

```python
def test_crear_corrida_con_nombre(tmp_path):
    cli, alm = _cliente(tmp_path)
    obra = cli.post("/api/carpetas", json={"nombre": "Obra"}).json()
    lic = _xlsx_lic(tmp_path)
    with open(lic, "rb") as f:
        cid = cli.post("/api/corridas",
                       data={"turno": "DIURNO", "use_ai": "false",
                             "carpeta_id": str(obra["id"]), "nombre": "Presupuesto Norte"},
                       files={"archivo": ("lic.xlsx", f, "application/octet-stream")}).json()["id"]
    assert alm.corridas.get_corrida(cid).nombre == "Presupuesto Norte"
    assert cli.get(f"/api/corridas/{cid}").json()["nombre"] == "Presupuesto Norte"


def test_crear_corrida_sin_nombre_usa_archivo_sin_ext(tmp_path):
    cli, alm = _cliente(tmp_path)
    obra = cli.post("/api/carpetas", json={"nombre": "Obra"}).json()
    lic = _xlsx_lic(tmp_path)
    with open(lic, "rb") as f:
        cid = cli.post("/api/corridas",
                       data={"turno": "DIURNO", "use_ai": "false", "carpeta_id": str(obra["id"])},
                       files={"archivo": ("lic.xlsx", f, "application/octet-stream")}).json()["id"]
    assert alm.corridas.get_corrida(cid).nombre == "lic"


def test_renombrar_corrida_endpoint(tmp_path):
    cli, alm = _cliente(tmp_path)
    obra = cli.post("/api/carpetas", json={"nombre": "Obra"}).json()
    lic = _xlsx_lic(tmp_path)
    with open(lic, "rb") as f:
        cid = cli.post("/api/corridas",
                       data={"turno": "DIURNO", "use_ai": "false", "carpeta_id": str(obra["id"])},
                       files={"archivo": ("lic.xlsx", f, "application/octet-stream")}).json()["id"]
    r = cli.post(f"/api/corridas/{cid}/renombrar", json={"nombre": "Obra Renombrada"})
    assert r.status_code == 200 and r.json()["nombre"] == "Obra Renombrada"
    assert alm.corridas.get_corrida(cid).nombre == "Obra Renombrada"


def test_renombrar_corrida_vacio_400(tmp_path):
    cli, _ = _cliente(tmp_path)
    obra = cli.post("/api/carpetas", json={"nombre": "Obra"}).json()
    lic = _xlsx_lic(tmp_path)
    with open(lic, "rb") as f:
        cid = cli.post("/api/corridas",
                       data={"turno": "DIURNO", "use_ai": "false", "carpeta_id": str(obra["id"])},
                       files={"archivo": ("lic.xlsx", f, "application/octet-stream")}).json()["id"]
    assert cli.post(f"/api/corridas/{cid}/renombrar", json={"nombre": "   "}).status_code == 400


def test_renombrar_corrida_inexistente_404(tmp_path):
    cli, _ = _cliente(tmp_path)
    assert cli.post("/api/corridas/999/renombrar", json={"nombre": "X"}).status_code == 404
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/test_api_corridas.py -q`
Expected: FAIL — el endpoint `/renombrar` no existe (404 en el flujo OK) y `nombre` no viaja.

- [ ] **Step 3: Declarar el modelo del body de renombrar**

En `apu_tool/servicio/rutas.py`, junto a `MoverCorridaIn` (~línea 50):

```python
class MoverCorridaIn(BaseModel):
    carpeta_id: int


class RenombrarCorridaIn(BaseModel):
    nombre: str
```

- [ ] **Step 4: Pasar `nombre` en `crear_corrida` y `crear_corrida_stream`**

En `crear_corrida` (~línea 121), agregar el parámetro Form y pasarlo al servicio:

```python
@router.post("/corridas")
async def crear_corrida(turno: str = Form(config.SHIFT_DIURNO),
                        use_ai: Optional[bool] = Form(None),
                        carpeta_id: int = Form(...),
                        nombre: Optional[str] = Form(None),
                        archivo: UploadFile = File(...),
                        alm: Almacen = Depends(get_almacen),
                        _: object = Depends(requiere_rol("consulta"))):
```

Y la llamada al servicio (~línea 146):

```python
    cid = svc.construir_corrida(alm, archivo.filename or "licitacion", items, turno, use_ai,
                                carpeta_id=carpeta_id, nombre=nombre)
```

En `crear_corrida_stream` (~línea 183), lo mismo:

```python
@router.post("/corridas/stream")
async def crear_corrida_stream(turno: str = Form(config.SHIFT_DIURNO),
                               use_ai: Optional[bool] = Form(None),
                               carpeta_id: int = Form(...),
                               nombre: Optional[str] = Form(None),
                               archivo: UploadFile = File(...),
                               alm: Almacen = Depends(get_almacen),
                               _: object = Depends(requiere_rol("consulta"))):
```

Y la llamada (~línea 208):

```python
    gen = svc.construir_corrida_stream(alm, archivo.filename or "licitacion", items, turno, use_ai,
                                       carpeta_id=carpeta_id, nombre=nombre)
```

- [ ] **Step 5: Nombre "Ejemplo" en los endpoints de sample**

En `crear_sample` (~línea 168):

```python
    cid = svc.construir_corrida(alm, "ejemplo.xlsx", items, config.SHIFT_DIURNO, False,
                                carpeta_id=sc, nombre="Ejemplo")
```

En `crear_sample_stream` (~línea 231):

```python
    gen = svc.construir_corrida_stream(alm, "ejemplo.xlsx", items, config.SHIFT_DIURNO, False,
                                       carpeta_id=sc, nombre="Ejemplo")
```

- [ ] **Step 6: Agregar el endpoint `renombrar`**

En `apu_tool/servicio/rutas.py`, después de `activar` (~línea 284):

```python
@router.post("/corridas/{cid}/renombrar")
def renombrar(cid: int, body: RenombrarCorridaIn,
              alm: Almacen = Depends(get_almacen),
              _: object = Depends(requiere_rol("consulta"))):
    try:
        v = svc.renombrar_corrida(alm, cid, body.nombre)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if v is None:
        raise HTTPException(status_code=404, detail="Corrida no encontrada.")
    return v
```

- [ ] **Step 7: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/test_api_corridas.py -q`
Expected: PASS (incluye los 5 nuevos).

- [ ] **Step 8: Commit**

```bash
git add apu_tool/servicio/rutas.py tests/test_api_corridas.py
git commit -m "$(cat <<'EOF'
feat(api): nombre al crear corrida + POST /corridas/{id}/renombrar

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Frontend — tipos + cliente API

**Files:**
- Modify: `web/src/lib/tipos.ts` (`CorridaResumen` ~123-137; `CorridaDetalle` ~152-161)
- Modify: `web/src/api/corridas.ts` (nueva función `renombrarCorrida`)

**Interfaces:**
- Produces:
  - `CorridaResumen.nombre: string`, `CorridaDetalle.nombre: string`
  - `renombrarCorrida(id: number, nombre: string): Promise<CorridaDetalle>`

- [ ] **Step 1: Agregar `nombre` a los tipos**

En `web/src/lib/tipos.ts`, en `CorridaResumen` (después de `id`, línea 124):

```typescript
export interface CorridaResumen {
  id: number;
  nombre: string;
  archivo: string;
  creada_en: string;
  estado: string;
  modo: string;
  n_items: number;
  n_revision: number;
  duracion_ms: number | null;
  contractual: number | null;
  costo: number | null;
  margen: number | null;
  margen_pct: number | null;
  carpeta_id: number | null;
}
```

Y en `CorridaDetalle` (después de `id`, línea 153):

```typescript
export interface CorridaDetalle {
  id: number;
  nombre: string;
  archivo: string;
  estado: string;
  modo: string;
  items: ItemCuadro[];
  totales: Totales;
  duracion_ms: number | null;
  carpeta_id: number | null;
}
```

- [ ] **Step 2: Agregar `renombrarCorrida` al cliente API**

En `web/src/api/corridas.ts`, después de `eliminarCorrida` (~línea 30):

```typescript
export function renombrarCorrida(id: number, nombre: string): Promise<CorridaDetalle> {
  return apiPost<CorridaDetalle>(`/corridas/${id}/renombrar`, { nombre });
}
```

- [ ] **Step 3: Verificar que el proyecto compila (tsc)**

Run: `cd web && npx tsc --noEmit`
Expected: sin errores (los tipos nuevos son opcionales de consumir todavía).

- [ ] **Step 4: Commit**

```bash
git add web/src/lib/tipos.ts web/src/api/corridas.ts
git commit -m "$(cat <<'EOF'
feat(web): tipo nombre en corridas + api renombrarCorrida

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Frontend — campo "Nombre" con precarga en el alta

**Files:**
- Modify: `web/src/pages/CorridasInicio.tsx` (estado ~11-13; handler del file input; JSX del campo Archivo ~118-131; `handleArmar` ~89-92; `styles`)
- Test: `web/src/pages/CorridasInicio.test.tsx` (Modify)

**Interfaces:**
- Consumes: nada nuevo (envía `nombre` en el `FormData`, ya consumido por Task 5).

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `web/src/pages/CorridasInicio.test.tsx`:

```typescript
test("al elegir archivo, precarga el Nombre sin extensión", async () => {
  const { default: CorridasInicio } = await import("./CorridasInicio");
  render(<MemoryRouter><CorridasInicio /></MemoryRouter>);
  await screen.findByText("Calle 13");

  const fileInput = document.getElementById("archivo") as HTMLInputElement;
  const file = new File(["x"], "Licitacion Calle 13.xlsx", { type: "application/octet-stream" });
  fireEvent.change(fileInput, { target: { files: [file] } });

  const nombreInput = screen.getByLabelText("Nombre") as HTMLInputElement;
  await waitFor(() => expect(nombreInput.value).toBe("Licitacion Calle 13"));
});

test("no pisa el Nombre si el usuario ya lo editó", async () => {
  const { default: CorridasInicio } = await import("./CorridasInicio");
  render(<MemoryRouter><CorridasInicio /></MemoryRouter>);
  await screen.findByText("Calle 13");

  const nombreInput = screen.getByLabelText("Nombre") as HTMLInputElement;
  fireEvent.change(nombreInput, { target: { value: "Mi alias" } });

  const fileInput = document.getElementById("archivo") as HTMLInputElement;
  const file = new File(["x"], "otra.xlsx", { type: "application/octet-stream" });
  fireEvent.change(fileInput, { target: { files: [file] } });

  expect(nombreInput.value).toBe("Mi alias");
});
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `cd web && npx vitest run src/pages/CorridasInicio.test.tsx`
Expected: FAIL — no existe el input con label "Nombre".

- [ ] **Step 3: Estado + helper + handler del archivo**

En `web/src/pages/CorridasInicio.tsx`, agregar estado junto a los existentes (~línea 12):

```tsx
  const [usarIA, setUsarIA] = useState(true);
  const [cargando, setCargando] = useState(false);
  const [nombre, setNombre] = useState("");
  const [nombreTocado, setNombreTocado] = useState(false);
```

Agregar el helper y el handler (antes de `handleArmar`, ~línea 78):

```tsx
  function stripExt(name: string): string {
    const i = name.lastIndexOf(".");
    return (i > 0 ? name.slice(0, i) : name).trim();
  }

  function handleArchivoChange(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (f && !nombreTocado) setNombre(stripExt(f.name));
  }
```

- [ ] **Step 4: Enviar `nombre` en el FormData**

En `handleArmar` (~línea 89), tras `form.append("carpeta_id", ...)`:

```tsx
    const form = new FormData();
    form.append("archivo", archivo);
    form.append("use_ai", String(usarIA));
    form.append("carpeta_id", String(carpetaDestino));
    form.append("nombre", nombre.trim());
```

- [ ] **Step 5: JSX del campo Nombre + `onChange` del archivo**

En el campo Archivo (~línea 123), agregar `onChange={handleArchivoChange}` al input file:

```tsx
            <input
              id="archivo"
              ref={fileRef}
              type="file"
              accept=".xlsx,.csv"
              onChange={handleArchivoChange}
              style={styles.inputFile}
              disabled={cargando}
            />
```

E inmediatamente después de ese `<div style={styles.campo}>` del archivo (antes del bloque "Usar IA", ~línea 132), agregar:

```tsx
          {/* Nombre */}
          <div style={styles.campo}>
            <label style={styles.label} htmlFor="nombre">
              Nombre
            </label>
            <input
              id="nombre"
              type="text"
              value={nombre}
              onChange={(e) => { setNombre(e.target.value); setNombreTocado(true); }}
              placeholder="Nombre de la corrida"
              style={styles.input}
              disabled={cargando}
            />
          </div>
```

- [ ] **Step 6: Estilo `input`**

En el objeto `styles` (~línea 244, junto a `inputFile`):

```tsx
  input: {
    fontSize: "12px",
    color: "#2d3748",
    padding: "4px 6px",
    borderRadius: "4px",
    border: "1px solid #cbd5e0",
    background: "#fff",
  },
```

- [ ] **Step 7: Correr los tests para verificar que pasan**

Run: `cd web && npx vitest run src/pages/CorridasInicio.test.tsx`
Expected: PASS (incluye los 2 nuevos y el existente de "Armar deshabilitado").

- [ ] **Step 8: Commit**

```bash
git add web/src/pages/CorridasInicio.tsx web/src/pages/CorridasInicio.test.tsx
git commit -m "$(cat <<'EOF'
feat(web): campo Nombre con precarga sin extensión en el alta de corrida

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Frontend — mostrar `nombre` y acción "Renombrar" en Mis corridas

**Files:**
- Modify: `web/src/pages/MisCorridas.tsx` (import ~4; handler nuevo; display ~340; prompts de eliminar/mover ~105-108, ~157-163; botón en la celda de acciones ~370-387)
- Test: `web/src/pages/MisCorridas.test.tsx` (Modify)

**Interfaces:**
- Consumes: `renombrarCorrida` y `CorridaResumen.nombre` (Task 6).

- [ ] **Step 1: Escribir el test que falla**

En `web/src/pages/MisCorridas.test.tsx`, actualizar el mock de `@/api/corridas` para incluir `nombre` en la corrida y la función `renombrarCorrida`:

```typescript
vi.mock("@/api/corridas", () => ({
  listarCorridas: vi.fn(async () => [{
    id: 1, nombre: "lic.xlsx", archivo: "lic.xlsx", creada_en: "2026-07-08T10:00:00",
    estado: "en_revision", modo: "activa", n_items: 2, n_revision: 1, duracion_ms: 1000,
    contractual: 4000000, costo: 3675000, margen: 325000, margen_pct: 0.08125,
    carpeta_id: 1,
  }]),
  eliminarCorrida: vi.fn(),
  renombrarCorrida: vi.fn(async () => ({})),
  descargarPlantillaLicitacion: vi.fn(),
}));
```

Y agregar el test:

```typescript
test("Renombrar corrida: al hacer clic y confirmar, llama renombrarCorrida(1, nuevo)", async () => {
  const { default: MisCorridas } = await import("./MisCorridas");
  const { renombrarCorrida } = await import("@/api/corridas");

  const promptSpy = vi.spyOn(window, "prompt").mockReturnValue("Obra Norte");

  render(
    <MemoryRouter initialEntries={["/corridas?carpeta=1"]}>
      <MisCorridas />
    </MemoryRouter>
  );

  await waitFor(() => expect(screen.getByText("lic.xlsx")).toBeTruthy());
  const row = screen.getByText("lic.xlsx").closest("tr")!;
  const btnRenombrar = within(row).getByRole("button", { name: /renombrar/i });
  fireEvent.click(btnRenombrar);

  await waitFor(() => {
    expect(renombrarCorrida).toHaveBeenCalledWith(1, "Obra Norte");
  });

  promptSpy.mockRestore();
});
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `cd web && npx vitest run src/pages/MisCorridas.test.tsx`
Expected: FAIL — no existe el botón "Renombrar".

- [ ] **Step 3: Importar `renombrarCorrida`**

En `web/src/pages/MisCorridas.tsx`, línea 4:

```tsx
import { listarCorridas, eliminarCorrida, renombrarCorrida, descargarPlantillaLicitacion } from "@/api/corridas";
```

- [ ] **Step 4: Handler `handleRenombrarCorrida`**

Junto a `handleMoverCorrida` (~línea 149):

```tsx
  async function handleRenombrarCorrida(e: React.MouseEvent, corrida: CorridaResumen) {
    e.stopPropagation();
    const nuevo = window.prompt("Nuevo nombre", corrida.nombre);
    if (!nuevo?.trim() || nuevo.trim() === corrida.nombre) return;
    try {
      await renombrarCorrida(corrida.id, nuevo.trim());
      toast.success(`Corrida renombrada a "${nuevo.trim()}"`);
      cargar();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Error al renombrar");
    }
  }
```

- [ ] **Step 5: Mostrar `nombre` (con `archivo` como tooltip) y actualizar prompts**

En el display de la fila (~línea 340):

```tsx
                        <span style={styles.nombre} title={c.archivo}>{c.nombre}</span>
```

En `handleEliminar` (~línea 105-108), usar `c.nombre`:

```tsx
    if (!window.confirm(`¿Eliminar la corrida "${corrida.nombre}"?`)) return;
    try {
      await eliminarCorrida(corrida.id);
      toast.success(`Corrida "${corrida.nombre}" eliminada`);
```

En `handleMoverCorrida` (~línea 157-163), usar `corrida.nombre`:

```tsx
    const resp = window.prompt(`Mover "${corrida.nombre}" a:\n${opciones}\n\nEscribe el número:`);
    if (!resp?.trim()) return;
    const idx = parseInt(resp.trim(), 10) - 1;
    if (isNaN(idx) || idx < 0 || idx >= destinos.length) return;
    try {
      await moverCorrida(corrida.id, destinos[idx].id);
      toast.success(`Corrida "${corrida.nombre}" movida a "${destinos[idx].etiqueta}"`);
```

- [ ] **Step 6: Botón "Renombrar" en la celda de acciones**

En la celda de acciones (~línea 370), antes del botón "Mover", gateado por `puedeEditar`:

```tsx
                      <td style={{ ...styles.td, ...styles.tdAccion }}>
                        {puedeEditar && (
                          <button
                            style={styles.btnMover}
                            onClick={(e) => handleRenombrarCorrida(e, c)}
                            title="Renombrar corrida"
                          >
                            Renombrar
                          </button>
                        )}
                        {puedeEditar && (
                          <button
                            style={styles.btnMover}
                            onClick={(e) => handleMoverCorrida(e, c)}
                            title="Mover corrida"
                          >
                            Mover
                          </button>
                        )}
                        <button
                          style={styles.btnEliminar}
                          onClick={(e) => handleEliminar(e, c)}
                          title="Eliminar corrida"
                        >
                          Eliminar
                        </button>
                      </td>
```

- [ ] **Step 7: Correr el test para verificar que pasa**

Run: `cd web && npx vitest run src/pages/MisCorridas.test.tsx`
Expected: PASS (incluye el nuevo de renombrar; los existentes siguen verdes porque `nombre === "lic.xlsx"`).

- [ ] **Step 8: Verificar tsc + toda la suite frontend**

Run: `cd web && npx tsc --noEmit && npx vitest run`
Expected: sin errores de tipos; todos los tests verdes.

- [ ] **Step 9: Commit**

```bash
git add web/src/pages/MisCorridas.tsx web/src/pages/MisCorridas.test.tsx
git commit -m "$(cat <<'EOF'
feat(web): mostrar nombre de corrida + acción Renombrar en Mis corridas

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Verificación final (tras todas las tareas)

- [ ] Backend: `python -m pytest tests/ -q` → verde.
- [ ] Frontend: `cd web && npx tsc --noEmit && npx vitest run` → verde.
- [ ] Manual (opcional, `python run_gui.py` o la web): crear corrida (el Nombre se precarga sin extensión y es editable, admite espacios); renombrar desde "Mis corridas"; verificar que el archivo original sigue como tooltip.

## Self-Review (cobertura del spec)

- Default sin extensión → Task 1 (`nombre_desde_archivo`) + Task 4 (armado) + Task 7 (precarga UI).
- Conservar `archivo` (procedencia) → Tasks 2/3 (columna aparte) + Task 8 (`title={c.archivo}`).
- Crear con nombre → Tasks 4/5/7.
- Renombrar después → Tasks 4/5/8.
- Espacios permitidos → sin sanitización más allá de trim (Tasks 4/7/8).
- Renombrar en congelada permitido → `renombrar_corrida` no checa `modo` (Task 4).
- Migración dual-backend + backfill → Tasks 2 (SQLite) y 3 (Postgres).
- Cero regresión → fallback a `archivo` en `_row_to_meta`; suites verdes.
