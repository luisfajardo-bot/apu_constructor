# Totales en la lista de corridas — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mostrar en la lista `Mis corridas` (sin abrir cada una) el precio contractual, el costo interno, la diferencia $ y el margen %, reusando el mismo cálculo del detalle.

**Architecture:** Extraer de `vista_corrida` dos helpers (`_ensamblar_corrida`, `_totales`) para que lista y detalle usen el mismo camino (valores idénticos). `listar_corridas` los reusa por corrida (fail-safe). El frontend agrega 4 columnas numéricas a `MisCorridas.tsx`.

**Tech Stack:** Python (FastAPI, servicio/corridas.py), pytest; React + TS + Vite, Vitest, @testing-library/react.

## Global Constraints

- **Invariante:** los totales de `listar_corridas` deben ser IDÉNTICOS al bloque `totales` de `vista_corrida` para la misma corrida (mismo cálculo, no uno nuevo).
- `margen = contractual − costo`; `margen_pct = (contractual − costo)/contractual` (0 si contractual = 0) — fórmula AGREGADA, igual a la actual de `vista_corrida`.
- Respetar el modo: **activa** = costeo en vivo (`PricingEngine` + `precargar`); **congelada** = snapshot.
- Fail-safe: si una corrida falla al costear, su fila muestra los 4 números en `null` y NO rompe la lista; los conteos `n_items`/`n_revision` se conservan siempre.
- Moneda con `cop()` y porcentaje con `pct()` de `web/src/lib/moneda.ts`. Dif. $ y Margen % en verde si ≥ 0, rojo si < 0. `null` → `—`.
- Trabajar en la rama `feat/totales-lista-corridas` (ya creada). No romper tests existentes.

---

### Task 1: Backend — cálculo compartido y totales en `listar_corridas`

**Files:**
- Modify: `apu_tool/servicio/corridas.py` (refactor `vista_corrida` ~161-182; `listar_corridas` ~272-280; agregar `_ensamblar_corrida` y `_totales`)
- Test: `tests/test_servicio_corridas.py`

**Interfaces:**
- Consume: `PricingEngine` (ya importado), `_costear_row(alm, row, pricing)`, `_assembled_desde_snapshot(row, snap)`, `_vista_item(ens, seq, status)`, `AssembledApu.contractual_total`/`.costo_total`, `alm.corridas.listar_corridas()`, `alm.corridas.get_items(id)`, `alm.corridas.get_snapshots(id)`.
- Produce:
  - `_ensamblar_corrida(alm, meta, rows, pricing) -> list[AssembledApu]`
  - `_totales(ensambles, rows) -> dict` con claves `contractual, costo, margen, margen_pct, n_items, n_revision`
  - `listar_corridas(alm) -> list[dict]` con las claves actuales + `contractual, costo, margen, margen_pct` (float o `None`)

- [ ] **Step 1: Escribir el test del invariante (falla)**

En `tests/test_servicio_corridas.py`, agregar:

```python
def test_listar_corridas_totales_igual_a_vista(tmp_path):
    alm = _almacen_seed(tmp_path)
    items = [LicitacionItem(item="1", descripcion="Concreto clase D", unidad="M3",
                            cantidad=10.0, precio_contractual=400000.0, shift="DIURNO")]
    cid = corridas.construir_corrida(alm, "lic.xlsx", items, "DIURNO", use_ai=False)

    tot_v = corridas.vista_corrida(alm, cid)["totales"]
    fila = next(c for c in corridas.listar_corridas(alm) if c["id"] == cid)
    for k in ("contractual", "costo", "margen", "margen_pct"):
        assert fila[k] == pytest.approx(tot_v[k])

    corridas.congelar(alm, cid)                       # congelada: mismo invariante vs snapshot
    tot_v2 = corridas.vista_corrida(alm, cid)["totales"]
    fila2 = next(c for c in corridas.listar_corridas(alm) if c["id"] == cid)
    for k in ("contractual", "costo", "margen", "margen_pct"):
        assert fila2[k] == pytest.approx(tot_v2[k])


def test_listar_corridas_fila_robusta_ante_error_de_costeo(tmp_path, monkeypatch):
    alm = _almacen_seed(tmp_path)
    items = [LicitacionItem(item="1", descripcion="Concreto clase D", unidad="M3",
                            cantidad=10.0, precio_contractual=400000.0, shift="DIURNO")]
    corridas.construir_corrida(alm, "lic.xlsx", items, "DIURNO", use_ai=False)

    def _boom(*a, **k):
        raise RuntimeError("costeo falló")
    monkeypatch.setattr(corridas, "_ensamblar_corrida", _boom)

    fila = corridas.listar_corridas(alm)[0]
    assert fila["n_items"] == 1                        # conteos no dependen del costeo
    assert fila["contractual"] is None and fila["costo"] is None
    assert fila["margen"] is None and fila["margen_pct"] is None
```

- [ ] **Step 2: Correr y ver que falla**

Run: `python -m pytest tests/test_servicio_corridas.py::test_listar_corridas_totales_igual_a_vista tests/test_servicio_corridas.py::test_listar_corridas_fila_robusta_ante_error_de_costeo -q`
Expected: FAIL (`listar_corridas` no tiene la clave `contractual`; `corridas._ensamblar_corrida` no existe).

- [ ] **Step 3: Agregar los helpers `_ensamblar_corrida` y `_totales`**

En `apu_tool/servicio/corridas.py`, justo ANTES de `def vista_corrida(`, agregar:

```python
def _ensamblar_corrida(alm: Almacen, meta, rows, pricing: PricingEngine) -> list[AssembledApu]:
    """Ensambla los ítems de una corrida respetando el modo: congelada -> snapshot por
    ítem (con caída a costeo en vivo si falta el snapshot); activa -> costeo en vivo.
    Camino ÚNICO compartido por vista_corrida y listar_corridas."""
    if meta.modo == "congelada":
        snaps = alm.corridas.get_snapshots(meta.id)
        return [_assembled_desde_snapshot(r, snaps[r.seq]) if r.seq in snaps
                else _costear_row(alm, r, pricing) for r in rows]
    return [_costear_row(alm, r, pricing) for r in rows]


def _totales(ensambles: list[AssembledApu], rows) -> dict:
    """Totales de una corrida (fórmula única). margen_pct es AGREGADO."""
    tot_c = sum(e.contractual_total for e in ensambles)
    tot_k = sum(e.costo_total for e in ensambles)
    n_rev = sum(1 for r in rows if r.status in ("review", "new"))
    return {"contractual": tot_c, "costo": tot_k, "margen": tot_c - tot_k,
            "margen_pct": ((tot_c - tot_k) / tot_c) if tot_c else 0.0,
            "n_items": len(rows), "n_revision": n_rev}
```

- [ ] **Step 4: Refactorizar `vista_corrida` para usar los helpers (sin cambiar comportamiento)**

Reemplazar el cuerpo actual de `vista_corrida` (desde `rows = alm.corridas.get_items(...)` hasta el `return`) por:

```python
    rows = alm.corridas.get_items(corrida_id)
    pricing = PricingEngine(alm)                       # motor COMPARTIDO por toda la corrida
    pricing.precargar((r.apu_codigo, r.shift) for r in rows if r.apu_codigo)  # lote
    ensambles = _ensamblar_corrida(alm, meta, rows, pricing)
    items = [_vista_item(ens, r.seq, r.status) for ens, r in zip(ensambles, rows)]
    return {
        "id": meta.id, "archivo": meta.archivo, "estado": meta.estado, "modo": meta.modo,
        "duracion_ms": meta.duracion_ms, "items": items,
        "totales": _totales(ensambles, rows),
    }
```

- [ ] **Step 5: Agregar los totales a `listar_corridas` (fail-safe)**

Reemplazar todo el cuerpo de `listar_corridas` por:

```python
def listar_corridas(alm: Almacen) -> list[dict]:
    out: list[dict] = []
    for meta in alm.corridas.listar_corridas():
        rows = alm.corridas.get_items(meta.id)
        n_rev = sum(1 for it in rows if it.status in ("review", "new"))
        fila = {"id": meta.id, "archivo": meta.archivo, "creada_en": meta.creada_en,
                "estado": meta.estado, "modo": meta.modo, "duracion_ms": meta.duracion_ms,
                "n_items": len(rows), "n_revision": n_rev,
                "contractual": None, "costo": None, "margen": None, "margen_pct": None}
        try:                                           # fail-safe: si una corrida no
            pricing = PricingEngine(alm)               # costea, su fila queda con None
            pricing.precargar((r.apu_codigo, r.shift) for r in rows if r.apu_codigo)
            tot = _totales(_ensamblar_corrida(alm, meta, rows, pricing), rows)
            fila.update(contractual=tot["contractual"], costo=tot["costo"],
                        margen=tot["margen"], margen_pct=tot["margen_pct"])
        except Exception:
            pass
        out.append(fila)
    return out
```

- [ ] **Step 6: Correr los tests nuevos + los de corridas (verde, sin regresión)**

Run: `python -m pytest tests/test_servicio_corridas.py -q`
Expected: PASS (incluye los 2 nuevos y todos los existentes de vista/congelar).

- [ ] **Step 7: Suite completa**

Run: `python -m pytest tests/ -q`
Expected: PASS (mismos skipped de siempre; 0 fallos).

- [ ] **Step 8: Commit**

```bash
git add apu_tool/servicio/corridas.py tests/test_servicio_corridas.py
git commit -m "feat(corridas): totales (contractual/costo/margen) en listar_corridas, reusando el cálculo de vista_corrida"
```

---

### Task 2: Frontend — 4 columnas en `MisCorridas`

**Files:**
- Modify: `web/src/lib/tipos.ts` (interface `CorridaResumen`, ~109-118)
- Modify: `web/src/pages/MisCorridas.tsx`
- Test: `web/src/pages/MisCorridas.test.tsx` (crear)

**Interfaces:**
- Consume: `cop`, `pct` de `@/lib/moneda`; `CorridaResumen` con `contractual, costo, margen, margen_pct: number | null`; `listarCorridas()` de `@/api/corridas`.
- Produce: helper `colorSigno(n: number | null): string | undefined` (color hex o `undefined`).

- [ ] **Step 1: Extender el tipo `CorridaResumen`**

En `web/src/lib/tipos.ts`, dentro de `export interface CorridaResumen { ... }`, agregar antes del cierre `}`:

```ts
  contractual: number | null;
  costo: number | null;
  margen: number | null;
  margen_pct: number | null;
```

- [ ] **Step 2: Escribir el test de front (falla)**

Crear `web/src/pages/MisCorridas.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test, vi } from "vitest";
import { colorSigno } from "./MisCorridas";

vi.mock("@/api/corridas", () => ({
  listarCorridas: vi.fn(async () => [{
    id: 1, archivo: "lic.xlsx", creada_en: "2026-07-08T10:00:00", estado: "en_revision",
    modo: "activa", n_items: 2, n_revision: 1, duracion_ms: 1000,
    contractual: 4000000, costo: 3675000, margen: 325000, margen_pct: 0.08125,
  }]),
  eliminarCorrida: vi.fn(),
  descargarPlantillaLicitacion: vi.fn(),
}));

test("colorSigno: verde si >=0, rojo si <0, undefined si null", () => {
  expect(colorSigno(10)).toBe("#276749");
  expect(colorSigno(0)).toBe("#276749");
  expect(colorSigno(-5)).toBe("#c53030");
  expect(colorSigno(null)).toBeUndefined();
});

test("MisCorridas muestra contractual, costo, dif y margen % formateados", async () => {
  const { default: MisCorridas } = await import("./MisCorridas");
  render(<MemoryRouter><MisCorridas /></MemoryRouter>);
  await waitFor(() => expect(screen.getByText("$4.000.000")).toBeInTheDocument());
  expect(screen.getByText("$3.675.000")).toBeInTheDocument();
  expect(screen.getByText("$325.000")).toBeInTheDocument();
  expect(screen.getByText("8.1%")).toBeInTheDocument();
});
```

- [ ] **Step 3: Correr y ver que falla**

Run: `cd web && npx vitest run src/pages/MisCorridas.test.tsx`
Expected: FAIL (`colorSigno` no existe; los textos no se renderizan).

- [ ] **Step 4: Agregar el helper `colorSigno` y el import del formateador**

En `web/src/pages/MisCorridas.tsx`, agregar el import (junto a los otros imports de `@/lib`):

```tsx
import { cop, pct } from "@/lib/moneda";
```

Y al final del archivo (después del objeto `styles` o antes, a nivel de módulo), exportar:

```tsx
export function colorSigno(n: number | null): string | undefined {
  if (n === null || n === undefined) return undefined;
  return n >= 0 ? "#276749" : "#c53030";
}
```

- [ ] **Step 5: Agregar los `<th>` de las 4 columnas**

En el `<thead>`, tras el `<th>` de "Por revisar" (`>Por revisar</th>`), insertar:

```tsx
                <th style={{ ...styles.th, ...styles.thNum }}>Contractual</th>
                <th style={{ ...styles.th, ...styles.thNum }}>Costo</th>
                <th style={{ ...styles.th, ...styles.thNum }}>Dif. $</th>
                <th style={{ ...styles.th, ...styles.thNum }}>Margen %</th>
```

- [ ] **Step 6: Agregar los `<td>` de las 4 columnas**

En el `<tbody>`, tras el `<td>` de "Por revisar" (`{c.n_revision}</td>`), insertar:

```tsx
                  <td style={{ ...styles.td, ...styles.tdNum }}>
                    {c.contractual === null ? "—" : cop(c.contractual)}
                  </td>
                  <td style={{ ...styles.td, ...styles.tdNum }}>
                    {c.costo === null ? "—" : cop(c.costo)}
                  </td>
                  <td style={{ ...styles.td, ...styles.tdNum, color: colorSigno(c.margen) }}>
                    {c.margen === null ? "—" : cop(c.margen)}
                  </td>
                  <td style={{ ...styles.td, ...styles.tdNum, color: colorSigno(c.margen) }}>
                    {c.margen_pct === null ? "—" : pct(c.margen_pct)}
                  </td>
```

- [ ] **Step 7: Correr el test de front (verde)**

Run: `cd web && npx vitest run src/pages/MisCorridas.test.tsx`
Expected: PASS.

- [ ] **Step 8: Typecheck + suite de front + build**

Run: `cd web && npx tsc -b && npx vitest run && npm run build`
Expected: sin errores de tipos; todos los tests verdes; build OK.

- [ ] **Step 9: Commit**

```bash
git add web/src/lib/tipos.ts web/src/pages/MisCorridas.tsx web/src/pages/MisCorridas.test.tsx
git commit -m "feat(corridas-ui): columnas contractual/costo/dif/margen% en la lista de corridas"
```

---

## Notas de verificación

- El invariante lista==detalle está cubierto por `test_listar_corridas_totales_igual_a_vista` (activa y congelada).
- Rendimiento: `listar_corridas` costea al vuelo cada corrida activa con `PricingEngine` + `precargar` (barato tras la optimización previa). No se cachea (YAGNI).
- Fuera de alcance: persistir totales, ordenar/filtrar por las nuevas columnas, cambios en `Corrida.tsx`.
