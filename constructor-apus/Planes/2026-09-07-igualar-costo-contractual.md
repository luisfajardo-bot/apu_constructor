> Espejo automático — no editar aquí. Fuente: `docs/superpowers/plans/2026-09-07-igualar-costo-contractual.md`

# Igualar el costo unitario al precio contractual — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un botón en la barra de selección de la tabla de corrida que, con N filas marcadas, copia el precio contractual de cada una como su costo unitario — marcado, auditado y reversible.

**Architecture:** Una columna nueva `corrida_item.costo_manual` (NULL = costeo normal) en los dos backends. `_costear_row` sale temprano cuando está puesta; `seqs_sin_apu` deja pasar esas filas; `alertas_costeo` las marca siempre. Se borra sola en `actualizar_eleccion`, el único punto de paso por el que cambia el APU de una fila.

**Tech Stack:** Python 3.14 · FastAPI · SQLite + Postgres (dos backends espejo) · pytest · React + TypeScript + vitest

**Spec:** `docs/superpowers/specs/2026-09-07-igualar-costo-contractual-design.md`

**Rama:** `feat/igualar-costo-contractual` (ya creada desde `master`)

---

## Contexto que el spec no dice y hace falta para no romper nada

- **`assert_no_money` mira nombres de clave, no valores.** Por eso `costo_manual` entra en `_FORBIDDEN_KEYS` (Tarea 5) aunque hoy no filtre: los payloads de `revision.py` se arman con listas de campos explícitas (`payload_profundo`, `indice_corrida`), nunca volcando la fila.
- **Postgres devuelve `numeric` como `Decimal`**, y `Decimal + float` explota. La columna se declara `DOUBLE PRECISION` (igual que `confianza` en esa misma tabla) y aun así se hidrata con `float(...)`.
- **Los dos backends son espejo 1:1.** Todo cambio en `datos/corridas_db.py` va también en `datos/pg/corridas_pg.py`, en `datos/repositorio.py` (el `Protocol`) y en los DOS archivos de esquema: `db/corridas.sql` y `db/pg/corridas.sql`.
- **`tests/test_repositorios_contrato.py` no cubre corridas**: su fixture arma solo `PreciosDB`/`ApusDB`. Por eso la Tarea 1 crea `tests/test_corridas_contrato.py`. Es la brecha por la que ya se escapó un bug de `CorridasPg`.
- **Correr los tests:** `python -m pytest tests/ -q`. Los de Postgres solo corren con `TEST_DATABASE_URL` puesta; **nunca** apuntarla a producción (esos tests hacen `DROP SCHEMA`). Hay un guard autouse en `tests/conftest.py`.
- **Frontend:** verificar con `cd web && npm run build` (`tsc -b`), NO con `tsc --noEmit`. Tests: `cd web && npx vitest run`.

---

## Estructura de archivos

| Archivo | Responsabilidad en esta feature |
|---|---|
| `db/corridas.sql` | columna `costo_manual` en el `CREATE TABLE` de SQLite |
| `db/pg/corridas.sql` | idem Postgres + `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` |
| `apu_tool/nucleo/models.py` | campo `costo_manual` en `CorridaItemRow` |
| `apu_tool/datos/repositorio.py` | `set_costo_manual` en el `Protocol` + docstring del borrado |
| `apu_tool/datos/corridas_db.py` | migración al boot, `set_costo_manual`, hidratación, borrado en `actualizar_eleccion` |
| `apu_tool/datos/pg/corridas_pg.py` | lo mismo, backend Postgres |
| `apu_tool/servicio/corridas.py` | `_costear_row`, `seqs_sin_apu`, `_vista_item`, `igualar_costo_al_contractual` |
| `apu_tool/dominio/alertas.py` | motivo "costo puesto a mano" |
| `apu_tool/dominio/privacy.py` | `costo_manual` en `_FORBIDDEN_KEYS` |
| `apu_tool/servicio/esquemas.py` | DTO `IgualarCostoIn` |
| `apu_tool/servicio/rutas.py` | `POST /api/corridas/{cid}/igualar-costo` |
| `web/src/lib/tipos.ts` | `costo_manual` en `ItemCuadro`, campos de respuesta |
| `web/src/api/corridas.ts` | `igualarCostoAlContractual` |
| `web/src/components/corrida/TablaItems.tsx` | botón en la barra + badge `[a mano]` |
| `CLAUDE.md` | el candado deja de ser "ninguna fila sin APU" |

---

## Tarea 1: La columna y el repositorio (dos backends)

**Files:**
- Modify: `db/corridas.sql:45-48`
- Modify: `db/pg/corridas.sql` (CREATE TABLE + bloque de migración idempotente)
- Modify: `apu_tool/nucleo/models.py:263-276` (`CorridaItemRow`)
- Modify: `apu_tool/datos/repositorio.py:178-183` (`RepositorioCorridas`)
- Modify: `apu_tool/datos/corridas_db.py:64-68, 148-162, 230-240`
- Modify: `apu_tool/datos/pg/corridas_pg.py:83-95, 154-163`
- Test: `tests/test_corridas_contrato.py` (nuevo)

- [ ] **Step 1: Escribir el test que falla (contrato dual-backend)**

Crear `tests/test_corridas_contrato.py`:

```python
"""Contrato del repositorio de corridas: la MISMA batería contra los dos backends.

SQLite corre siempre; Postgres solo con TEST_DATABASE_URL. Existe porque
`test_repositorios_contrato.py` cubre precios y apus pero NO corridas, y esa
brecha ya dejó pasar un bug de CorridasPg.
"""
import os
import pytest

from apu_tool.nucleo.models import CorridaItemRow, CorridaMeta, LicitacionItem


def _corridas_sqlite(tmp_path):
    from apu_tool.datos.corridas_db import CorridasDB
    r = CorridasDB(tmp_path / "corridas.db")
    r.init_schema()
    return r, None


def _corridas_postgres(tmp_path):
    from apu_tool.datos.pg.conexion import Conexion
    from apu_tool.datos.pg.corridas_pg import CorridasPg
    cx = Conexion(os.environ["TEST_DATABASE_URL"])
    r = CorridasPg(cx)
    r.reset()
    return r, cx


_BACKENDS = ["sqlite"]
if os.environ.get("TEST_DATABASE_URL"):
    _BACKENDS.append("postgres")


@pytest.fixture(params=_BACKENDS)
def repo(request, tmp_path):
    r, cx = (_corridas_sqlite(tmp_path) if request.param == "sqlite"
             else _corridas_postgres(tmp_path))
    yield r
    if cx is not None:
        cx.cerrar()


def _item(seq: int, contractual: float) -> CorridaItemRow:
    return CorridaItemRow(
        seq=seq,
        item=LicitacionItem(item=str(seq), descripcion=f"ACTIVIDAD {seq}", unidad="GLB",
                            cantidad=1.0, precio_contractual=contractual, shift="DIURNO"),
        status="new", apu_codigo=None, apu_nombre="", unidad="GLB", shift="DIURNO",
        origen="historico", confianza=0.0, explicacion="", componentes=[], candidatos=[])


def _corrida_con(repo, *filas) -> int:
    cid = repo.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-09-07T10:00:00", archivo="x.xlsx", turno_def="DIURNO",
        use_ai=None, estado="en_revision", cuadro_path=None, nombre="x"))
    repo.guardar_items(cid, list(filas))
    return cid


def test_costo_manual_arranca_en_none(repo):
    cid = _corrida_con(repo, _item(0, 1000.0))
    assert repo.get_items(cid)[0].costo_manual is None


def test_set_costo_manual_persiste_y_confirma(repo):
    cid = _corrida_con(repo, _item(0, 92106000.0), _item(1, 500.0))
    repo.set_costo_manual(cid, {0: 92106000.0})
    filas = {r.seq: r for r in repo.get_items(cid)}
    assert filas[0].costo_manual == 92106000.0
    assert filas[0].status == "confirmed"       # la resolvió una persona a propósito
    assert filas[1].costo_manual is None        # la otra fila no se toca
    assert filas[1].status == "new"


def test_set_costo_manual_es_float_no_decimal(repo):
    """Postgres devuelve numeric como Decimal y Decimal+float explota al sumar totales."""
    cid = _corrida_con(repo, _item(0, 1500.0))
    repo.set_costo_manual(cid, {0: 1500.0})
    assert isinstance(repo.get_items(cid)[0].costo_manual, float)


def test_actualizar_eleccion_borra_el_costo_manual(repo):
    """Armaste el APU de verdad y lo asignaste: el costo a mano ya no manda."""
    cid = _corrida_con(repo, _item(0, 1500.0))
    repo.set_costo_manual(cid, {0: 1500.0})
    repo.actualizar_eleccion(
        cid, 0, status="confirmed", apu_codigo="100", apu_nombre="EXCAVACION",
        unidad="M3", shift="DIURNO", origen="historico", confianza=1.0,
        explicacion="", componentes=[{"insumo_codigo": "4279", "insumo_nombre": "CUADRILLA",
                                      "unidad": "HR", "rendimiento": 1.0}])
    assert repo.get_items(cid)[0].costo_manual is None


def test_set_costo_manual_vacio_no_escribe(repo):
    cid = _corrida_con(repo, _item(0, 1000.0))
    repo.set_costo_manual(cid, {})
    assert repo.get_items(cid)[0].costo_manual is None
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_corridas_contrato.py -q`
Expected: FAIL — `TypeError: CorridaItemRow.__init__() got an unexpected keyword argument` no; el fallo real es `AttributeError: 'CorridasDB' object has no attribute 'set_costo_manual'` en 4 de los 5 tests, y `AttributeError: 'CorridaItemRow' object has no attribute 'costo_manual'` en el primero.

- [ ] **Step 3: Agregar la columna a los dos esquemas**

En `db/corridas.sql`, dentro de `CREATE TABLE IF NOT EXISTS corrida_item`, después de `revision_json    TEXT`:

```sql
  -- Veredicto de la IA revisora sobre el APU de esta fila. NULL = nunca revisada.
  revision_json    TEXT,
  -- Costo unitario declarado por una persona (proyectos especiales: la actividad vale
  -- lo que dice el contrato y armarle el APU no paga). NULL = costeo normal desde la
  -- composición. Se borra en actualizar_eleccion: si la fila cambia de APU, manda el APU.
  costo_manual     REAL
```

En `db/pg/corridas.sql`, lo mismo en el `CREATE TABLE` (con `costo_manual DOUBLE PRECISION`,
igual que `confianza`, para no recibir `Decimal`), y en el bloque de migración idempotente,
junto a los otros `ADD COLUMN IF NOT EXISTS`:

```sql
ALTER TABLE corridas.corrida_item ADD COLUMN IF NOT EXISTS costo_manual DOUBLE PRECISION;
```

- [ ] **Step 4: Campo en el modelo**

En `apu_tool/nucleo/models.py`, en `CorridaItemRow`, después de `revision`:

```python
    revision: Optional[dict] = None   # veredicto de la IA (sin dinero); None = sin revisar
    # Costo unitario puesto a mano (proyectos especiales). None = costear normal desde
    # la composición. NUNCA entra a un payload de la IA: es dinero (ver privacy.py).
    costo_manual: Optional[float] = None
```

- [ ] **Step 5: Migración al boot + método + hidratación en SQLite**

En `apu_tool/datos/corridas_db.py`, en `init_schema`, junto a los otros `icols`:

```python
            if "revision_json" not in icols:
                conn.execute("ALTER TABLE corrida_item ADD COLUMN revision_json TEXT")
            if "costo_manual" not in icols:
                conn.execute("ALTER TABLE corrida_item ADD COLUMN costo_manual REAL")
```

En `actualizar_eleccion`, agregar `costo_manual=NULL` al UPDATE (y ampliar el comentario):

```python
            conn.execute(
                # El APU cambió: el veredicto de la IA hablaba del anterior, y un costo
                # puesto a mano ya no manda (la fila volvió a tener composición real).
                # Se borran acá, el único punto por el que pasa un cambio del APU elegido.
                "UPDATE corrida_item SET status=?, apu_codigo=?, apu_nombre=?, unidad=?, "
                "shift=?, origen=?, confianza=?, explicacion=?, componentes_json=?, "
                "revision_json=NULL, costo_manual=NULL "
                "WHERE corrida_id=? AND seq=?",
```

Método nuevo, al lado de `set_revision`:

```python
    def set_costo_manual(self, corrida_id: int, costos: dict[int, float], conn=None) -> None:
        """Fija el costo unitario a mano de varias filas y las deja en `confirmed`.

        `costos` es {seq: costo}. Es UNA acción del usuario ("estas filas las resuelvo
        así"), así que es una escritura por lote: el status va junto porque la fila
        quedó resuelta a propósito y seguir contándola en "en revisión" mentiría en
        los totales."""
        if not costos:
            return
        filas = [(float(c), int(corrida_id), int(s)) for s, c in costos.items()]
        sql = ("UPDATE corrida_item SET costo_manual=?, status='confirmed' "
               "WHERE corrida_id=? AND seq=?")
        if conn is not None:
            conn.executemany(sql, filas)
            return
        with self.connect() as c:
            c.executemany(sql, filas)
```

En `_row_to_item`, agregar el campo:

```python
            revision=(json.loads(r["revision_json"]) if r["revision_json"] else None),
            costo_manual=(None if r["costo_manual"] is None else float(r["costo_manual"])))
```

- [ ] **Step 6: Lo mismo en el backend Postgres**

En `apu_tool/datos/pg/corridas_pg.py`, `actualizar_eleccion`:

```python
                "UPDATE corridas.corrida_item SET status=%s, apu_codigo=%s, apu_nombre=%s, "
                "unidad=%s, shift=%s, origen=%s, confianza=%s, explicacion=%s, "
                "componentes_json=%s, revision_json=NULL, costo_manual=NULL "
                "WHERE corrida_id=%s AND seq=%s",
```

Método nuevo (mismo docstring corto que en SQLite, `executemany` de psycopg):

```python
    def set_costo_manual(self, corrida_id: int, costos: dict[int, float], conn=None) -> None:
        """Fija el costo unitario a mano de varias filas y las deja en `confirmed`.
        `costos` es {seq: costo}. Ver el docstring del contrato en repositorio.py."""
        if not costos:
            return
        filas = [(float(c), int(corrida_id), int(s)) for s, c in costos.items()]
        sql = ("UPDATE corridas.corrida_item SET costo_manual=%s, status='confirmed' "
               "WHERE corrida_id=%s AND seq=%s")
        if conn is not None:
            with conn.cursor() as cur:
                cur.executemany(sql, filas)
            return
        with self.cx.connection() as c, c.cursor() as cur:
            cur.executemany(sql, filas)
```

En `_row_to_item`, idéntico al de SQLite:

```python
            revision=(json.loads(r["revision_json"]) if r["revision_json"] else None),
            costo_manual=(None if r["costo_manual"] is None else float(r["costo_manual"])))
```

- [ ] **Step 7: Declararlo en el contrato**

En `apu_tool/datos/repositorio.py`, en `RepositorioCorridas`, después de `set_revision`:

```python
    def set_costo_manual(self, corrida_id: int, costos: dict[int, float], conn=None) -> None:
        """Costo unitario puesto a mano, {seq: costo}, y la fila queda `confirmed`.

        Lo BORRA `actualizar_eleccion`: si la fila cambia de APU, manda el APU. Es el
        único punto de paso, así que no hace falta acordarse de limpiarlo."""
        ...
```

Y ampliar el docstring de `actualizar_eleccion` en el mismo archivo:

```python
        """Cambia el APU elegido de una fila. BORRA su revisión y su costo puesto a
        mano: el veredicto hablaba del APU anterior, y el costo a mano ya no manda
        porque la fila volvió a tener una composición real."""
```

- [ ] **Step 8: Correr el test para verificar que pasa**

Run: `python -m pytest tests/test_corridas_contrato.py -q`
Expected: PASS (5 tests con SQLite; 10 si `TEST_DATABASE_URL` está puesta)

- [ ] **Step 9: Correr la suite entera (no debe romper nada)**

Run: `python -m pytest tests/ -q`
Expected: PASS — todo verde. `CorridaItemRow` tiene un campo nuevo con default, así que ningún llamador existente cambia.

- [ ] **Step 10: Commit**

```bash
git add db/corridas.sql db/pg/corridas.sql apu_tool/nucleo/models.py \
        apu_tool/datos/repositorio.py apu_tool/datos/corridas_db.py \
        apu_tool/datos/pg/corridas_pg.py tests/test_corridas_contrato.py
git commit -m "feat(corridas): columna costo_manual en los dos backends"
```

---

## Tarea 2: El costeo respeta el costo a mano

**Files:**
- Modify: `apu_tool/servicio/corridas.py:281-316` (`_costear_row`)
- Test: `tests/test_costo_manual.py` (nuevo)

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_costo_manual.py`:

```python
"""Una fila con costo puesto a mano cuesta eso, sin mirar el catálogo.

Proyectos especiales: la actividad vale lo que dice el contrato y armarle el APU
no paga. El costo lo declara una persona; el motor no lo recalcula.
"""
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import (
    Apu, ApuComponent, CorridaItemRow, CorridaMeta, Insumo, LicitacionItem,
)
from apu_tool.servicio import corridas as svc


@pytest.fixture()
def alm(tmp_path):
    a = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                corridas_path=tmp_path / "c.db")
    a.init_schema()
    a.precios.insert_insumos([Insumo("4279", "CUADRILLA", "HR", "MO", 40000.0, "PRECIO IDU")])
    a.apus.insert_apus([Apu("100", "EXCAVACION MANUAL", "M3", "DIURNO", "MOV")])
    a.apus.insert_components([
        ApuComponent("100", "DIURNO", "4279", "CUADRILLA", "HR", 1.0, 40000.0)])
    return a


def _corrida(alm, *, contractual: float, cantidad: float = 1.0,
             apu: str | None = None, estado: str = "en_revision") -> int:
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-09-07T10:00:00", archivo="x.xlsx", turno_def="DIURNO",
        use_ai=None, estado=estado, cuadro_path=None, nombre="x"))
    alm.corridas.agregar_item(cid, CorridaItemRow(
        seq=0,
        item=LicitacionItem(item="1", descripcion="PRUEBA DE CARGA 6 PUENTES",
                            unidad="GLB", cantidad=cantidad,
                            precio_contractual=contractual, shift="DIURNO"),
        status="new", apu_codigo=apu, apu_nombre=("EXCAVACION MANUAL" if apu else ""),
        unidad="GLB", shift="DIURNO", origen="historico", confianza=0.0,
        explicacion="", componentes=[], candidatos=[]))
    return cid


def test_costo_manual_manda_sobre_la_composicion(alm):
    """Aunque la fila tenga un APU con composición real, el costo a mano gana."""
    cid = _corrida(alm, contractual=92106000.0, apu="100")
    alm.corridas.set_costo_manual(cid, {0: 92106000.0})
    fila = svc.vista_corrida(alm, cid)["items"][0]
    assert fila["costo_unitario"] == 92106000.0    # no los $40.000 del APU 100
    assert fila["costo_manual"] is True


def test_margen_cero_exacto_en_el_total(alm):
    """El redondeo a la unidad no debe dejar un peso de resto en el total."""
    cid = _corrida(alm, contractual=92106000.0, cantidad=7.0)
    alm.corridas.set_costo_manual(cid, {0: 92106000.0})
    v = svc.vista_corrida(alm, cid)
    fila = v["items"][0]
    assert fila["costo_total"] == fila["contractual_total"]
    assert fila["margen_total"] == 0
    assert v["totales"]["margen"] == 0


def test_sin_costo_manual_la_vista_no_lo_marca(alm):
    cid = _corrida(alm, contractual=1000.0, apu="100")
    fila = svc.vista_corrida(alm, cid)["items"][0]
    assert fila["costo_manual"] is False
    assert fila["costo_unitario"] == 40000.0
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_costo_manual.py -q`
Expected: FAIL — `KeyError: 'costo_manual'` en la vista, y `costo_unitario == 40000.0` donde el test espera 92106000.0.

- [ ] **Step 3: Salida temprana en `_costear_row`**

En `apu_tool/servicio/corridas.py`, dentro de `_costear_row`, inmediatamente después del docstring y ANTES de `pricing = pricing or PricingEngine(...)`:

```python
    if row.costo_manual is not None:
        # Costo declarado por una persona (proyectos especiales: la actividad vale lo
        # que dice el contrato y armarle el APU no paga). No se consulta el catálogo:
        # no hay composición que costear. La firma "sin componentes + costo > 0" es la
        # que `alertas_costeo` reconoce para marcar la fila, activa y congelada.
        return AssembledApu(
            item=row.item, apu_codigo=row.apu_codigo, apu_nombre=row.apu_nombre,
            unidad=row.unidad or row.item.unidad, shift=row.shift, componentes=[],
            costo_unitario=row.costo_manual, status=MatchStatus(row.status),
            confianza=row.confianza, explicacion=row.explicacion, origen=row.origen)
    pricing = pricing or PricingEngine(alm, lista_id=lista_id)
```

- [ ] **Step 4: Exponerlo en la vista**

En `apu_tool/servicio/corridas.py`, en el dict que devuelve `_vista_item`, junto a `costo_unitario`:

```python
        "costo_unitario": ens.costo_unitario, "margen_unitario": ens.margen_unitario,
        # Costo puesto a mano. Derivado del ensamble, no de la fila, así los dos call
        # sites de `_vista_item` quedan sin tocar y funciona igual con la corrida
        # congelada (el snapshot reconstruye `composicion: []` y el mismo costo). La
        # firma es inequívoca: sin componentes el motor no puede dar un costo positivo.
        "costo_manual": not ens.componentes and ens.costo_unitario > 0,
```

- [ ] **Step 5: Correr el test para verificar que pasa**

Run: `python -m pytest tests/test_costo_manual.py -q`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add apu_tool/servicio/corridas.py tests/test_costo_manual.py
git commit -m "feat(corridas): el costeo respeta el costo puesto a mano"
```

---

## Tarea 3: La alerta que lo hace visible

**Files:**
- Modify: `apu_tool/dominio/alertas.py:24-42` (`alertas_costeo`)
- Test: `tests/test_alertas_costeo.py` (existente, agregar tests)

- [ ] **Step 1: Escribir el test que falla**

Agregar al final de `tests/test_alertas_costeo.py` (reusar los helpers que ya tenga
el archivo para armar un `AssembledApu`; si no hay, usar este):

```python
def _ensamble(componentes, costo_unitario, cantidad=1.0, contractual=100.0):
    from apu_tool.nucleo.models import AssembledApu, LicitacionItem, MatchStatus
    item = LicitacionItem(item="1", descripcion="PRUEBA DE CARGA", unidad="GLB",
                          cantidad=cantidad, precio_contractual=contractual,
                          shift="DIURNO")
    return AssembledApu(item=item, apu_codigo=None, apu_nombre="", unidad="GLB",
                        shift="DIURNO", componentes=componentes,
                        costo_unitario=costo_unitario, status=MatchStatus.CONFIRMED,
                        confianza=1.0)


def test_costo_a_mano_siempre_se_marca():
    """Nada silencioso: un costo que puso una persona tiene que distinguirse de
    uno que calculó el motor."""
    motivos = alertas_costeo(_ensamble([], 92106000.0))
    assert motivos == ["costo puesto a mano (igualado al contractual)"]


def test_sin_composicion_y_sin_costo_sigue_siendo_el_cero_de_antes():
    """No romper el mensaje que ya existía para las filas en $0."""
    motivos = alertas_costeo(_ensamble([], 0.0))
    assert motivos == ["APU en $0 (sin composición o sin costo)"]
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_alertas_costeo.py -q`
Expected: FAIL en `test_costo_a_mano_siempre_se_marca` — devuelve `[]` (con costo > 0 y sin componentes hoy no hay ningún motivo).

- [ ] **Step 3: Agregar el motivo**

En `apu_tool/dominio/alertas.py`, en `alertas_costeo`, entre el `for` de componentes y
el chequeo del $0:

```python
    # Costo declarado por una persona, no calculado por el motor (proyectos
    # especiales). Firma inequívoca: sin componentes el motor no puede dar un costo
    # positivo. Se marca SIEMPRE — activa y congelada, porque el snapshot reconstruye
    # `composicion: []` con el mismo costo. Va antes de la regla del $0 para dar el
    # motivo real en vez del genérico, igual que `sin_precio_lista`.
    if not a.componentes and a.costo_unitario > 0:
        motivos.append("costo puesto a mano (igualado al contractual)")
    if not motivos and a.costo_unitario <= 0:               # ítem sin composición / sin costo
        motivos.append("APU en $0 (sin composición o sin costo)")
```

- [ ] **Step 4: Correr el test para verificar que pasa**

Run: `python -m pytest tests/test_alertas_costeo.py -q`
Expected: PASS (todos, los viejos incluidos)

- [ ] **Step 5: Commit**

```bash
git add apu_tool/dominio/alertas.py tests/test_alertas_costeo.py
git commit -m "feat(alertas): el costo puesto a mano se marca siempre"
```

---

## Tarea 4: El candado deja pasar la fila

**Files:**
- Modify: `apu_tool/servicio/corridas.py:54-56` (`seqs_sin_apu`)
- Test: `tests/test_candado_sin_apu.py` (existente, agregar tests)

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_candado_sin_apu.py`, reusando sus helpers `_almacen` /
`_corrida_con_fila_sin_apu`:

```python
def test_costo_a_mano_abre_el_candado(alm):
    """La fila sin APU pero con costo declarado ya no bloquea: es el caso de uso
    entero (proyectos especiales que no se arman). El candado sigue existiendo para
    las filas que de verdad no tienen nada."""
    cid = _corrida_con_fila_sin_apu(alm)
    seq_malo = [r.seq for r in alm.corridas.get_items(cid) if not r.apu_codigo][0]
    contractual = {r.seq: r.item.precio_contractual
                   for r in alm.corridas.get_items(cid)}[seq_malo]
    alm.corridas.set_costo_manual(cid, {seq_malo: contractual})
    assert svc.seqs_sin_apu(alm.corridas.get_items(cid)) == []
    assert svc.congelar(alm, cid) is not None      # no levanta FilasSinApu


def test_fila_pelada_sigue_bloqueando(alm):
    """Sin APU y sin costo: el candado tiene que seguir trabado."""
    cid = _corrida_con_fila_sin_apu(alm)
    assert svc.seqs_sin_apu(alm.corridas.get_items(cid)) != []
    with pytest.raises(svc.FilasSinApu):
        svc.congelar(alm, cid)


def test_el_cuadro_nombra_la_fila_con_costo_a_mano(alm):
    """Que salga en el cuadro no significa que salga callada: la hoja ALERTAS la nombra."""
    from apu_tool.dominio.alertas import filas_alertadas
    cid = _corrida_con_fila_sin_apu(alm)
    seq_malo = [r.seq for r in alm.corridas.get_items(cid) if not r.apu_codigo][0]
    alm.corridas.set_costo_manual(cid, {seq_malo: 92106000.0})
    rows = alm.corridas.get_items(cid)
    meta = alm.corridas.get_corrida(cid)
    from apu_tool.dominio.pricing import PricingEngine
    ensambles = svc._ensamblar_corrida(alm, meta, rows, PricingEngine(alm))
    motivos = {a.item.item: ac for a, ac in filas_alertadas(ensambles)}
    assert any("costo puesto a mano" in m
               for ms in motivos.values() for m in ms)


def test_congelada_sigue_marcando_el_costo_a_mano(alm):
    """El snapshot guarda `composicion: []` con el mismo costo, así que la firma que
    reconoce `alertas_costeo` sobrevive a congelar. Sin esto, el cuadro de una corrida
    congelada emitiría la fila sin decir que el costo lo puso una persona."""
    cid = _corrida_con_fila_sin_apu(alm)
    seq_malo = [r.seq for r in alm.corridas.get_items(cid) if not r.apu_codigo][0]
    alm.corridas.set_costo_manual(cid, {seq_malo: 92106000.0})
    svc.congelar(alm, cid)
    assert alm.corridas.get_corrida(cid).modo == "congelada"
    fila = {f["seq"]: f for f in svc.vista_corrida(alm, cid)["items"]}[seq_malo]
    assert fila["costo_unitario"] == 92106000.0
    assert fila["costo_manual"] is True
    assert any("costo puesto a mano" in m for m in fila["alertas_costeo"])
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_candado_sin_apu.py -q`
Expected: FAIL en `test_costo_a_mano_abre_el_candado` y en `test_congelada_sigue_marcando_el_costo_a_mano` — `seqs_sin_apu` devuelve el seq igual y `congelar` levanta `FilasSinApu`. Los otros dos pasan (`test_fila_pelada_sigue_bloqueando` porque describe el comportamiento de hoy, y el de ALERTAS porque la Tarea 3 ya está).

- [ ] **Step 3: Cambiar el candado**

En `apu_tool/servicio/corridas.py`:

```python
def seqs_sin_apu(rows) -> list[int]:
    """Los seq de las filas que no tienen APU NI costo declarado a mano.
    Lista vacía = se puede cerrar.

    El candado existe para que no salga un cuadro con filas en $0 sin que nadie se
    entere. Una fila con costo puesto a mano no es ninguna de las dos cosas: el monto
    lo declaró una persona y la hoja ALERTAS la nombra (ver `alertas_costeo`)."""
    return [r.seq for r in rows if not r.apu_codigo and r.costo_manual is None]
```

- [ ] **Step 4: Correr el test para verificar que pasa**

Run: `python -m pytest tests/test_candado_sin_apu.py -q`
Expected: PASS (todos, los viejos incluidos)

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/corridas.py tests/test_candado_sin_apu.py
git commit -m "feat(corridas): el costo a mano abre el candado del cuadro"
```

---

## Tarea 5: El servicio, el endpoint y la frontera de privacidad

**Files:**
- Modify: `apu_tool/dominio/privacy.py:21-26` (`_FORBIDDEN_KEYS`)
- Modify: `apu_tool/servicio/corridas.py` (función nueva, después de `confirmar_item`)
- Modify: `apu_tool/servicio/esquemas.py:50-52` (DTO nuevo junto a `BorrarLineasIn`)
- Modify: `apu_tool/servicio/rutas.py` (endpoint nuevo, después de `confirmar_lote`)
- Test: `tests/test_costo_manual.py` (agregar), `tests/test_privacidad.py` (agregar)

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `tests/test_costo_manual.py`:

```python
def test_igualar_en_lote_copia_el_contractual_de_cada_fila(alm):
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-09-07T10:00:00", archivo="x.xlsx", turno_def="DIURNO",
        use_ai=None, estado="en_revision", cuadro_path=None, nombre="x"))
    for seq, precio in ((0, 92106000.0), (1, 10115000.0)):
        alm.corridas.agregar_item(cid, CorridaItemRow(
            seq=seq,
            item=LicitacionItem(item=str(seq), descripcion=f"ESPECIAL {seq}", unidad="GLB",
                                cantidad=1.0, precio_contractual=precio, shift="DIURNO"),
            status="new", apu_codigo=None, apu_nombre="", unidad="GLB", shift="DIURNO",
            origen="historico", confianza=0.0, explicacion="", componentes=[],
            candidatos=[]))
    v = svc.igualar_costo_al_contractual(alm, cid, [0, 1])
    assert v["igualadas"] == [0, 1]
    assert [f["costo_unitario"] for f in v["items"]] == [92106000.0, 10115000.0]
    assert all(f["status"] == "confirmed" for f in v["items"])


def test_contractual_en_cero_se_rechaza(alm):
    """Regla de negocio: nada en $0. Igualar a 0 es justo lo que la regla prohíbe."""
    cid = _corrida(alm, contractual=0.0)
    v = svc.igualar_costo_al_contractual(alm, cid, [0])
    assert v["rechazadas"] == [0]
    assert v["igualadas"] == []
    assert alm.corridas.get_items(cid)[0].costo_manual is None


def test_congelada_no_se_toca(alm):
    cid = _corrida(alm, contractual=1000.0)
    alm.corridas.set_modo(cid, "congelada")
    with pytest.raises(svc.CorridaCongelada):
        svc.igualar_costo_al_contractual(alm, cid, [0])


def test_corrida_inexistente_devuelve_none(alm):
    assert svc.igualar_costo_al_contractual(alm, 9999, [0]) is None


def test_finalizada_vuelve_a_revision(alm):
    """El cuadro emitido ya no dice la verdad."""
    cid = _corrida(alm, contractual=1000.0, estado="finalizada")
    svc.igualar_costo_al_contractual(alm, cid, [0])
    assert alm.corridas.get_corrida(cid).estado == "en_revision"


def test_seq_ajeno_se_saltea(alm):
    cid = _corrida(alm, contractual=1000.0)
    v = svc.igualar_costo_al_contractual(alm, cid, [0, 77])
    assert v["igualadas"] == [0]
```

Agregar a `tests/test_privacidad.py`:

```python
def test_costo_manual_es_campo_prohibido():
    """assert_no_money mira NOMBRES de clave: el campo nuevo tiene que estar en la
    denylist aunque hoy ningún payload de la IA lo arme."""
    import pytest as _pytest
    from apu_tool.dominio import privacy
    with _pytest.raises(privacy.PrivacyViolation):
        privacy.assert_no_money({"seq": 1, "costo_manual": 92106000.0})
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/test_costo_manual.py tests/test_privacidad.py -q`
Expected: FAIL — `AttributeError: module 'apu_tool.servicio.corridas' has no attribute 'igualar_costo_al_contractual'` y, en privacidad, `DID NOT RAISE PrivacyViolation`.

- [ ] **Step 3: La llave prohibida**

En `apu_tool/dominio/privacy.py`, en `_FORBIDDEN_KEYS`:

```python
_FORBIDDEN_KEYS = {
    "precio", "precio_unitario", "precio_contractual", "precio_unitario_hist",
    "costo", "costo_unitario", "costo_total", "valor", "valor_unitario",
    "valor_total", "margen", "price", "cost", "amount", "total",
    "fuente_precio", "costo_manual",
}
```

- [ ] **Step 4: La función de servicio**

En `apu_tool/servicio/corridas.py`, después de `confirmar_item`:

```python
def igualar_costo_al_contractual(alm: Almacen, corrida_id: int, seqs: Iterable[int],
                                 actor=None) -> Optional[dict]:
    """Copia el precio contractual de cada fila marcada como su costo unitario.

    Para proyectos especiales: actividades globales que valen lo que dice el contrato
    y a las que armarles el APU no paga. El margen de esas filas queda en 0 a
    propósito.

    Es una COPIA de una vez, no un vínculo vivo: si mañana cambia el contractual, el
    costo se queda donde estaba y aparece un margen ≠ 0 — visible, para que el usuario
    decida. Un costo que persiguiera al contractual escondería el cambio.

    Se deshace solo: `actualizar_eleccion` borra el `costo_manual` cuando la fila
    cambia de APU, así que armar el APU de verdad y asignarlo devuelve la fila al
    costeo normal sin ningún botón que acordarse de apretar.

    Devuelve la vista de la corrida con dos claves extra —`igualadas` y `rechazadas`
    (seqs con contractual ≤ 0, que no se tocan por la regla "nada en $0")— o None si
    la corrida no existe. Lanza CorridaCongelada si está congelada.
    """
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    if meta.modo == "congelada":
        raise CorridaCongelada(corrida_id)
    pedidos = {int(s) for s in seqs}
    filas = [r for r in alm.corridas.get_items(corrida_id) if r.seq in pedidos]
    costos: dict[int, float] = {}
    rechazadas: list[int] = []
    for r in filas:
        # `not (x > 0)` y NO `x <= 0`: con NaN, `nan <= 0` es False y el NaN se
        # colaría al costo, envenenando todos los totales de ahí para abajo.
        if not (r.item.precio_contractual > 0):
            rechazadas.append(r.seq)   # igualar a 0 es el $0 que la regla prohíbe
        else:
            costos[r.seq] = float(r.item.precio_contractual)
    if costos:
        with alm.transaccion("corridas") as conn:
            alm.corridas.set_costo_manual(corrida_id, costos, conn=conn)
            # Se audita como `precio.editar`, que ya se audita: una persona fijando
            # plata a mano. `antes` guarda el costo a mano previo (None la primera vez).
            registrar_auditoria(
                alm, conn, actor, "corrida.igualar_costo", "corrida", corrida_id,
                antes={"lineas": [{"seq": r.seq, "costo_manual": r.costo_manual}
                                  for r in filas if r.seq in costos]},
                despues={"lineas": [{"seq": s, "costo_manual": c}
                                    for s, c in sorted(costos.items())]},
                contexto={"rechazadas": sorted(rechazadas)})
        if meta.estado == "finalizada":
            alm.corridas.set_estado(corrida_id, "en_revision")   # el cuadro ya no dice la verdad
    vista = vista_corrida(alm, corrida_id)
    if vista is not None:
        vista["igualadas"] = sorted(costos)
        vista["rechazadas"] = sorted(rechazadas)
    return vista
```

- [ ] **Step 5: El DTO**

En `apu_tool/servicio/esquemas.py`, junto a `BorrarLineasIn`:

```python
class IgualarCostoIn(BaseModel):
    seqs: list[int]
```

- [ ] **Step 6: El endpoint**

En `apu_tool/servicio/rutas.py`, importar `IgualarCostoIn` donde están los otros DTOs
y agregar, después de `confirmar_lote`:

```python
@router.post("/corridas/{cid}/igualar-costo")
def igualar_costo(cid: int, body: IgualarCostoIn,
                  alm: Almacen = Depends(get_almacen),
                  actor=Depends(requiere_rol("editor"))):
    # Rol `editor` a propósito, MÁS ESTRICTO que sus vecinos (confirmar-lote, congelar
    # y generar-cuadro piden "consulta", que es el hallazgo Alto "el rol consulta
    # escribe/borra" de la auditoría 2026-08-28, todavía sin arreglar). No se les
    # cambia el rol a esos —le sacaría el acceso a gente que hoy trabaja— pero un
    # endpoint nuevo que DECLARA DINERO no se le abre a un rol de solo lectura.
    try:
        v = svc.igualar_costo_al_contractual(alm, cid, body.seqs, actor)
    except svc.CorridaCongelada:
        raise HTTPException(status_code=409,
                            detail="La corrida está congelada; actívala para modificar.")
    if v is None:
        raise HTTPException(status_code=404, detail="Corrida no encontrada.")
    return v
```

- [ ] **Step 7: Correr los tests para verificar que pasan**

Run: `python -m pytest tests/test_costo_manual.py tests/test_privacidad.py -q`
Expected: PASS

- [ ] **Step 8: Test del endpoint (rol + 409 + 404)**

Agregar a `tests/test_api_corridas.py`. El archivo ya trae `_cliente(tmp_path)` (devuelve
`(cli, alm)` con rol admin), `cliente` de `tests.conftest` y `create_app`; hacen falta dos
helpers nuevos y los imports de modelos:

```python
# Agregar a los imports del archivo:
#   from apu_tool.nucleo.models import CorridaItemRow, CorridaMeta


def _cli_rol(tmp_path, rol: str):
    """Cliente con un rol dado + su Almacen. Para los tests de autorización."""
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return cliente(create_app(almacen=alm), rol=rol), alm


def _corrida_especial(alm, contractual: float = 92106000.0) -> int:
    """Una corrida con una fila SIN APU: el caso de los proyectos especiales."""
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-09-07T10:00:00", archivo="x.xlsx", turno_def="DIURNO",
        use_ai=None, estado="en_revision", cuadro_path=None, nombre="x"))
    alm.corridas.agregar_item(cid, CorridaItemRow(
        seq=0,
        item=LicitacionItem(item="1", descripcion="PRUEBA DE CARGA 6 PUENTES",
                            unidad="GLB", cantidad=1.0,
                            precio_contractual=contractual, shift="DIURNO"),
        status="new", apu_codigo=None, apu_nombre="", unidad="GLB", shift="DIURNO",
        origen="historico", confianza=0.0, explicacion="", componentes=[], candidatos=[]))
    return cid


def test_igualar_costo_endpoint(tmp_path):
    """Feliz: 200, la fila queda con el contractual como costo y marcada."""
    cli, alm = _cliente(tmp_path)
    cid = _corrida_especial(alm)
    r = cli.post(f"/api/corridas/{cid}/igualar-costo", json={"seqs": [0]})
    assert r.status_code == 200, r.text
    fila = r.json()["items"][0]
    assert fila["costo_unitario"] == fila["precio_contractual"] == 92106000.0
    assert fila["costo_manual"] is True
    assert r.json()["igualadas"] == [0]


def test_igualar_costo_404_si_no_existe(tmp_path):
    cli, _ = _cliente(tmp_path)
    r = cli.post("/api/corridas/9999/igualar-costo", json={"seqs": [0]})
    assert r.status_code == 404


def test_igualar_costo_409_si_congelada(tmp_path):
    cli, alm = _cliente(tmp_path)
    cid = _corrida_especial(alm)
    alm.corridas.set_modo(cid, "congelada")
    r = cli.post(f"/api/corridas/{cid}/igualar-costo", json={"seqs": [0]})
    assert r.status_code == 409


def test_igualar_costo_rol_consulta_prohibido(tmp_path):
    """Un endpoint que declara dinero no se le abre al rol de solo lectura."""
    cli, alm = _cli_rol(tmp_path, "consulta")
    cid = _corrida_especial(alm)
    r = cli.post(f"/api/corridas/{cid}/igualar-costo", json={"seqs": [0]})
    assert r.status_code == 403


def test_igualar_costo_rol_editor_permitido(tmp_path):
    cli, alm = _cli_rol(tmp_path, "editor")
    cid = _corrida_especial(alm)
    r = cli.post(f"/api/corridas/{cid}/igualar-costo", json={"seqs": [0]})
    assert r.status_code == 200, r.text
```

- [ ] **Step 9: Correr los tests de la API**

Run: `python -m pytest tests/test_api_corridas.py -q`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add apu_tool/dominio/privacy.py apu_tool/servicio/corridas.py \
        apu_tool/servicio/esquemas.py apu_tool/servicio/rutas.py \
        tests/test_costo_manual.py tests/test_privacidad.py tests/test_api_corridas.py
git commit -m "feat(api): POST /corridas/{id}/igualar-costo, rol editor y auditado"
```

---

## Tarea 6: El botón y el badge

**Files:**
- Modify: `web/src/lib/tipos.ts:99-116` (`ItemCuadro`) y el tipo de la respuesta
- Modify: `web/src/api/corridas.ts:63-76` (junto a `confirmarLote`)
- Modify: `web/src/components/corrida/TablaItems.tsx:455-460, 521-545`
- Test: `web/src/components/corrida/TablaItems.test.tsx` (existente, agregar)

- [ ] **Step 1: Escribir el test que falla**

Tres cambios en `web/src/components/corrida/TablaItems.test.tsx`, que ya trae el harness
`TablaConControl`, el fixture `ITEM` y `itemsCuatro()`:

**(a)** Agregar la función al `vi.mock("@/api/corridas", ...)` del principio del archivo —
sin esto el import del componente falla:

```tsx
  igualarCostoAlContractual: vi.fn(async () => ({
    id: 1, archivo: "x", estado: "en_revision", modo: "activa", items: [], duracion_ms: null,
    totales: { contractual: 0, costo: 0, margen: 0, margen_pct: 0, n_items: 0, n_revision: 0 },
    igualadas: [0], rechazadas: [],
  })),
```

**(b)** Agregar `costo_manual: false` al fixture `ITEM` (el campo es requerido en el tipo).

**(c)** Los tests nuevos al final del archivo. Sin `await import(...)` adentro: un import
dentro del test se come su timeout de 5 s (ya pasó en este repo).

```tsx
test("con filas marcadas aparece el botón de igualar al contractual", async () => {
  render(<TablaConControl items={itemsCuatro()} />);
  fireEvent.click(screen.getByLabelText("Marcar ítem 1"));
  expect(await screen.findByText(/Igualar costo al contractual/i)).toBeTruthy();
});

test("igualar manda los seqs marcados y limpia la selección", async () => {
  const { igualarCostoAlContractual } = await import("@/api/corridas");
  render(<TablaConControl items={itemsCuatro()} />);
  fireEvent.click(screen.getByLabelText("Marcar ítem 1"));
  fireEvent.click(screen.getByLabelText("Marcar ítem 2"));
  fireEvent.click(await screen.findByText(/Igualar costo al contractual/i));
  await waitFor(() =>
    expect(igualarCostoAlContractual).toHaveBeenCalledWith(1, [0, 1]),
  );
});

test("la fila con costo a mano muestra el badge", () => {
  render(
    <TablaConControl
      items={[{ ...ITEM, seq: 0, costo_unitario: 92106000, costo_manual: true }]}
    />,
  );
  expect(screen.getByText("a mano")).toBeTruthy();
});

test("sin costo a mano no hay badge", () => {
  render(<TablaConControl items={[{ ...ITEM, seq: 0, costo_manual: false }]} />);
  expect(screen.queryByText("a mano")).toBeNull();
});

test("en solo lectura no hay botón de igualar", () => {
  render(<TablaConControl items={itemsCuatro()} readOnly={true} />);
  expect(screen.queryByText(/Igualar costo al contractual/i)).toBeNull();
});
```

Nota: `getByLabelText("Marcar ítem 1")` usa el campo `item` de la fila (el código de
licitación), no el `seq`. En `itemsCuatro()` el ítem "1" es `seq: 0` y el "2" es `seq: 1`,
de ahí el `[0, 1]` esperado.

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `cd web && npx vitest run src/components/corrida/TablaItems.test.tsx`
Expected: FAIL — no encuentra el botón ni el texto "a mano".

- [ ] **Step 3: El tipo**

En `web/src/lib/tipos.ts`, en `ItemCuadro`, después de `margen_total`:

```ts
  margen_total: number;
  /** El costo lo puso una persona (igualado al contractual), no lo calculó el motor. */
  costo_manual: boolean;
```

Y en el tipo de la corrida (`CorridaDetalle`), las dos claves que agrega el endpoint —
opcionales, porque el resto de los endpoints devuelven la misma forma sin ellas:

```ts
  /** Solo en la respuesta de `igualarCostoAlContractual`. */
  igualadas?: number[];
  /** Seqs con contractual ≤ 0: no se tocan (regla "nada en $0"). */
  rechazadas?: number[];
```

- [ ] **Step 4: El cliente de API**

En `web/src/api/corridas.ts`, después de `confirmarLote`:

```ts
/** Copia el precio contractual de cada línea marcada como su costo unitario.
 *  Para proyectos especiales: valen lo que dice el contrato y armarles el APU no paga.
 *  Devuelve la corrida recosteada (misma forma que `confirmarLote`) más `igualadas`
 *  y `rechazadas` (las de contractual ≤ 0, que no se tocan). */
export function igualarCostoAlContractual(
  id: number,
  seqs: number[],
): Promise<CorridaDetalle> {
  return apiPost<CorridaDetalle>(`/corridas/${id}/igualar-costo`, { seqs });
}
```

- [ ] **Step 5: El badge en la celda de costo**

En `web/src/components/corrida/TablaItems.tsx`, la celda de `costo_unitario`:

```tsx
                  <TableCell className="text-xs text-right font-mono tabular-nums">
                    {cop(it.costo_unitario)}
                    {it.costo_manual && (
                      <span className="ml-1 rounded bg-muted px-1 text-[10px] font-sans
                                       font-medium text-muted-foreground"
                            title="Costo puesto a mano (igualado al contractual)">
                        a mano
                      </span>
                    )}
                  </TableCell>
```

- [ ] **Step 6: El handler y el botón**

Importar `igualarCostoAlContractual` con los otros imports de `@/api/corridas`, y agregar
el handler al lado de `accionLote`:

```tsx
  /** Copia el contractual como costo en las filas marcadas (proyectos especiales). */
  async function igualarAlContractual() {
    if (seleccionadas.length === 0) return;
    setEnLote(true);
    try {
      const actualizada = await igualarCostoAlContractual(corridaId, seleccionadas);
      onConfirmado(actualizada);
      limpiarSeleccion();
      const n = actualizada.igualadas?.length ?? seleccionadas.length;
      const rechazadas = actualizada.rechazadas ?? [];
      toast.success(`${n} ${n === 1 ? "línea igualada" : "líneas igualadas"} al contractual`);
      if (rechazadas.length > 0) {
        // Nada silencioso: si no se tocó una fila, se dice por qué.
        toast.error(
          `Sin tocar por contractual en $0: ${rechazadas.map((s) => `#${s}`).join(", ")}`,
        );
      }
    } catch (e) {
      // La selección NO se limpia: el usuario puede reintentar sin volver a marcar.
      toast.error(e instanceof Error ? e.message : "No se pudo igualar el costo.");
    } finally {
      setEnLote(false);
    }
  }
```

Y el botón en la barra pegajosa, después de "Confirmar el APU actual":

```tsx
          <Button size="xs" variant="outline" disabled={enLote}
                  onClick={igualarAlContractual}
                  title="Copia el precio contractual como costo. Para actividades globales
                         que valen lo que dice el contrato.">
            Igualar costo al contractual
          </Button>
```

- [ ] **Step 7: Correr los tests y el build**

Run: `cd web && npx vitest run src/components/corrida/TablaItems.test.tsx`
Expected: PASS

Run: `cd web && npm run build`
Expected: build OK, sin errores de `tsc -b`. (Si falla por `costo_manual` faltante en
fixtures de otros tests, agregarlo a esos objetos: es un campo requerido del tipo.)

- [ ] **Step 8: Correr TODOS los tests del frontend**

Run: `cd web && npx vitest run`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add web/src/lib/tipos.ts web/src/api/corridas.ts \
        web/src/components/corrida/TablaItems.tsx \
        web/src/components/corrida/TablaItems.test.tsx
git commit -m "feat(web): boton para igualar el costo al contractual en lote"
```

---

## Tarea 7: Documentación y verificación final

**Files:**
- Modify: `CLAUDE.md` (sección **No hacer** y sección **Datos**)

- [ ] **Step 1: Actualizar el invariante del candado**

En `CLAUDE.md`, en **No hacer**, reemplazar el bullet del candado por:

```markdown
- No emitas un cuadro con filas sin APU **ni costo declarado**: el candado de
  `congelar`/`generar_cuadro` (`seqs_sin_apu`) está para eso, no lo esquives. Una fila
  con `costo_manual` sí pasa, a propósito: son los proyectos especiales, actividades
  globales que valen lo que dice el contrato y a las que armarles el APU no paga. No
  pasan calladas — `alertas_costeo` las marca "costo puesto a mano" y salen en la hoja
  ALERTAS. Ojo: el candado es **de la web**, no global — `pipeline.py` (CLI/GUI) llama
  `write_report` sin pasar por `seqs_sin_apu`, y ahí el hueco se ve en la hoja
  `ALERTAS` del cuadro, no en una puerta trabada. Si lo haces global, el punto de paso
  es `pipeline.py`.
```

- [ ] **Step 2: Documentar el campo**

En `CLAUDE.md`, en **Datos**, después del párrafo del "Veredicto de la revisión":

```markdown
- **Costo puesto a mano.** `corrida_item.costo_manual` (los dos backends) es el costo
  unitario que declaró una persona para una fila: lo escribe el botón "Igualar costo al
  contractual", que copia el `precio_contractual` de las filas marcadas. Es para los
  proyectos especiales — actividades globales que valen lo que dice el contrato y a las
  que armarles el APU no paga. Es una **copia de una vez**, no un vínculo: si cambia el
  contractual, el costo se queda y el margen ≠ 0 se ve. `_costear_row` sale temprano
  cuando está puesta (no consulta el catálogo), `seqs_sin_apu` deja pasar esas filas y
  `alertas_costeo` las marca siempre. Se **borra solo** en `actualizar_eleccion`, el
  único punto de paso por el que cambia el APU de una fila: armar el APU de verdad y
  asignarlo devuelve la fila al costeo normal. Igualar a un contractual ≤ 0 se rechaza
  (regla "nada en $0"). El endpoint es `POST /api/corridas/{id}/igualar-costo`, rol
  `editor` — más estricto que sus vecinos a propósito, porque declara dinero.
```

- [ ] **Step 3: Suite completa de Python**

Run: `python -m pytest tests/ -q`
Expected: PASS, todo verde. Anotar el número de tests para el reporte final.

- [ ] **Step 4: Suite completa del frontend + build**

Run: `cd web && npx vitest run && npm run build`
Expected: PASS y build OK.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: el candado del cuadro admite filas con costo declarado"
```

- [ ] **Step 6: Verificación en el navegador (NO se salta)**

Pedirle al usuario que levante el servidor **desde su propia terminal** (un servidor
interactivo no puede vivir en una sesión de agente que se mata sola) — en el prompt de
Claude Code alcanza con `! python scripts/servidor_local.py`, que ya resuelve
`SUPABASE_URL` y `APU_ADMIN_EMAILS` (sin ellas el login rebota con 401 en todo `/api`).

Comprobar a mano, en una corrida **activa**:

1. Marcar 2 filas → aparece el botón "Igualar costo al contractual".
2. Apretarlo → el costo de esas filas pasa a ser igual al contractual, con badge "a mano",
   y el margen de la fila queda en 0.
3. Recargar la página → el costo sigue puesto (es lo que la columna existe para probar).
4. Con una de esas filas, asignarle un APU con el buscador → el badge desaparece y la
   fila vuelve a costear desde la composición.
5. Descargar el cuadro → la fila igualada aparece, y en la hoja ALERTAS dice
   "costo puesto a mano".

Lección de una feature anterior que se revirtió: en cambios de UI, **el navegador va
ANTES del push**. Tests verdes no alcanzan.

- [ ] **Step 7: Reportar y pedir OK antes de mergear**

`master` auto-despliega a producción, así que el merge/push necesita aprobación explícita
del usuario. Reportar: número de tests, qué se verificó en el navegador, y que la migración
de Postgres (`ADD COLUMN IF NOT EXISTS`) corre sola al boot del servicio.

---

## Notas de alcance (del spec, para no expandir sin permiso)

- **La IA va a seguir objetando** las filas sin APU (`revision.py`: sin APU nunca es "ok").
  Excluirlas del barrido es una línea, pero es otra decisión y queda fuera.
- **No hay botón "quitar el costo a mano"**: asignar un APU ya lo limpia.
- **No se agrega costo editable a mano** con un valor arbitrario. El campo lo soportaría,
  pero el usuario eligió solo el botón.
- **No se cambia el rol de los endpoints vecinos**, aunque `requiere_rol("consulta")` en
  endpoints de escritura sea un hallazgo abierto de la auditoría. Sacarle el acceso a
  gente que hoy trabaja es otra decisión, y del usuario.
