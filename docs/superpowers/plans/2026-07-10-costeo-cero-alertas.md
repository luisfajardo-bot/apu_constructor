# Costeo en $0 nunca mudo + regla "nada en 0" — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que ningún costo en $0 (ni cruce dudoso / sub-APU vacío) pase silencioso al cuadro entregable, y que no se pueda registrar un precio ≤ 0.

**Architecture:** Defensa en dos capas. (1) Guard de entrada: las escrituras de precio del usuario rechazan `precio <= 0`. (2) Alerta de costeo: una función pura `alertas_costeo` deriva por ítem los motivos de revisión (encabezada por "en $0"), que se resaltan en el RESUMEN y se listan en ALERTAS de ambos reportes, y se exponen en la vista web de la corrida. El motor solo cambia en un punto: un sub-APU sin composición cae al histórico y se marca `apu_vacio` (antes daba $0 mudo).

**Tech Stack:** Python 3.12, openpyxl, pytest. Sin dependencias nuevas.

## Global Constraints

- Invariante #1: la IA NUNCA ve dinero. `alertas_costeo` vive del lado con dinero (dominio/report/servicio); jamás entra al payload de la IA ni a las vistas `DePriced*`.
- Regla de negocio: **nada puede costar $0; un $0 es SIEMPRE alerta**. Material del cliente se registra en 1.
- Comportamiento del cuadro: **marcar y seguir** — nunca se bloquea la generación.
- No romper comportamiento existente: los ítems que hoy costean bien deben dar resultados idénticos. Suite completa verde (`python -m pytest tests/ -q`) antes de terminar.
- Español en nombres de dominio y mensajes de usuario. Persistencia solo en `datos/` (este plan no toca repos ni SQL).
- Mensaje único de precio inválido (constante compartida): `"El precio debe ser mayor que 0. Usa 1 si el ítem no tiene costo (p. ej. material del cliente)."`

---

### Task 1: Función pura `alertas_costeo`

**Files:**
- Create: `apu_tool/dominio/alertas.py`
- Test: `tests/test_alertas_costeo.py`

**Interfaces:**
- Consumes: `AssembledApu`, `CostedComponent` de `apu_tool.nucleo.models`.
- Produces: `alertas_costeo(a: AssembledApu) -> list[str]` — lista de motivos legibles (vacía = sin alerta). La usarán Tasks 3, 4, 5.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_alertas_costeo.py
from apu_tool.dominio.alertas import alertas_costeo
from apu_tool.nucleo.models import AssembledApu, CostedComponent, LicitacionItem, MatchStatus


def _item():
    return LicitacionItem(item="1", descripcion="X", unidad="m3", cantidad=1.0,
                          precio_contractual=100.0, shift="DIURNO")


def _ensamble(comps, costo_unitario):
    return AssembledApu(item=_item(), apu_codigo="A", apu_nombre="A", unidad="m3",
                        shift="DIURNO", componentes=comps, costo_unitario=costo_unitario,
                        status=MatchStatus.AUTO, confianza=1.0)


def _comp(costo=10.0, precio=10.0, calidad="exacto"):
    return CostedComponent(insumo_codigo="7", insumo_nombre="Cemento", unidad="kg",
                           rendimiento=1.0, precio_unitario=precio, fuente_precio="X",
                           costo=costo, calidad_cruce=calidad)


def test_item_limpio_sin_alertas():
    assert alertas_costeo(_ensamble([_comp()], 10.0)) == []


def test_componente_en_cero_es_alerta():
    motivos = alertas_costeo(_ensamble([_comp(costo=0.0, precio=0.0)], 0.0))
    assert len(motivos) == 1 and "en $0" in motivos[0]


def test_cruce_ambiguo_con_precio_positivo():
    motivos = alertas_costeo(_ensamble([_comp(calidad="ambiguo")], 10.0))
    assert motivos == ["7 Cemento: cruce ambiguo"]


def test_cero_tiene_prioridad_sobre_cruce():
    # $0 + ambiguo -> solo reporta "en $0", no dobla el motivo
    motivos = alertas_costeo(_ensamble([_comp(costo=0.0, precio=0.0, calidad="ambiguo")], 0.0))
    assert len(motivos) == 1 and "en $0" in motivos[0]


def test_subapu_vacio_y_ciclo():
    assert alertas_costeo(_ensamble([_comp(calidad="apu_vacio")], 10.0)) == \
        ["7 Cemento: sub-APU sin composición"]
    assert alertas_costeo(_ensamble([_comp(calidad="ciclo")], 10.0)) == \
        ["7 Cemento: ciclo de sub-APUs"]


def test_item_sin_componentes_en_cero():
    assert alertas_costeo(_ensamble([], 0.0)) == ["APU en $0 (sin composición o sin costo)"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_alertas_costeo.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'apu_tool.dominio.alertas'`

- [ ] **Step 3: Write minimal implementation**

```python
# apu_tool/dominio/alertas.py
"""
Alertas de costeo: motivos por los que un ítem necesita revisión de costo.

Regla de negocio: nada puede costar $0 (un $0 SIEMPRE es alerta). Además se
señalan cruces dudosos y sub-APUs sin composición. Vive del lado con dinero;
NUNCA entra al payload de la IA (Invariante #1).
"""
from __future__ import annotations

from apu_tool.nucleo.models import AssembledApu

_MOTIVO_CRUCE = {
    "ambiguo": "cruce ambiguo",
    "huerfano": "sin insumo en catálogo",
    "apu_vacio": "sub-APU sin composición",
    "ciclo": "ciclo de sub-APUs",
}


def alertas_costeo(a: AssembledApu) -> list[str]:
    """Motivos de revisión de costo del ítem. Lista vacía = sin alerta."""
    motivos: list[str] = []
    for c in a.componentes:
        etiqueta = f"{c.insumo_codigo} {c.insumo_nombre}".strip()
        if c.costo <= 0 or c.precio_unitario <= 0:          # regla dura: $0 siempre
            motivos.append(f"{etiqueta}: en $0")
        elif c.calidad_cruce in _MOTIVO_CRUCE:
            motivos.append(f"{etiqueta}: {_MOTIVO_CRUCE[c.calidad_cruce]}")
    if not motivos and a.costo_unitario <= 0:               # ítem sin composición / sin costo
        motivos.append("APU en $0 (sin composición o sin costo)")
    return motivos
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_alertas_costeo.py -q`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add apu_tool/dominio/alertas.py tests/test_alertas_costeo.py
git commit -m "feat(alertas): funcion pura alertas_costeo (regla nada en \$0)"
```

---

### Task 2: Sub-APU sin composición cae al histórico y se marca `apu_vacio` (CR-2)

**Files:**
- Modify: `apu_tool/dominio/pricing.py` (`_cost_subapu`)
- Modify: `apu_tool/nucleo/models.py` (doc de `CostedComponent.calidad_cruce`)
- Test: `tests/test_pricing_subapu_vacio.py`

**Interfaces:**
- Consumes: `PricingEngine.components(codigo, shift)`, `CostedComponent`.
- Produces: un componente sub-APU con composición vacía retorna `CostedComponent(precio_unitario=hist, fuente_precio="histórico", calidad_cruce="apu_vacio")`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pricing_subapu_vacio.py
from apu_tool.dominio.pricing import PricingEngine
from apu_tool.nucleo.models import ApuComponent


class _ApusFake:
    def __init__(self, comps_por_clave):
        self._m = comps_por_clave
    def get_components(self, codigo, shift):
        return self._m.get((codigo, shift), [])


class _PreciosFake:
    def get_candidatos(self, codigo):
        return []


class _AlmFake:
    def __init__(self, comps_por_clave):
        self.apus = _ApusFake(comps_por_clave)
        self.precios = _PreciosFake()


def _sub(hist):
    return ApuComponent(apu_codigo="PADRE", shift="DIURNO", insumo_codigo="SUB",
                        insumo_nombre="Sub", unidad="un", rendimiento=2.0,
                        precio_unitario_hist=hist, tipo="apu", ref_shift="DIURNO")


def test_subapu_vacio_cae_a_historico_y_marca_apu_vacio():
    eng = PricingEngine(_AlmFake({}))          # ("SUB","DIURNO") no existe -> vacío
    costed = eng.cost_component(_sub(hist=50.0))
    assert costed.calidad_cruce == "apu_vacio"
    assert costed.fuente_precio == "histórico"
    assert costed.precio_unitario == 50.0
    assert costed.costo == 100.0               # rendimiento 2 * 50


def test_subapu_vacio_sin_historico_queda_en_cero():
    eng = PricingEngine(_AlmFake({}))
    costed = eng.cost_component(_sub(hist=0.0))
    assert costed.calidad_cruce == "apu_vacio"
    assert costed.costo == 0.0                 # lo atrapará alertas_costeo como "en $0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pricing_subapu_vacio.py -q`
Expected: FAIL — hoy `calidad_cruce == "apu"` y `costo == 0.0` en el primer test (no cae a histórico).

- [ ] **Step 3: Write minimal implementation**

En `apu_tool/dominio/pricing.py`, reemplazar el cuerpo de `_cost_subapu` (después del bloque de ciclo) para interceptar la composición vacía ANTES de llamar a `_costo_unitario_apu`:

```python
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
        if not self.components(comp.insumo_codigo, sub_shift):   # sub-APU SIN composición -> histórico
            precio = comp.precio_unitario_hist
            return CostedComponent(
                insumo_codigo=comp.insumo_codigo, insumo_nombre=comp.insumo_nombre,
                unidad=comp.unidad, rendimiento=comp.rendimiento,
                precio_unitario=precio, fuente_precio="histórico",
                costo=comp.rendimiento * precio, calidad_cruce="apu_vacio",
                tipo="apu", ref_shift=sub_shift)
        unit = self._costo_unitario_apu(comp.insumo_codigo, sub_shift, visitando + (clave,))
        return CostedComponent(
            insumo_codigo=comp.insumo_codigo, insumo_nombre=comp.insumo_nombre,
            unidad=comp.unidad, rendimiento=comp.rendimiento,
            precio_unitario=unit, fuente_precio="APU",
            costo=comp.rendimiento * unit, calidad_cruce="apu",
            tipo="apu", ref_shift=sub_shift)
```

En `apu_tool/nucleo/models.py`, actualizar el comentario del campo (documentación, sin cambio funcional):

```python
    calidad_cruce: str = "exacto" # exacto | aproximado | ambiguo | huerfano | apu | apu_vacio | ciclo
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_pricing_subapu_vacio.py tests/test_pricing_ingest.py tests/test_pricing_cruce.py -q`
Expected: PASS (nuevos verdes; los de costeo existentes siguen verdes)

- [ ] **Step 5: Commit**

```bash
git add apu_tool/dominio/pricing.py apu_tool/nucleo/models.py tests/test_pricing_subapu_vacio.py
git commit -m "fix(pricing): sub-APU sin composicion cae a historico + marca apu_vacio (CR-2)"
```

---

### Task 3: RESUMEN/ALERTAS de `report.py` muestran la alerta de costeo

**Files:**
- Modify: `apu_tool/dominio/report.py` (`_ALERT_FILL`, `_build_resumen`, `_build_alertas`)
- Test: `tests/test_report_alertas_costeo.py`

**Interfaces:**
- Consumes: `alertas_costeo` (Task 1), estilos existentes de `report.py`.
- Produces: `_ALERT_FILL` (PatternFill) exportable para `report_categorizado.py` (Task 4).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_report_alertas_costeo.py
import openpyxl
from apu_tool.dominio.report import write_report, _ALERT_FILL
from apu_tool.nucleo.models import AssembledApu, CostedComponent, LicitacionItem, MatchStatus


def _item(item="1"):
    return LicitacionItem(item=item, descripcion="Losa", unidad="m3", cantidad=2.0,
                          precio_contractual=100.0, shift="DIURNO")


def _apu(comps, costo, status=MatchStatus.AUTO):
    return AssembledApu(item=_item(), apu_codigo="A", apu_nombre="Losa", unidad="m3",
                        shift="DIURNO", componentes=comps, costo_unitario=costo,
                        status=status, confianza=1.0)


def _comp(costo, precio, calidad="exacto"):
    return CostedComponent(insumo_codigo="7", insumo_nombre="Cemento", unidad="kg",
                           rendimiento=1.0, precio_unitario=precio, fuente_precio="X",
                           costo=costo, calidad_cruce=calidad)


def test_resumen_resalta_fila_con_costeo_en_cero(tmp_path):
    out = write_report([_apu([_comp(0.0, 0.0)], 0.0)], tmp_path / "c.xlsx")
    ws = openpyxl.load_workbook(out)["RESUMEN"]
    # fila 2 = primer ítem; celda con fill de alerta de costeo
    assert ws.cell(row=2, column=1).fill.fgColor.rgb.endswith("F8CBAD")


def test_alertas_lista_motivo_de_costeo(tmp_path):
    out = write_report([_apu([_comp(0.0, 0.0)], 0.0)], tmp_path / "c.xlsx")
    ws = openpyxl.load_workbook(out)["ALERTAS"]
    textos = [ws.cell(row=r, column=6).value for r in range(2, ws.max_row + 1)]
    assert any(t and "en $0" in t for t in textos)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_report_alertas_costeo.py -q`
Expected: FAIL — `_ALERT_FILL` no existe (ImportError) y el ítem AUTO no aparece en ALERTAS hoy.

- [ ] **Step 3: Write minimal implementation**

En `apu_tool/dominio/report.py`: agregar el import y el fill nuevo cerca de los otros fills:

```python
from apu_tool.dominio.alertas import alertas_costeo
```

```python
_ALERT_FILL = PatternFill("solid", fgColor="F8CBAD")   # naranja: alerta de costeo ($0 / cruce dudoso)
```

Reemplazar el bloque de resaltado dentro de `_build_resumen` (el `if a.margen_total < 0 ... elif ...`) por:

```python
        # Resaltado por prioridad: alerta de costeo > margen negativo > revisar.
        if alertas_costeo(a):
            fill = _ALERT_FILL
        elif a.margen_total < 0:
            fill = _BAD_FILL
        elif a.status in (MatchStatus.REVIEW, MatchStatus.NEW):
            fill = _WARN_FILL
        else:
            fill = None
        if fill is not None:
            for col in range(1, len(headers) + 1):
                ws.cell(row=r, column=col).fill = fill
```

Reemplazar el cuerpo de `_build_alertas` por (incluye ítems con alerta de costeo y combina el motivo):

```python
def _build_alertas(ws, apus: list[AssembledApu]) -> None:
    headers = ["Ítem", "Descripción", "Estado", "Confianza",
               "APU propuesto", "Justificación / motivo"]
    ws.append(headers)
    _style_header(ws, 1, len(headers))
    ws.freeze_panes = "A2"
    filas = [(a, alertas_costeo(a)) for a in apus]
    flagged = [(a, ac) for a, ac in filas
               if a.status in (MatchStatus.REVIEW, MatchStatus.NEW) or ac]
    for a, ac in flagged:
        motivo = a.explicacion
        if ac:
            motivo = (motivo + " | " if motivo else "") + "Costeo: " + "; ".join(ac)
        ws.append([a.item.item, a.item.descripcion,
                   _STATUS_LABEL.get(a.status, a.status), round(a.confianza, 2),
                   a.apu_codigo or "", motivo])
        ws.cell(row=ws.max_row, column=4).number_format = '0.00'
    if not flagged:
        ws.append(["", "Sin alertas: todos los ítems se armaron con coincidencia clara.",
                   "", "", "", ""])
    _autosize(ws, {1: 8, 2: 45, 3: 12, 4: 10, 5: 14, 6: 60})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_report_alertas_costeo.py tests/test_report_categorizado.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apu_tool/dominio/report.py tests/test_report_alertas_costeo.py
git commit -m "feat(report): resaltar y listar alertas de costeo en RESUMEN/ALERTAS (CR-1)"
```

---

### Task 4: `report_categorizado.py` refleja la alerta de costeo

**Files:**
- Modify: `apu_tool/dominio/report_categorizado.py` (import, `_build_detalle`, `_build_alertas`)
- Test: `tests/test_report_categorizado_alertas.py`

**Interfaces:**
- Consumes: `alertas_costeo` (Task 1), `_ALERT_FILL` (Task 3), `_WARN_FILL`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_report_categorizado_alertas.py
import openpyxl
from apu_tool.dominio.report_categorizado import write_report_categorizado
from apu_tool.nucleo.models import AssembledApu, CostedComponent, LicitacionItem, MatchStatus


def _apu():
    item = LicitacionItem(item="1", descripcion="Losa", unidad="m3", cantidad=1.0,
                          precio_contractual=100.0, shift="DIURNO", categoria="CAP-1")
    comp = CostedComponent(insumo_codigo="7", insumo_nombre="Cemento", unidad="kg",
                           rendimiento=1.0, precio_unitario=0.0, fuente_precio="X",
                           costo=0.0, calidad_cruce="exacto")
    return AssembledApu(item=item, apu_codigo="A", apu_nombre="Losa", unidad="m3",
                        shift="DIURNO", componentes=[comp], costo_unitario=0.0,
                        status=MatchStatus.AUTO, confianza=1.0)


def test_detalle_resalta_costeo_cero(tmp_path):
    out = write_report_categorizado([_apu()], tmp_path / "c.xlsx")
    ws = openpyxl.load_workbook(out)["DETALLE"]
    tiene_alerta = any(ws.cell(row=r, column=1).fill.fgColor.rgb.endswith("F8CBAD")
                       for r in range(1, ws.max_row + 1))
    assert tiene_alerta


def test_alertas_incluye_costeo(tmp_path):
    out = write_report_categorizado([_apu()], tmp_path / "c.xlsx")
    ws = openpyxl.load_workbook(out)["ALERTAS"]
    textos = [ws.cell(row=r, column=7).value for r in range(2, ws.max_row + 1)]
    assert any(t and "en $0" in t for t in textos)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_report_categorizado_alertas.py -q`
Expected: FAIL — el ítem AUTO no se resalta ni aparece en ALERTAS hoy.

- [ ] **Step 3: Write minimal implementation**

En `apu_tool/dominio/report_categorizado.py`, ampliar el import existente desde `report`:

```python
from apu_tool.dominio.report import (_MONEY, _PCT, _REND, _STATUS_LABEL, _TOTAL_FILL,
                                     _WARN_FILL, _ALERT_FILL, _autosize, _style_header)
from apu_tool.dominio.alertas import alertas_costeo
```

En `_build_detalle`, reemplazar el resaltado por-ítem (el `if a.status in (REVIEW, NEW)`) por:

```python
            if alertas_costeo(a):
                for col in range(1, len(headers) + 1):
                    ws.cell(row=r, column=col).fill = _ALERT_FILL
            elif a.status in (MatchStatus.REVIEW, MatchStatus.NEW):
                for col in range(1, len(headers) + 1):
                    ws.cell(row=r, column=col).fill = _WARN_FILL
```

Reemplazar el cuerpo de `_build_alertas` por (tiene columna extra "Capítulo"):

```python
def _build_alertas(ws, apus: list[AssembledApu]) -> None:
    headers = ["Ítem", "Descripción", "Capítulo", "Estado", "Confianza",
               "APU propuesto", "Justificación / motivo"]
    ws.append(headers)
    _style_header(ws, 1, len(headers))
    ws.freeze_panes = "A2"
    filas = [(a, alertas_costeo(a)) for a in apus]
    flagged = [(a, ac) for a, ac in filas
               if a.status in (MatchStatus.REVIEW, MatchStatus.NEW) or ac]
    for a, ac in flagged:
        motivo = a.explicacion
        if ac:
            motivo = (motivo + " | " if motivo else "") + "Costeo: " + "; ".join(ac)
        ws.append([a.item.item, a.item.descripcion, a.item.categoria,
                   _STATUS_LABEL.get(a.status, a.status), round(a.confianza, 2),
                   a.apu_codigo or "", motivo])
        ws.cell(row=ws.max_row, column=5).number_format = '0.00'
    if not flagged:
        ws.append(["", "Sin alertas: todos los ítems se armaron con coincidencia clara."])
    _autosize(ws, {1: 9, 2: 45, 3: 30, 4: 12, 5: 10, 6: 14, 7: 50})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_report_categorizado_alertas.py tests/test_report_categorizado.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apu_tool/dominio/report_categorizado.py tests/test_report_categorizado_alertas.py
git commit -m "feat(report-cat): alertas de costeo en DETALLE/ALERTAS del cuadro por capitulo"
```

---

### Task 5: La vista web de la corrida expone la alerta de costeo

**Files:**
- Modify: `apu_tool/servicio/corridas.py` (`_vista_item`, `_totales`)
- Test: `tests/test_corrida_alertas_costeo.py`

**Interfaces:**
- Consumes: `alertas_costeo` (Task 1).
- Produces: `_vista_item(...)` incluye clave `"alertas_costeo": list[str]`; `_totales(...)` incluye `"n_alertas_costeo": int`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_corrida_alertas_costeo.py
from apu_tool.servicio.corridas import _vista_item, _totales
from apu_tool.nucleo.models import AssembledApu, CostedComponent, LicitacionItem, MatchStatus


def _ensamble(costo, precio_comp):
    item = LicitacionItem(item="1", descripcion="Losa", unidad="m3", cantidad=1.0,
                          precio_contractual=100.0, shift="DIURNO")
    comp = CostedComponent(insumo_codigo="7", insumo_nombre="Cemento", unidad="kg",
                           rendimiento=1.0, precio_unitario=precio_comp, fuente_precio="X",
                           costo=costo, calidad_cruce="exacto")
    return AssembledApu(item=item, apu_codigo="A", apu_nombre="Losa", unidad="m3",
                        shift="DIURNO", componentes=[comp], costo_unitario=costo,
                        status=MatchStatus.AUTO, confianza=1.0)


class _Row:
    def __init__(self, status="auto"):
        self.status = status


def test_vista_item_expone_alertas_costeo():
    v = _vista_item(_ensamble(0.0, 0.0), seq=0, status="auto")
    assert v["alertas_costeo"] and "en $0" in v["alertas_costeo"][0]
    v_ok = _vista_item(_ensamble(10.0, 10.0), seq=0, status="auto")
    assert v_ok["alertas_costeo"] == []


def test_totales_cuenta_items_con_alerta():
    ens = [_ensamble(0.0, 0.0), _ensamble(10.0, 10.0)]
    tot = _totales(ens, [_Row(), _Row()])
    assert tot["n_alertas_costeo"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_corrida_alertas_costeo.py -q`
Expected: FAIL con `KeyError: 'alertas_costeo'` / `'n_alertas_costeo'`.

- [ ] **Step 3: Write minimal implementation**

En `apu_tool/servicio/corridas.py`, agregar el import:

```python
from apu_tool.dominio.alertas import alertas_costeo
```

En `_vista_item`, agregar la clave al dict devuelto (junto a los demás campos):

```python
        "costo_total": ens.costo_total, "margen_total": ens.margen_total,
        "alertas_costeo": alertas_costeo(ens),
    }
```

En `_totales`, agregar el conteo:

```python
    return {"contractual": tot_c, "costo": tot_k, "margen": tot_c - tot_k,
            "margen_pct": ((tot_c - tot_k) / tot_c) if tot_c else 0.0,
            "n_items": len(rows), "n_revision": n_rev,
            "n_alertas_costeo": sum(1 for e in ensambles if alertas_costeo(e))}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_corrida_alertas_costeo.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/corridas.py tests/test_corrida_alertas_costeo.py
git commit -m "feat(corridas): exponer alertas_costeo por item y n_alertas_costeo en totales"
```

---

### Task 6: Guard de entrada en las escrituras de precio de servicio

**Files:**
- Modify: `apu_tool/servicio/insumos.py` (constante `MSG_PRECIO_POSITIVO`, `aplicar_cambios`)
- Modify: `apu_tool/servicio/autoria.py` (`crear_insumo`, `aplicar_importar_insumos`)
- Test: `tests/test_guard_precio_positivo.py`

**Interfaces:**
- Produces: `MSG_PRECIO_POSITIVO` (str) en `insumos.py`, reutilizada por `autoria.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_guard_precio_positivo.py
import pytest
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Insumo
from apu_tool.servicio.insumos import aplicar_cambios, MSG_PRECIO_POSITIVO
from apu_tool.servicio import autoria


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo("100", "Concreto 3000 PSI", "M3", "CONCRETOS", 350000.0, "COSTO INTERNO")])
    return alm


def test_aplicar_cambios_rechaza_cero(tmp_path):
    alm = _alm(tmp_path)
    iid = alm.precios.get_candidatos("100")[0].id
    res = aplicar_cambios(alm, [{"insumo_id": iid, "precio": 0, "fuente": "X"}])
    assert res["aplicados"] == 0
    assert res["errores"] and "mayor que 0" in res["errores"][0]["error"]


def test_crear_insumo_rechaza_cero(tmp_path):
    alm = _alm(tmp_path)
    with pytest.raises(ValueError) as e:
        autoria.crear_insumo(alm, {"codigo": "Z9", "nombre": "Test", "precio": 0})
    assert "mayor que 0" in str(e.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_guard_precio_positivo.py -q`
Expected: FAIL — hoy `aplicar_cambios` acepta `precio=0` y `crear_insumo` solo rechaza negativos (ImportError de `MSG_PRECIO_POSITIVO`).

- [ ] **Step 3: Write minimal implementation**

En `apu_tool/servicio/insumos.py`, agregar la constante (nivel de módulo, tras los imports) y endurecer el check:

```python
MSG_PRECIO_POSITIVO = ("El precio debe ser mayor que 0. Usa 1 si el ítem no tiene "
                       "costo (p. ej. material del cliente).")
```

En `aplicar_cambios`, cambiar:

```python
            precio = float(c["precio"])
            if precio <= 0:
                raise ValueError(MSG_PRECIO_POSITIVO)
```

En `apu_tool/servicio/autoria.py`, importar la constante y endurecer `crear_insumo`:

```python
from apu_tool.servicio.insumos import _insumo_out, _norm_h, _to_float, MSG_PRECIO_POSITIVO
```

```python
    precio = _to_float(datos.get("precio"))
    if precio <= 0:
        raise ValueError(MSG_PRECIO_POSITIVO)
```

En `aplicar_importar_insumos`, guardar ambos bucles. En el bucle `for f in prev["crear"]`, al inicio del `try`:

```python
        try:
            if f["precio"] <= 0:
                raise ValueError(MSG_PRECIO_POSITIVO)
            ins = Insumo(codigo=f["codigo"], ...)
```

En el bucle `for c in prev["actualizar"]`, tras el `continue` de no-op, al inicio del `try`:

```python
        try:
            if c["precio_nuevo"] <= 0:
                raise ValueError(MSG_PRECIO_POSITIVO)
            with alm.transaccion("precios") as conn:
                ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_guard_precio_positivo.py tests/test_servicio_insumos.py tests/test_api_autoria.py -q`
Expected: PASS (revisar que ningún test existente sembrara precio 0; si lo hacía, cambiarlo a 1 — es el comportamiento correcto).

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/insumos.py apu_tool/servicio/autoria.py tests/test_guard_precio_positivo.py
git commit -m "feat(precios): rechazar precio <= 0 al editar/crear/importar insumos (regla nada en \$0)"
```

---

### Task 7: Guard de entrada en el CLI `db update-price`

**Files:**
- Modify: `apu_tool/interfaz/cli.py` (`cmd_db_update_price`)
- Test: `tests/test_cli_update_price_guard.py`

**Interfaces:**
- Consumes: `MSG_PRECIO_POSITIVO` de `apu_tool.servicio.insumos`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_update_price_guard.py
from types import SimpleNamespace
from apu_tool.interfaz import cli


def test_update_price_rechaza_cero(capsys, monkeypatch):
    # No debe intentar escribir: retorna código de error y no llama set_precio.
    llamado = {"set": False}

    class _Precios:
        def get_candidatos(self, codigo):
            return [SimpleNamespace(id=1, nombre="Cemento")]
        def set_precio(self, *a, **k):
            llamado["set"] = True

    class _Alm:
        precios = _Precios()

    monkeypatch.setattr(cli, "get_almacen", lambda: _Alm())
    rc = cli.cmd_db_update_price(SimpleNamespace(codigo="7", precio=0.0, nombre=None, fuente=None))
    assert rc == 1
    assert llamado["set"] is False
    assert "mayor que 0" in capsys.readouterr().out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli_update_price_guard.py -q`
Expected: FAIL — hoy llama `set_precio` con 0 y retorna 0.

- [ ] **Step 3: Write minimal implementation**

En `apu_tool/interfaz/cli.py`, dentro de `cmd_db_update_price`, antes del `try`/`set_precio` (tras las validaciones de existencia/ambigüedad):

```python
    if args.precio <= 0:
        from apu_tool.servicio.insumos import MSG_PRECIO_POSITIVO
        print(MSG_PRECIO_POSITIVO)
        return 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cli_update_price_guard.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apu_tool/interfaz/cli.py tests/test_cli_update_price_guard.py
git commit -m "feat(cli): db update-price rechaza precio <= 0"
```

---

### Task 8: Verificación integral (suite completa + regresión)

**Files:**
- (ninguno nuevo; solo corrida de la suite y ajustes menores si algún test viejo sembraba precio 0)

- [ ] **Step 1: Correr la suite Python completa**

Run: `python -m pytest tests/ -q`
Expected: PASS. Si falla algún test por sembrar `precio=0`, corregir el dato de prueba a `1` (es el comportamiento correcto según la regla), NO relajar el guard.

- [ ] **Step 2: Verificar manualmente el cuadro demo**

Run: `python run_cli.py demo`
Expected: se genera el cuadro; si hay ítems en $0, aparecen resaltados en RESUMEN y listados en ALERTAS con "en $0".

- [ ] **Step 3: Commit (si hubo ajustes de datos de prueba)**

```bash
git add -A
git commit -m "test: ajustar datos de prueba a precio > 0 (regla nada en \$0)"
```

---

## Self-review (hecho al escribir el plan)

- **Cobertura de la spec:** Capa 1 (guard) → Tasks 6, 7. Capa 2: motor CR-2 → Task 2; `alertas_costeo` → Task 1; report.py → Task 3; report_categorizado.py → Task 4; vista web → Task 5. Regla "$0 siempre alerta" → Task 1 (regla dura) + Tasks 6/7 (entrada). Privacidad: `alertas` no toca `DePriced*`/IA (verificado en el diseño). Suite verde → Task 8.
- **Sin placeholders:** cada step tiene código real y comando con salida esperada. Los tests construyen el `Almacen` con el patrón real del proyecto (`Almacen(precios_path=..., apus_path=..., corridas_path=...)` + `init_schema()` + `insert_insumos`, calcado de `tests/test_servicio_insumos.py`).
- **Consistencia de tipos:** `alertas_costeo(a) -> list[str]` usada idéntica en Tasks 3, 4, 5. `_ALERT_FILL` definida en Task 3, importada en Task 4. `MSG_PRECIO_POSITIVO` definida en Task 6, importada en Tasks 6/7. `calidad_cruce="apu_vacio"` producido en Task 2, consumido en Task 1.

## Fuera de este plan (seguimiento)

- Renderizado visual en el frontend (marcar filas con `alertas_costeo` y mostrar `n_alertas_costeo` en la barra de totales de la corrida) + tipos en `web/src/lib/tipos.ts`. Plan frontend-only aparte; el backend ya expone los campos (Task 5).
- CR-3 (edición en lote que corrompe precio/fuente al paginar).
