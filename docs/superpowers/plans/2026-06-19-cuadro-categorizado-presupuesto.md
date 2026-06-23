# Cuadro categorizado desde presupuesto — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Leer el presupuesto oficial por capítulos (hoja `FOR 1-PPTO OFICIAL`), armar/costear cada ítem por su código IDU, y entregar un cuadro resumen agrupado por capítulo que compara precio contractual (básico, sin AIU) vs costo interno, con una hoja para ver cada APU completo.

**Architecture:** Flujo nuevo en paralelo al de licitación plana. Un lector (`presupuesto.py`) produce `LicitacionItem`s con `categoria` y `codigo_sugerido`; el ensamblador arma por código directo cuando lo hay; un reporte nuevo (`report_categorizado.py`) agrupa por capítulo. Reúsa matching/costeo/ensamblaje y los estilos de `report.py`. No toca el flujo plano ni el esquema.

**Tech Stack:** Python 3, `openpyxl`, `sqlite3` (stdlib), `pytest`.

## Global Constraints

- **Invariante #1 (NO romper):** la IA nunca ve dinero. Ni el precio contractual del presupuesto ni el costo interno se pasan a la IA. No se tocan `privacy.py` ni las vistas `DePriced*`.
- **Persistencia aislada en `db.py`:** sin SQL crudo fuera de `db.py`/`db/schema.sql`. Los lectores nuevos no acceden a la base directamente; usan métodos de `Database`.
- **Precio contractual = valor unitario BÁSICO sin AIU = columna 0-indexada `[9]`.** No usar `[10]` (con AIU) ni `[11]` (valor total).
- **Fuente por defecto:** hoja `FOR 1-PPTO OFICIAL` del Excel detectado por `config.detect_source_xlsx()`.
- **Agrupación por capítulo** (nivel alto), no por subgrupo. Se procesan todos los capítulos.
- **Reuso de estilos:** importar los helpers de formato de `report.py` (DRY), no reimplementarlos.
- **Sin git:** el proyecto NO es repositorio git. Donde un plan normal diría "Commit", aquí el checkpoint de cada tarea es **correr la suite completa** (`python -m pytest tests/ -q`) y verla pasar.
- **Español** en nombres de dominio, comentarios y mensajes de usuario.
- Entorno Windows; tests con `python -m pytest tests/ -q`.

---

## File Structure

- **Modificar:** `apu_tool/models.py` — `LicitacionItem` gana `categoria` y `codigo_sugerido` (opcionales).
- **Crear:** `apu_tool/presupuesto.py` — lector del presupuesto por capítulos.
- **Modificar:** `apu_tool/assemble.py` — armado por código directo cuando hay `codigo_sugerido`.
- **Crear:** `apu_tool/report_categorizado.py` — reporte agrupado por capítulo (4-5 hojas).
- **Modificar:** `apu_tool/pipeline.py` — `build_desde_presupuesto(...)`.
- **Modificar:** `apu_tool/cli.py` — comando `build-ppto`.
- **Crear (tests):** `tests/test_presupuesto.py`, `tests/test_assemble_codigo.py`, `tests/test_report_categorizado.py`.

---

### Task 1: Extender `LicitacionItem` con `categoria` y `codigo_sugerido`

Deliverable: el modelo admite los dos campos nuevos con default vacío; el flujo plano sigue construyendo `LicitacionItem` igual que antes (campos posicionales intactos). Suite verde.

**Files:**
- Modify: `apu_tool/models.py:83-90`
- Test: `tests/test_presupuesto.py` (primer test)

**Interfaces:**
- Produces: `LicitacionItem(item, descripcion, unidad, cantidad, precio_contractual, shift, categoria="", codigo_sugerido="")` — los dos últimos son opcionales con default `""`.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_presupuesto.py`:

```python
"""Pruebas del lector de presupuesto y del modelo extendido."""
from apu_tool.models import LicitacionItem


def test_licitacion_item_campos_nuevos_opcionales():
    # El flujo plano construye sin los campos nuevos: deben quedar en "".
    plano = LicitacionItem(item="1", descripcion="X", unidad="M2",
                           cantidad=1.0, precio_contractual=100.0, shift="DIURNO")
    assert plano.categoria == ""
    assert plano.codigo_sugerido == ""
    # El flujo de presupuesto los puede pasar.
    ppto = LicitacionItem(item="7.101", descripcion="EXCAVACION", unidad="M3",
                          cantidad=10.0, precio_contractual=49473.0, shift="DIURNO",
                          categoria="7 · REDES ELÉCTRICAS EXTERNAS", codigo_sugerido="3009")
    assert ppto.categoria == "7 · REDES ELÉCTRICAS EXTERNAS"
    assert ppto.codigo_sugerido == "3009"
```

- [ ] **Step 2: Correr el test y verlo fallar**

Run: `python -m pytest tests/test_presupuesto.py::test_licitacion_item_campos_nuevos_opcionales -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'categoria'`.

- [ ] **Step 3: Añadir los campos en `models.py`**

Reemplazar la dataclass `LicitacionItem` (líneas 83-90):

```python
@dataclass(frozen=True)
class LicitacionItem:
    item: str                     # número/código de ítem en la licitación
    descripcion: str
    unidad: str
    cantidad: float
    precio_contractual: float     # precio unitario contractual (lo pone el cliente)
    shift: str                    # DIURNO / NOCTURNO (del ítem o global)
    categoria: str = ""           # capítulo del presupuesto (vacío en el flujo plano)
    codigo_sugerido: str = ""     # código IDU dado por el presupuesto (armado directo)
```

- [ ] **Step 4: Correr el test y verlo pasar**

Run: `python -m pytest tests/test_presupuesto.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint — suite completa**

Run: `python -m pytest tests/ -q`
Expected: todo verde. Sin commit (proyecto no-git).

---

### Task 2: Lector del presupuesto — `apu_tool/presupuesto.py`

Deliverable: `read_presupuesto(path, hoja=...)` recorre la hoja llevando estado (capítulo, turno) y devuelve `list[LicitacionItem]` con los ítems del presupuesto, precio = columna `[9]`.

**Files:**
- Create: `apu_tool/presupuesto.py`
- Test: `tests/test_presupuesto.py` (añadir casos)

**Interfaces:**
- Consumes: `LicitacionItem` (con `categoria`/`codigo_sugerido` de Task 1); `config.SHIFT_DIURNO`/`SHIFT_NOCTURNO`.
- Produces: `read_presupuesto(path: Path | str, hoja: str = "FOR 1-PPTO OFICIAL", default_shift: str = config.SHIFT_DIURNO) -> list[LicitacionItem]`. Índices de columna (0-idx): `COL_CODIGO=2, COL_ITEMPAGO=3, COL_DESC=6, COL_UND=7, COL_CANT=8, COL_PRECIO=9`.

- [ ] **Step 1: Escribir los tests que fallan**

Añadir a `tests/test_presupuesto.py`:

```python
import openpyxl
from apu_tool.presupuesto import read_presupuesto


def _mini_ppto(path):
    """Crea un Excel mínimo con la estructura de FOR 1-PPTO OFICIAL.
    Columnas 0-idx relevantes: [2]=codigo, [3]=item de pago, [6]=desc/encabezado,
    [7]=und, [8]=cantidad, [9]=valor unit básico, [10]=valor+AIU."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "FOR 1-PPTO OFICIAL"

    def fila(**kw):
        row = [None] * 12
        for idx, val in kw.items():
            row[idx] = val
        ws.append(row)

    fila()  # fila 1 vacía
    # Encabezado de tabla (fila de títulos): se ignora (no hay codigo+cantidad).
    fila(**{2: "N°", 3: "ITEM DE PAGO", 6: "DESCRIPCION", 7: "UND.", 8: "CANTIDAD",
            9: "VALOR UNITARIO BASICO", 10: "VALOR + AIU"})
    # Capítulo 7 (tiene número en [3]).
    fila(**{3: 7, 6: "REDES ELÉCTRICAS EXTERNAS"})
    fila(**{6: "TURNO DIURNO"})
    fila(**{6: "REDES ENERGÍA"})   # subgrupo (sin número)
    fila(**{2: 3009, 3: "7.101", 6: "EXCAVACION MANUAL PARA RED", 7: "M3",
            8: 6445, 9: 49473, 10: 67153})
    fila(**{2: 4489, 3: "7.104", 6: "SUBBASE GRANULAR CLASE B", 7: "M3",
            8: 2265, 9: 177852, 10: 241411})
    # Capítulo 9 + turno nocturno.
    fila(**{3: 9, 6: "OBRA CIVIL"})
    fila(**{6: "TURNO NOCTURNO"})
    fila(**{2: 3010, 3: "9.001", 6: "DEMOLICION PAVIMENTO", 7: "M3",
            8: 100, 9: 45548, 10: 61800})
    wb.save(path)


def test_read_presupuesto_items_y_herencia(tmp_path):
    p = tmp_path / "ppto.xlsx"
    _mini_ppto(p)
    items = read_presupuesto(p)

    assert len(items) == 3
    exc = items[0]
    assert exc.codigo_sugerido == "3009"
    assert exc.item == "7.101"
    assert exc.descripcion == "EXCAVACION MANUAL PARA RED"
    assert exc.unidad == "M3"
    assert exc.cantidad == 6445
    assert exc.precio_contractual == 49473      # columna [9], NO [10]
    assert exc.shift == "DIURNO"
    assert "REDES ELÉCTRICAS EXTERNAS" in exc.categoria

    # El tercer ítem hereda capítulo "OBRA CIVIL" y turno NOCTURNO.
    dem = items[2]
    assert dem.codigo_sugerido == "3010"
    assert "OBRA CIVIL" in dem.categoria
    assert dem.shift == "NOCTURNO"


def test_read_presupuesto_ignora_encabezados_y_vacias(tmp_path):
    p = tmp_path / "ppto.xlsx"
    _mini_ppto(p)
    items = read_presupuesto(p)
    # No deben colarse filas de encabezado/capítulo/turno como ítems.
    descripciones = [i.descripcion for i in items]
    assert "REDES ELÉCTRICAS EXTERNAS" not in descripciones
    assert "TURNO DIURNO" not in descripciones
    assert "REDES ENERGÍA" not in descripciones
```

- [ ] **Step 2: Correr los tests y verlos fallar**

Run: `python -m pytest tests/test_presupuesto.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apu_tool.presupuesto'`.

- [ ] **Step 3: Crear `apu_tool/presupuesto.py`**

```python
"""
Lectura del presupuesto oficial por capítulos (hoja FOR 1-PPTO OFICIAL).

El presupuesto está organizado jerárquicamente:
    Capítulo (con número)  ->  TURNO DIURNO/NOCTURNO  ->  subgrupo  ->  ítems.

Se recorre de arriba abajo llevando el estado (capítulo, turno) vigente; cada ítem
hereda ambos. El precio contractual es el valor unitario BÁSICO (sin AIU), columna [9].
A diferencia de la licitación plana, cada ítem trae su código IDU (columna [2]), que
permite armar el APU por código directo.
"""
from __future__ import annotations

import unicodedata
from pathlib import Path

import openpyxl

from . import config
from .models import LicitacionItem

# Índices de columna (0-idx) en la hoja FOR 1-PPTO OFICIAL.
COL_CODIGO = 2
COL_ITEMPAGO = 3
COL_DESC = 6
COL_UND = 7
COL_CANT = 8
COL_PRECIO = 9   # valor unitario BÁSICO (sin AIU)

HOJA_DEFECTO = "FOR 1-PPTO OFICIAL"


def _norm(s) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", str(s or ""))
                if unicodedata.category(c) != "Mn")
    return s.strip().lower()


def _to_float(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("$", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _code(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, int):
        return str(v)
    return str(v).strip()


def _es_codigo_item(v) -> bool:
    """Un código de ítem del presupuesto es numérico (3009) o alfanumérico corto."""
    c = _code(v)
    if not c:
        return False
    if c.isdigit():
        return True
    return len(c) <= 8 and any(ch.isalpha() for ch in c) and any(ch.isdigit() for ch in c)


def _es_numero_capitulo(v) -> bool:
    """Capítulo: la columna de ítem de pago trae un entero (7), no un 7.101."""
    if isinstance(v, int):
        return True
    if isinstance(v, float):
        return v.is_integer()
    s = str(v or "").strip()
    return s.isdigit()


def _get(row: list, idx: int):
    return row[idx] if idx < len(row) else None


def read_presupuesto(path: Path | str, hoja: str = HOJA_DEFECTO,
                     default_shift: str = config.SHIFT_DIURNO) -> list[LicitacionItem]:
    path = Path(path)
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        if hoja not in wb.sheetnames:
            raise ValueError(
                f"No se encontró la hoja '{hoja}'. Hojas: {wb.sheetnames}")
        ws = wb[hoja]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
    finally:
        wb.close()

    capitulo = ""
    turno = default_shift
    items: list[LicitacionItem] = []

    for row in rows:
        codigo = _code(_get(row, COL_CODIGO))
        cantidad = _to_float(_get(row, COL_CANT))
        desc = str(_get(row, COL_DESC) or "").strip()

        # Ítem: tiene código válido y cantidad > 0.
        if cantidad > 0 and _es_codigo_item(_get(row, COL_CODIGO)):
            items.append(LicitacionItem(
                item=_code(_get(row, COL_ITEMPAGO)) or codigo,
                descripcion=desc,
                unidad=str(_get(row, COL_UND) or "").strip(),
                cantidad=cantidad,
                precio_contractual=_to_float(_get(row, COL_PRECIO)),
                shift=turno,
                categoria=capitulo,
                codigo_sugerido=codigo,
            ))
            continue

        # Encabezado: hay descripción y NO hay código de ítem.
        if desc and not codigo:
            n = _norm(desc)
            if "turno" in n:
                turno = (config.SHIFT_NOCTURNO if "noc" in n else config.SHIFT_DIURNO)
            elif _es_numero_capitulo(_get(row, COL_ITEMPAGO)):
                num = _code(_get(row, COL_ITEMPAGO))
                capitulo = f"{num} · {desc}" if num else desc
            # otros encabezados (subgrupos) no cambian capítulo ni turno.
    return items
```

- [ ] **Step 4: Correr los tests y verlos pasar**

Run: `python -m pytest tests/test_presupuesto.py -v`
Expected: PASS (los 3 tests).

- [ ] **Step 5: Checkpoint — suite completa**

Run: `python -m pytest tests/ -q`
Expected: todo verde.

---

### Task 3: Armado por código directo en `assemble.py`

Deliverable: si un `LicitacionItem` trae `codigo_sugerido` y ese código existe como APU, el ensamblador lo arma directo (status `AUTO`, confianza 1.0) sin pasar por el match difuso/IA. Si no existe, cae al flujo actual.

**Files:**
- Modify: `apu_tool/assemble.py:34-49`
- Test: `tests/test_assemble_codigo.py`

**Interfaces:**
- Consumes: `Database`, `Assembler`, `LicitacionItem.codigo_sugerido`, `MatchStatus.AUTO`, `db.apu_index()` (lista de `(codigo, nombre, shift)`).
- Produces: `Assembler` gana el atributo `self._codigos_apu: set[str]`; `assemble_item` resuelve por código directo primero. Firma de `assemble_item` sin cambios.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_assemble_codigo.py`:

```python
"""El armado por código directo (presupuesto) no pasa por el match difuso."""
import pytest

from apu_tool.ai_assist import ApuAdvisor
from apu_tool.assemble import Assembler
from apu_tool.db import Database
from apu_tool.models import Apu, ApuComponent, Insumo, LicitacionItem, MatchStatus


@pytest.fixture()
def db(tmp_path):
    d = Database(tmp_path / "t.db")
    d.reset()
    d.insert_insumos([Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU")])
    d.insert_apus([Apu("3009", "EXCAVACION MANUAL PARA RED", "M3", "DIURNO")])
    d.insert_components([ApuComponent("3009", "DIURNO", "100", "CEMENTO", "KG", 3.0, 900)])
    return d


def test_arma_por_codigo_directo(db):
    asm = Assembler(db, advisor=ApuAdvisor(enabled=False))
    # Descripción deliberadamente NO parecida: si funcionara por nombre, fallaría.
    item = LicitacionItem(item="7.101", descripcion="texto irrelevante zzz",
                          unidad="M3", cantidad=10.0, precio_contractual=50000.0,
                          shift="DIURNO", categoria="7 · REDES", codigo_sugerido="3009")
    res = asm.assemble_item(item)
    assert res.apu_codigo == "3009"
    assert res.status == MatchStatus.AUTO
    assert res.confianza == 1.0
    assert res.costo_unitario == pytest.approx(3000)   # 3 * 1000


def test_codigo_inexistente_cae_al_flujo_normal(db):
    asm = Assembler(db, advisor=ApuAdvisor(enabled=False))
    item = LicitacionItem(item="9.999", descripcion="actividad sin match alguno",
                          unidad="UN", cantidad=1.0, precio_contractual=10.0,
                          shift="DIURNO", categoria="9 · X", codigo_sugerido="NO_EXISTE")
    res = asm.assemble_item(item)
    # No se armó por código: o quedó NEW/manual o algún match difuso, pero NO AUTO-3009.
    assert res.apu_codigo != "3009"
```

- [ ] **Step 2: Correr los tests y verlos fallar**

Run: `python -m pytest tests/test_assemble_codigo.py -v`
Expected: FAIL — sin el camino por código, `assemble_item` usa el matcher difuso y `test_arma_por_codigo_directo` no obtiene `AUTO`/`3009`.

- [ ] **Step 3: Modificar `assemble.py`**

En `__init__` (tras crear `self.retriever`, línea 40), añadir el set de códigos:

```python
        self.retriever = InsumoRetriever(db, self.matcher)
        self._codigos_apu = {cod for cod, _, _ in db.apu_index()}
```

Al inicio de `assemble_item` (justo después de `def assemble_item(self, item):`, antes de `result = self.matcher.match(item)`):

```python
    def assemble_item(self, item: LicitacionItem) -> AssembledApu:
        # Armado por código directo (presupuesto): si el ítem trae un código IDU y
        # ese APU existe, se usa directo — el código es autoritativo, sin fuzzy/IA.
        if item.codigo_sugerido and item.codigo_sugerido in self._codigos_apu:
            return self._build(
                item, item.codigo_sugerido, item.shift, MatchStatus.AUTO, 1.0,
                f"Armado por código del presupuesto ({item.codigo_sugerido}).")

        result = self.matcher.match(item)
```

(El resto de `assemble_item` queda igual.)

- [ ] **Step 4: Correr los tests y verlos pasar**

Run: `python -m pytest tests/test_assemble_codigo.py -v`
Expected: PASS (ambos).

- [ ] **Step 5: Checkpoint — suite completa**

Run: `python -m pytest tests/ -q`
Expected: todo verde.

---

### Task 4: Reporte categorizado — `apu_tool/report_categorizado.py`

Deliverable: `write_report_categorizado(apus, path)` escribe un Excel con hojas RESUMEN POR CAPÍTULO (subtotales + gran total), DETALLE (ítems bajo cada capítulo), APUS (cada APU como bloque estilo Excel), ALERTAS e INFO.

**Files:**
- Create: `apu_tool/report_categorizado.py`
- Test: `tests/test_report_categorizado.py`

**Interfaces:**
- Consumes: `AssembledApu` (con `.item.categoria`, `.contractual_total`, `.costo_total`, `.margen_total`, `.componentes`, etc.), `MatchStatus`; helpers de `report.py`: `_style_header`, `_autosize`, `_MONEY`, `_PCT`, `_REND`, `_STATUS_LABEL`.
- Produces: `write_report_categorizado(apus: list[AssembledApu], path: Path | str) -> Path`; helper `agrupar_por_capitulo(apus) -> dict[str, list[AssembledApu]]` (preserva orden de aparición).

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_report_categorizado.py`:

```python
"""Pruebas del reporte categorizado: agrupación y subtotales por capítulo."""
import openpyxl
import pytest

from apu_tool.models import AssembledApu, LicitacionItem, MatchStatus, CostedComponent
from apu_tool.report_categorizado import agrupar_por_capitulo, write_report_categorizado


def _apu(cat, item, contractual, costo_unit, cant=1.0):
    it = LicitacionItem(item=item, descripcion=f"ACT {item}", unidad="M3",
                        cantidad=cant, precio_contractual=contractual, shift="DIURNO",
                        categoria=cat, codigo_sugerido=item)
    comp = CostedComponent("100", "CEMENTO", "KG", 3.0, costo_unit / 3.0,
                           "PRECIO IDU", costo_unit)
    return AssembledApu(item=it, apu_codigo=item, apu_nombre=f"ACT {item}",
                        unidad="M3", shift="DIURNO", componentes=[comp],
                        costo_unitario=costo_unit, status=MatchStatus.AUTO, confianza=1.0)


def test_agrupar_por_capitulo_preserva_orden():
    apus = [_apu("A", "1", 100, 80), _apu("B", "2", 200, 150), _apu("A", "3", 50, 40)]
    grupos = agrupar_por_capitulo(apus)
    assert list(grupos.keys()) == ["A", "B"]
    assert len(grupos["A"]) == 2 and len(grupos["B"]) == 1


def test_reporte_subtotales_y_gran_total(tmp_path):
    apus = [_apu("A", "1", 100, 80, cant=2.0),   # contractual 200, costo 160
            _apu("B", "2", 200, 150, cant=1.0)]   # contractual 200, costo 150
    out = write_report_categorizado(apus, tmp_path / "cat.xlsx")
    wb = openpyxl.load_workbook(out, data_only=True)
    assert "RESUMEN POR CAPÍTULO" in wb.sheetnames
    assert "DETALLE" in wb.sheetnames
    assert "APUS" in wb.sheetnames

    # En RESUMEN, debe existir una fila de gran total con contractual 400 y costo 310.
    ws = wb["RESUMEN POR CAPÍTULO"]
    valores = [tuple(r) for r in ws.iter_rows(values_only=True)]
    plano = [c for fila in valores for c in fila]
    assert 400 in plano       # gran total contractual
    assert 310 in plano       # gran total costo
```

- [ ] **Step 2: Correr los tests y verlos fallar**

Run: `python -m pytest tests/test_report_categorizado.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apu_tool.report_categorizado'`.

- [ ] **Step 3: Crear `apu_tool/report_categorizado.py`**

```python
"""
Cuadro resumen agrupado por capítulos del presupuesto.

Hojas:
  - RESUMEN POR CAPÍTULO : un renglón por capítulo (contractual vs costo, margen) + gran total.
  - DETALLE              : ítems agrupados bajo cada capítulo, con subtotal por capítulo.
  - APUS                 : cada APU como bloque apilado (estilo de la pestaña APUS original).
  - ALERTAS              : ítems que requieren revisión o armado manual.
  - INFO                 : metadatos + nota de privacidad (la IA no vio dinero).

Reúsa los estilos de report.py para no duplicar formato.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import openpyxl
from openpyxl.styles import Font

from .models import AssembledApu, MatchStatus
from .report import (_MONEY, _PCT, _REND, _STATUS_LABEL, _TOTAL_FILL,
                     _WARN_FILL, _autosize, _style_header)


def agrupar_por_capitulo(apus: list[AssembledApu]) -> dict[str, list[AssembledApu]]:
    """Agrupa por capítulo preservando el orden de aparición."""
    grupos: dict[str, list[AssembledApu]] = {}
    for a in apus:
        cap = a.item.categoria or "(sin capítulo)"
        grupos.setdefault(cap, []).append(a)
    return grupos


def _build_resumen_capitulo(ws, grupos: dict[str, list[AssembledApu]]) -> None:
    headers = ["Capítulo", "Total Contractual", "Total Costo",
               "Margen Total", "Margen %"]
    ws.append(headers)
    _style_header(ws, 1, len(headers))
    ws.freeze_panes = "A2"

    g_contractual = g_costo = 0.0
    for cap, apus in grupos.items():
        c = sum(a.contractual_total for a in apus)
        k = sum(a.costo_total for a in apus)
        m = c - k
        ws.append([cap, c, k, m, (m / c) if c else 0.0])
        r = ws.max_row
        for col in (2, 3, 4):
            ws.cell(row=r, column=col).number_format = _MONEY
        ws.cell(row=r, column=5).number_format = _PCT
        g_contractual += c
        g_costo += k

    g_margen = g_contractual - g_costo
    ws.append(["GRAN TOTAL", g_contractual, g_costo, g_margen,
               (g_margen / g_contractual) if g_contractual else 0.0])
    r = ws.max_row
    for col in (2, 3, 4):
        cell = ws.cell(row=r, column=col)
        cell.number_format = _MONEY
        cell.font = Font(bold=True)
    ws.cell(row=r, column=5).number_format = _PCT
    for col in range(1, len(headers) + 1):
        ws.cell(row=r, column=col).fill = _TOTAL_FILL
    ws.cell(row=r, column=1).font = Font(bold=True)
    _autosize(ws, {1: 46, 2: 18, 3: 16, 4: 16, 5: 10})


def _build_detalle(ws, grupos: dict[str, list[AssembledApu]]) -> None:
    headers = ["Ítem", "Descripción", "Und", "Cantidad", "P. Contractual",
               "Costo Unit.", "Margen Unit.", "Margen %", "Total Contractual",
               "Total Costo", "Margen Total", "Estado"]
    ws.append(headers)
    _style_header(ws, 1, len(headers))
    ws.freeze_panes = "A2"

    for cap, apus in grupos.items():
        ws.append([cap])
        cr = ws.max_row
        ws.cell(row=cr, column=1).font = Font(bold=True)
        for col in range(1, len(headers) + 1):
            ws.cell(row=cr, column=col).fill = _TOTAL_FILL

        for a in apus:
            ws.append([
                a.item.item, a.item.descripcion, a.unidad, a.item.cantidad,
                a.item.precio_contractual, a.costo_unitario, a.margen_unitario,
                a.margen_pct, a.contractual_total, a.costo_total, a.margen_total,
                _STATUS_LABEL.get(a.status, a.status),
            ])
            r = ws.max_row
            ws.cell(row=r, column=4).number_format = _REND
            for col in (5, 6, 7, 9, 10, 11):
                ws.cell(row=r, column=col).number_format = _MONEY
            ws.cell(row=r, column=8).number_format = _PCT
            if a.status in (MatchStatus.REVIEW, MatchStatus.NEW):
                for col in range(1, len(headers) + 1):
                    ws.cell(row=r, column=col).fill = _WARN_FILL

        sc = sum(a.contractual_total for a in apus)
        sk = sum(a.costo_total for a in apus)
        ws.append(["", f"Subtotal {cap}", "", "", "", "", "", "",
                   sc, sk, sc - sk, ""])
        r = ws.max_row
        for col in (9, 10, 11):
            cell = ws.cell(row=r, column=col)
            cell.number_format = _MONEY
            cell.font = Font(bold=True)
        ws.cell(row=r, column=2).font = Font(bold=True)
    _autosize(ws, {1: 9, 2: 46, 3: 6, 4: 12, 5: 16, 6: 14, 7: 14, 8: 10,
                   9: 18, 10: 16, 11: 16, 12: 12})


def _build_apus(ws, apus: list[AssembledApu]) -> None:
    """Cada APU como bloque apilado: título + insumos + costo unitario."""
    sub = ["Insumo Cód", "Insumo", "Und", "Rendimiento", "Precio Unit.",
           "Fuente", "Costo"]
    for a in apus:
        titulo = f"{a.item.item}   {a.apu_nombre}   ({a.unidad})"
        ws.append([titulo])
        tr = ws.max_row
        ws.cell(row=tr, column=1).font = Font(bold=True, color="FFFFFF")
        from openpyxl.styles import PatternFill
        for col in range(1, len(sub) + 1):
            ws.cell(row=tr, column=col).fill = PatternFill("solid", fgColor="1F4E78")

        ws.append(sub)
        _style_header(ws, ws.max_row, len(sub))

        if not a.componentes:
            ws.append(["", "(sin composición — armar manual)", "", "", "", "", ""])
        for c in a.componentes:
            ws.append([c.insumo_codigo, c.insumo_nombre, c.unidad, c.rendimiento,
                       c.precio_unitario, c.fuente_precio, c.costo])
            r = ws.max_row
            ws.cell(row=r, column=4).number_format = _REND
            ws.cell(row=r, column=5).number_format = _MONEY
            ws.cell(row=r, column=7).number_format = _MONEY

        ws.append(["", "COSTO UNITARIO APU", "", "", "", "", a.costo_unitario])
        r = ws.max_row
        ws.cell(row=r, column=2).font = Font(bold=True)
        ws.cell(row=r, column=7).number_format = _MONEY
        ws.cell(row=r, column=7).font = Font(bold=True)
        ws.append([])  # línea en blanco entre APUs
    _autosize(ws, {1: 12, 2: 46, 3: 8, 4: 14, 5: 14, 6: 18, 7: 14})


def _build_alertas(ws, apus: list[AssembledApu]) -> None:
    headers = ["Ítem", "Descripción", "Capítulo", "Estado", "Confianza",
               "APU propuesto", "Justificación / motivo"]
    ws.append(headers)
    _style_header(ws, 1, len(headers))
    ws.freeze_panes = "A2"
    flagged = [a for a in apus if a.status in (MatchStatus.REVIEW, MatchStatus.NEW)]
    for a in flagged:
        ws.append([a.item.item, a.item.descripcion, a.item.categoria,
                   _STATUS_LABEL.get(a.status, a.status), round(a.confianza, 2),
                   a.apu_codigo or "", a.explicacion])
        ws.cell(row=ws.max_row, column=5).number_format = '0.00'
    if not flagged:
        ws.append(["", "Sin alertas: todos los ítems se armaron con coincidencia clara."])
    _autosize(ws, {1: 9, 2: 45, 3: 30, 4: 12, 5: 10, 6: 14, 7: 50})


def write_report_categorizado(apus: list[AssembledApu], path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    grupos = agrupar_por_capitulo(apus)

    wb = openpyxl.Workbook()
    _build_resumen_capitulo(wb.active, grupos)
    wb.active.title = "RESUMEN POR CAPÍTULO"
    _build_detalle(wb.create_sheet("DETALLE"), grupos)
    _build_apus(wb.create_sheet("APUS"), apus)
    _build_alertas(wb.create_sheet("ALERTAS"), apus)

    info = wb.create_sheet("INFO")
    info.append(["Generado", date.today().isoformat()])
    info.append(["Ítems", len(apus)])
    info.append(["Capítulos", len(grupos)])
    info.append(["Precio contractual", "Valor unitario BÁSICO (sin AIU)"])
    info.append(["Nota", "Los precios de costo NO fueron vistos por la IA. "
                         "La IA solo decidió la estructura de los APUs."])
    wb.save(path)
    return path
```

- [ ] **Step 4: Correr los tests y verlos pasar**

Run: `python -m pytest tests/test_report_categorizado.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint — suite completa**

Run: `python -m pytest tests/ -q`
Expected: todo verde.

---

### Task 5: Orquestación y CLI — `build-ppto`

Deliverable: `pipeline.build_desde_presupuesto(...)` lee el presupuesto, arma/costea y escribe el cuadro categorizado; el comando `build-ppto` lo expone. Verificación real sobre el Excel.

**Files:**
- Modify: `apu_tool/pipeline.py` (añadir import y función)
- Modify: `apu_tool/cli.py` (añadir `cmd_build_ppto` y el subparser)
- Test: reusar verificación real (no test unitario nuevo obligatorio; la función reúsa piezas ya testeadas)

**Interfaces:**
- Consumes: `read_presupuesto` (Task 2), `Assembler` (Task 3), `write_report_categorizado` (Task 4), `config`, `ensure_ingested`, `get_db`, `ApuAdvisor`.
- Produces: `build_desde_presupuesto(path: Optional[Path] = None, hoja: str = "FOR 1-PPTO OFICIAL", out_path: Optional[Path] = None, progress: ProgressCb = None, use_ai: Optional[bool] = None) -> tuple[list[AssembledApu], Path]`.

- [ ] **Step 1: Añadir la función en `pipeline.py`**

Añadir el import junto a los demás (cerca de la línea 18):

```python
from .presupuesto import read_presupuesto
from .report_categorizado import write_report_categorizado
```

Añadir la función tras `run_pipeline` (después de la línea 65):

```python
def build_desde_presupuesto(
    path: Optional[Path] = None,
    hoja: str = "FOR 1-PPTO OFICIAL",
    out_path: Optional[Path] = None,
    progress: ProgressCb = None,
    use_ai: Optional[bool] = None,
) -> tuple[list[AssembledApu], Path]:
    """Lee el presupuesto por capítulos, arma/costea cada ítem (por código directo
    cuando se puede) y escribe el cuadro resumen categorizado."""
    config.ensure_dirs()
    ensure_ingested()
    db = get_db()
    src = Path(path) if path else config.detect_source_xlsx()
    if not src or not Path(src).exists():
        raise FileNotFoundError(
            "No se encontró el Excel del presupuesto. Define APU_SOURCE_XLSX o "
            "pasa la ruta.")
    items = read_presupuesto(src, hoja=hoja)
    advisor = ApuAdvisor(enabled=use_ai)
    assembler = Assembler(db, advisor=advisor)
    assembled = assembler.assemble_all(items, progress=progress)
    if out_path is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = config.OUTPUT_DIR / f"cuadro_categorizado_{stamp}.xlsx"
    write_report_categorizado(assembled, out_path)
    return assembled, Path(out_path)
```

- [ ] **Step 2: Añadir el comando en `cli.py`**

Añadir `build_desde_presupuesto` al import de `.pipeline` (líneas 19-24):

```python
from .pipeline import (
    build_desde_presupuesto,
    ensure_ingested,
    generate_sample,
    get_db,
    run_pipeline,
)
```

Añadir el handler (tras `cmd_build`, antes de `cmd_demo`):

```python
def cmd_build_ppto(args) -> int:
    print(f"Armando APUs desde el presupuesto (hoja: {args.hoja})…")
    assembled, out = build_desde_presupuesto(
        hoja=args.hoja,
        out_path=Path(args.out) if args.out else None,
        progress=_progress,
        use_ai=None if not args.no_ai else False,
    )
    _summary(assembled)
    print(f"\nCuadro categorizado escrito en: {out}")
    return 0
```

Registrar el subparser en `build_parser` (tras el bloque de `pb`/`build`, antes del grupo `db`):

```python
    pp = sub.add_parser("build-ppto",
                        help="Armar APUs desde el presupuesto oficial por capítulos.")
    pp.add_argument("hoja", nargs="?", default="FOR 1-PPTO OFICIAL",
                    help="Nombre de la hoja del presupuesto.")
    pp.add_argument("--out", help="Ruta de salida del cuadro categorizado.")
    pp.add_argument("--no-ai", action="store_true", help="Forzar fallback determinístico.")
    pp.set_defaults(func=cmd_build_ppto)
```

- [ ] **Step 3: Correr la suite completa**

Run: `python -m pytest tests/ -q`
Expected: todo verde (sin regresiones).

- [ ] **Step 4: Verificación real sobre el Excel**

Run: `python run_cli.py build-ppto`
Expected: imprime el avance por ítem, un resumen y `Cuadro categorizado escrito en: salidas\cuadro_categorizado_*.xlsx`, sin error.

- [ ] **Step 5: Revisión a mano del cuadro**

Abrir el `.xlsx` generado y verificar:
- Hoja **RESUMEN POR CAPÍTULO**: aparecen capítulos reales (p. ej. "REDES ELÉCTRICAS EXTERNAS") y la fila GRAN TOTAL; los subtotales suman el gran total.
- Hoja **DETALLE**: los ítems quedan bajo su capítulo, con subtotal por capítulo.
- Hoja **APUS**: cada actividad aparece como bloque con sus insumos y el costo unitario.
- Que los ítems con código IDU existente NO caigan en "Revisar" (deben ir `Automático`).

Reportar conteos observados (capítulos, ítems, cuántos a revisar).

---

## Self-Review

**Spec coverage:**
- Fuente `FOR 1-PPTO OFICIAL`, precio col `[9]` → Task 2 (`COL_PRECIO=9`) + tests.
- Extensión del modelo (`categoria`, `codigo_sugerido`) → Task 1.
- Lector por capítulos con herencia capítulo/turno → Task 2.
- Armado por código directo (sin fuzzy) → Task 3.
- Reporte por capítulo con subtotales + gran total → Task 4 (RESUMEN POR CAPÍTULO, DETALLE).
- Ver APUs estilo Excel → Task 4 (hoja APUS).
- Orquestación + comando `build-ppto` → Task 5.
- Invariante #1 / IA sin dinero → ningún payload nuevo a la IA; el costo lo pone `pricing`, el contractual el presupuesto. Verificado por construcción (no se modifica `ai_assist`/`privacy`).
- Verificación real → Task 5 Steps 4-5.

**Placeholder scan:** sin TBD/TODO; todo el código y los comandos están completos.

**Type consistency:** `read_presupuesto`, `agrupar_por_capitulo`, `write_report_categorizado`, `build_desde_presupuesto`, `LicitacionItem.categoria/codigo_sugerido`, `self._codigos_apu` usados con nombres y firmas idénticas entre tareas. Los helpers importados de `report.py` (`_style_header`, `_autosize`, `_MONEY`, `_PCT`, `_REND`, `_STATUS_LABEL`, `_TOTAL_FILL`, `_WARN_FILL`) existen en ese módulo.
