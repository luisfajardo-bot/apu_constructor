> Espejo automático — no editar aquí. Fuente: `docs/superpowers/plans/2026-07-27-ocultar-insumos-duplicados-apu.md`

# Ocultar del catálogo de insumos los códigos duplicados de APU — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ocultar (no borrar) del catálogo de insumos los ~1123 códigos que son "ecos" aplanados de un APU y ya no tienen ningún componente usándolos como insumo real, sin afectar nunca el costeo (`pricing.py`) ni tocar las 29 colisiones reales.

**Architecture:** Columna aditiva `oculto` en `insumos` (dual-backend, mismo patrón que `modo`/`snapshot_json` en corridas). Una migración idempotente y auditada (`ocultar_apus_duplicados`, en `apu_tool/servicio/insumos_ocultos.py`, mismo estilo que `servicio/subapus.py::marcar_subapus`) la puebla. Los métodos de lectura orientados a humanos/IA (`list_insumos`, `search_insumos`, `search_insumos_por_palabras`, `grupos`, `fuentes`) excluyen `oculto=true`; los de lookup exacto por código que usa el costeo (`get_candidatos`, `get_candidatos_bulk`, `get_insumo_por_id`, `price_history`) quedan intactos.

**Tech Stack:** Python 3 (SQLite + Postgres vía `psycopg`), `pytest`.

## Global Constraints

- **Ocultar, no borrar.** Ningún `DELETE`; solo un flag reversible.
- **El costeo nunca depende de `oculto`:** `get_candidatos`, `get_candidatos_bulk`,
  `get_insumo_por_id`, `price_history` no se tocan.
- **Regla de ocultamiento exacta:** se oculta la fila de `insumos` (por `id`) solo si
  (a) su código es también código de un APU, (b) su nombre normalizado coincide con el
  nombre normalizado de ese APU, y (c) ningún componente `apu_componentes` tiene hoy
  `tipo='insumo'` con ese mismo `insumo_codigo` + `insumo_nombre` normalizado. Si el
  nombre no coincide (colisión real) o todavía hay un uso real, **no se oculta**.
- **Sin dependencias nuevas.**
- **Español** en nombres de funciones, comentarios y mensajes.
- **Sin `incluir_ocultos` ni vista de "mostrar ocultos"** — decidido explícitamente que
  no, por ahora (spec, Fuera de alcance).
- **No tocar `nucleo/models.py`** — `oculto` no se expone en el dataclass `Insumo` ni en
  ninguna respuesta de API.
- **Commits:** terminar el mensaje con `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.

## Preparación

Trabajar en una rama nueva desde `master`: `git checkout -b feat/ocultar-insumos-duplicados-apu`.

---

### Task 1: Esquema — columna `oculto` (SQLite + Postgres)

**Files:**
- Modify: `db/precios.sql` (agregar columna a `insumos`)
- Modify: `db/pg/precios.sql` (agregar columna + `ALTER ... IF NOT EXISTS`)
- Modify: `apu_tool/datos/precios_db.py::init_schema` (migración idempotente SQLite)
- Test: `tests/test_precios_db.py` (Modify — agregar test)

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_precios_db.py`:

```python
def test_insumo_nuevo_no_esta_oculto_por_defecto(tmp_path):
    from apu_tool.datos.precios_db import PreciosDB
    from apu_tool.nucleo.models import Insumo
    repo = PreciosDB(tmp_path / "p.db")
    repo.init_schema()
    iid = repo.crear_insumo(Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU"))
    with repo.connect() as conn:
        r = conn.execute("SELECT oculto FROM insumos WHERE id=?", (iid,)).fetchone()
    assert r["oculto"] == 0
```

(Si `tests/test_precios_db.py` no existe todavía como archivo con imports propios,
crear los imports `from apu_tool.datos.precios_db import PreciosDB` y
`from apu_tool.nucleo.models import Insumo` en el encabezado del archivo en vez de
dentro de la función, siguiendo el estilo del resto del archivo.)

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_precios_db.py::test_insumo_nuevo_no_esta_oculto_por_defecto -v`
Expected: FAIL con `sqlite3.OperationalError: no such column: oculto`.

- [ ] **Step 3: Agregar la columna al esquema canónico SQLite**

En `db/precios.sql`, en la tabla `insumos` (después de la línea `grupo       TEXT,` y
antes de `UNIQUE (codigo, nombre_norm)`), agregar:

```sql
    oculto      INTEGER NOT NULL DEFAULT 0,   -- 1 = eco de un APU sin uso real; se filtra, nunca se borra
```

- [ ] **Step 4: Migración idempotente SQLite**

En `apu_tool/datos/precios_db.py`, en `init_schema` (~línea 45-50), agregar el chequeo
de columna para `insumos` junto al de `insumo_precios` ya existente:

```python
    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(_load_schema())
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(insumo_precios)").fetchall()}
            if "creado_por" not in cols:
                conn.execute("ALTER TABLE insumo_precios ADD COLUMN creado_por TEXT")
            insumos_cols = {r["name"] for r in conn.execute("PRAGMA table_info(insumos)").fetchall()}
            if "oculto" not in insumos_cols:
                conn.execute("ALTER TABLE insumos ADD COLUMN oculto INTEGER NOT NULL DEFAULT 0")
```

- [ ] **Step 5: Esquema Postgres**

En `db/pg/precios.sql`, en `CREATE TABLE IF NOT EXISTS precios.insumos` (después de
`grupo       TEXT,` y antes de `UNIQUE (codigo, nombre_norm)`), agregar:

```sql
    oculto      BOOLEAN NOT NULL DEFAULT FALSE,
```

Y agregar, después del bloque de `CREATE TABLE` de `precios.insumos` (mismo patrón que
`corridas.sql` usa para `modo`/`snapshot_json` — una línea de migración idempotente
suelta en el script):

```sql
ALTER TABLE precios.insumos ADD COLUMN IF NOT EXISTS oculto BOOLEAN NOT NULL DEFAULT FALSE;
```

(Postgres no necesita cambios en `precios_pg.py::init_schema` — ya delega todo el DDL,
incluida esta migración, a `self.cx.ejecutar_migracion(SCHEMA_PATH.read_text(...))`.)

- [ ] **Step 6: Correr el test para verificar que pasa**

Run: `python -m pytest tests/test_precios_db.py::test_insumo_nuevo_no_esta_oculto_por_defecto -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add db/precios.sql db/pg/precios.sql apu_tool/datos/precios_db.py tests/test_precios_db.py
git commit -m "$(cat <<'EOF'
feat(insumos): columna oculto en el catálogo (dual-backend, aditiva)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `set_oculto` + `todos_no_ocultos` en el repositorio de precios

**Files:**
- Modify: `apu_tool/datos/precios_db.py` (agregar los dos métodos)
- Modify: `apu_tool/datos/pg/precios_pg.py` (agregar los dos métodos)
- Test: `tests/test_precios_db.py` (Modify — agregar tests)

**Interfaces:**
- Produces: `PreciosDB.set_oculto(insumo_id: int, oculto: bool, conn=None) -> None`,
  `PreciosDB.todos_no_ocultos() -> list[tuple[int, str, str]]` (id, codigo, nombre),
  y los mismos dos métodos en `PreciosPg` con igual firma.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `tests/test_precios_db.py`:

```python
def test_set_oculto_y_todos_no_ocultos(tmp_path):
    from apu_tool.datos.precios_db import PreciosDB
    from apu_tool.nucleo.models import Insumo
    repo = PreciosDB(tmp_path / "p.db")
    repo.init_schema()
    iid1 = repo.crear_insumo(Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU"))
    iid2 = repo.crear_insumo(Insumo("200", "ARENA", "M3", "MAT", 500, "PRECIO IDU"))

    repo.set_oculto(iid1, True)

    no_ocultos = {(iid, cod) for iid, cod, _nom in repo.todos_no_ocultos()}
    assert (iid1, "100") not in no_ocultos
    assert (iid2, "200") in no_ocultos


def test_set_oculto_con_conn_no_autocommite(tmp_path):
    import pytest
    from apu_tool.datos.almacen import Almacen
    from apu_tool.nucleo.models import Insumo
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    iid = alm.precios.crear_insumo(Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU"))
    with pytest.raises(RuntimeError):
        with alm.transaccion("precios") as conn:
            alm.precios.set_oculto(iid, True, conn=conn)
            raise RuntimeError("aborta")
    no_ocultos = {iid_ for iid_, _c, _n in alm.precios.todos_no_ocultos()}
    assert iid in no_ocultos   # el rollback dejó el insumo NO oculto
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/test_precios_db.py -k "oculto" -v`
Expected: FAIL con `AttributeError: 'PreciosDB' object has no attribute 'set_oculto'`.

- [ ] **Step 3: Implementar en `precios_db.py`**

Agregar al final de `apu_tool/datos/precios_db.py` (después de `set_meta`, antes de la
sección `# ---- lectura ----`, o al final del archivo — cualquiera de las dos
ubicaciones es correcta, seguir el orden de escritura/lectura ya existente en el
archivo):

```python
    def set_oculto(self, insumo_id: int, oculto: bool,
                   conn: Optional[sqlite3.Connection] = None) -> None:
        sql = "UPDATE insumos SET oculto=? WHERE id=?"
        args = (1 if oculto else 0, int(insumo_id))
        if conn is not None:
            conn.execute(sql, args)
            return
        with self.connect() as c:
            c.execute(sql, args)

    def todos_no_ocultos(self) -> list[tuple[int, str, str]]:
        """(id, codigo, nombre) de todos los insumos con oculto=0."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, codigo, nombre FROM insumos WHERE oculto = 0").fetchall()
        return [(r["id"], r["codigo"], r["nombre"]) for r in rows]
```

- [ ] **Step 4: Implementar en `precios_pg.py`**

Agregar al final de `apu_tool/datos/pg/precios_pg.py`:

```python
    def set_oculto(self, insumo_id: int, oculto: bool, conn=None) -> None:
        sql = "UPDATE precios.insumos SET oculto=%s WHERE id=%s"
        args = (bool(oculto), int(insumo_id))
        if conn is not None:
            conn.execute(sql, args)
            return
        with self.cx.connection() as c:
            c.execute(sql, args)

    def todos_no_ocultos(self) -> list[tuple[int, str, str]]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT id, codigo, nombre FROM precios.insumos WHERE oculto = FALSE").fetchall()
        return [(r["id"], r["codigo"], r["nombre"]) for r in rows]
```

- [ ] **Step 5: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/test_precios_db.py -v`
Expected: PASS (todos, incluidos los nuevos).

- [ ] **Step 6: Commit**

```bash
git add apu_tool/datos/precios_db.py apu_tool/datos/pg/precios_pg.py tests/test_precios_db.py
git commit -m "$(cat <<'EOF'
feat(insumos): set_oculto + todos_no_ocultos en ambos backends

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `pares_insumo_en_uso` en el repositorio de APUs

**Files:**
- Modify: `apu_tool/datos/apus_db.py`
- Modify: `apu_tool/datos/pg/apus_pg.py`
- Test: `tests/test_subapus_migracion.py` (Modify — agregar test) o
  `tests/test_apus_detalle_subapu.py` si resulta más natural agregarlo ahí; usar el
  primero que ya importe `Almacen`/`Apu`/`ApuComponent` con menos fricción.

**Interfaces:**
- Produces: `ApusDB.pares_insumo_en_uso() -> list[tuple[str, str]]` (insumo_codigo,
  insumo_nombre, sin normalizar, uno por combinación distinta), y el mismo método en
  `ApusPg`.

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_subapus_migracion.py`:

```python
def test_pares_insumo_en_uso(tmp_path):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("A", "COMP", "M2", "DIURNO")])
    alm.apus.insert_components([
        ApuComponent("A", "DIURNO", "100", "CEMENTO", "KG", 2.0, 900),
        ApuComponent("A", "DIURNO", "200", "ARENA", "M3", 1.0, 500),
    ])
    pares = set(alm.apus.pares_insumo_en_uso())
    assert ("100", "CEMENTO") in pares
    assert ("200", "ARENA") in pares
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_subapus_migracion.py::test_pares_insumo_en_uso -v`
Expected: FAIL con `AttributeError: 'ApusDB' object has no attribute 'pares_insumo_en_uso'`.

- [ ] **Step 3: Implementar en `apus_db.py`**

Agregar al final de `apu_tool/datos/apus_db.py`, cerca de
`componentes_subapu_candidatos` (mismo estilo):

```python
    def pares_insumo_en_uso(self) -> list[tuple[str, str]]:
        """(insumo_codigo, insumo_nombre) distintos de cada componente tipo='insumo'."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT insumo_codigo, insumo_nombre FROM apu_componentes "
                "WHERE tipo = 'insumo'"
            ).fetchall()
        return [(r["insumo_codigo"], r["insumo_nombre"]) for r in rows]
```

- [ ] **Step 4: Implementar en `apus_pg.py`**

Agregar al final de `apu_tool/datos/pg/apus_pg.py`, cerca de
`componentes_subapu_candidatos`:

```python
    def pares_insumo_en_uso(self) -> list[tuple[str, str]]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT insumo_codigo, insumo_nombre FROM apus.apu_componentes "
                "WHERE tipo = 'insumo'"
            ).fetchall()
        return [(r["insumo_codigo"], r["insumo_nombre"]) for r in rows]
```

- [ ] **Step 5: Correr el test para verificar que pasa**

Run: `python -m pytest tests/test_subapus_migracion.py -v`
Expected: PASS (todos).

- [ ] **Step 6: Commit**

```bash
git add apu_tool/datos/apus_db.py apu_tool/datos/pg/apus_pg.py tests/test_subapus_migracion.py
git commit -m "$(cat <<'EOF'
feat(apus): pares_insumo_en_uso — pares código+nombre usados como insumo hoy

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Filtrar `oculto` en las lecturas orientadas a humanos/IA

**Files:**
- Modify: `apu_tool/datos/precios_db.py` (`list_insumos`, `search_insumos`,
  `search_insumos_por_palabras`, `grupos`, `fuentes`)
- Modify: `apu_tool/datos/pg/precios_pg.py` (los mismos cinco métodos)
- Test: `tests/test_precios_db.py` (Modify — agregar tests)

**Interfaces:**
- Consumes: columna `oculto` (Task 1)
- Produces: los cinco métodos ahora excluyen filas `oculto=true` por defecto;
  `get_candidatos`, `get_candidatos_bulk`, `get_insumo_por_id`, `price_history`
  **no cambian**.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `tests/test_precios_db.py`:

```python
def _repo_con_uno_oculto(tmp_path):
    from apu_tool.datos.precios_db import PreciosDB
    from apu_tool.nucleo.models import Insumo
    repo = PreciosDB(tmp_path / "p.db")
    repo.init_schema()
    iid_oculto = repo.crear_insumo(Insumo("8044", "CODO EN ACERO", "UND", "MAT", 100, "PRECIO IDU"))
    repo.crear_insumo(Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU"))
    repo.set_oculto(iid_oculto, True)
    return repo, iid_oculto


def test_list_insumos_excluye_ocultos(tmp_path):
    repo, iid_oculto = _repo_con_uno_oculto(tmp_path)
    items, total = repo.list_insumos()
    assert iid_oculto not in {i.id for i in items}
    assert total == 1


def test_search_insumos_excluye_ocultos(tmp_path):
    repo, iid_oculto = _repo_con_uno_oculto(tmp_path)
    resultados = repo.search_insumos("codo")
    assert iid_oculto not in {i.id for i in resultados}


def test_search_insumos_por_palabras_excluye_ocultos(tmp_path):
    repo, iid_oculto = _repo_con_uno_oculto(tmp_path)
    resultados = repo.search_insumos_por_palabras(["acero"])
    assert iid_oculto not in {i.id for i in resultados}


def test_get_candidatos_encuentra_ocultos(tmp_path):
    """El costeo nunca debe depender de si el insumo está oculto."""
    repo, iid_oculto = _repo_con_uno_oculto(tmp_path)
    candidatos = repo.get_candidatos("8044")
    assert iid_oculto in {i.id for i in candidatos}


def test_get_insumo_por_id_encuentra_ocultos(tmp_path):
    repo, iid_oculto = _repo_con_uno_oculto(tmp_path)
    assert repo.get_insumo_por_id(iid_oculto) is not None
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/test_precios_db.py -k "oculto" -v`
Expected: FAIL en `test_list_insumos_excluye_ocultos`,
`test_search_insumos_excluye_ocultos` y `test_search_insumos_por_palabras_excluye_ocultos`
(el insumo oculto sigue apareciendo); `test_get_candidatos_encuentra_ocultos` y
`test_get_insumo_por_id_encuentra_ocultos` deberían pasar ya (no hay que tocar esos
métodos).

- [ ] **Step 3: Editar `precios_db.py`**

En `list_insumos` (~línea 222-253), agregar `oculto` como primera condición fija del
`where`, justo antes del bloque `if q:`:

```python
        where, params = ["i.oculto = 0"], []
```

(reemplaza la línea `where, params = [], []` existente.)

En `search_insumos` (~línea 270-276), cambiar:

```python
    def search_insumos(self, texto: str, limit: int = 20) -> list[Insumo]:
        like = f"%{normalizar(texto)}%"
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id FROM insumos WHERE nombre_norm LIKE ? OR UPPER(codigo) LIKE ? LIMIT ?",
                (like, like, limit)).fetchall()
        return [self.get_insumo_por_id(r["id"]) for r in rows]
```

por:

```python
    def search_insumos(self, texto: str, limit: int = 20) -> list[Insumo]:
        like = f"%{normalizar(texto)}%"
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id FROM insumos WHERE (nombre_norm LIKE ? OR UPPER(codigo) LIKE ?) "
                "AND oculto = 0 LIMIT ?",
                (like, like, limit)).fetchall()
        return [self.get_insumo_por_id(r["id"]) for r in rows]
```

En `search_insumos_por_palabras` (~línea 278-288), cambiar la línea de la query de:

```python
            rows = conn.execute(
                f"SELECT id FROM insumos WHERE {clauses} LIMIT ?", params).fetchall()
```

a:

```python
            rows = conn.execute(
                f"SELECT id FROM insumos WHERE ({clauses}) AND oculto = 0 LIMIT ?", params).fetchall()
```

En `grupos` (~línea 255-260), cambiar:

```python
                "SELECT DISTINCT grupo FROM insumos "
                "WHERE grupo IS NOT NULL AND grupo <> '' ORDER BY grupo").fetchall()
```

a:

```python
                "SELECT DISTINCT grupo FROM insumos "
                "WHERE grupo IS NOT NULL AND grupo <> '' AND oculto = 0 ORDER BY grupo").fetchall()
```

En `fuentes` (~línea 262-268), cambiar:

```python
    def fuentes(self) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT fuente FROM insumo_precios "
                "WHERE vigente = 1 AND fuente IS NOT NULL AND fuente <> '' "
                "ORDER BY fuente").fetchall()
        return [r["fuente"] for r in rows]
```

por:

```python
    def fuentes(self) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT p.fuente FROM insumo_precios p "
                "JOIN insumos i ON i.id = p.insumo_id AND i.oculto = 0 "
                "WHERE p.vigente = 1 AND p.fuente IS NOT NULL AND p.fuente <> '' "
                "ORDER BY p.fuente").fetchall()
        return [r["fuente"] for r in rows]
```

- [ ] **Step 4: Editar `precios_pg.py` (mismos cinco cambios, sintaxis Postgres)**

En `list_insumos` (~línea 196), cambiar `where, params = [], []` por:

```python
        where, params = ["i.oculto = FALSE"], []
```

En `search_insumos` (~línea 239-245), cambiar:

```python
    def search_insumos(self, texto: str, limit: int = 20) -> list[Insumo]:
        like = f"%{normalizar(texto)}%"
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT id FROM precios.insumos WHERE nombre_norm LIKE %s OR UPPER(codigo) LIKE %s "
                "LIMIT %s", (like, like, limit)).fetchall()
        return [self.get_insumo_por_id(r["id"]) for r in rows]
```

por:

```python
    def search_insumos(self, texto: str, limit: int = 20) -> list[Insumo]:
        like = f"%{normalizar(texto)}%"
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT id FROM precios.insumos WHERE (nombre_norm LIKE %s OR UPPER(codigo) LIKE %s) "
                "AND oculto = FALSE LIMIT %s", (like, like, limit)).fetchall()
        return [self.get_insumo_por_id(r["id"]) for r in rows]
```

En `search_insumos_por_palabras` (~línea 247-256), cambiar la línea de la query
(la que arma `f"SELECT id FROM precios.insumos WHERE {clauses} LIMIT %s"`) a:

```python
                f"SELECT id FROM precios.insumos WHERE ({clauses}) AND oculto = FALSE LIMIT %s",
```

En `grupos` (~línea 224-229), cambiar:

```python
                "SELECT DISTINCT grupo FROM precios.insumos "
                "WHERE grupo IS NOT NULL AND grupo <> '' ORDER BY grupo").fetchall()
```

a:

```python
                "SELECT DISTINCT grupo FROM precios.insumos "
                "WHERE grupo IS NOT NULL AND grupo <> '' AND oculto = FALSE ORDER BY grupo").fetchall()
```

En `fuentes` (~línea 231-237), cambiar:

```python
    def fuentes(self) -> list[str]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT fuente FROM precios.insumo_precios "
                "WHERE vigente = 1 AND fuente IS NOT NULL AND fuente <> '' "
                "ORDER BY fuente").fetchall()
        return [r["fuente"] for r in rows]
```

por:

```python
    def fuentes(self) -> list[str]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT p.fuente FROM precios.insumo_precios p "
                "JOIN precios.insumos i ON i.id = p.insumo_id AND i.oculto = FALSE "
                "WHERE p.vigente = 1 AND p.fuente IS NOT NULL AND p.fuente <> '' "
                "ORDER BY p.fuente").fetchall()
        return [r["fuente"] for r in rows]
```

- [ ] **Step 5: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/test_precios_db.py -v`
Expected: PASS (todos).

- [ ] **Step 6: Correr la suite completa (SQLite) — nada debe romperse**

Run: `python -m pytest tests/ -q`
Expected: verde. `list_insumos`/`search_insumos*` sin ningún insumo oculto en las
bases de test existentes deben comportarse exactamente igual que antes (la condición
`oculto = 0` es siempre verdadera si nadie ocultó nada).

- [ ] **Step 7: Commit**

```bash
git add apu_tool/datos/precios_db.py apu_tool/datos/pg/precios_pg.py tests/test_precios_db.py
git commit -m "$(cat <<'EOF'
feat(insumos): excluir oculto=true de list/search/grupos/fuentes

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `ocultar_apus_duplicados` — la migración

**Files:**
- Create: `apu_tool/servicio/insumos_ocultos.py`
- Test: `tests/test_ocultar_duplicados.py` (Create)

**Interfaces:**
- Consumes: `alm.apus.apu_index()` (ya existe), `alm.apus.pares_insumo_en_uso()`
  (Task 3), `alm.precios.todos_no_ocultos()` + `alm.precios.set_oculto()` (Task 2),
  `alm.transaccion("precios")`, `registrar_auditoria` (`apu_tool.servicio.auditoria`)
- Produces: `ocultar_apus_duplicados(alm: Almacen, actor: Optional[Perfil] = None) -> dict`
  con forma `{"insumos_ocultados": int}`

- [ ] **Step 1: Escribir los tests que fallan**

Create `tests/test_ocultar_duplicados.py`:

```python
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo
from apu_tool.servicio.insumos_ocultos import ocultar_apus_duplicados


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def test_oculta_insumo_sin_uso_que_coincide_con_apu(tmp_path):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("8044", "CODO EN ACERO", "UND", "DIURNO")])
    iid = alm.precios.crear_insumo(
        Insumo("8044", "CODO EN ACERO", "UND", "MAT", 500, "PRECIO IDU"))

    res = ocultar_apus_duplicados(alm)

    assert res == {"insumos_ocultados": 1}
    ocultos_ids = {iid_ for iid_, _c, _n in alm.precios.todos_no_ocultos()}
    assert iid not in ocultos_ids
    _, total = alm.auditoria.listar(accion="insumo.ocultar_duplicado_apu")
    assert total == 1


def test_no_oculta_colision_real_con_nombre_distinto(tmp_path):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("7439", "TAPA CIRCULAR", "UND", "DIURNO")])
    iid = alm.precios.crear_insumo(
        Insumo("7439", "MARTILLO DEMOLEDOR NEUMATICO", "UND", "EQUIPO", 100, "PRECIO IDU"))

    res = ocultar_apus_duplicados(alm)

    assert res == {"insumos_ocultados": 0}
    ocultos_ids = {iid_ for iid_, _c, _n in alm.precios.todos_no_ocultos()}
    assert iid in ocultos_ids


def test_no_oculta_si_todavia_hay_uso_real_con_mismo_nombre(tmp_path):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("8044", "CODO EN ACERO", "UND", "DIURNO"),
                          Apu("A", "OTRO APU", "M2", "DIURNO")])
    iid = alm.precios.crear_insumo(
        Insumo("8044", "CODO EN ACERO", "UND", "MAT", 500, "PRECIO IDU"))
    # Un componente SIN marcar (tipo='insumo' es el default) sigue usando 8044
    # con el mismo nombre — no debería pasar tras marcar-subapus, pero la
    # migración debe ser segura igual: no oculta si todavía hay uso real.
    alm.apus.insert_components([
        ApuComponent("A", "DIURNO", "8044", "CODO EN ACERO", "UND", 2.0, 500)])

    res = ocultar_apus_duplicados(alm)

    assert res == {"insumos_ocultados": 0}
    ocultos_ids = {iid_ for iid_, _c, _n in alm.precios.todos_no_ocultos()}
    assert iid in ocultos_ids


def test_idempotente(tmp_path):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("8044", "CODO EN ACERO", "UND", "DIURNO")])
    alm.precios.crear_insumo(
        Insumo("8044", "CODO EN ACERO", "UND", "MAT", 500, "PRECIO IDU"))

    ocultar_apus_duplicados(alm)
    res2 = ocultar_apus_duplicados(alm)

    assert res2 == {"insumos_ocultados": 0}
    _, total = alm.auditoria.listar(accion="insumo.ocultar_duplicado_apu")
    assert total == 1   # no re-audita
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/test_ocultar_duplicados.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'apu_tool.servicio.insumos_ocultos'`.

- [ ] **Step 3: Implementar**

Create `apu_tool/servicio/insumos_ocultos.py`:

```python
"""Migración: oculta (no borra) del catálogo de insumos los códigos que son un eco
aplanado de un APU y ya no tienen ningún componente usándolos como insumo real.

Auto-marcado con auditoría; idempotente. NO ve la IA. El costeo (pricing.py) sigue
encontrando cualquier insumo por código exista o no esté oculto — `oculto` solo
filtra las lecturas orientadas a humanos/IA (list_insumos, search_insumos*).
"""
from __future__ import annotations

from typing import Optional

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Perfil
from apu_tool.nucleo.texto import normalizar
from apu_tool.servicio.auditoria import registrar_auditoria


def ocultar_apus_duplicados(alm: Almacen, actor: Optional[Perfil] = None) -> dict:
    alm.precios.init_schema()   # idempotente: asegura la columna oculto

    codigos_apu: set[str] = set()
    nombres_por_codigo_apu: dict[str, set] = {}
    for cod, nom, _sh in alm.apus.apu_index():
        codigos_apu.add(cod)
        nombres_por_codigo_apu.setdefault(cod, set()).add(normalizar(nom))

    usos_restantes = {
        (cod, normalizar(nom)) for cod, nom in alm.apus.pares_insumo_en_uso()
    }

    a_ocultar = [
        (iid, cod, nom) for iid, cod, nom in alm.precios.todos_no_ocultos()
        if cod in codigos_apu
        and normalizar(nom) in nombres_por_codigo_apu.get(cod, set())
        and (cod, normalizar(nom)) not in usos_restantes
    ]

    if not a_ocultar:
        return {"insumos_ocultados": 0}

    with alm.transaccion("precios") as conn:
        for iid, cod, nom in a_ocultar:
            alm.precios.set_oculto(iid, True, conn=conn)
            registrar_auditoria(
                alm, conn, actor, "insumo.ocultar_duplicado_apu", "insumo", iid,
                antes={"oculto": False},
                despues={"oculto": True, "codigo": cod, "nombre": nom})
    return {"insumos_ocultados": len(a_ocultar)}
```

- [ ] **Step 4: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/test_ocultar_duplicados.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/insumos_ocultos.py tests/test_ocultar_duplicados.py
git commit -m "$(cat <<'EOF'
feat(insumos): migración ocultar_apus_duplicados (auto-marcado + auditoría)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: CLI `ocultar-duplicados`

**Files:**
- Modify: `apu_tool/interfaz/cli.py`

No hay test automatizado dedicado para este comando — mismo criterio ya aplicado a
`cmd_marcar_subapus` (sin test de CLI propio en la suite existente): la lógica real ya
está cubierta por `test_ocultar_duplicados.py` (Task 5); este wrapper de 4 líneas se
verifica a mano (Step 3).

**Interfaces:**
- Consumes: `ocultar_apus_duplicados` (Task 5)

- [ ] **Step 1: Implementar `cmd_ocultar_duplicados`**

Agregar en `apu_tool/interfaz/cli.py`, inmediatamente después de `cmd_marcar_subapus`:

```python
def cmd_ocultar_duplicados(args) -> int:
    from apu_tool.servicio.insumos_ocultos import ocultar_apus_duplicados
    alm = get_almacen()
    res = ocultar_apus_duplicados(alm)
    print(f"Insumos ocultados: {res['insumos_ocultados']}.")
    return 0
```

- [ ] **Step 2: Registrar el subcomando**

En `build_parser()`, el final de la función es exactamente:

```python
    pms = sub.add_parser(
        "marcar-subapus",
        help="Marcar como sub-APU los componentes cuyo código es un APU (idempotente, auditado).")
    pms.set_defaults(func=cmd_marcar_subapus)
    return p
```

Reemplazar por:

```python
    pms = sub.add_parser(
        "marcar-subapus",
        help="Marcar como sub-APU los componentes cuyo código es un APU (idempotente, auditado).")
    pms.set_defaults(func=cmd_marcar_subapus)

    poc = sub.add_parser(
        "ocultar-duplicados",
        help="Ocultar del catálogo los códigos que son eco de un APU sin uso real (idempotente, auditado).")
    poc.set_defaults(func=cmd_ocultar_duplicados)
    return p
```

- [ ] **Step 3: Verificar manualmente**

Run: `python run_cli.py ocultar-duplicados`
Expected: corre sin error contra la base local (SQLite por defecto, sin `DATABASE_URL`),
imprime `Insumos ocultados: N.` con el `N` real de los datos locales.

- [ ] **Step 4: Correr la suite completa**

Run: `python -m pytest tests/ -q`
Expected: verde, sin regresiones.

- [ ] **Step 5: Commit**

```bash
git add apu_tool/interfaz/cli.py
git commit -m "$(cat <<'EOF'
feat(cli): comando ocultar-duplicados

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Verificación final (tras todas las tareas)

- [ ] `python -m pytest tests/ -q` → verde.
- [ ] `python run_cli.py ocultar-duplicados` corrido contra la base local real
  (`data/precios.db` + `data/apus.db`) — anotar cuántos insumos ocultó y confirmar a
  mano (vía `sqlite3`/un script chico) que los 29 códigos de colisión real (los que
  aparecían como "descartados" en el preview de la sesión de brainstorming) siguen con
  `oculto=0`.
- [ ] Manual: abrir la página Insumos localmente (`python run_web.py` o el frontend
  contra el backend local) y confirmar que un código recién ocultado ya no aparece en
  la lista/búsqueda, pero que abrir una corrida que lo use como componente sigue
  costeando igual (no depende de la visibilidad).
- [ ] **No correr todavía contra producción** — eso es un paso operativo aparte,
  supervisado (backup + verificación manual), igual que se hizo con `marcar-subapus`.
  No forma parte de este plan.

## Self-Review (cobertura del spec)

- Columna aditiva dual-backend → Task 1.
- Regla exacta de ocultamiento (código+nombre coincide, sin uso real, colisiones
  intactas) → Task 5, con los 4 tests de `test_ocultar_duplicados.py` cubriendo cada
  rama de la regla explícitamente.
- Costeo no depende de `oculto` → Task 4, tests dedicados
  (`test_get_candidatos_encuentra_ocultos`, `test_get_insumo_por_id_encuentra_ocultos`).
- Migración idempotente y auditada, mismo patrón que `marcar-subapus` → Task 5.
- CLI para correrla → Task 6.
- Sin toggle "mostrar ocultos", sin tocar `nucleo/models.py`, sin borrado → ninguna
  tarea lo agrega (verificado por omisión).
- Operación real en producción (backup + verificación) → explícitamente fuera de este
  plan, queda para una sesión de trabajo supervisada aparte, igual que
  `marcar-subapus`.
