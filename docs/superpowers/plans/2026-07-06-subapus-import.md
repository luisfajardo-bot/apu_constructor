# Detección de sub-APUs en el import — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que la vista previa del import de APUs detecte y liste los sub-APUs (biblioteca ∪ lote), y que al aplicar el import se marquen `tipo='apu'` automáticamente, sin correr `marcar-subapus` aparte.

**Architecture:** La lógica de detección vive en `apu_tool/servicio/subapus.py` (reusa `_ref_shift`); `apu_tool/servicio/autoria.py` la usa en `preview_importar_apus` (reporta) y `aplicar_importar_apus` (marca con `dataclasses.replace`). El frontend (`DialogoImportarApus.tsx`) muestra una sección "Sub-APUs detectados". Apilado sobre la Fase 1 (`feat/apus-compuestos`).

**Tech Stack:** Python + pytest (backend); React + TypeScript + Vitest (frontend).

## Global Constraints

- **Apilado sobre Fase 1:** usa `ApuComponent.tipo`/`ref_shift`, `subapus._ref_shift`, el costeo recursivo. No reimplementar nada de Fase 1.
- **Trabajo LOCAL, sin push a prod.**
- Persistencia/detección: la lógica de detección va en `subapus.py`; `autoria.py` orquesta. Sin SQL crudo fuera de los repos. Sin dependencias nuevas. Español. Invariante #1 intacta (`tipo`/`ref_shift` son estructura; nada de dinero a la IA).
- Detección "biblioteca ∪ lote": un componente es sub-APU si su `insumo_codigo` coincide con el `codigo` de un APU que ya existe en la biblioteca o viene en el mismo lote. `ref_shift`: turno del padre si el sub-APU existe en ese turno; si no `DIURNO`; si no el único (regla de `_ref_shift`).
- `origen` de cada vínculo: `"biblioteca"` si el código ya existe en la biblioteca, si no `"lote"`.
- `marcar-subapus` (CLI) **se mantiene** (backfill).
- **Refinamiento vs spec:** el spec mencionaba un `n_subapus` por fila de "A crear"; se implementa SOLO la lista raíz `subapus` (Opción B) para no ensuciar el tipo compartido `ApuResumen` (usado por otras vistas). El conteo total se ve en el encabezado de la sección; la lista cubre el objetivo de "verlo" y verificar.
- Verificación: `python -m pytest tests/ -q`; desde `web/`: `npx tsc --noEmit`, `npx vitest run`, `npm run build`.

---

### Task 1: Detección compartida en `subapus.py`

**Files:**
- Modify: `apu_tool/servicio/subapus.py`
- Test: `tests/test_subapus_import.py`

**Interfaces:**
- Consumes: `subapus._ref_shift` (Fase 1), `alm.apus.apu_index()`, `ApuComponent` (con `tipo`/`ref_shift`).
- Produces:
  - `mapa_codigos_apu(alm, apus_extra=()) -> dict[str, set[str]]` — `codigo -> {turnos}` de biblioteca ∪ `apus_extra`.
  - `detectar_subapus_lote(alm, apus_lote, comps_por, solo=None) -> list[dict]` — vínculos `{apu_codigo, apu_turno, sub_codigo, sub_turno, sub_nombre, origen}`.
  - `marcar_comps_subapu(comps, apu_shift, mapa) -> tuple[list[ApuComponent], int]` — comps con sub-APUs marcados + nº marcados.

- [ ] **Step 1: Write the failing test**

Crear `tests/test_subapus_import.py`:

```python
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent
from apu_tool.servicio.subapus import (
    mapa_codigos_apu, detectar_subapus_lote, marcar_comps_subapu,
)


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def test_mapa_une_biblioteca_y_lote(tmp_path):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("B", "SUB", "M3", "DIURNO")])          # en biblioteca
    lote = [Apu("Z", "SUB2", "M3", "NOCTURNO")]                       # en el lote
    mapa = mapa_codigos_apu(alm, lote)
    assert mapa["B"] == {"DIURNO"} and mapa["Z"] == {"NOCTURNO"}


def test_detecta_subapu_de_biblioteca_y_de_lote(tmp_path):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("B", "SUB-BIBLIO", "M3", "DIURNO")])    # sub-APU ya existe
    # lote: A usa a B (biblioteca) y a C (viene en el lote); D es insumo normal
    apus_lote = [Apu("A", "PADRE", "M2", "DIURNO"), Apu("C", "SUB-LOTE", "M3", "DIURNO")]
    comps_por = {
        ("A", "DIURNO"): [
            ApuComponent("A", "DIURNO", "B", "SUB-BIBLIO", "M3", 1.0, 0.0),
            ApuComponent("A", "DIURNO", "C", "SUB-LOTE", "M3", 2.0, 0.0),
            ApuComponent("A", "DIURNO", "100", "CEMENTO", "KG", 3.0, 0.0),
        ],
        ("C", "DIURNO"): [ApuComponent("C", "DIURNO", "100", "CEMENTO", "KG", 1.0, 0.0)],
    }
    vinc = detectar_subapus_lote(alm, apus_lote, comps_por, solo=apus_lote)
    porcod = {v["sub_codigo"]: v for v in vinc if v["apu_codigo"] == "A"}
    assert set(porcod) == {"B", "C"}                                  # 100 (insumo) NO aparece
    assert porcod["B"]["origen"] == "biblioteca" and porcod["B"]["sub_turno"] == "DIURNO"
    assert porcod["C"]["origen"] == "lote" and porcod["C"]["sub_turno"] == "DIURNO"


def test_ref_shift_hereda_o_cae_a_diurno(tmp_path):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("B", "SUB", "M3", "DIURNO")])           # solo DIURNO
    apus_lote = [Apu("A", "PADRE", "M2", "NOCTURNO")]                 # padre NOCTURNO
    comps_por = {("A", "NOCTURNO"): [ApuComponent("A", "NOCTURNO", "B", "SUB", "M3", 1.0, 0.0)]}
    vinc = detectar_subapus_lote(alm, apus_lote, comps_por, solo=apus_lote)
    assert vinc[0]["sub_turno"] == "DIURNO"                            # cae a DIURNO


def test_marcar_comps_subapu(tmp_path):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("B", "SUB", "M3", "DIURNO")])
    mapa = mapa_codigos_apu(alm, [])
    comps = [ApuComponent("A", "DIURNO", "B", "SUB", "M3", 1.0, 0.0),
             ApuComponent("A", "DIURNO", "100", "CEMENTO", "KG", 3.0, 0.0)]
    marcados, n = marcar_comps_subapu(comps, "DIURNO", mapa)
    assert n == 1
    sub = [c for c in marcados if c.insumo_codigo == "B"][0]
    ins = [c for c in marcados if c.insumo_codigo == "100"][0]
    assert sub.tipo == "apu" and sub.ref_shift == "DIURNO"
    assert ins.tipo == "insumo"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_subapus_import.py -q`
Expected: FAIL — `mapa_codigos_apu`/`detectar_subapus_lote`/`marcar_comps_subapu` no existen.

- [ ] **Step 3: Implementar los helpers**

En `apu_tool/servicio/subapus.py`, añadir el import de `replace` y `ApuComponent` arriba, y las tres funciones (después de `_ref_shift`):

```python
from dataclasses import replace

from apu_tool.nucleo.models import ApuComponent, Perfil
```
(añade `ApuComponent` al import existente de `models`; ya importa `Perfil`.)

```python
def mapa_codigos_apu(alm: Almacen, apus_extra=()) -> dict:
    """codigo -> {turnos}, uniendo la biblioteca con los APUs `apus_extra` del lote."""
    m: dict[str, set] = {}
    for cod, _nom, sh in alm.apus.apu_index():
        m.setdefault(cod, set()).add(sh)
    for a in apus_extra:
        m.setdefault(a.codigo, set()).add(a.shift)
    return m


def detectar_subapus_lote(alm: Almacen, apus_lote, comps_por, solo=None) -> list[dict]:
    """Vínculos sub-APU de los componentes de `solo` (o de todos los del lote).
    El mapa de códigos-APU cubre biblioteca ∪ apus_lote completo."""
    scan = solo if solo is not None else apus_lote
    lib_codes = {cod for cod, _nom, _sh in alm.apus.apu_index()}
    mapa = mapa_codigos_apu(alm, apus_lote)
    vinculos: list[dict] = []
    for a in scan:
        for c in comps_por.get((a.codigo, a.shift), []):
            if c.insumo_codigo and c.insumo_codigo in mapa:
                vinculos.append({
                    "apu_codigo": a.codigo, "apu_turno": a.shift,
                    "sub_codigo": c.insumo_codigo,
                    "sub_turno": _ref_shift(c.insumo_codigo, a.shift, mapa),
                    "sub_nombre": c.insumo_nombre,
                    "origen": "biblioteca" if c.insumo_codigo in lib_codes else "lote"})
    return vinculos


def marcar_comps_subapu(comps, apu_shift: str, mapa: dict):
    """Devuelve (comps con sub-APUs marcados tipo='apu'+ref_shift, nº marcados)."""
    out, n = [], 0
    for c in comps:
        if c.insumo_codigo and c.insumo_codigo in mapa:
            out.append(replace(c, tipo="apu",
                               ref_shift=_ref_shift(c.insumo_codigo, apu_shift, mapa)))
            n += 1
        else:
            out.append(c)
    return out, n
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_subapus_import.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/subapus.py tests/test_subapus_import.py
git commit -m "feat(subapus): detección de sub-APUs en un lote (biblioteca ∪ lote) + marcado de componentes"
```

---

### Task 2: `preview` reporta y `aplicar` marca (`autoria.py`)

**Files:**
- Modify: `apu_tool/servicio/autoria.py`
- Test: `tests/test_subapus_import.py` (añadir)

**Interfaces:**
- Consumes: `subapus.mapa_codigos_apu`, `subapus.detectar_subapus_lote`, `subapus.marcar_comps_subapu`; `_parse_apus` (ya en autoria.py).
- Produces:
  - `preview_importar_apus(alm, contenido)` → dict con `crear`, `ya_existe`, **`subapus`** (lista de vínculos).
  - `aplicar_importar_apus(alm, contenido, actor=None)` → dict con `creados`, **`subapus_marcados`**, `errores`.

- [ ] **Step 1: Write the failing test**

Añadir a `tests/test_subapus_import.py` (usa `monkeypatch` para no construir un Excel real):

```python
import pytest
from apu_tool.servicio import autoria


def _parse_fake(apus_lote, comps_por):
    def _fake(_contenido):
        return apus_lote, comps_por
    return _fake


def test_preview_reporta_subapus(tmp_path, monkeypatch):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("B", "SUB-BIBLIO", "M3", "DIURNO")])
    apus_lote = [Apu("A", "PADRE", "M2", "DIURNO")]
    comps_por = {("A", "DIURNO"): [
        ApuComponent("A", "DIURNO", "B", "SUB-BIBLIO", "M3", 1.0, 0.0),
        ApuComponent("A", "DIURNO", "100", "CEMENTO", "KG", 3.0, 0.0)]}
    monkeypatch.setattr(autoria, "_parse_apus", _parse_fake(apus_lote, comps_por))
    res = autoria.preview_importar_apus(alm, b"x")
    assert len(res["crear"]) == 1
    assert len(res["subapus"]) == 1
    assert res["subapus"][0]["sub_codigo"] == "B" and res["subapus"][0]["origen"] == "biblioteca"


def test_aplicar_marca_subapus(tmp_path, monkeypatch):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("B", "SUB-BIBLIO", "M3", "DIURNO")])
    apus_lote = [Apu("A", "PADRE", "M2", "DIURNO")]
    comps_por = {("A", "DIURNO"): [
        ApuComponent("A", "DIURNO", "B", "SUB-BIBLIO", "M3", 1.0, 0.0),
        ApuComponent("A", "DIURNO", "100", "CEMENTO", "KG", 3.0, 0.0)]}
    monkeypatch.setattr(autoria, "_parse_apus", _parse_fake(apus_lote, comps_por))
    res = autoria.aplicar_importar_apus(alm, b"x")
    assert res["creados"] == 1 and res["subapus_marcados"] == 1
    comps = alm.apus.get_components("A", "DIURNO")
    sub = [c for c in comps if c.insumo_codigo == "B"][0]
    ins = [c for c in comps if c.insumo_codigo == "100"][0]
    assert sub.tipo == "apu" and sub.ref_shift == "DIURNO"
    assert ins.tipo == "insumo"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_subapus_import.py -q`
Expected: FAIL — `preview_importar_apus` no devuelve `subapus`; `aplicar_importar_apus` no marca ni devuelve `subapus_marcados`.

- [ ] **Step 3: Modificar `preview_importar_apus`**

En `apu_tool/servicio/autoria.py`, añadir al inicio el import:

```python
from apu_tool.servicio.subapus import (
    mapa_codigos_apu, detectar_subapus_lote, marcar_comps_subapu,
)
```

Reemplazar `preview_importar_apus` (líneas 288-296) por:

```python
def preview_importar_apus(alm: Almacen, contenido: bytes) -> dict:
    apus, comps_por = _parse_apus(contenido)
    crear, ya_existe, crear_apus = [], [], []
    for a in apus:
        info = {"codigo": a.codigo, "turno": a.shift, "nombre": a.nombre,
                "unidad": a.unidad, "grupo": a.grupo,
                "n_componentes": len(comps_por.get((a.codigo, a.shift), []))}
        if alm.apus.get_apu(a.codigo, a.shift):
            ya_existe.append(info)
        else:
            crear.append(info)
            crear_apus.append(a)
    subapus = detectar_subapus_lote(alm, apus, comps_por, solo=crear_apus)
    return {"crear": crear, "ya_existe": ya_existe, "subapus": subapus}
```

- [ ] **Step 4: Modificar `aplicar_importar_apus`**

Reemplazar `aplicar_importar_apus` (líneas 299-318) por:

```python
def aplicar_importar_apus(alm: Almacen, contenido: bytes, actor=None) -> dict:
    apus, comps_por = _parse_apus(contenido)
    mapa = mapa_codigos_apu(alm, apus)
    creados, subapus_marcados, errores = 0, 0, []
    lote = nuevo_lote()
    for a in apus:
        if alm.apus.get_apu(a.codigo, a.shift):
            continue                                   # ya existe: no se pisa
        try:
            comps = comps_por.get((a.codigo, a.shift), [])
            comps, n_sub = marcar_comps_subapu(comps, a.shift, mapa)
            with alm.transaccion("apus") as conn:
                alm.apus.crear_apu(a, comps, conn=conn)
                registrar_auditoria(
                    alm, conn, actor, "apu.crear", "apu", a.codigo, antes=None,
                    despues={"codigo": a.codigo, "turno": a.shift, "nombre": a.nombre,
                             "unidad": a.unidad, "grupo": a.grupo,
                             "n_componentes": len(comps), "n_subapus": n_sub},
                    contexto={"origen": "import", "lote_id": lote})
            creados += 1
            subapus_marcados += n_sub
        except ValueError as e:
            errores.append({"codigo": a.codigo, "turno": a.shift, "error": str(e)})
    return {"creados": creados, "subapus_marcados": subapus_marcados, "errores": errores}
```

- [ ] **Step 5: Run test + suite**

Run: `python -m pytest tests/test_subapus_import.py -q` (los 2 nuevos + los 4 de Task 1).
Luego `python -m pytest tests/ -q` → suite completa verde (sin regresión del import existente).

- [ ] **Step 6: Commit**

```bash
git add apu_tool/servicio/autoria.py tests/test_subapus_import.py
git commit -m "feat(import): preview reporta sub-APUs y aplicar los marca (tipo='apu') sin marcar-subapus aparte"
```

---

### Task 3: Vista previa muestra "Sub-APUs detectados" (frontend)

**Files:**
- Modify: `web/src/lib/tipos.ts`
- Modify: `web/src/components/autoria/DialogoImportarApus.tsx`
- Test: `web/src/components/autoria/SeccionSubApus.test.tsx`

**Interfaces:**
- Consumes: la respuesta de `previewImportarApus` (ahora con `subapus`).
- Produces: tipo `VinculoSubApu`; subcomponente `SeccionSubApus` (exportado desde `DialogoImportarApus.tsx`).

- [ ] **Step 1: Write the failing test**

Crear `web/src/components/autoria/SeccionSubApus.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { SeccionSubApus } from "./DialogoImportarApus";

test("lista los sub-APUs detectados con su origen", () => {
  render(
    <SeccionSubApus
      vinculos={[
        { apu_codigo: "3010", apu_turno: "DIURNO", sub_codigo: "7439",
          sub_turno: "DIURNO", sub_nombre: "MARTILLO", origen: "lote" },
        { apu_codigo: "3011", apu_turno: "DIURNO", sub_codigo: "7439",
          sub_turno: "DIURNO", sub_nombre: "MARTILLO", origen: "biblioteca" },
      ]}
    />,
  );
  expect(screen.getByText(/Sub-APUs detectados/)).toBeTruthy();
  expect(screen.getByText("3010")).toBeTruthy();
  expect(screen.getByText(/en el lote/)).toBeTruthy();
  expect(screen.getByText(/en biblioteca/)).toBeTruthy();
});

test("no renderiza nada si no hay vínculos", () => {
  const { container } = render(<SeccionSubApus vinculos={[]} />);
  expect(container.textContent).toBe("");
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (desde `web/`): `npx vitest run src/components/autoria/SeccionSubApus.test.tsx`
Expected: FAIL — `SeccionSubApus` no existe.

- [ ] **Step 3: Tipos (`web/src/lib/tipos.ts`)**

Reemplazar `ImportApusPreview` (líneas 244-247) y añadir el tipo del vínculo + el resultado:

```ts
export interface VinculoSubApu {
  apu_codigo: string;
  apu_turno: string;
  sub_codigo: string;
  sub_turno: string;
  sub_nombre: string;
  origen: "lote" | "biblioteca";
}

export interface ImportApusPreview {
  crear: ApuResumen[];
  ya_existe: ApuResumen[];
  subapus: VinculoSubApu[];
}
```

Y a `ImportResultado` (líneas 249-252) añadir el conteo:

```ts
export interface ImportResultado {
  creados: number;
  subapus_marcados?: number;
  errores: { codigo: string; turno?: string; error: string }[];
}
```

- [ ] **Step 4: Subcomponente + sección en `DialogoImportarApus.tsx`**

En `web/src/components/autoria/DialogoImportarApus.tsx`:

(a) Importar el tipo y ampliar el estado de preview:

```tsx
import type { ApuResumen, VinculoSubApu } from "@/lib/tipos";
```
En `type EstadoDial`, la variante `preview` gana `subapus`:
```tsx
  | { fase: "preview"; crear: ApuResumen[]; ya_existe: ApuResumen[]; subapus: VinculoSubApu[] }
```
En `handleFileChange`, al setear el estado preview, incluir `subapus: res.subapus ?? []`.
En el bloque `const crear = ...`, añadir:
```tsx
  const subapus = enPreview ? estado.subapus : [];
```

(b) En el JSX de preview, insertar la sección (antes de `<SeccionApus titulo="A crear" ... />`):

```tsx
        {enPreview && (
          <div className="space-y-3">
            <SeccionSubApus vinculos={subapus} />
            <SeccionApus titulo="A crear" filas={crear} />
            <SeccionApus titulo="Ya existen" filas={yaExiste} />
          </div>
        )}
```
(reemplaza el `<div className="space-y-3">` de preview existente por este bloque.)

(c) Añadir el subcomponente exportado al final del archivo:

```tsx
export function SeccionSubApus({ vinculos }: { vinculos: VinculoSubApu[] }) {
  if (vinculos.length === 0) return null;
  return (
    <div>
      <p className="text-xs font-semibold mb-1">
        Sub-APUs detectados{" "}
        <span className="font-normal text-muted-foreground">({vinculos.length})</span>
        <span className="ml-2 font-normal text-muted-foreground">
          — al crear, estas líneas se marcan como sub-APU
        </span>
      </p>
      <div className="overflow-x-hidden overflow-y-auto max-h-40 border rounded">
        <table className="w-full text-xs border-collapse">
          <tbody>
            {vinculos.map((v, i) => (
              <tr key={`${v.apu_codigo}-${v.sub_codigo}-${i}`} className="even:bg-muted/10">
                <td className="px-2 py-0.5 font-mono">{v.apu_codigo}</td>
                <td className="px-2 py-0.5 text-muted-foreground">→ usa</td>
                <td className="px-2 py-0.5 font-mono">{v.sub_codigo}</td>
                <td className="px-2 py-0.5">({v.sub_turno})</td>
                <td className="px-2 py-0.5 align-top break-words" title={v.sub_nombre}>
                  {v.sub_nombre}
                </td>
                <td className="px-2 py-0.5 text-[10px] text-muted-foreground whitespace-nowrap">
                  {v.origen === "lote" ? "en el lote" : "en biblioteca"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

(d) (Opcional, mismo archivo) en `aplicar`, enriquecer el toast de éxito:
```tsx
        const nSub = res.subapus_marcados ?? 0;
        toast.success(`${res.creados} APU(s) creados` + (nSub ? ` · ${nSub} sub-APU(s) enlazados` : ""));
```

- [ ] **Step 5: Run test + verificación**

Run (desde `web/`): `npx vitest run src/components/autoria/SeccionSubApus.test.tsx` → PASS.
Luego: `npx vitest run` (todo verde), `npx tsc --noEmit` (limpio), `npm run build` (OK).

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/tipos.ts web/src/components/autoria/DialogoImportarApus.tsx web/src/components/autoria/SeccionSubApus.test.tsx
git commit -m "feat(web): vista previa del import muestra 'Sub-APUs detectados' (origen lote/biblioteca)"
```

---

## Verificación final

- [ ] `python -m pytest tests/ -q` verde; desde `web/`: `npx tsc --noEmit`, `npx vitest run`, `npm run build` — verde/OK.
- [ ] La vista previa del import lista los sub-APUs detectados (origen lote/biblioteca) antes de confirmar.
- [ ] Al confirmar, esos componentes quedan `tipo='apu'` con turno correcto (sin correr `marcar-subapus`); un import solo de insumos no cambia (sin regresión).
- [ ] `marcar-subapus` (CLI) sigue disponible. Invariante #1 intacta.
