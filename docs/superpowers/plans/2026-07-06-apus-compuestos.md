# APUs compuestos (Fase 1 backend) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un componente de APU puede ser un sub-APU marcado explícitamente (`tipo='apu'`), costeado en vivo desde su composición vigente, con guarda de ciclos; y una migración auditada marca los sub-APUs ya existentes.

**Architecture:** Backend Python. `apu_componentes` gana `tipo`/`ref_shift` (aditivo, dual-backend SQLite+Postgres). El motor de precios (`pricing.py`, único módulo con dinero) costea sub-APUs recursivamente. Una función de servicio + comando CLI migra los datos existentes con auditoría. La IA solo ve `tipo` como estructura (Invariante #1 intacta).

**Tech Stack:** Python 3, SQLite + Postgres (psycopg), pytest, argparse (CLI).

## Global Constraints

- **Solo backend.** No tocar `web/` ni el frontend. Modificar solo `apu_tool/`, `db/` y `tests/`.
- **Invariante #1:** la IA nunca ve dinero. El costeo recursivo vive solo en `apu_tool/dominio/pricing.py`. `DePricedComponent` solo gana `tipo` (estructura, sin dinero); `assert_no_money` debe seguir pasando.
- **Persistencia aislada:** SQL crudo solo en los repos (`apu_tool/datos/apus_db.py`, `apu_tool/datos/pg/apus_pg.py`). Nada de SQL en dominio/servicio.
- **Cambios de esquema aditivos e idempotentes:** SQLite vía `PRAGMA table_info` + `ALTER TABLE ADD COLUMN` en `init_schema`; Postgres vía `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` en `db/pg/apus.sql`. Igual patrón que `modo`/`snapshot_json`.
- **Sin regresión:** un componente sin marcar es `tipo='insumo'` y se costea EXACTAMENTE como hoy.
- **Turnos:** etiquetas `config.SHIFT_DIURNO='DIURNO'`, `config.SHIFT_NOCTURNO='NOCTURNO'`. La identidad de un APU es `(codigo, shift)`.
- Español en dominio/mensajes. Sin dependencias nuevas. Verificación: `python -m pytest tests/ -q` verde.

---

### Task 1: Campos de modelo `tipo`/`ref_shift` + `tipo` en la vista DePriced

**Files:**
- Modify: `apu_tool/nucleo/models.py`
- Modify: `apu_tool/dominio/privacy.py`
- Test: `tests/test_modelos_subapu.py`

**Interfaces:**
- Produces (usado por Tareas 2, 3, 4, 5):
  - `ApuComponent` con `tipo: str = "insumo"`, `ref_shift: str = ""`.
  - `CostedComponent` con `tipo: str = "insumo"`, `ref_shift: str = ""`.
  - `DePricedComponent` con `tipo: str = "insumo"`.
  - `privacy.depriced_component_to_dict` incluye la clave `"tipo"`.

- [ ] **Step 1: Write the failing test**

Crear `tests/test_modelos_subapu.py`:

```python
from apu_tool.nucleo.models import (
    ApuComponent, CostedComponent, DePricedComponent, DePricedApu,
)
from apu_tool.dominio.privacy import depriced_apu_to_dict, assert_no_money


def test_apucomponent_default_es_insumo():
    c = ApuComponent("A", "DIURNO", "100", "CEMENTO", "KG", 3.0, 900)
    assert c.tipo == "insumo" and c.ref_shift == ""


def test_apucomponent_como_subapu():
    c = ApuComponent("A", "DIURNO", "3017", "SUB APU", "M3", 1.0, 0.0,
                     tipo="apu", ref_shift="DIURNO")
    assert c.tipo == "apu" and c.ref_shift == "DIURNO"


def test_costedcomponent_default_es_insumo():
    c = CostedComponent("100", "CEMENTO", "KG", 3.0, 900, "PRECIO IDU", 2700)
    assert c.tipo == "insumo" and c.ref_shift == ""


def test_depriced_incluye_tipo_y_sigue_sin_dinero():
    apu = DePricedApu("A", "MURO", "M2", "DIURNO", "", (
        DePricedComponent("3017", "SUB APU", "M3", 1.0, tipo="apu"),))
    d = depriced_apu_to_dict(apu)
    assert d["componentes"][0]["tipo"] == "apu"
    assert_no_money(d)  # no debe lanzar PrivacyViolation
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_modelos_subapu.py -q`
Expected: FAIL — `ApuComponent`/`CostedComponent` no aceptan `tipo`/`ref_shift`; `DePricedComponent` no acepta `tipo`; el dict no tiene `"tipo"`.

- [ ] **Step 3: Añadir campos a los dataclasses**

En `apu_tool/nucleo/models.py`, `ApuComponent` (bloque actual líneas 40-48) → añadir dos campos con default al final:

```python
@dataclass(frozen=True)
class ApuComponent:
    apu_codigo: str
    shift: str
    insumo_codigo: str
    insumo_nombre: str
    unidad: str
    rendimiento: float
    precio_unitario_hist: float   # costo histórico embebido (NO se expone a la IA)
    tipo: str = "insumo"          # "insumo" | "apu" (sub-APU)
    ref_shift: str = ""           # turno del sub-APU cuando tipo == "apu"
```

`DePricedComponent` (líneas 90-95) → añadir `tipo`:

```python
@dataclass(frozen=True)
class DePricedComponent:
    insumo_codigo: str
    insumo_nombre: str
    unidad: str
    rendimiento: float            # cantidad, no es dinero
    tipo: str = "insumo"          # estructura: "insumo" | "apu" (sin dinero)
```

`CostedComponent` (líneas 152-161) → añadir dos campos con default al final:

```python
@dataclass
class CostedComponent:
    insumo_codigo: str
    insumo_nombre: str
    unidad: str
    rendimiento: float
    precio_unitario: float        # precio usado (catálogo actual o histórico)
    fuente_precio: str
    costo: float                  # rendimiento * precio_unitario
    calidad_cruce: str = "exacto" # exacto | aproximado | ambiguo | huerfano | apu | ciclo
    tipo: str = "insumo"          # "insumo" | "apu"
    ref_shift: str = ""           # turno del sub-APU cuando tipo == "apu"
```

- [ ] **Step 4: Exponer `tipo` a la IA (solo estructura)**

En `apu_tool/dominio/privacy.py`, `depriced_component_to_dict` (líneas 32-38) → añadir `"tipo"`:

```python
def depriced_component_to_dict(c: DePricedComponent) -> dict[str, Any]:
    return {
        "insumo_codigo": c.insumo_codigo,
        "insumo_nombre": c.insumo_nombre,
        "unidad": c.unidad,
        "rendimiento": round(c.rendimiento, 6),
        "tipo": c.tipo,
    }
```

(`"tipo"` no está en `_FORBIDDEN_KEYS` ni es dinero → `assert_no_money` sigue pasando.)

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_modelos_subapu.py -q`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add apu_tool/nucleo/models.py apu_tool/dominio/privacy.py tests/test_modelos_subapu.py
git commit -m "feat(modelos): tipo/ref_shift en ApuComponent/CostedComponent + tipo en DePriced (sub-APUs)"
```

---

### Task 2: Persistir `tipo`/`ref_shift` en la biblioteca (esquema + repos dual-backend)

**Files:**
- Modify: `db/apus.sql`, `db/pg/apus.sql`
- Modify: `apu_tool/datos/apus_db.py`, `apu_tool/datos/pg/apus_pg.py`
- Test: `tests/test_apus_db.py`

**Interfaces:**
- Consumes: `ApuComponent.tipo`/`ref_shift`, `DePricedComponent.tipo` (Task 1).
- Produces: `insert_components`, `crear_apu`, `editar_apu` persisten `tipo`/`ref_shift`; `get_components` los devuelve; `get_depriced_apu` propaga `tipo`.

- [ ] **Step 1: Write the failing test**

Añadir al final de `tests/test_apus_db.py`:

```python
def test_round_trip_subapu(apus):
    apus.crear_apu(
        Apu("C3", "COMPUESTO", "M2", "DIURNO"),
        [ApuComponent("C3", "DIURNO", "3017", "SUB APU", "M3", 1.0, 0.0,
                      tipo="apu", ref_shift="DIURNO"),
         ApuComponent("C3", "DIURNO", "100", "CEMENTO", "KG", 2.0, 900)])
    comps = apus.get_components("C3", "DIURNO")
    sub = [c for c in comps if c.insumo_codigo == "3017"][0]
    ins = [c for c in comps if c.insumo_codigo == "100"][0]
    assert sub.tipo == "apu" and sub.ref_shift == "DIURNO"
    assert ins.tipo == "insumo" and ins.ref_shift == ""


def test_depriced_propaga_tipo(apus):
    apus.crear_apu(
        Apu("C4", "COMP", "M2", "DIURNO"),
        [ApuComponent("C4", "DIURNO", "3017", "SUB", "M3", 1.0, 0.0,
                      tipo="apu", ref_shift="DIURNO")])
    dp = apus.get_depriced_apu("C4", "DIURNO")
    assert dp.componentes[0].tipo == "apu"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_apus_db.py -q`
Expected: FAIL — las columnas `tipo`/`ref_shift` no existen / no se leen; `ApuComponent.tipo` vuelve por default y no se persiste.

- [ ] **Step 3: Esquema SQLite (`db/apus.sql`)**

En `db/apus.sql`, en `CREATE TABLE IF NOT EXISTS apu_componentes`, añadir dos columnas antes de `PRIMARY KEY`:

```sql
    rendimiento           REAL,
    precio_unitario_hist  REAL,
    tipo                  TEXT NOT NULL DEFAULT 'insumo',   -- 'insumo' | 'apu' (sub-APU)
    ref_shift             TEXT,                             -- turno del sub-APU si tipo='apu'
    PRIMARY KEY (apu_codigo, shift, seq),
```

- [ ] **Step 4: Migración SQLite en `init_schema` (`apu_tool/datos/apus_db.py`)**

Reemplazar `init_schema` (líneas 44-46) por:

```python
    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(_load_schema())
            cols = {r["name"] for r in
                    conn.execute("PRAGMA table_info(apu_componentes)").fetchall()}
            if "tipo" not in cols:
                conn.execute("ALTER TABLE apu_componentes "
                             "ADD COLUMN tipo TEXT NOT NULL DEFAULT 'insumo'")
            if "ref_shift" not in cols:
                conn.execute("ALTER TABLE apu_componentes ADD COLUMN ref_shift TEXT")
```

- [ ] **Step 5: Escritura/lectura SQLite (`apu_tool/datos/apus_db.py`)**

Reemplazar `insert_components` (líneas 64-85) por:

```python
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
                             c.precio_unitario_hist, c.tipo, c.ref_shift))
            conn.executemany(
                "INSERT INTO apu_componentes "
                "(apu_codigo, shift, seq, insumo_codigo, insumo_nombre, unidad, "
                " rendimiento, precio_unitario_hist, tipo, ref_shift) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        return len(rows)
```

En `_crear_apu` (líneas 97-113) y `_editar_apu` (líneas 122-140), reemplazar la construcción de `rows` y el `executemany` (idénticos en ambos) por:

```python
        rows = [(str(apu.codigo), apu.shift, seq, c.insumo_codigo, c.insumo_nombre,
                 c.unidad, c.rendimiento, c.precio_unitario_hist, c.tipo, c.ref_shift)
                for seq, c in enumerate(componentes)]
        if rows:
            conn.executemany(
                "INSERT INTO apu_componentes "
                "(apu_codigo, shift, seq, insumo_codigo, insumo_nombre, unidad, "
                " rendimiento, precio_unitario_hist, tipo, ref_shift) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
```

Reemplazar `get_components` (líneas 216-225) por:

```python
    def get_components(self, apu_codigo: str, shift: str) -> list[ApuComponent]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM apu_componentes WHERE apu_codigo=? AND shift=? ORDER BY seq",
                (str(apu_codigo), shift)).fetchall()
        return [ApuComponent(
            apu_codigo=r["apu_codigo"], shift=r["shift"], insumo_codigo=r["insumo_codigo"],
            insumo_nombre=r["insumo_nombre"], unidad=r["unidad"],
            rendimiento=r["rendimiento"] or 0.0,
            precio_unitario_hist=r["precio_unitario_hist"] or 0.0,
            tipo=(r["tipo"] or "insumo"), ref_shift=(r["ref_shift"] or "")) for r in rows]
```

Reemplazar `get_depriced_apu` (líneas 227-237) el bloque de `componentes=` por:

```python
            componentes=tuple(
                DePricedComponent(c.insumo_codigo, c.insumo_nombre, c.unidad,
                                  c.rendimiento, c.tipo)
                for c in comps))
```

- [ ] **Step 6: Esquema Postgres (`db/pg/apus.sql`)**

En `db/pg/apus.sql`, añadir a `CREATE TABLE ... apus.apu_componentes` las dos columnas (antes de `PRIMARY KEY`):

```sql
    precio_unitario_hist  DOUBLE PRECISION,
    tipo                  TEXT NOT NULL DEFAULT 'insumo',
    ref_shift             TEXT,
    PRIMARY KEY (apu_codigo, shift, seq),
```

Y añadir, después del bloque `CREATE TABLE` de `apu_componentes` (para bases ya creadas), estas sentencias idempotentes:

```sql
ALTER TABLE apus.apu_componentes ADD COLUMN IF NOT EXISTS tipo TEXT NOT NULL DEFAULT 'insumo';
ALTER TABLE apus.apu_componentes ADD COLUMN IF NOT EXISTS ref_shift TEXT;
```

- [ ] **Step 7: Escritura/lectura Postgres (`apu_tool/datos/pg/apus_pg.py`)**

Reemplazar `insert_components` (líneas 42-64): añadir `c.tipo, c.ref_shift` a cada tupla de `rows` y las columnas `tipo, ref_shift` al INSERT con dos `%s` más:

```python
                rows.append((c.apu_codigo, c.shift, seq, c.insumo_codigo,
                             c.insumo_nombre, c.unidad, c.rendimiento,
                             c.precio_unitario_hist, c.tipo, c.ref_shift))
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO apus.apu_componentes "
                    "(apu_codigo, shift, seq, insumo_codigo, insumo_nombre, unidad, "
                    " rendimiento, precio_unitario_hist, tipo, ref_shift) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", rows)
```

En `_crear_apu` (líneas 74-92) y `_editar_apu` (líneas 101-120), reemplazar `rows`/`executemany` (idénticos) por:

```python
        rows = [(str(apu.codigo), apu.shift, seq, c.insumo_codigo, c.insumo_nombre,
                 c.unidad, c.rendimiento, c.precio_unitario_hist, c.tipo, c.ref_shift)
                for seq, c in enumerate(componentes)]
        if rows:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO apus.apu_componentes "
                    "(apu_codigo, shift, seq, insumo_codigo, insumo_nombre, unidad, "
                    " rendimiento, precio_unitario_hist, tipo, ref_shift) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", rows)
```

Reemplazar `get_components` (líneas 198-207) por:

```python
    def get_components(self, apu_codigo: str, shift: str) -> list[ApuComponent]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM apus.apu_componentes WHERE apu_codigo=%s AND shift=%s ORDER BY seq",
                (str(apu_codigo), shift)).fetchall()
        return [ApuComponent(
            apu_codigo=r["apu_codigo"], shift=r["shift"], insumo_codigo=r["insumo_codigo"],
            insumo_nombre=r["insumo_nombre"], unidad=r["unidad"],
            rendimiento=r["rendimiento"] or 0.0,
            precio_unitario_hist=r["precio_unitario_hist"] or 0.0,
            tipo=(r["tipo"] or "insumo"), ref_shift=(r["ref_shift"] or "")) for r in rows]
```

En `get_depriced_apu` (líneas 209-219), reemplazar el bloque `componentes=` por el mismo de SQLite (añadir `c.tipo` como 5º argumento de `DePricedComponent`).

- [ ] **Step 8: Run test to verify it passes**

Run: `python -m pytest tests/test_apus_db.py -q`
Expected: PASS (los 2 nuevos + los existentes). El contrato `RepositorioApus` sigue cumpliéndose.

- [ ] **Step 9: Commit**

```bash
git add db/apus.sql db/pg/apus.sql apu_tool/datos/apus_db.py apu_tool/datos/pg/apus_pg.py tests/test_apus_db.py
git commit -m "feat(datos): persistir tipo/ref_shift de componentes (sub-APUs), dual-backend + migración aditiva"
```

---

### Task 3: Costeo recursivo de sub-APUs en el motor de precios

**Files:**
- Modify: `apu_tool/dominio/pricing.py`
- Test: `tests/test_pricing_subapu.py`

**Interfaces:**
- Consumes: `ApuComponent.tipo`/`ref_shift` (Task 1/2); `CostedComponent.tipo`/`ref_shift`.
- Produces: `PricingEngine.cost_component(comp, _visitando=())`; `cost_apu`/`cost_components` sin cambio de firma pública; sub-APU → `CostedComponent(tipo="apu", fuente_precio="APU", calidad_cruce="apu")`; ciclo → `calidad_cruce="ciclo"` con respaldo histórico.

- [ ] **Step 1: Write the failing test**

Crear `tests/test_pricing_subapu.py`:

```python
import pytest
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo
from apu_tool.dominio.pricing import PricingEngine


@pytest.fixture()
def alm(tmp_path):
    a = Almacen(tmp_path / "p.db", tmp_path / "a.db")
    a.reset()
    a.precios.insert_insumos([Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU")])
    # sub-APU B: 2 KG de cemento = 2000
    a.apus.insert_apus([Apu("B", "SUBAPU", "M3", "DIURNO")])
    a.apus.insert_components([ApuComponent("B", "DIURNO", "100", "CEMENTO", "KG", 2.0, 0.0)])
    # APU A usa 3 de B (sub-APU) => 6000
    a.apus.insert_apus([Apu("A", "COMP", "M2", "DIURNO")])
    a.apus.insert_components([ApuComponent(
        "A", "DIURNO", "B", "SUBAPU", "M3", 3.0, 999, tipo="apu", ref_shift="DIURNO")])
    return a


def test_subapu_se_costea_en_vivo(alm):
    eng = PricingEngine(alm)
    costed, total = eng.cost_apu("A", "DIURNO")
    assert total == pytest.approx(6000)
    assert costed[0].tipo == "apu"
    assert costed[0].fuente_precio == "APU"
    assert costed[0].calidad_cruce == "apu"
    assert costed[0].costo == pytest.approx(6000)


def test_subapu_refleja_cambio_de_precio(alm):
    alm.precios.set_precio("100", 2000, nombre="CEMENTO")
    eng = PricingEngine(alm)
    _, total = eng.cost_apu("A", "DIURNO")
    assert total == pytest.approx(12000)   # 3 * (2 * 2000)


def test_anidamiento_dos_niveles(alm):
    alm.apus.insert_apus([Apu("C", "NIVEL2", "M2", "DIURNO")])
    alm.apus.insert_components([ApuComponent(
        "C", "DIURNO", "A", "COMP", "M2", 1.0, 0.0, tipo="apu", ref_shift="DIURNO")])
    eng = PricingEngine(alm)
    _, total = eng.cost_apu("C", "DIURNO")
    assert total == pytest.approx(6000)


def test_ciclo_self_ref_no_cuelga(alm):
    alm.apus.insert_apus([Apu("Z", "Z", "M2", "DIURNO")])
    alm.apus.insert_components([ApuComponent(
        "Z", "DIURNO", "Z", "Z", "M2", 1.0, 500, tipo="apu", ref_shift="DIURNO")])
    eng = PricingEngine(alm)
    costed, total = eng.cost_apu("Z", "DIURNO")
    assert total == pytest.approx(500)          # el back-edge cae a histórico
    assert costed[0].calidad_cruce == "ciclo"


def test_componente_insumo_sin_cambio(alm):
    alm.apus.insert_apus([Apu("M", "MAT", "M2", "DIURNO")])
    alm.apus.insert_components([ApuComponent("M", "DIURNO", "100", "CEMENTO", "KG", 5.0, 0.0)])
    eng = PricingEngine(alm)
    costed, total = eng.cost_apu("M", "DIURNO")
    assert total == pytest.approx(5000)         # 5 * 1000
    assert costed[0].tipo == "insumo" and costed[0].calidad_cruce == "exacto"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pricing_subapu.py -q`
Expected: FAIL — `cost_apu("A")` costea el componente `B` como insumo (huérfano → histórico 999), no recursivamente.

- [ ] **Step 3: Implementar la recursión**

Reemplazar el cuerpo de `PricingEngine` en `apu_tool/dominio/pricing.py` (líneas 19-56) por:

```python
class PricingEngine:
    def __init__(self, almacen: Almacen):
        self.alm = almacen
        self._cache: dict[str, list] = {}          # codigo -> list[Insumo] candidatos
        self._apu_cost_cache: dict[tuple, float] = {}  # (codigo, shift) -> costo_unitario

    def _candidatos(self, codigo: str) -> list:
        if not codigo:
            return []
        if codigo not in self._cache:
            self._cache[codigo] = self.alm.precios.get_candidatos(codigo)
        return self._cache[codigo]

    def cost_component(self, comp: ApuComponent, _visitando: tuple = ()) -> CostedComponent:
        if (comp.tipo or "insumo") == "apu":
            return self._cost_subapu(comp, _visitando)
        r = cruce.resolver(self._candidatos(comp.insumo_codigo), comp.insumo_nombre)
        if r.insumo is not None and r.insumo.precio > 0:        # EXACTO o APROXIMADO
            precio, fuente = r.insumo.precio, r.insumo.fuente_precio
        else:                                                   # AMBIGUO o HUERFANO
            precio, fuente = comp.precio_unitario_hist, "histórico"
        costo = comp.rendimiento * precio
        return CostedComponent(
            insumo_codigo=comp.insumo_codigo, insumo_nombre=comp.insumo_nombre,
            unidad=comp.unidad, rendimiento=comp.rendimiento,
            precio_unitario=precio, fuente_precio=fuente, costo=costo,
            calidad_cruce=r.calidad.value, tipo="insumo", ref_shift="")

    def _cost_subapu(self, comp: ApuComponent, visitando: tuple) -> CostedComponent:
        sub_shift = comp.ref_shift or comp.shift
        clave = (comp.insumo_codigo, sub_shift)
        if clave in visitando:                                  # ciclo -> respaldo histórico
            precio = comp.precio_unitario_hist
            return CostedComponent(
                insumo_codigo=comp.insumo_codigo, insumo_nombre=comp.insumo_nombre,
                unidad=comp.unidad, rendimiento=comp.rendimiento,
                precio_unitario=precio, fuente_precio="histórico",
                costo=comp.rendimiento * precio, calidad_cruce="ciclo",
                tipo="apu", ref_shift=sub_shift)
        unit = self._costo_unitario_apu(comp.insumo_codigo, sub_shift, visitando + (clave,))
        return CostedComponent(
            insumo_codigo=comp.insumo_codigo, insumo_nombre=comp.insumo_nombre,
            unidad=comp.unidad, rendimiento=comp.rendimiento,
            precio_unitario=unit, fuente_precio="APU",
            costo=comp.rendimiento * unit, calidad_cruce="apu",
            tipo="apu", ref_shift=sub_shift)

    def _costo_unitario_apu(self, codigo: str, shift: str, visitando: tuple) -> float:
        clave = (codigo, shift)
        if clave in self._apu_cost_cache:                       # memoización por pasada
            return self._apu_cost_cache[clave]
        comps = self.alm.apus.get_components(codigo, shift)
        total = sum(self.cost_component(c, visitando).costo for c in comps)
        self._apu_cost_cache[clave] = total
        return total

    def cost_components(self, comps: list[ApuComponent]) -> tuple[list[CostedComponent], float]:
        costed = [self.cost_component(c) for c in comps]
        total = sum(c.costo for c in costed)
        return costed, total

    def cost_apu(self, apu_codigo: str, shift: str) -> tuple[list[CostedComponent], float]:
        comps = self.alm.apus.get_components(apu_codigo, shift)
        seed = ((apu_codigo, shift),)                           # detecta auto-referencia nivel 1
        costed = [self.cost_component(c, seed) for c in comps]
        return costed, sum(c.costo for c in costed)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_pricing_subapu.py tests/test_pricing_cruce.py -q`
Expected: PASS (los nuevos + los de cruce existentes; sin regresión en el camino insumo).

- [ ] **Step 5: Commit**

```bash
git add apu_tool/dominio/pricing.py tests/test_pricing_subapu.py
git commit -m "feat(pricing): costeo recursivo de sub-APUs (guarda de ciclos + memoización)"
```

---

### Task 4: Migración `marcar-subapus` (auto-marcado + auditoría) + comando CLI

**Files:**
- Modify: `apu_tool/datos/repositorio.py` (Protocol), `apu_tool/datos/apus_db.py`, `apu_tool/datos/pg/apus_pg.py`
- Create: `apu_tool/servicio/subapus.py`
- Modify: `apu_tool/interfaz/cli.py`
- Test: `tests/test_subapus_migracion.py`

**Interfaces:**
- Consumes: repos con `tipo`/`ref_shift` (Task 2); `registrar_auditoria(alm, conn, actor, accion, entidad_tipo, entidad_id, antes=None, despues=None, contexto=None)`; `alm.transaccion("apus")`.
- Produces:
  - Repo: `componentes_subapu_candidatos() -> list[dict]` (`{apu_codigo, shift, seq, insumo_codigo}`), `set_componente_subapu(apu_codigo, shift, seq, ref_shift, conn=None) -> None`.
  - Servicio: `marcar_subapus(alm, actor=None) -> dict` (`{"apus_afectados", "componentes_marcados"}`).
  - CLI: `python run_cli.py marcar-subapus`.

- [ ] **Step 1: Write the failing test**

Crear `tests/test_subapus_migracion.py`:

```python
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent
from apu_tool.servicio.subapus import marcar_subapus


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def test_marca_subapus_y_audita(tmp_path):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("B", "SUBAPU", "M3", "DIURNO"), Apu("A", "COMP", "M2", "DIURNO")])
    alm.apus.insert_components([
        ApuComponent("A", "DIURNO", "B", "SUBAPU", "M3", 1.0, 0.0),    # código B = un APU
        ApuComponent("A", "DIURNO", "100", "CEMENTO", "KG", 2.0, 900),  # insumo normal
    ])
    res = marcar_subapus(alm)
    assert res == {"apus_afectados": 1, "componentes_marcados": 1}
    comps = alm.apus.get_components("A", "DIURNO")
    sub = [c for c in comps if c.insumo_codigo == "B"][0]
    ins = [c for c in comps if c.insumo_codigo == "100"][0]
    assert sub.tipo == "apu" and sub.ref_shift == "DIURNO"
    assert ins.tipo == "insumo"
    _, total = alm.auditoria.listar(accion="apu.componente.marcar_subapu")
    assert total == 1


def test_ref_shift_cae_a_diurno(tmp_path):
    alm = _alm(tmp_path)
    # B solo existe DIURNO; el padre A es NOCTURNO -> ref_shift = DIURNO
    alm.apus.insert_apus([Apu("B", "SUBAPU", "M3", "DIURNO"), Apu("A", "COMP", "M2", "NOCTURNO")])
    alm.apus.insert_components([ApuComponent("A", "NOCTURNO", "B", "SUBAPU", "M3", 1.0, 0.0)])
    marcar_subapus(alm)
    sub = alm.apus.get_components("A", "NOCTURNO")[0]
    assert sub.tipo == "apu" and sub.ref_shift == "DIURNO"


def test_idempotente(tmp_path):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("B", "SUBAPU", "M3", "DIURNO"), Apu("A", "COMP", "M2", "DIURNO")])
    alm.apus.insert_components([ApuComponent("A", "DIURNO", "B", "SUBAPU", "M3", 1.0, 0.0)])
    marcar_subapus(alm)
    res2 = marcar_subapus(alm)
    assert res2 == {"apus_afectados": 0, "componentes_marcados": 0}
    _, total = alm.auditoria.listar(accion="apu.componente.marcar_subapu")
    assert total == 1   # no re-audita
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_subapus_migracion.py -q`
Expected: FAIL — no existe `apu_tool/servicio/subapus.py` ni los métodos de repo.

- [ ] **Step 3: Métodos de repo (SQLite)**

En `apu_tool/datos/apus_db.py`, añadir (junto a los otros métodos de escritura/lectura):

```python
    def componentes_subapu_candidatos(self) -> list[dict]:
        """Componentes tipo='insumo' cuyo código es un APU (candidatos a sub-APU)."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT apu_codigo, shift, seq, insumo_codigo FROM apu_componentes "
                "WHERE tipo = 'insumo' AND insumo_codigo IN (SELECT codigo FROM apus)"
            ).fetchall()
        return [{"apu_codigo": r["apu_codigo"], "shift": r["shift"],
                 "seq": r["seq"], "insumo_codigo": r["insumo_codigo"]} for r in rows]

    def set_componente_subapu(self, apu_codigo: str, shift: str, seq: int,
                              ref_shift: str, conn=None) -> None:
        sql = ("UPDATE apu_componentes SET tipo='apu', ref_shift=? "
               "WHERE apu_codigo=? AND shift=? AND seq=?")
        args = (ref_shift, str(apu_codigo), shift, int(seq))
        if conn is not None:
            conn.execute(sql, args)
            return
        with self.connect() as c:
            c.execute(sql, args)
```

- [ ] **Step 4: Métodos de repo (Postgres)**

En `apu_tool/datos/pg/apus_pg.py`, añadir:

```python
    def componentes_subapu_candidatos(self) -> list[dict]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT apu_codigo, shift, seq, insumo_codigo FROM apus.apu_componentes "
                "WHERE tipo = 'insumo' AND insumo_codigo IN (SELECT codigo FROM apus.apus)"
            ).fetchall()
        return [{"apu_codigo": r["apu_codigo"], "shift": r["shift"],
                 "seq": r["seq"], "insumo_codigo": r["insumo_codigo"]} for r in rows]

    def set_componente_subapu(self, apu_codigo: str, shift: str, seq: int,
                              ref_shift: str, conn=None) -> None:
        sql = ("UPDATE apus.apu_componentes SET tipo='apu', ref_shift=%s "
               "WHERE apu_codigo=%s AND shift=%s AND seq=%s")
        args = (ref_shift, str(apu_codigo), shift, int(seq))
        if conn is not None:
            conn.execute(sql, args)
            return
        with self.cx.connection() as c:
            c.execute(sql, args)
```

- [ ] **Step 5: Declarar en el Protocol (`apu_tool/datos/repositorio.py`)**

En `RepositorioApus` (Protocol, tras `component_counts`), añadir las firmas:

```python
    def componentes_subapu_candidatos(self) -> list[dict]:
        """Componentes tipo='insumo' cuyo código es un APU (candidatos a sub-APU)."""
        ...
    def set_componente_subapu(self, apu_codigo: str, shift: str, seq: int,
                              ref_shift: str, conn=None) -> None:
        """Marca un componente como sub-APU (tipo='apu') con su turno de referencia."""
        ...
```

- [ ] **Step 6: Servicio de migración (`apu_tool/servicio/subapus.py`)**

Crear `apu_tool/servicio/subapus.py`:

```python
"""Migración: marca como sub-APU los componentes cuyo código es un APU existente.

Auto-marcado con auditoría; idempotente. Regla de turno del sub-APU: hereda el del
APU padre si existe en ese turno; si no, DIURNO; si no, el único turno disponible.
NO ve la IA (solo estructura). Persistencia via los repos (sin SQL crudo aquí).
"""
from __future__ import annotations

from typing import Optional

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Perfil
from apu_tool.servicio.auditoria import registrar_auditoria


def _ref_shift(sub_cod: str, parent_shift: str, shifts_por_codigo: dict) -> str:
    disponibles = shifts_por_codigo.get(sub_cod, set())
    if parent_shift in disponibles:
        return parent_shift
    if config.SHIFT_DIURNO in disponibles:
        return config.SHIFT_DIURNO
    return next(iter(disponibles)) if disponibles else parent_shift


def marcar_subapus(alm: Almacen, actor: Optional[Perfil] = None) -> dict:
    alm.apus.init_schema()   # idempotente: asegura columnas tipo/ref_shift
    candidatos = alm.apus.componentes_subapu_candidatos()
    if not candidatos:
        return {"apus_afectados": 0, "componentes_marcados": 0}

    shifts_por_codigo: dict[str, set] = {}
    for cod, _nom, sh in alm.apus.apu_index():
        shifts_por_codigo.setdefault(cod, set()).add(sh)

    por_padre: dict[tuple, list] = {}
    for c in candidatos:
        c["ref_shift"] = _ref_shift(c["insumo_codigo"], c["shift"], shifts_por_codigo)
        por_padre.setdefault((c["apu_codigo"], c["shift"]), []).append(c)

    marcados = 0
    with alm.transaccion("apus") as conn:
        for (padre_cod, padre_shift), comps in por_padre.items():
            for c in comps:
                alm.apus.set_componente_subapu(
                    c["apu_codigo"], c["shift"], c["seq"], c["ref_shift"], conn=conn)
                marcados += 1
            registrar_auditoria(
                alm, conn, actor, "apu.componente.marcar_subapu", "apu", padre_cod,
                despues={"shift": padre_shift, "componentes": [
                    {"seq": c["seq"], "ref_codigo": c["insumo_codigo"],
                     "ref_shift": c["ref_shift"]} for c in comps]})
    return {"apus_afectados": len(por_padre), "componentes_marcados": marcados}
```

- [ ] **Step 7: Comando CLI (`apu_tool/interfaz/cli.py`)**

Añadir la función de comando (junto a las otras `cmd_*`):

```python
def cmd_marcar_subapus(args) -> int:
    from apu_tool.servicio.subapus import marcar_subapus
    alm = get_almacen()
    res = marcar_subapus(alm)
    print(f"Sub-APUs marcados: {res['componentes_marcados']} componentes "
          f"en {res['apus_afectados']} APUs.")
    return 0
```

Y en `build_parser`, antes de `return p`, registrar el subcomando:

```python
    pms = sub.add_parser(
        "marcar-subapus",
        help="Marcar como sub-APU los componentes cuyo código es un APU (idempotente, auditado).")
    pms.set_defaults(func=cmd_marcar_subapus)
```

- [ ] **Step 8: Run test to verify it passes**

Run: `python -m pytest tests/test_subapus_migracion.py -q`
Expected: PASS (3 tests).

- [ ] **Step 9: Commit**

```bash
git add apu_tool/datos/repositorio.py apu_tool/datos/apus_db.py apu_tool/datos/pg/apus_pg.py apu_tool/servicio/subapus.py apu_tool/interfaz/cli.py tests/test_subapus_migracion.py
git commit -m "feat(subapus): migración idempotente marcar-subapus (auto-marcado + auditoría) + CLI"
```

---

### Task 5: Propagar `tipo`/`ref_shift` en la corrida (estructura + respaldo)

**Files:**
- Modify: `apu_tool/servicio/corridas.py`
- Test: `tests/test_servicio_corridas.py`

**Interfaces:**
- Consumes: `CostedComponent.tipo`/`ref_shift` (Task 1/3); `PricingEngine` recursivo (Task 3).
- Produces: `_estructura` incluye `tipo`/`ref_shift`; el respaldo de `_costear_row` reconstruye `ApuComponent` con ellos (costea sub-APUs aun si el APU padre fue borrado).

**Nota:** El camino de corrida ACTIVA ya funciona sin cambios (re-lee `alm.apus.get_components`, que ahora traen `tipo`/`ref_shift`, y `cost_components` recursa). El snapshot de corrida CONGELADA no cambia (guarda el costo ya calculado; `_assembled_desde_snapshot` reconstruye `CostedComponent` con los defaults `tipo='insumo'`/`ref_shift=''`, sin dinero perdido). Este task solo cubre `_estructura` y el respaldo por APU borrado.

- [ ] **Step 1: Write the failing test**

Añadir a `tests/test_servicio_corridas.py` (usa `Almacen` en `tmp_path`; si el archivo ya tiene un fixture/almacén, reutilízalo; si no, crea el `alm` local mostrado):

```python
import pytest
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import (
    Apu, ApuComponent, CostedComponent, CorridaItemRow, Insumo, LicitacionItem,
)
from apu_tool.servicio.corridas import _estructura, _costear_row


def test_estructura_incluye_tipo_y_ref_shift():
    cc = CostedComponent("B", "SUBAPU", "M3", 3.0, 2000, "APU", 6000, "apu",
                         tipo="apu", ref_shift="DIURNO")
    d = _estructura([cc])[0]
    assert d["tipo"] == "apu" and d["ref_shift"] == "DIURNO"


def test_costear_row_respaldo_costea_subapu(tmp_path):
    alm = Almacen(tmp_path / "p.db", tmp_path / "a.db", tmp_path / "c.db")
    alm.reset()
    alm.precios.insert_insumos([Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU")])
    alm.apus.insert_apus([Apu("B", "SUBAPU", "M3", "DIURNO")])
    alm.apus.insert_components([ApuComponent("B", "DIURNO", "100", "CEMENTO", "KG", 2.0, 0.0)])
    # El APU padre "GONE" NO existe -> el respaldo usa row.componentes (con tipo='apu')
    row = CorridaItemRow(
        seq=0, item=LicitacionItem("1", "act", "M2", 1.0, 0.0, "DIURNO"),
        status="auto", apu_codigo="GONE", apu_nombre="X", unidad="M2", shift="DIURNO",
        origen="historico", confianza=1.0, explicacion="",
        componentes=[{"insumo_codigo": "B", "insumo_nombre": "SUBAPU", "unidad": "M3",
                      "rendimiento": 3.0, "tipo": "apu", "ref_shift": "DIURNO"}],
        candidatos=[])
    ens = _costear_row(alm, row)
    assert ens.costo_unitario == pytest.approx(6000)   # 3 * (2 * 1000), recursivo
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_servicio_corridas.py -q`
Expected: FAIL — `_estructura` no emite `tipo`/`ref_shift`; el respaldo arma `ApuComponent` sin `tipo` → costea `B` como insumo huérfano (costo 0), no 6000.

- [ ] **Step 3: Incluir `tipo`/`ref_shift` en `_estructura`**

En `apu_tool/servicio/corridas.py`, reemplazar `_estructura` (líneas 35-38) por:

```python
def _estructura(componentes) -> list[dict]:
    """Snapshot SIN dinero de una composición costeada (incluye tipo/ref_shift del componente)."""
    return [{"insumo_codigo": c.insumo_codigo, "insumo_nombre": c.insumo_nombre,
             "unidad": c.unidad, "rendimiento": c.rendimiento,
             "tipo": getattr(c, "tipo", "insumo"), "ref_shift": getattr(c, "ref_shift", "")}
            for c in componentes]
```

- [ ] **Step 4: Propagar en el respaldo de `_costear_row`**

En `_costear_row` (líneas 114-120), reemplazar la construcción de `comps` del respaldo por:

```python
    if costed is None:
        comps = [ApuComponent(
            apu_codigo=row.apu_codigo or "", shift=row.shift,
            insumo_codigo=c["insumo_codigo"], insumo_nombre=c["insumo_nombre"],
            unidad=c["unidad"], rendimiento=c["rendimiento"],
            precio_unitario_hist=0.0,
            tipo=c.get("tipo", "insumo"), ref_shift=c.get("ref_shift", ""))
            for c in row.componentes]
        costed, total = pricing.cost_components(comps)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_servicio_corridas.py -q`
Expected: PASS (los 2 nuevos + los existentes).

- [ ] **Step 6: Commit**

```bash
git add apu_tool/servicio/corridas.py tests/test_servicio_corridas.py
git commit -m "feat(corridas): propagar tipo/ref_shift en estructura + respaldo (costeo de sub-APUs)"
```

---

## Verificación final

- [ ] `python -m pytest tests/ -q` — toda la suite en verde (sin regresión).
- [ ] Un APU con componente `tipo='apu'` se costea desde la composición vigente del sub-APU; cambiar el precio de un insumo del sub-APU cambia el costo del padre.
- [ ] Anidamiento (≥2 niveles) memoiza; una auto/mutua referencia cae a `calidad_cruce='ciclo'` con respaldo histórico y no cuelga.
- [ ] `marcar-subapus` marca `tipo='apu'` con el turno correcto (padre/DIURNO/único), deja auditoría `apu.componente.marcar_subapu` y es idempotente.
- [ ] Un componente sin marcar (`tipo='insumo'`) se costea igual que hoy.
- [ ] `DePricedApu` de un APU compuesto pasa `assert_no_money` y expone `tipo` (Invariante #1 intacta).
- [ ] Cambios de esquema aditivos en ambos backends (SQLite `init_schema` + Postgres `ADD COLUMN IF NOT EXISTS`).

## Notas de despliegue (fuera del código, con OK explícito del usuario)

- La migración de datos `marcar-subapus` se corre de forma controlada contra prod (`DATABASE_URL` de Supabase) DESPUÉS de desplegar el esquema; no corre al bootear. Marca ~267 componentes.
- Fases posteriores (no en este plan): UI del editor (elegir insumo vs sub-APU), líneas de sub-APU distinguidas en la corrida, etiqueta en el Excel (`report.py`), limpieza del catálogo de insumos.
