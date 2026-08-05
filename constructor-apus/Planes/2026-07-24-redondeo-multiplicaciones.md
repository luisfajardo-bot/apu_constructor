> Espejo automático — no editar aquí. Fuente: `docs/superpowers/plans/2026-07-24-redondeo-multiplicaciones.md`

# Redondeo a la unidad en multiplicaciones — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redondear el resultado de cada multiplicación monetaria a la unidad (peso) más cercana, en el cálculo, para que no haya decimales en costos ni totales.

**Architecture:** Un helper puro central (`mul_redondeado`) con gemelo en backend (Python) y frontend (TS) encapsula la regla: multiplicar → redondear a la unidad (medio hacia arriba) → si el producto es positivo y redondea a 0, fijar en 1 (nada en $0). Se reemplaza cada multiplicación monetaria (`pricing.py`, `models.py`, `costoApu.ts`) por ese helper.

**Tech Stack:** Python 3 / FastAPI backend; React + TypeScript + Vitest en `web/`.

## Global Constraints

- **Regla del redondeo (exacta):** unidad entera, **medio hacia arriba** = `floor(p + 0.5)` (dominio no-negativo). Producto **positivo** que redondearía a 0 → **1**. Producto `== 0` (o ≤ 0) → **0** (0 genuino; lo marca la alerta de costeo existente).
- **Alcance:** ambos lados — **costo Y contractual**. NO tocar restas (`margen`), divisiones ni `margen_pct`.
- **Invariante #1 (la IA nunca ve dinero):** esta feature no toca la IA ni `privacy.py`; no hay payload nuevo.
- **No re-redondear** snapshots de corridas congeladas ni el redondeo de display (`cop()`).
- **Sin dependencias nuevas.** Español en comentarios/mensajes.
- **Verificación frontend:** usar `npm run build` (= `tsc -b && vite build`), NUNCA solo `tsc --noEmit` (no detecta errores de project references).
- **Commits:** terminar el mensaje con `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

## Preparación

Trabajar en una rama nueva: `git checkout -b feat/redondeo-multiplicaciones`.

---

### Task 1: Helper de redondeo (backend) + tests

**Files:**
- Create: `apu_tool/nucleo/redondeo.py`
- Test: `tests/test_redondeo.py` (Create)

> Nota: vive en `nucleo/` (no en `dominio/` como sugería el spec) porque `models.py` (que está en `nucleo`) lo consume; un helper puro sin dependencias en la capa base evita cualquier ciclo de import.

**Interfaces:**
- Produces: `apu_tool.nucleo.redondeo.mul_redondeado(a: float, b: float) -> int`

- [ ] **Step 1: Escribir el test que falla**

Create `tests/test_redondeo.py`:

```python
from apu_tool.nucleo.redondeo import mul_redondeado


def test_medio_hacia_arriba():
    assert mul_redondeado(1.05, 1250) == 1313      # 1312.5 -> 1313
    assert mul_redondeado(1.0, 1312.4) == 1312     # 1312.4 -> 1312
    assert mul_redondeado(0.5, 1) == 1             # 0.5 -> 1


def test_producto_entero_exacto_sin_cambio():
    assert mul_redondeado(1.05, 350000) == 367500
    assert mul_redondeado(2.0, 350000) == 700000


def test_minimo_uno_si_positivo_redondea_a_cero():
    assert mul_redondeado(0.0003, 1000) == 1       # 0.3 -> 1 (nada en $0 por redondeo)
    assert mul_redondeado(0.4, 1) == 1             # 0.4 -> 1


def test_cero_genuino_queda_en_cero():
    assert mul_redondeado(2.0, 0) == 0             # precio 0
    assert mul_redondeado(0, 1000) == 0            # rendimiento 0


def test_devuelve_int():
    assert isinstance(mul_redondeado(1.05, 1250), int)
    assert isinstance(mul_redondeado(2.0, 0), int)
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_redondeo.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'apu_tool.nucleo.redondeo'`.

- [ ] **Step 3: Implementar el helper**

Create `apu_tool/nucleo/redondeo.py`:

```python
"""Redondeo a la unidad (peso) en multiplicaciones monetarias.

Regla del negocio: no se trabaja con decimales en dinero. El resultado de CADA
multiplicación monetaria se redondea a la unidad más cercana (medio hacia arriba).
Si el producto es positivo pero redondearía a 0, se fija en 1 (invariante "nada en
$0": el redondeo nunca hace desaparecer un costo real). Un 0 genuino queda en 0.

Módulo puro (solo stdlib). No toca dinero hacia la IA (invariante #1 no aplica aquí).
"""
from __future__ import annotations

import math


def mul_redondeado(a: float, b: float) -> int:
    """Multiplica y redondea a la unidad más cercana, medio hacia arriba.

    - ``a * b <= 0``  -> 0 (0 genuino; lo marca la alerta de costeo).
    - ``a * b > 0`` que redondearía a 0 -> 1 (nada en $0 por redondeo).
    - resto -> ``floor(a * b + 0.5)``.
    """
    p = a * b
    if p <= 0:
        return 0
    r = math.floor(p + 0.5)
    return r if r != 0 else 1
```

- [ ] **Step 4: Correr el test para verificar que pasa**

Run: `python -m pytest tests/test_redondeo.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add apu_tool/nucleo/redondeo.py tests/test_redondeo.py
git commit -m "$(cat <<'EOF'
feat(redondeo): helper mul_redondeado (unidad más cercana, mínimo 1 si positivo)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Aplicar el redondeo en el costeo backend (pricing + models)

**Files:**
- Modify: `apu_tool/dominio/pricing.py` (imports; `cost_component` ~89; `_fallback_historico` ~104; `_cost_subapu` ~119)
- Modify: `apu_tool/nucleo/models.py` (import; `costo_total` ~194; `contractual_total` ~198)
- Test: `tests/test_redondeo.py` (Modify — agregar tests de integración pricing + models)

**Interfaces:**
- Consumes: `mul_redondeado` (Task 1)
- Produces: `CostedComponent.costo`, `AssembledApu.costo_total` y `AssembledApu.contractual_total` ahora enteros (redondeados por multiplicación).

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `tests/test_redondeo.py`:

```python
def test_pricing_redondea_costo_de_componente(tmp_path):
    from apu_tool.datos.almacen import Almacen
    from apu_tool.nucleo.models import Apu, ApuComponent, Insumo
    from apu_tool.dominio.pricing import PricingEngine
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([Insumo("100", "X", "KG", "MAT", 1000.0, "PRECIO IDU")])
    alm.apus.crear_apu(Apu("A1", "APU", "M2", "DIURNO"),
                       [ApuComponent("A1", "DIURNO", "100", "X", "KG", 1.0005, 1000.0)])
    costed, total = PricingEngine(alm).cost_apu("A1", "DIURNO")
    assert costed[0].costo == 1001            # 1.0005 * 1000 = 1000.5 -> 1001
    assert isinstance(costed[0].costo, int)
    assert total == 1001


def test_assembledapu_totales_redondeados():
    from apu_tool.nucleo.models import AssembledApu, LicitacionItem, MatchStatus
    item = LicitacionItem(item="1", descripcion="x", unidad="M2", cantidad=3.0,
                          precio_contractual=1000.5, shift="DIURNO")
    a = AssembledApu(item=item, apu_codigo="A1", apu_nombre="X", unidad="M2",
                     shift="DIURNO", componentes=[], costo_unitario=1312,
                     status=MatchStatus.AUTO, confianza=1.0)
    assert a.costo_total == 3936              # 1312 * 3 = 3936
    assert a.contractual_total == 3002        # 1000.5 * 3 = 3001.5 -> 3002
    assert isinstance(a.contractual_total, int)
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/test_redondeo.py -q`
Expected: FAIL — `costed[0].costo == 1000.5` (aún float sin redondear) y `contractual_total == 3001.5`.

- [ ] **Step 3: Aplicar el helper en `pricing.py`**

En `apu_tool/dominio/pricing.py`, agregar el import junto a los existentes (~línea 16):

```python
from apu_tool.nucleo.models import ApuComponent, CostedComponent
from apu_tool.nucleo.redondeo import mul_redondeado
```

En `cost_component` (~línea 89), reemplazar:

```python
        costo = mul_redondeado(comp.rendimiento, precio)
```

En `_fallback_historico` (~línea 104), el campo `costo`:

```python
            costo=mul_redondeado(comp.rendimiento, precio), calidad_cruce=calidad,
```

En `_cost_subapu` (~línea 119), el campo `costo`:

```python
            costo=mul_redondeado(comp.rendimiento, unit), calidad_cruce="apu",
```

(El costo unitario del APU en `_costo_unitario_apu`/`cost_apu`/`cost_components` es `sum(...)` de estos enteros → queda entero; no se toca.)

- [ ] **Step 4: Aplicar el helper en `models.py`**

En `apu_tool/nucleo/models.py`, agregar el import cerca de la cabecera del archivo (con los demás imports del módulo):

```python
from apu_tool.nucleo.redondeo import mul_redondeado
```

Reemplazar las dos propiedades de total (~líneas 193-199):

```python
    @property
    def costo_total(self) -> int:
        return mul_redondeado(self.costo_unitario, self.item.cantidad)

    @property
    def contractual_total(self) -> int:
        return mul_redondeado(self.item.precio_contractual, self.item.cantidad)
```

(No tocar `margen_unitario`, `margen_total` ni `margen_pct`: son restas/divisiones.)

- [ ] **Step 5: Correr los tests nuevos**

Run: `python -m pytest tests/test_redondeo.py -q`
Expected: PASS (7 passed).

- [ ] **Step 6: Correr la suite completa y ajustar valores esperados si cambian**

Run: `python -m pytest tests/ -q`
Expected: verde. La mayoría de tests usan productos ya enteros (p. ej. `1.05*350000=367500`) y `int == float` es verdadero, así que **no deberían cambiar**. Si algún test falla porque su valor esperado era un producto con fracción, actualízalo al entero redondeado (medio hacia arriba) y muéstralo en el reporte. No cambies la lógica de producción para hacer pasar un test: el valor correcto es el redondeado.

- [ ] **Step 7: Commit**

```bash
git add apu_tool/dominio/pricing.py apu_tool/nucleo/models.py tests/test_redondeo.py
git commit -m "$(cat <<'EOF'
feat(costeo): redondear cada multiplicación monetaria a la unidad (pricing + totales)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Helper de redondeo (frontend) + tests

**Files:**
- Create: `web/src/lib/redondeo.ts`
- Test: `web/src/lib/redondeo.test.ts` (Create)

**Interfaces:**
- Produces: `mulRedondeado(a: number, b: number): number` (gemelo de `mul_redondeado`)

- [ ] **Step 1: Escribir el test que falla**

Create `web/src/lib/redondeo.test.ts`:

```typescript
import { expect, test } from "vitest";
import { mulRedondeado } from "./redondeo";

test("mulRedondeado: unidad más cercana, medio hacia arriba", () => {
  expect(mulRedondeado(1.05, 1250)).toBe(1313);   // 1312.5 -> 1313
  expect(mulRedondeado(1.0, 1312.4)).toBe(1312);  // 1312.4 -> 1312
  expect(mulRedondeado(0.5, 1)).toBe(1);          // 0.5 -> 1
});

test("mulRedondeado: producto entero exacto sin cambio", () => {
  expect(mulRedondeado(1.05, 350000)).toBe(367500);
  expect(mulRedondeado(2.5, 2000)).toBe(5000);
});

test("mulRedondeado: mínimo 1 si positivo redondea a 0", () => {
  expect(mulRedondeado(0.0003, 1000)).toBe(1);    // 0.3 -> 1
  expect(mulRedondeado(0.4, 1)).toBe(1);
});

test("mulRedondeado: 0 genuino queda en 0", () => {
  expect(mulRedondeado(2, 0)).toBe(0);
  expect(mulRedondeado(0, 1000)).toBe(0);
});
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `cd web && npx vitest run src/lib/redondeo.test.ts`
Expected: FAIL — no existe `./redondeo`.

- [ ] **Step 3: Implementar el helper**

Create `web/src/lib/redondeo.ts`:

```typescript
// Redondeo a la unidad (peso) en multiplicaciones monetarias. Gemelo de
// apu_tool/nucleo/redondeo.py. Regla: cada producto monetario se redondea a la
// unidad más cercana (medio hacia arriba); un producto positivo que redondearía
// a 0 se fija en 1 (nada en $0 por redondeo); un 0 genuino queda en 0.
export function mulRedondeado(a: number, b: number): number {
  const p = a * b;
  if (p <= 0) return 0;
  // Math.round en JS es medio-hacia-+∞: Math.round(0.5)=1, Math.round(1312.5)=1313.
  const r = Math.round(p);
  return r !== 0 ? r : 1;
}
```

- [ ] **Step 4: Correr el test para verificar que pasa**

Run: `cd web && npx vitest run src/lib/redondeo.test.ts`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/redondeo.ts web/src/lib/redondeo.test.ts
git commit -m "$(cat <<'EOF'
feat(web): helper mulRedondeado (gemelo del redondeo de costeo)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Aplicar el redondeo en el diálogo editable (`costoApu.ts`)

**Files:**
- Modify: `web/src/lib/costoApu.ts` (import; `costoDeFila` ~15-19)
- Test: `web/src/lib/costoApu.test.ts` (Modify — agregar caso de redondeo)

**Interfaces:**
- Consumes: `mulRedondeado` (Task 3)
- Produces: `costoDeFila` devuelve el costo de la fila ya redondeado; `costoTotalApu` (suma de enteros) queda entero.

- [ ] **Step 1: Escribir el test que falla**

Agregar a `web/src/lib/costoApu.test.ts`:

```typescript
test("costoDeFila: redondea el producto a la unidad (medio hacia arriba)", () => {
  expect(costoDeFila("1.0005", 1000)).toBe(1001);  // 1000.5 -> 1001
  expect(costoDeFila("0.0003", 1000)).toBe(1);     // 0.3 -> 1 (nada en $0)
});
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `cd web && npx vitest run src/lib/costoApu.test.ts`
Expected: FAIL — `costoDeFila("1.0005", 1000)` devuelve `1000.5` (sin redondear).

- [ ] **Step 3: Aplicar el helper en `costoApu.ts`**

En `web/src/lib/costoApu.ts`, agregar el import (bajo el existente, ~línea 6):

```typescript
import { rendimientoValido } from "./validacionApu";
import { mulRedondeado } from "./redondeo";
```

Reemplazar el cuerpo de `costoDeFila` (~líneas 15-19) — conservando el early-return para rendimiento no numérico:

```typescript
export function costoDeFila(rendimiento: string, precio: number): number {
  const r = Number(rendimiento);
  if (!Number.isFinite(r) || rendimiento.trim() === "") return 0;
  return mulRedondeado(r, precio);
}
```

(No tocar `rendimientoDesdeCosto`: es una división `costo/precio`, no una multiplicación; el rendimiento sigue con decimales.)

- [ ] **Step 4: Correr el test del archivo (nuevos + existentes)**

Run: `cd web && npx vitest run src/lib/costoApu.test.ts`
Expected: PASS. Los tests existentes siguen verdes (sus productos ya eran enteros; el round-trip de la línea 22 ya envuelve en `Math.round`).

- [ ] **Step 5: Verificar tipos + build de producción + suite completa frontend**

Run: `cd web && npx tsc --noEmit && npm run build && npx vitest run`
Expected: `tsc` sin errores; `npm run build` (`tsc -b && vite build`) ✓; vitest todo verde (salvo el flake conocido de `Auditoria.test.tsx` por timeout, ajeno a esta feature — si aparece, corre `npx vitest run src/pages/Auditoria.test.tsx` para confirmar que pasa aislado).

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/costoApu.ts web/src/lib/costoApu.test.ts
git commit -m "$(cat <<'EOF'
feat(web): redondear el costo por fila del diálogo editable (usa mulRedondeado)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Verificación final (tras todas las tareas)

- [ ] Backend: `python -m pytest tests/ -q` → verde.
- [ ] Frontend: `cd web && npx tsc --noEmit && npm run build && npx vitest run` → verde (salvo flake Auditoria aislado).
- [ ] Manual (opcional): armar una corrida con un APU cuyo `rendimiento × precio` dé fracción y confirmar en el cuadro/diálogo que costos y totales salen enteros; y que un componente diminuto no cae a $0 por redondeo (queda en 1).

## Self-Review (cobertura del spec)

- Redondeo por cada multiplicación → Task 2 (pricing 3 sitios + models 2) + Task 4 (costoDeFila).
- Unidad entera, medio hacia arriba → helper (Tasks 1 y 3), `floor(p+0.5)` / `Math.round`.
- Mínimo 1 si positivo; 0 genuino queda 0 → helper (Tasks 1 y 3), verificado en tests.
- Ambos lados (costo y contractual) → Task 2 (`costo_total` y `contractual_total`).
- No tocar restas/divisiones/`margen_pct` ni snapshots → no se modifican esas propiedades.
- Gemelo backend/frontend coherente → mismos casos de test en ambos.
- No romper existentes → Task 2 Step 6 y Task 4 Step 5 corren la suite completa; los productos enteros no cambian.
