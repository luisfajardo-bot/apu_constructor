# Editar y borrar APUs (biblioteca) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cerrar el CRUD de APUs de la biblioteca agregando **editar** (cabecera + composición) y **borrar** end-to-end, sobre los dos backends (SQLite y Postgres), con auth/RBAC y auditoría.

**Architecture:** Se extiende `apu_tool/servicio/autoria.py` (donde ya viven crear/importar) con `editar_apu`/`borrar_apu` auditados y transaccionales, apoyados en métodos nuevos de la capa de datos (`editar_apu`/`borrar_apu` en `ApusDB` y `ApusPg`; `contar_items_por_apu` en `CorridasDB`/`CorridasPg`), declarados en los `Protocol` de `repositorio.py`. La API expone `PUT`/`DELETE /api/apus/{codigo}/{turno}`. El frontend reutiliza `DialogoAgregarApu` en modo edición y agrega un diálogo de borrado en `web/src/pages/Apus.tsx`.

**Tech Stack:** Python 3, FastAPI, SQLite + Postgres (psycopg), pytest + TestClient, React + TypeScript + Vite, Vitest.

## Global Constraints

- **Invariante #1 (la IA nunca ve dinero):** editar/borrar NO abren ningún camino hacia la IA. No importar `ai_assist` en `apu_tool/servicio/`. El test `tests/test_servicio_privacidad.py` debe seguir verde.
- **Doble backend:** todo método nuevo de capa de datos se implementa en SQLite (`apu_tool/datos/*.py`) **y** Postgres (`apu_tool/datos/pg/*.py`), y se declara en el `Protocol` correspondiente de `apu_tool/datos/repositorio.py`. El oráculo dual-backend es `tests/test_repositorios_contrato.py` (SQLite siempre; Postgres si hay `TEST_DATABASE_URL`).
- **Sin migración de esquema:** editar/borrar usan las tablas existentes `apus`, `apu_componentes`, `corrida_item`. No se toca `db/apus.sql`, `db/pg/apus.sql`, `db/corridas.sql` ni `db/pg/corridas.sql`.
- **Identidad inmutable:** `codigo` + `shift`(turno) son la identidad de un APU; editar NO los cambia.
- **Permisos:** editar = rol `editor`; borrar = rol `admin`. Gating con `Depends(requiere_rol(...))` en la ruta.
- **Convención de errores del servicio:** "no encontrado" → el servicio devuelve `None` (endpoint responde `404`); error de validación → `ValueError` (endpoint responde `400`, patrón ya usado por `crear_apu`/`detalle_apu`).
- **Español** en nombres de dominio, mensajes de usuario y comentarios.
- **Persistencia aislada en la capa de datos:** nada de SQL crudo fuera de `apu_tool/datos/`.

---

### Task 1: Capa de datos — `editar_apu` (SQLite + Postgres + Protocol)

**Files:**
- Modify: `apu_tool/datos/repositorio.py` (Protocol `RepositorioApus`)
- Modify: `apu_tool/datos/apus_db.py`
- Modify: `apu_tool/datos/pg/apus_pg.py`
- Test: `tests/test_repositorios_contrato.py`

**Interfaces:**
- Consumes: nada de tareas previas. Usa modelos `Apu`, `ApuComponent` (ya existen) y `get_apu`/`get_components` (ya existen).
- Produces: `editar_apu(self, apu: Apu, componentes: list[ApuComponent], conn=None) -> None` en `RepositorioApus`, `ApusDB` y `ApusPg`. Lanza `ValueError` si `(codigo, shift)` no existe. Reemplaza cabecera (nombre/unidad/grupo) y toda la composición (seq 0..n).

- [ ] **Step 1: Write the failing tests** (dual-backend, en el oráculo de contrato)

En `tests/test_repositorios_contrato.py`, al final del archivo, agregar:

```python
def test_apu_editar_reemplaza_cabecera_y_composicion(repos):
    _, apus = repos
    apus.crear_apu(Apu("A1", "MURO", "M2", "DIURNO", "ESTR"),
                   [ApuComponent("A1", "DIURNO", "1", "ARENA", "M3", 0.5, 10.0)])
    apus.editar_apu(
        Apu("A1", "MURO REFORZADO", "M2", "DIURNO", "ESTR"),
        [ApuComponent("A1", "DIURNO", "2", "CEMENTO", "KG", 3.0, 20.0),
         ApuComponent("A1", "DIURNO", "1", "ARENA", "M3", 0.8, 10.0)])
    apu = apus.get_apu("A1", "DIURNO")
    assert apu.nombre == "MURO REFORZADO"
    comps = apus.get_components("A1", "DIURNO")
    assert [c.insumo_codigo for c in comps] == ["2", "1"]   # reemplazada, seq 0..n
    assert comps[1].rendimiento == 0.8


def test_apu_editar_inexistente_lanza(repos):
    _, apus = repos
    with pytest.raises(ValueError):
        apus.editar_apu(Apu("NOPE", "X", "M2", "DIURNO"), [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_repositorios_contrato.py -k editar -v`
Expected: FAIL con `AttributeError: 'ApusDB' object has no attribute 'editar_apu'`.

- [ ] **Step 3: Add `editar_apu` to the Protocol**

En `apu_tool/datos/repositorio.py`, dentro de `class RepositorioApus(Protocol):`, justo debajo de la línea `def crear_apu(self, apu: Apu, componentes: list[ApuComponent], conn=None) -> None: ...`, agregar:

```python
    def editar_apu(self, apu: Apu, componentes: list[ApuComponent], conn=None) -> None:
        """Edita cabecera (nombre/unidad/grupo) y REEMPLAZA la composición de un APU
        existente. Identidad (codigo, shift) inmutable. ValueError si no existe."""
        ...
```

- [ ] **Step 4: Implement `editar_apu` in SQLite (`apus_db.py`)**

En `apu_tool/datos/apus_db.py`, justo después del método `_crear_apu` (que termina en la línea del `executemany` de componentes), agregar:

```python
    def editar_apu(self, apu: Apu, componentes: list[ApuComponent], conn=None) -> None:
        """Edita cabecera + reemplaza composición de un APU existente. ValueError si no existe."""
        if conn is not None:
            return self._editar_apu(conn, apu, componentes)
        with self.connect() as c:
            return self._editar_apu(c, apu, componentes)

    def _editar_apu(self, conn, apu: Apu, componentes: list[ApuComponent]) -> None:
        existe = conn.execute("SELECT 1 FROM apus WHERE codigo=? AND shift=?",
                              (str(apu.codigo), apu.shift)).fetchone()
        if not existe:
            raise ValueError(
                f"No existe un APU con código {apu.codigo} en turno {apu.shift}.")
        conn.execute(
            "UPDATE apus SET nombre=?, unidad=?, grupo=? WHERE codigo=? AND shift=?",
            (apu.nombre, apu.unidad, apu.grupo, str(apu.codigo), apu.shift))
        conn.execute("DELETE FROM apu_componentes WHERE apu_codigo=? AND shift=?",
                     (str(apu.codigo), apu.shift))
        rows = [(str(apu.codigo), apu.shift, seq, c.insumo_codigo, c.insumo_nombre,
                 c.unidad, c.rendimiento, c.precio_unitario_hist)
                for seq, c in enumerate(componentes)]
        if rows:
            conn.executemany(
                "INSERT INTO apu_componentes "
                "(apu_codigo, shift, seq, insumo_codigo, insumo_nombre, unidad, "
                " rendimiento, precio_unitario_hist) VALUES (?,?,?,?,?,?,?,?)", rows)
```

- [ ] **Step 5: Implement `editar_apu` in Postgres (`apus_pg.py`)**

En `apu_tool/datos/pg/apus_pg.py`, justo después del método `_crear_apu`, agregar:

```python
    def editar_apu(self, apu: Apu, componentes: list[ApuComponent], conn=None) -> None:
        if conn is not None:
            return self._editar_apu(conn, apu, componentes)
        with self.cx.connection() as c:
            return self._editar_apu(c, apu, componentes)

    def _editar_apu(self, conn, apu: Apu, componentes: list[ApuComponent]) -> None:
        existe = conn.execute("SELECT 1 FROM apus.apus WHERE codigo=%s AND shift=%s",
                              (str(apu.codigo), apu.shift)).fetchone()
        if not existe:
            raise ValueError(
                f"No existe un APU con código {apu.codigo} en turno {apu.shift}.")
        conn.execute(
            "UPDATE apus.apus SET nombre=%s, unidad=%s, grupo=%s WHERE codigo=%s AND shift=%s",
            (apu.nombre, apu.unidad, apu.grupo, str(apu.codigo), apu.shift))
        conn.execute("DELETE FROM apus.apu_componentes WHERE apu_codigo=%s AND shift=%s",
                     (str(apu.codigo), apu.shift))
        rows = [(str(apu.codigo), apu.shift, seq, c.insumo_codigo, c.insumo_nombre,
                 c.unidad, c.rendimiento, c.precio_unitario_hist)
                for seq, c in enumerate(componentes)]
        if rows:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO apus.apu_componentes "
                    "(apu_codigo, shift, seq, insumo_codigo, insumo_nombre, unidad, "
                    " rendimiento, precio_unitario_hist) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", rows)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_repositorios_contrato.py -k editar -v`
Expected: PASS (2 passed; backend `sqlite`. Si hay `TEST_DATABASE_URL`, también `postgres`.)

- [ ] **Step 7: Commit**

```bash
git add apu_tool/datos/repositorio.py apu_tool/datos/apus_db.py apu_tool/datos/pg/apus_pg.py tests/test_repositorios_contrato.py
git commit -m "feat(datos): editar_apu en ApusDB/ApusPg + Protocol (reemplaza cabecera y composición)"
```

---

### Task 2: Capa de datos — `borrar_apu` (SQLite + Postgres + Protocol)

**Files:**
- Modify: `apu_tool/datos/repositorio.py` (Protocol `RepositorioApus`)
- Modify: `apu_tool/datos/apus_db.py`
- Modify: `apu_tool/datos/pg/apus_pg.py`
- Test: `tests/test_repositorios_contrato.py`

**Interfaces:**
- Consumes: `crear_apu`, `get_apu`, `get_components` (ya existen).
- Produces: `borrar_apu(self, codigo: str, shift: str, conn=None) -> bool` en `RepositorioApus`, `ApusDB` y `ApusPg`. Devuelve `False` si no existía; borra componentes y cabecera.

- [ ] **Step 1: Write the failing tests**

En `tests/test_repositorios_contrato.py`, al final, agregar:

```python
def test_apu_borrar_elimina_cabecera_y_componentes(repos):
    _, apus = repos
    apus.crear_apu(Apu("A1", "MURO", "M2", "DIURNO"),
                   [ApuComponent("A1", "DIURNO", "1", "ARENA", "M3", 0.5, 10.0)])
    assert apus.borrar_apu("A1", "DIURNO") is True
    assert apus.get_apu("A1", "DIURNO") is None
    assert apus.get_components("A1", "DIURNO") == []


def test_apu_borrar_inexistente_devuelve_false(repos):
    _, apus = repos
    assert apus.borrar_apu("NOPE", "DIURNO") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_repositorios_contrato.py -k borrar -v`
Expected: FAIL con `AttributeError: 'ApusDB' object has no attribute 'borrar_apu'`.

- [ ] **Step 3: Add `borrar_apu` to the Protocol**

En `apu_tool/datos/repositorio.py`, en `class RepositorioApus(Protocol):`, debajo del `editar_apu` agregado en Task 1, agregar:

```python
    def borrar_apu(self, codigo: str, shift: str, conn=None) -> bool:
        """Borra componentes + cabecera de un APU. False si no existía."""
        ...
```

- [ ] **Step 4: Implement `borrar_apu` in SQLite (`apus_db.py`)**

En `apu_tool/datos/apus_db.py`, después de `_editar_apu` (Task 1), agregar:

```python
    def borrar_apu(self, codigo: str, shift: str, conn=None) -> bool:
        """Borra componentes + cabecera de un APU. False si no existía."""
        if conn is not None:
            return self._borrar_apu(conn, codigo, shift)
        with self.connect() as c:
            return self._borrar_apu(c, codigo, shift)

    def _borrar_apu(self, conn, codigo: str, shift: str) -> bool:
        existe = conn.execute("SELECT 1 FROM apus WHERE codigo=? AND shift=?",
                              (str(codigo), shift)).fetchone()
        if not existe:
            return False
        conn.execute("DELETE FROM apu_componentes WHERE apu_codigo=? AND shift=?",
                     (str(codigo), shift))
        conn.execute("DELETE FROM apus WHERE codigo=? AND shift=?", (str(codigo), shift))
        return True
```

- [ ] **Step 5: Implement `borrar_apu` in Postgres (`apus_pg.py`)**

En `apu_tool/datos/pg/apus_pg.py`, después de `_editar_apu` (Task 1), agregar:

```python
    def borrar_apu(self, codigo: str, shift: str, conn=None) -> bool:
        if conn is not None:
            return self._borrar_apu(conn, codigo, shift)
        with self.cx.connection() as c:
            return self._borrar_apu(c, codigo, shift)

    def _borrar_apu(self, conn, codigo: str, shift: str) -> bool:
        existe = conn.execute("SELECT 1 FROM apus.apus WHERE codigo=%s AND shift=%s",
                              (str(codigo), shift)).fetchone()
        if not existe:
            return False
        conn.execute("DELETE FROM apus.apu_componentes WHERE apu_codigo=%s AND shift=%s",
                     (str(codigo), shift))
        conn.execute("DELETE FROM apus.apus WHERE codigo=%s AND shift=%s", (str(codigo), shift))
        return True
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_repositorios_contrato.py -k borrar -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apu_tool/datos/repositorio.py apu_tool/datos/apus_db.py apu_tool/datos/pg/apus_pg.py tests/test_repositorios_contrato.py
git commit -m "feat(datos): borrar_apu en ApusDB/ApusPg + Protocol"
```

---

### Task 3: Capa de datos — `contar_items_por_apu` en corridas (SQLite + Postgres + Protocol)

**Files:**
- Modify: `apu_tool/datos/repositorio.py` (Protocol `RepositorioCorridas`)
- Modify: `apu_tool/datos/corridas_db.py`
- Modify: `apu_tool/datos/pg/corridas_pg.py`
- Test: `tests/test_corridas_db.py`

**Interfaces:**
- Consumes: nada nuevo.
- Produces: `contar_items_por_apu(self, apu_codigo: str) -> int` en `RepositorioCorridas`, `CorridasDB` y `CorridasPg`. Cuenta filas de `corrida_item` con ese `apu_codigo`.

- [ ] **Step 1: Write the failing test** (SQLite)

En `tests/test_corridas_db.py`, al final del archivo, agregar:

```python
def test_contar_items_por_apu(tmp_path):
    alm = _almacen_tmp(tmp_path)
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="x", archivo="a.xlsx", turno_def="DIURNO",
        use_ai=False, estado="en_revision"))
    alm.corridas.guardar_items(cid, [_fila(0), _fila(1)])   # ambos con apu_codigo="A1"
    assert alm.corridas.contar_items_por_apu("A1") == 2
    assert alm.corridas.contar_items_por_apu("ZZZ") == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_corridas_db.py::test_contar_items_por_apu -v`
Expected: FAIL con `AttributeError: 'CorridasDB' object has no attribute 'contar_items_por_apu'`.

- [ ] **Step 3: Add `contar_items_por_apu` to the Protocol**

En `apu_tool/datos/repositorio.py`, en `class RepositorioCorridas(Protocol):`, después de `def counts(self) -> dict[str, int]: ...`, agregar:

```python
    def contar_items_por_apu(self, apu_codigo: str) -> int:
        """Nº de ítems de corrida que referencian este apu_codigo (aviso al borrar)."""
        ...
```

- [ ] **Step 4: Implement in SQLite (`corridas_db.py`)**

En `apu_tool/datos/corridas_db.py`, después del método `counts`, agregar:

```python
    def contar_items_por_apu(self, apu_codigo: str) -> int:
        with self.connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM corrida_item WHERE apu_codigo = ?",
                (str(apu_codigo),)).fetchone()[0]
```

- [ ] **Step 5: Implement in Postgres (`corridas_pg.py`)**

En `apu_tool/datos/pg/corridas_pg.py`, después del método `counts` (o al final de la clase), agregar:

```python
    def contar_items_por_apu(self, apu_codigo: str) -> int:
        with self.cx.connection() as conn:
            return conn.execute(
                "SELECT COUNT(*) AS n FROM corridas.corrida_item WHERE apu_codigo = %s",
                (str(apu_codigo),)).fetchone()["n"]
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_corridas_db.py::test_contar_items_por_apu -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apu_tool/datos/repositorio.py apu_tool/datos/corridas_db.py apu_tool/datos/pg/corridas_pg.py tests/test_corridas_db.py
git commit -m "feat(datos): contar_items_por_apu en CorridasDB/CorridasPg + Protocol"
```

---

### Task 4: Servicio — `editar_apu` en `autoria.py` (auditado)

**Files:**
- Modify: `apu_tool/servicio/autoria.py`
- Test: `tests/test_servicio_autoria.py`

**Interfaces:**
- Consumes: `ApusDB.editar_apu` / Protocol (Task 1); `_componentes_de` y `registrar_auditoria` (ya en `autoria.py`); `alm.apus.get_apu`, `alm.apus.get_components`.
- Produces: `editar_apu(alm, codigo, shift, datos, actor=None) -> dict | None`. `None` si no existe; `dict` `{codigo, shift, nombre, unidad, grupo, n_componentes}` si editó; `ValueError` en validación.

- [ ] **Step 1: Write the failing tests**

En `tests/test_servicio_autoria.py`, al final, agregar:

```python
def test_editar_apu_reemplaza_y_devuelve_resumen(tmp_path):
    alm = _alm(tmp_path)
    autoria.crear_apu(alm, {"codigo": "B2", "turno": "DIURNO", "nombre": "PISO",
        "unidad": "M2", "grupo": "ACAB",
        "componentes": [{"insumo_codigo": "100", "rendimiento": 2.0}]})
    out = autoria.editar_apu(alm, "B2", "DIURNO", {"nombre": "PISO PULIDO",
        "unidad": "M2", "grupo": "ACAB",
        "componentes": [{"insumo_codigo": "200", "rendimiento": 0.5}]})
    assert out["nombre"] == "PISO PULIDO" and out["n_componentes"] == 1
    comps = alm.apus.get_components("B2", "DIURNO")
    assert [c.insumo_codigo for c in comps] == ["200"]


def test_editar_apu_inexistente_devuelve_none(tmp_path):
    alm = _alm(tmp_path)
    assert autoria.editar_apu(alm, "NOPE", "DIURNO", {"nombre": "X",
        "componentes": [{"insumo_codigo": "100", "rendimiento": 1.0}]}) is None


def test_editar_apu_rendimiento_invalido_lanza(tmp_path):
    alm = _alm(tmp_path)
    autoria.crear_apu(alm, {"codigo": "B2", "turno": "DIURNO", "nombre": "PISO",
        "componentes": [{"insumo_codigo": "100", "rendimiento": 2.0}]})
    with pytest.raises(ValueError):
        autoria.editar_apu(alm, "B2", "DIURNO", {"nombre": "PISO",
            "componentes": [{"insumo_codigo": "100", "rendimiento": 0}]})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_servicio_autoria.py -k editar_apu -v`
Expected: FAIL con `AttributeError: module 'apu_tool.servicio.autoria' has no attribute 'editar_apu'`.

- [ ] **Step 3: Implement `editar_apu` in `autoria.py`**

En `apu_tool/servicio/autoria.py`, justo después de la función `crear_apu` (antes del comentario `# ------- import insumos`), agregar:

```python
def editar_apu(alm: Almacen, codigo: str, shift: str, datos: dict, actor=None) -> dict | None:
    """Edita cabecera + composición de un APU existente. Identidad (codigo, turno) fija.
    Devuelve None si no existe (endpoint -> 404); ValueError en validación (-> 400)."""
    codigo = str(codigo or "").strip()
    shift = str(shift or "").strip().upper()
    previo = alm.apus.get_apu(codigo, shift)
    if previo is None:
        return None
    nombre = str(datos.get("nombre", "") or "").strip()
    if not nombre:
        raise ValueError("El nombre es obligatorio.")
    comps = _componentes_de(alm, datos.get("componentes", []) or [], shift)
    antes = {"nombre": previo.nombre, "unidad": previo.unidad, "grupo": previo.grupo,
             "n_componentes": len(alm.apus.get_components(codigo, shift))}
    apu = Apu(codigo=codigo, nombre=nombre, unidad=str(datos.get("unidad", "") or ""),
              shift=shift, grupo=str(datos.get("grupo", "") or ""))
    with alm.transaccion("apus") as conn:
        alm.apus.editar_apu(apu, comps, conn=conn)
        registrar_auditoria(
            alm, conn, actor, "apu.editar", "apu", codigo, antes=antes,
            despues={"nombre": nombre, "unidad": apu.unidad, "grupo": apu.grupo,
                     "n_componentes": len(comps)})
    return {"codigo": codigo, "shift": shift, "nombre": nombre,
            "unidad": apu.unidad, "grupo": apu.grupo, "n_componentes": len(comps)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_servicio_autoria.py -k editar_apu -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/autoria.py tests/test_servicio_autoria.py
git commit -m "feat(autoria): servicio editar_apu (auditado, None si no existe)"
```

---

### Task 5: Servicio — `borrar_apu` en `autoria.py` (auditado, con `n_corridas`)

**Files:**
- Modify: `apu_tool/servicio/autoria.py`
- Test: `tests/test_servicio_autoria.py`

**Interfaces:**
- Consumes: `ApusDB.borrar_apu` (Task 2); `Corridas*.contar_items_por_apu` (Task 3); `registrar_auditoria`.
- Produces: `borrar_apu(alm, codigo, shift, actor=None) -> dict | None`. `None` si no existe; `{"borrado": True, "n_corridas": int}` si borró.

- [ ] **Step 1: Write the failing tests**

En `tests/test_servicio_autoria.py`, al final, agregar:

```python
def test_borrar_apu_ok_devuelve_resultado(tmp_path):
    alm = _alm(tmp_path)
    autoria.crear_apu(alm, {"codigo": "B2", "turno": "DIURNO", "nombre": "PISO",
        "componentes": [{"insumo_codigo": "100", "rendimiento": 2.0}]})
    out = autoria.borrar_apu(alm, "B2", "DIURNO")
    assert out == {"borrado": True, "n_corridas": 0}
    assert alm.apus.get_apu("B2", "DIURNO") is None


def test_borrar_apu_inexistente_devuelve_none(tmp_path):
    alm = _alm(tmp_path)
    assert autoria.borrar_apu(alm, "NOPE", "DIURNO") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_servicio_autoria.py -k borrar_apu -v`
Expected: FAIL con `AttributeError: module 'apu_tool.servicio.autoria' has no attribute 'borrar_apu'`.

- [ ] **Step 3: Implement `borrar_apu` in `autoria.py`**

En `apu_tool/servicio/autoria.py`, justo después de `editar_apu` (Task 4), agregar:

```python
def borrar_apu(alm: Almacen, codigo: str, shift: str, actor=None) -> dict | None:
    """Borra un APU (cabecera + composición). Devuelve None si no existe (endpoint -> 404).
    Las corridas ya armadas conservan su foto; se informa cuántas lo referencian."""
    codigo = str(codigo or "").strip()
    shift = str(shift or "").strip().upper()
    previo = alm.apus.get_apu(codigo, shift)
    if previo is None:
        return None
    n_comps = len(alm.apus.get_components(codigo, shift))
    n_corridas = alm.corridas.contar_items_por_apu(codigo)
    antes = {"codigo": codigo, "turno": shift, "nombre": previo.nombre,
             "unidad": previo.unidad, "grupo": previo.grupo, "n_componentes": n_comps}
    with alm.transaccion("apus") as conn:
        alm.apus.borrar_apu(codigo, shift, conn=conn)
        registrar_auditoria(
            alm, conn, actor, "apu.borrar", "apu", codigo, antes=antes, despues=None,
            contexto={"n_corridas": n_corridas})
    return {"borrado": True, "n_corridas": n_corridas}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_servicio_autoria.py -k borrar_apu -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/autoria.py tests/test_servicio_autoria.py
git commit -m "feat(autoria): servicio borrar_apu (auditado, informa n_corridas)"
```

---

### Task 6: Servicio de lectura — `n_corridas` en el detalle del APU

**Files:**
- Modify: `apu_tool/servicio/apus.py` (función `detalle`)
- Test: `tests/test_api_autoria.py`

**Interfaces:**
- Consumes: `Corridas*.contar_items_por_apu` (Task 3).
- Produces: la respuesta de `apus.detalle(...)` y del endpoint `GET /api/apus/{codigo}/{turno}` incluye la clave `n_corridas: int`. La usa el diálogo de borrado (Task 10) para avisar antes de borrar.

- [ ] **Step 1: Write the failing test**

En `tests/test_api_autoria.py`, al final, agregar:

```python
def test_detalle_apu_incluye_n_corridas(tmp_path):
    cli, alm = _cli(tmp_path)   # A1 existe por el seed de _cli; sin corridas -> 0
    r = cli.get("/api/apus/A1/DIURNO")
    assert r.status_code == 200, r.text
    assert r.json()["n_corridas"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api_autoria.py::test_detalle_apu_incluye_n_corridas -v`
Expected: FAIL con `KeyError: 'n_corridas'`.

- [ ] **Step 3: Add `n_corridas` to `apus.detalle`**

En `apu_tool/servicio/apus.py`, en la función `detalle`, agregar la clave `n_corridas` al dict retornado (justo después de `"costo_unitario": total,`):

```python
    return {
        "codigo": apu.codigo, "turno": apu.shift, "nombre": apu.nombre,
        "unidad": apu.unidad, "grupo": apu.grupo, "costo_unitario": total,
        "n_corridas": alm.corridas.contar_items_por_apu(codigo),
        "composicion": [{
            "insumo_codigo": c.insumo_codigo, "insumo_nombre": c.insumo_nombre,
            "unidad": c.unidad, "rendimiento": c.rendimiento,
            "precio_unitario": c.precio_unitario, "fuente_precio": c.fuente_precio,
            "costo": c.costo, "calidad_cruce": c.calidad_cruce} for c in costed],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_api_autoria.py::test_detalle_apu_incluye_n_corridas -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/apus.py tests/test_api_autoria.py
git commit -m "feat(apus): detalle incluye n_corridas (aviso previo al borrado)"
```

---

### Task 7: API — DTO `ApuEditIn` + endpoints `PUT`/`DELETE /api/apus/{codigo}/{turno}`

**Files:**
- Modify: `apu_tool/servicio/esquemas.py`
- Modify: `apu_tool/servicio/rutas.py`
- Test: `tests/test_api_autoria.py`

**Interfaces:**
- Consumes: `autoria.editar_apu` (Task 4), `autoria.borrar_apu` (Task 5); helpers ya existentes `requiere_rol`, `get_almacen`, `HTTPException`.
- Produces: `PUT /api/apus/{codigo}/{turno}` (rol `editor`) y `DELETE /api/apus/{codigo}/{turno}` (rol `admin`). DTO `ApuEditIn`.

- [ ] **Step 1: Write the failing tests**

En `tests/test_api_autoria.py`, al final, agregar:

```python
def test_editar_apu_endpoint(tmp_path):
    cli, alm = _cli(tmp_path)   # rol admin
    cli.post("/api/apus/crear", json={"codigo": "B2", "turno": "DIURNO", "nombre": "PISO",
        "unidad": "M2", "grupo": "ACAB",
        "componentes": [{"insumo_codigo": "100", "rendimiento": 2.0}]})
    r = cli.put("/api/apus/B2/DIURNO", json={"nombre": "PISO PULIDO", "unidad": "M2",
        "grupo": "ACAB", "componentes": [{"insumo_codigo": "100", "rendimiento": 3.0}]})
    assert r.status_code == 200, r.text
    assert r.json()["nombre"] == "PISO PULIDO"
    assert cli.put("/api/apus/NOPE/DIURNO", json={"nombre": "X",
        "componentes": [{"insumo_codigo": "100", "rendimiento": 1.0}]}).status_code == 404


def test_borrar_apu_endpoint(tmp_path):
    cli, alm = _cli(tmp_path)   # rol admin
    cli.post("/api/apus/crear", json={"codigo": "B2", "turno": "DIURNO", "nombre": "PISO",
        "componentes": [{"insumo_codigo": "100", "rendimiento": 2.0}]})
    r = cli.delete("/api/apus/B2/DIURNO")
    assert r.status_code == 200 and r.json()["borrado"] is True
    assert cli.delete("/api/apus/NOPE/DIURNO").status_code == 404


def test_editar_borrar_gating_por_rol(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([Insumo("100", "CEMENTO GRIS", "KG", "MAT", 1000, "PRECIO IDU")])
    alm.apus.insert_apus([Apu("A1", "MURO", "M2", "DIURNO", "ESTR")])
    editor = cliente(create_app(almacen=alm), rol="editor")
    consulta = cliente(create_app(almacen=alm), rol="consulta")
    body = {"nombre": "MURO 2", "unidad": "M2", "grupo": "ESTR",
            "componentes": [{"insumo_codigo": "100", "rendimiento": 1.0}]}
    assert editor.put("/api/apus/A1/DIURNO", json=body).status_code == 200   # editor edita
    assert editor.delete("/api/apus/A1/DIURNO").status_code == 403           # editor NO borra
    assert consulta.put("/api/apus/A1/DIURNO", json=body).status_code == 403 # consulta NO edita
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_api_autoria.py -k "editar_apu_endpoint or borrar_apu_endpoint or gating_por_rol" -v`
Expected: FAIL (los `PUT`/`DELETE` devuelven `405 Method Not Allowed`).

- [ ] **Step 3: Add the `ApuEditIn` DTO**

En `apu_tool/servicio/esquemas.py`, justo después de la clase `ApuNuevoIn`, agregar:

```python
class ApuEditIn(BaseModel):
    nombre: str
    unidad: str = ""
    grupo: str = ""
    componentes: list[ComponenteIn] = []
```

- [ ] **Step 4: Import `ApuEditIn` in `rutas.py`**

En `apu_tool/servicio/rutas.py`, en el `from apu_tool.servicio.esquemas import (...)`, agregar `ApuEditIn` a la lista de nombres importados.

- [ ] **Step 5: Add the endpoints in `rutas.py`**

En `apu_tool/servicio/rutas.py`, justo después del endpoint `detalle_apu` (`GET /apus/{codigo}/{turno}`) y antes del comentario `# ---- usuarios (solo Admin) ----`, agregar:

```python
@router.put("/apus/{codigo}/{turno}")
def editar_apu(codigo: str, turno: str, body: ApuEditIn,
               alm: Almacen = Depends(get_almacen),
               actor=Depends(requiere_rol("editor"))):
    try:
        r = autoria.editar_apu(alm, codigo, turno, body.model_dump(), actor=actor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if r is None:
        raise HTTPException(status_code=404, detail="APU no encontrado.")
    return r


@router.delete("/apus/{codigo}/{turno}")
def borrar_apu(codigo: str, turno: str, alm: Almacen = Depends(get_almacen),
               actor=Depends(requiere_rol("admin"))):
    r = autoria.borrar_apu(alm, codigo, turno, actor=actor)
    if r is None:
        raise HTTPException(status_code=404, detail="APU no encontrado.")
    return r
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_api_autoria.py -k "editar_apu_endpoint or borrar_apu_endpoint or gating_por_rol" -v`
Expected: PASS (3 passed).

- [ ] **Step 7: Run the whole backend suite (no regressions)**

Run: `python -m pytest tests/ -q`
Expected: todo verde (incluye seed, privacidad, contrato, auditoría).

- [ ] **Step 8: Commit**

```bash
git add apu_tool/servicio/esquemas.py apu_tool/servicio/rutas.py tests/test_api_autoria.py
git commit -m "feat(api): PUT/DELETE /apus/{codigo}/{turno} (editar=editor, borrar=admin)"
```

---

### Task 8: Frontend — cliente `editarApu`/`borrarApu` + `apiPut` + tipos

**Files:**
- Modify: `web/src/api/client.ts`
- Modify: `web/src/api/autoria.ts`
- Modify: `web/src/lib/tipos.ts`
- Test: `web/src/api/autoria.editar.test.ts` (Create)

**Interfaces:**
- Consumes: endpoints de Task 7.
- Produces: `editarApu(codigo, turno, body: ApuEditar): Promise<ApuResumen>`, `borrarApu(codigo, turno): Promise<void>`, tipo `ApuEditar`, y `n_corridas?: number` en `ApuDetalle`.

- [ ] **Step 1: Write the failing test** (mock del módulo cliente)

Crear `web/src/api/autoria.editar.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { editarApu, borrarApu } from "@/api/autoria";
import * as client from "@/api/client";

describe("autoria: editar/borrar APU", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("editarApu hace PUT a la ruta con el turno codificado", async () => {
    const spy = vi.spyOn(client, "apiPut").mockResolvedValue({} as never);
    await editarApu("9593 N", "DIURNO", {
      nombre: "X", unidad: "M2", grupo: "G", componentes: [],
    });
    expect(spy).toHaveBeenCalledWith("/apus/9593%20N/DIURNO", {
      nombre: "X", unidad: "M2", grupo: "G", componentes: [],
    });
  });

  it("borrarApu hace DELETE a la ruta", async () => {
    const spy = vi.spyOn(client, "apiDelete").mockResolvedValue(undefined);
    await borrarApu("B2", "DIURNO");
    expect(spy).toHaveBeenCalledWith("/apus/B2/DIURNO");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (desde `web/`): `npx vitest run src/api/autoria.editar.test.ts`
Expected: FAIL (`editarApu`/`borrarApu` no existen; `apiPut` no existe).

- [ ] **Step 3: Add `apiPut` to `client.ts`**

En `web/src/api/client.ts`, justo después de `apiPatch`, agregar:

```typescript
export async function apiPut<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(BASE + path, {
    method: "PUT",
    headers: { ...(await authHeader()), "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  return (await manejar(r)).json() as Promise<T>;
}
```

- [ ] **Step 4: Add the `ApuEditar` type and `n_corridas` to `tipos.ts`**

En `web/src/lib/tipos.ts`:
1. Agregar la interfaz nueva (junto a `ApuNuevo`):

```typescript
export interface ApuEditar {
  nombre: string;
  unidad: string;
  grupo: string;
  componentes: ComponenteNuevo[];
}
```

2. En la interfaz `ApuDetalle`, agregar el campo opcional:

```typescript
  n_corridas?: number;
```

- [ ] **Step 5: Add `editarApu`/`borrarApu` to `autoria.ts`**

En `web/src/api/autoria.ts`:
1. Actualizar el import del cliente (línea 1) para incluir `apiPut` y `apiDelete`:

```typescript
import { apiGet, apiPost, apiPut, apiDelete, descargarArchivo } from "@/api/client";
```

2. Agregar `ApuEditar` a los tipos importados de `@/lib/tipos`.
3. Después de `crearApu`, agregar:

```typescript
export function editarApu(
  codigo: string,
  turno: string,
  body: ApuEditar,
): Promise<ApuResumen> {
  return apiPut<ApuResumen>(
    `/apus/${encodeURIComponent(codigo)}/${encodeURIComponent(turno)}`,
    body,
  );
}

export function borrarApu(codigo: string, turno: string): Promise<void> {
  return apiDelete(
    `/apus/${encodeURIComponent(codigo)}/${encodeURIComponent(turno)}`,
  );
}
```

- [ ] **Step 6: Run test + typecheck to verify they pass**

Run (desde `web/`): `npx vitest run src/api/autoria.editar.test.ts` → PASS.
Run (desde `web/`): `npx tsc --noEmit` → sin errores.

- [ ] **Step 7: Commit**

```bash
git add web/src/api/client.ts web/src/api/autoria.ts web/src/lib/tipos.ts web/src/api/autoria.editar.test.ts
git commit -m "feat(web): cliente editarApu/borrarApu + apiPut + tipos"
```

---

### Task 9: Frontend — modo edición en `DialogoAgregarApu` + acción "Editar" en `Apus.tsx`

**Files:**
- Modify: `web/src/components/autoria/DialogoAgregarApu.tsx`
- Modify: `web/src/pages/Apus.tsx`

**Interfaces:**
- Consumes: `editarApu` y `ApuDetalle`/`ApuEditar` (Task 8).
- Produces: `DialogoAgregarApu` acepta `modo?: "crear" | "editar"` e `inicial?: ApuDetalle | null`; en modo editar precarga, deshabilita `codigo`/`turno` y guarda con `editarApu`. `Apus.tsx` muestra "Editar" (rol `editor`) en el detalle expandido.

- [ ] **Step 1: Add edit-mode props + prefill to `DialogoAgregarApu.tsx`**

1. Actualizar imports (líneas 11-12): agregar `ApuDetalle` a los tipos y `editarApu` al cliente:

```typescript
import type { ComponenteNuevo, Insumo, ApuDetalle } from "@/lib/tipos";
import { crearApu, editarApu } from "@/api/autoria";
```

2. Extender la interfaz de props (reemplazar `DialogoAgregarApuProps`):

```typescript
interface DialogoAgregarApuProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreado: () => void;
  modo?: "crear" | "editar";
  inicial?: ApuDetalle | null;
}
```

3. En la firma del componente, aceptar los props nuevos con defaults:

```typescript
export function DialogoAgregarApu({
  open,
  onOpenChange,
  onCreado,
  modo = "crear",
  inicial = null,
}: DialogoAgregarApuProps) {
```

4. Justo después de los `useState` de `cab`/`filas`/`guardando`, agregar el efecto de precarga (usa `inicial` en modo editar al abrir):

```typescript
  useEffect(() => {
    if (!open) return;
    if (modo === "editar" && inicial) {
      setCab({
        codigo: inicial.codigo,
        turno: inicial.turno,
        nombre: inicial.nombre,
        unidad: inicial.unidad,
        grupo: inicial.grupo,
      });
      setFilas(
        inicial.composicion.length === 0
          ? [nuevaFila()]
          : inicial.composicion.map((c) => ({
              uid: uidSeq++,
              insumo_codigo: c.insumo_codigo,
              insumo_nombre: c.insumo_nombre,
              unidad: c.unidad,
              rendimiento: String(c.rendimiento),
            })),
      );
    }
  }, [open, modo, inicial]);
```

- [ ] **Step 2: Branch `guardar()` and adjust labels/disabled fields**

1. Reemplazar la función `guardar` para ramificar crear/editar:

```typescript
  async function guardar() {
    if (!valido) return;
    setGuardando(true);
    try {
      const payload = {
        nombre: cab.nombre.trim(),
        unidad: cab.unidad.trim(),
        grupo: cab.grupo.trim(),
        componentes: compValidos,
      };
      if (modo === "editar") {
        await editarApu(cab.codigo, cab.turno, payload);
        toast.success(`APU ${cab.codigo} (${cab.turno}) actualizado`);
      } else {
        await crearApu({ codigo: cab.codigo.trim(), turno: cab.turno, ...payload });
        toast.success(`APU ${cab.codigo.trim()} (${cab.turno}) creado`);
      }
      handleOpenChange(false);
      onCreado();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Error al guardar el APU";
      toast.error(msg);
      setGuardando(false);
    }
  }
```

2. En el `<DialogTitle>` usar el modo:

```tsx
          <DialogTitle className="text-sm">
            {modo === "editar" ? "Editar APU" : "Agregar APU"}
          </DialogTitle>
```

3. Deshabilitar `codigo` y `turno` en modo editar. En el `<input>` de código agregar `disabled={modo === "editar"}`; en el `<select>` de turno agregar `disabled={modo === "editar"}`.

4. En el botón de guardar, actualizar la etiqueta:

```tsx
          <Button size="sm" onClick={guardar} disabled={!valido || guardando}>
            {guardando
              ? modo === "editar"
                ? "Guardando…"
                : "Creando…"
              : modo === "editar"
                ? "Guardar cambios"
                : "Crear APU"}
          </Button>
```

- [ ] **Step 3: Wire "Editar" into `Apus.tsx`**

1. Imports: agregar `editarApu` no hace falta aquí (lo usa el diálogo). Asegurar que `ApuDetalle` ya está importado (lo está).
2. Estado nuevo (junto a `agregarOpen`):

```typescript
  const [editarDetalle, setEditarDetalle] = useState<ApuDetalle | null>(null);
```

3. Pasar props al detalle expandido: en el render de `<DetalleApu detalle={estado} />` (dentro del `TableCell` expandido), reemplazar por:

```tsx
                          <DetalleApu
                            detalle={estado}
                            puedeEditar={puedeEditar}
                            onEditar={() => setEditarDetalle(estado)}
                          />
```

4. Extender el componente `DetalleApu` (firma + botón de editar al final del encabezado):

```tsx
function DetalleApu({
  detalle,
  puedeEditar,
  onEditar,
}: {
  detalle: ApuDetalle;
  puedeEditar: boolean;
  onEditar: () => void;
}) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3 flex-wrap text-xs">
        <span className="font-mono text-muted-foreground">
          APU: {detalle.codigo} · {detalle.turno}
        </span>
        <span className="text-muted-foreground truncate max-w-md">{detalle.nombre}</span>
        {puedeEditar && (
          <Button size="xs" variant="outline" className="ml-auto" onClick={onEditar}>
            Editar
          </Button>
        )}
      </div>
```

(el resto de `DetalleApu` queda igual.)

5. Renderizar el diálogo en modo edición (dentro del bloque `{puedeEditar && (<> ... </>)}`, después del `DialogoImportarApus`):

```tsx
          <DialogoAgregarApu
            key={editarDetalle ? `${editarDetalle.codigo}@@${editarDetalle.turno}` : "nuevo-edit"}
            open={editarDetalle !== null}
            onOpenChange={(v) => { if (!v) setEditarDetalle(null); }}
            onCreado={recargar}
            modo="editar"
            inicial={editarDetalle}
          />
```

(El `key` fuerza el remonte del diálogo por APU, garantizando que el efecto de precarga corra con el `inicial` correcto.)

- [ ] **Step 4: Typecheck + build**

Run (desde `web/`): `npx tsc --noEmit` → sin errores.
Run (desde `web/`): `npm run build` → build OK (`web/dist` regenerado).

- [ ] **Step 5: Manual smoke**

Levantar el server y la web (coordinar con el usuario; no reiniciar el proceso del server sin aviso). En la página **APUs**: expandir un APU → **Editar** → cambiar un rendimiento y el nombre → **Guardar cambios** → verificar toast y que el detalle refleje el cambio. Confirmar que `código`/`turno` están deshabilitados.

- [ ] **Step 6: Commit**

```bash
git add web/src/components/autoria/DialogoAgregarApu.tsx web/src/pages/Apus.tsx
git commit -m "feat(web): editar APU reutilizando DialogoAgregarApu en modo edición"
```

---

### Task 10: Frontend — `DialogoBorrarApu` + acción "Borrar" (admin) en `Apus.tsx`

**Files:**
- Create: `web/src/components/autoria/DialogoBorrarApu.tsx`
- Modify: `web/src/pages/Apus.tsx`

**Interfaces:**
- Consumes: `borrarApu` (Task 8), `ApuDetalle` con `n_corridas` (Tasks 6/8), `puede` (rol `admin`).
- Produces: diálogo de confirmación de borrado que informa `n_corridas`; acción "Borrar" visible solo para `admin`.

- [ ] **Step 1: Create `DialogoBorrarApu.tsx`**

Crear `web/src/components/autoria/DialogoBorrarApu.tsx`:

```tsx
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { ApuDetalle } from "@/lib/tipos";
import { borrarApu } from "@/api/autoria";

interface DialogoBorrarApuProps {
  apu: ApuDetalle | null;
  onOpenChange: (open: boolean) => void;
  onBorrado: () => void;
}

export function DialogoBorrarApu({ apu, onOpenChange, onBorrado }: DialogoBorrarApuProps) {
  const [borrando, setBorrando] = useState(false);
  const n = apu?.n_corridas ?? 0;

  async function confirmar() {
    if (!apu) return;
    setBorrando(true);
    try {
      await borrarApu(apu.codigo, apu.turno);
      toast.success(`APU ${apu.codigo} (${apu.turno}) borrado`);
      onOpenChange(false);
      onBorrado();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Error al borrar el APU");
    } finally {
      setBorrando(false);
    }
  }

  return (
    <Dialog open={apu !== null} onOpenChange={(v) => { if (!v) onOpenChange(false); }}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="text-sm">Borrar APU</DialogTitle>
        </DialogHeader>
        {apu && (
          <div className="flex flex-col gap-2 text-xs">
            <p>
              ¿Borrar el APU <span className="font-mono">{apu.codigo}</span> ({apu.turno})
              — {apu.nombre}?
            </p>
            {n > 0 && (
              <p className="text-muted-foreground">
                Este APU está referenciado en {n} corrida{n === 1 ? "" : "s"}. Las corridas
                ya armadas conservan su composición y no se verán afectadas.
              </p>
            )}
          </div>
        )}
        <DialogFooter>
          <Button size="sm" variant="outline" onClick={() => onOpenChange(false)} disabled={borrando}>
            Cancelar
          </Button>
          <Button size="sm" variant="destructive" onClick={confirmar} disabled={borrando}>
            {borrando ? "Borrando…" : "Borrar"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 2: Wire "Borrar" (admin) into `Apus.tsx`**

1. Imports: agregar el diálogo nuevo:

```typescript
import { DialogoBorrarApu } from "@/components/autoria/DialogoBorrarApu";
```

2. Rol admin + estado (junto a `puedeEditar` y `editarDetalle`):

```typescript
  const puedeBorrar = puede(perfil?.rol, "admin");
  const [borrarDetalle, setBorrarDetalle] = useState<ApuDetalle | null>(null);
```

3. Pasar `puedeBorrar`/`onBorrar` al `DetalleApu` (junto a los props de Task 9):

```tsx
                          <DetalleApu
                            detalle={estado}
                            puedeEditar={puedeEditar}
                            onEditar={() => setEditarDetalle(estado)}
                            puedeBorrar={puedeBorrar}
                            onBorrar={() => setBorrarDetalle(estado)}
                          />
```

4. Extender `DetalleApu` (firma + botón borrar junto al de editar):

```tsx
function DetalleApu({
  detalle,
  puedeEditar,
  onEditar,
  puedeBorrar,
  onBorrar,
}: {
  detalle: ApuDetalle;
  puedeEditar: boolean;
  onEditar: () => void;
  puedeBorrar: boolean;
  onBorrar: () => void;
}) {
```

Y en el encabezado, después del botón Editar, agregar (el `ml-auto` pasa al primer botón del grupo):

```tsx
        {(puedeEditar || puedeBorrar) && (
          <div className="ml-auto flex gap-2">
            {puedeEditar && (
              <Button size="xs" variant="outline" onClick={onEditar}>
                Editar
              </Button>
            )}
            {puedeBorrar && (
              <Button size="xs" variant="destructive" onClick={onBorrar}>
                Borrar
              </Button>
            )}
          </div>
        )}
```

(reemplaza el botón "Editar" suelto agregado en Task 9 por este grupo.)

5. Renderizar el diálogo de borrado. Como `puedeBorrar` implica `puedeEditar` (admin ⊇ editor), va dentro del mismo bloque `{puedeEditar && (<> ... </>)}`, después del `DialogoAgregarApu` de edición:

```tsx
          <DialogoBorrarApu
            apu={borrarDetalle}
            onOpenChange={(v) => { if (!v) setBorrarDetalle(null); }}
            onBorrado={recargar}
          />
```

- [ ] **Step 3: Typecheck + build**

Run (desde `web/`): `npx tsc --noEmit` → sin errores.
Run (desde `web/`): `npm run build` → build OK.

- [ ] **Step 4: Manual smoke**

Con un usuario **admin**: expandir un APU → **Borrar** → confirmar el diálogo (verificar que si el APU está en corridas, muestra el aviso de `n_corridas`) → toast y desaparición de la fila. Con un usuario **editor**: verificar que el botón **Borrar** NO aparece (sí el de Editar).

- [ ] **Step 5: Commit**

```bash
git add web/src/components/autoria/DialogoBorrarApu.tsx web/src/pages/Apus.tsx
git commit -m "feat(web): borrar APU (admin) con diálogo de confirmación y aviso de n_corridas"
```

---

## Verificación final

- [ ] Backend completo: `python -m pytest tests/ -q` → verde.
- [ ] (Opcional, si hay Postgres) `TEST_DATABASE_URL=... python -m pytest tests/test_repositorios_contrato.py -q` → verde en ambos backends.
- [ ] Frontend: desde `web/`, `npx tsc --noEmit` y `npx vitest run` → verde; `npm run build` → OK.
- [ ] Privacidad (Invariante #1): `python -m pytest tests/test_servicio_privacidad.py -q` → verde (la IA nunca ve dinero).
- [ ] Smoke manual de editar y borrar en la página APUs, con roles editor y admin.
