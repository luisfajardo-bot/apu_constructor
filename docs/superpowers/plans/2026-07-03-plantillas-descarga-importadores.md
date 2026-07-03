# Plantillas de descarga para importadores — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un botón "Descargar plantilla" junto a cada control de importación (APUs, insumos nuevos, actualización de precios) que entrega un `.xlsx` con el formato exacto del parser.

**Architecture:** Las plantillas se generan al vuelo en el backend con openpyxl, usando las mismas columnas/constantes que el parser (imposible desincronizar). 3 endpoints GET (rol `editor`) las sirven; el frontend las descarga con un helper autenticado reutilizable y las expone con un botón en cada diálogo de importar. Adición pura: no se modifica ningún parser ni endpoint existente.

**Tech Stack:** Python + FastAPI + openpyxl (backend); React + TypeScript + Vitest (frontend). Iconos: `lucide-react`.

## Global Constraints

- **Invariante #1:** la IA nunca ve dinero. Estas plantillas son catálogo y NO tocan el camino de la IA. No agregar nada al payload de IA.
- **Persistencia solo en `db.py`/repos:** este trabajo no persiste nada (generación en memoria).
- **Español** en nombres de dominio, comentarios y mensajes de usuario.
- **Sin dependencias nuevas:** openpyxl y lucide-react ya están en el proyecto.
- **Adición pura:** no modificar parsers ni endpoints de import existentes.
- Comando de pruebas backend: `python -m pytest tests/ -q` (desde la raíz).
- Comandos frontend (desde `web/`): test `npm run test`, typecheck+build `npm run build`.

---

### Task 1: Backend — módulo `plantillas.py` (generadores) + round-trip tests

**Files:**
- Create: `apu_tool/servicio/plantillas.py`
- Test: `tests/test_plantillas.py`

**Interfaces:**
- Consumes: `apu_tool.datos.seed.APUS_COLS` (dict de posiciones) y `APUS_SHEET` ("APUS"); `apu_tool.servicio.autoria.preview_importar_apus`, `preview_importar_insumos`; `apu_tool.servicio.insumos._parse_tabla`.
- Produces (lo que usan Task 2 y los tests):
  - `plantilla_apus() -> bytes`
  - `plantilla_insumos_crear() -> bytes`
  - `plantilla_precios() -> bytes`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_plantillas.py`:

```python
"""Plantillas de importación: round-trip contra su propio parser (candado anti-drift)."""
import io

import openpyxl

from apu_tool.datos.almacen import Almacen
from apu_tool.servicio import plantillas


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def test_plantillas_abren_como_workbook_valido():
    for gen in (plantillas.plantilla_apus, plantillas.plantilla_insumos_crear,
                plantillas.plantilla_precios):
        data = gen()
        assert data, f"{gen.__name__} devolvió vacío"
        wb = openpyxl.load_workbook(io.BytesIO(data))
        wb.close()
    wb = openpyxl.load_workbook(io.BytesIO(plantillas.plantilla_apus()))
    assert "APUS" in wb.sheetnames  # el parser exige la hoja 'APUS'
    wb.close()


def test_plantilla_apus_round_trip(tmp_path):
    from apu_tool.servicio import autoria
    alm = _alm(tmp_path)
    pv = autoria.preview_importar_apus(alm, plantillas.plantilla_apus())
    apus = pv["crear"] + pv["ya_existe"]
    assert len(apus) == 1
    assert apus[0]["codigo"] == "999001"
    assert apus[0]["n_componentes"] == 2


def test_plantilla_insumos_round_trip(tmp_path):
    from apu_tool.servicio import autoria
    alm = _alm(tmp_path)
    pv = autoria.preview_importar_insumos(alm, plantillas.plantilla_insumos_crear(),
                                          "plantilla_insumos.xlsx")
    codigos = [f["codigo"] for f in pv["crear"]]
    assert "EJEMPLO-1" in codigos


def test_plantilla_precios_round_trip():
    from apu_tool.servicio.insumos import _parse_tabla
    filas = _parse_tabla(plantillas.plantilla_precios(), "plantilla_precios.xlsx")
    assert len(filas) == 1
    assert filas[0]["codigo"] == "EJEMPLO-1"
    assert filas[0]["precio"] == 1000.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_plantillas.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'apu_tool.servicio.plantillas'`.

- [ ] **Step 3: Write the implementation**

Create `apu_tool/servicio/plantillas.py`:

```python
"""Generación de plantillas .xlsx para los importadores (APUs, insumos, precios).

Cada plantilla se arma al vuelo con openpyxl usando las MISMAS columnas que espera
el parser correspondiente, de modo que plantilla y parser no puedan desincronizarse
(ver tests/test_plantillas.py: round-trip). NO toca la IA (Invariante #1: catálogo).
"""
from __future__ import annotations

import io

import openpyxl

from apu_tool.datos.seed import APUS_COLS, APUS_SHEET


def _a_bytes(wb) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# Encabezados de la hoja APUS en las posiciones que dicta APUS_COLS (sin drift).
_APUS_HEADERS = {
    APUS_COLS["actividad"]: "ACTIVIDAD",
    APUS_COLS["cod_idu"]: "COD IDU",
    APUS_COLS["unidad"]: "UN",
    APUS_COLS["insumo_nombre"]: "INSUMO",
    APUS_COLS["insumo_cod"]: "COD",
    APUS_COLS["insumo_und"]: "UND",
    APUS_COLS["rendimiento"]: "RENDIMIENTO",
    APUS_COLS["precio_unitario"]: "PRECIO UNITARIO",
    APUS_COLS["shift"]: "DIURNO/NOCTURNO",
}


def plantilla_apus() -> bytes:
    """Hoja 'APUS': fila de encabezados + 1 APU de ejemplo (encabezado + 2 componentes).

    El COD IDU del ejemplo es numérico ('999001') porque el parser detecta el
    encabezado de un APU con `_looks_like_code`.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = APUS_SHEET
    ancho = max(_APUS_HEADERS) + 1

    fila_h = [""] * ancho
    for i, txt in _APUS_HEADERS.items():
        fila_h[i] = txt
    ws.append(fila_h)

    fila_apu = [""] * ancho
    fila_apu[APUS_COLS["actividad"]] = "EJEMPLO — reemplazar por su actividad"
    fila_apu[APUS_COLS["cod_idu"]] = "999001"
    fila_apu[APUS_COLS["unidad"]] = "M2"
    fila_apu[APUS_COLS["shift"]] = "DIURNO"
    ws.append(fila_apu)

    for nombre, cod, und, rend in [
        ("EJEMPLO cemento gris", "6140", "KG", 0.5),
        ("EJEMPLO arena", "6200", "M3", 0.02),
    ]:
        fila_c = [""] * ancho
        fila_c[APUS_COLS["insumo_nombre"]] = nombre
        fila_c[APUS_COLS["insumo_cod"]] = cod
        fila_c[APUS_COLS["insumo_und"]] = und
        fila_c[APUS_COLS["rendimiento"]] = rend
        ws.append(fila_c)
    return _a_bytes(wb)


def plantilla_insumos_crear() -> bytes:
    """Tabla codigo, nombre, unidad, grupo, precio, fuente + 1 fila de ejemplo."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["codigo", "nombre", "unidad", "grupo", "precio", "fuente"])
    ws.append(["EJEMPLO-1", "EJEMPLO — reemplazar por el nombre del insumo",
               "KG", "MAT", 1000, "COTIZACIÓN"])
    return _a_bytes(wb)


def plantilla_precios() -> bytes:
    """Tabla codigo, precio, fuente + 1 fila de ejemplo."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["codigo", "precio", "fuente"])
    ws.append(["EJEMPLO-1", 1000, "COTIZACIÓN"])
    return _a_bytes(wb)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_plantillas.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/plantillas.py tests/test_plantillas.py
git commit -m "feat(plantillas): generadores xlsx con round-trip contra el parser"
```

---

### Task 2: Backend — 3 endpoints GET en `rutas.py` + tests de ruta

**Files:**
- Modify: `apu_tool/servicio/rutas.py` (imports + 3 endpoints)
- Test: `tests/test_api_autoria.py` (apus + insumos-crear + 403), `tests/test_api_insumos.py` (precios)

**Interfaces:**
- Consumes: `plantillas.plantilla_apus/plantilla_insumos_crear/plantilla_precios` (Task 1); `_XLSX`, `requiere_rol`, `router` (ya en `rutas.py`).
- Produces: `GET /apus/importar/plantilla`, `GET /insumos/importar-crear/plantilla`, `GET /insumos/importar/plantilla`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_api_autoria.py` (usa `_cli`, `cliente`, `create_app`, `Almacen`, `_XLSX` ya presentes en ese archivo):

```python
def test_plantilla_apus_endpoint(tmp_path):
    cli, _ = _cli(tmp_path)
    r = cli.get("/api/apus/importar/plantilla")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == _XLSX
    assert "attachment" in r.headers["content-disposition"]
    assert len(r.content) > 0
    # lo descargado es re-importable por su propio endpoint (round-trip end-to-end)
    pv = cli.post("/api/apus/importar/preview",
                  files={"archivo": ("plantilla_apus.xlsx", r.content, _XLSX)})
    assert pv.status_code == 200
    assert any(c["codigo"] == "999001" for c in pv.json()["crear"])


def test_plantilla_insumos_crear_endpoint(tmp_path):
    cli, _ = _cli(tmp_path)
    r = cli.get("/api/insumos/importar-crear/plantilla")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == _XLSX
    assert "attachment" in r.headers["content-disposition"]
    assert len(r.content) > 0


def test_plantillas_requieren_editor(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    cli = cliente(create_app(almacen=alm), rol="consulta")
    assert cli.get("/api/apus/importar/plantilla").status_code == 403
    assert cli.get("/api/insumos/importar-crear/plantilla").status_code == 403
    assert cli.get("/api/insumos/importar/plantilla").status_code == 403
```

Add to `tests/test_api_insumos.py` (usa `_cli`, `_XLSX`… `_XLSX` NO está en ese archivo, se define aquí):

```python
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_plantilla_precios_endpoint(tmp_path):
    cli, _ = _cli(tmp_path)
    r = cli.get("/api/insumos/importar/plantilla")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == _XLSX
    assert "attachment" in r.headers["content-disposition"]
    assert len(r.content) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_api_autoria.py -q tests/test_api_insumos.py -q`
Expected: FAIL — los `GET .../plantilla` devuelven 404 (o el de apus podría matchear `/apus/{codigo}/{turno}` → 404 "APU no encontrado").

- [ ] **Step 3: Write the implementation**

In `apu_tool/servicio/rutas.py`, add `Response` to the responses import (línea ~14):

```python
from fastapi.responses import FileResponse, Response, StreamingResponse
```

Add `plantillas` to the servicio imports (junto a los otros `from apu_tool.servicio import ...`):

```python
from apu_tool.servicio import plantillas as plantillas_svc
```

Add a helper (después de la línea `_XLSX = "..."`, ~línea 66):

```python
def _descarga_xlsx(data: bytes, filename: str) -> Response:
    return Response(content=data, media_type=_XLSX,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
```

Add the APUs endpoint **inmediatamente después** de `@router.post("/apus/importar")` (la función `apus_importar`, ~línea 367) y **antes** de `@router.get("/apus/{codigo}/{turno}")` — el orden importa: `/apus/{codigo}/{turno}` capturaría `/apus/importar/plantilla` si se declarara después:

```python
@router.get("/apus/importar/plantilla")
def apus_plantilla(_: object = Depends(requiere_rol("editor"))):
    return _descarga_xlsx(plantillas_svc.plantilla_apus(), "plantilla_apus.xlsx")
```

Add the insumos-crear endpoint después de `@router.post("/insumos/importar-crear")` (~línea 324):

```python
@router.get("/insumos/importar-crear/plantilla")
def insumos_crear_plantilla(_: object = Depends(requiere_rol("editor"))):
    return _descarga_xlsx(plantillas_svc.plantilla_insumos_crear(), "plantilla_insumos.xlsx")
```

Add the precios endpoint después de `@router.post("/insumos/importar/preview")` (~línea 279):

```python
@router.get("/insumos/importar/plantilla")
def insumos_precios_plantilla(_: object = Depends(requiere_rol("editor"))):
    return _descarga_xlsx(plantillas_svc.plantilla_precios(), "plantilla_precios.xlsx")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_api_autoria.py tests/test_api_insumos.py -q`
Expected: PASS (incluye los 4 tests nuevos).

- [ ] **Step 5: Run the full backend suite (no regressions)**

Run: `python -m pytest tests/ -q`
Expected: PASS (todos menos los skips habituales de Postgres).

- [ ] **Step 6: Commit**

```bash
git add apu_tool/servicio/rutas.py tests/test_api_autoria.py tests/test_api_insumos.py
git commit -m "feat(api): endpoints GET de plantilla para los 3 importadores (rol editor)"
```

---

### Task 3: Frontend — helper de descarga reutilizable + funciones de API + test

**Files:**
- Modify: `web/src/api/client.ts` (nuevo `descargarArchivo`)
- Modify: `web/src/api/autoria.ts` (`descargarPlantillaApus`, `descargarPlantillaInsumos`)
- Modify: `web/src/api/insumos.ts` (`descargarPlantillaPrecios`)
- Test: `web/src/api/plantillas.descarga.test.ts`

**Interfaces:**
- Consumes: los 3 endpoints GET (Task 2); `authHeader`, `BASE`, `supabase` (ya en `client.ts`).
- Produces:
  - `descargarArchivo(path: string, filename: string): Promise<void>` (client.ts)
  - `descargarPlantillaApus(): Promise<void>`, `descargarPlantillaInsumos(): Promise<void>` (autoria.ts)
  - `descargarPlantillaPrecios(): Promise<void>` (insumos.ts)

- [ ] **Step 1: Write the failing test**

Create `web/src/api/plantillas.descarga.test.ts`:

```ts
import { expect, test, vi, beforeEach } from "vitest";

vi.mock("@/lib/supabase", () => ({
  supabase: {
    auth: {
      getSession: vi.fn(async () => ({ data: { session: { access_token: "T" } } })),
      signOut: vi.fn(),
    },
  },
}));

beforeEach(() => {
  vi.restoreAllMocks();
});

test("descargarArchivo usa Bearer y dispara la descarga", async () => {
  const { descargarArchivo } = await import("./client");

  const fetchMock = vi.fn(async () => ({
    status: 200,
    ok: true,
    blob: async () => new Blob(["x"]),
  })) as unknown as typeof fetch;
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("URL", { createObjectURL: () => "blob:x", revokeObjectURL: () => {} });
  const click = vi.fn();
  vi.spyOn(document, "createElement").mockReturnValue({
    click, remove: () => {}, href: "", download: "",
  } as unknown as HTMLAnchorElement);
  vi.spyOn(document.body, "appendChild").mockImplementation((n) => n as never);

  await descargarArchivo("/apus/importar/plantilla", "plantilla_apus.xlsx");

  const [url, init] = (fetchMock as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
  expect(url).toBe("/api/apus/importar/plantilla");
  expect((init.headers as Record<string, string>).Authorization).toBe("Bearer T");
  expect(click).toHaveBeenCalled();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (desde `web/`): `npm run test -- plantillas.descarga`
Expected: FAIL — `descargarArchivo` no existe (no exportado por `./client`).

- [ ] **Step 3: Write the implementation**

In `web/src/api/client.ts`, add at the end (usa `BASE`, `authHeader`, `supabase` ya importados arriba):

```ts
/** Descarga un archivo protegido con el token Bearer (una navegación normal no lleva el header). */
export async function descargarArchivo(path: string, filename: string): Promise<void> {
  const r = await fetch(BASE + path, { headers: { ...(await authHeader()) } });
  if (r.status === 401) {
    await supabase.auth.signOut();
    throw new Error("Sesión expirada.");
  }
  if (!r.ok) {
    const err = await r.json().catch(() => ({}) as { detail?: string });
    throw new Error(err.detail || r.statusText);
  }
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
```

In `web/src/api/autoria.ts`, change the client import (línea 1) y añade dos funciones al final:

```ts
import { apiGet, apiPost, descargarArchivo } from "@/api/client";
```

```ts
export function descargarPlantillaApus(): Promise<void> {
  return descargarArchivo("/apus/importar/plantilla", "plantilla_apus.xlsx");
}

export function descargarPlantillaInsumos(): Promise<void> {
  return descargarArchivo("/insumos/importar-crear/plantilla", "plantilla_insumos.xlsx");
}
```

In `web/src/api/insumos.ts`, change the client import (línea 1) y añade una función al final:

```ts
import { apiGet, apiPost, descargarArchivo } from "@/api/client";
```

```ts
export function descargarPlantillaPrecios(): Promise<void> {
  return descargarArchivo("/insumos/importar/plantilla", "plantilla_precios.xlsx");
}
```

- [ ] **Step 4: Run test to verify it passes**

Run (desde `web/`): `npm run test -- plantillas.descarga`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/api/client.ts web/src/api/autoria.ts web/src/api/insumos.ts web/src/api/plantillas.descarga.test.ts
git commit -m "feat(web): helper descargarArchivo + funciones de descarga de plantillas"
```

---

### Task 4: Frontend — botón "Descargar plantilla" en los 3 diálogos

**Files:**
- Modify: `web/src/components/autoria/DialogoImportarApus.tsx`
- Modify: `web/src/components/autoria/DialogoImportarCrearInsumos.tsx`
- Modify: `web/src/components/insumos/DialogoImportar.tsx`

**Interfaces:**
- Consumes: `descargarPlantillaApus`, `descargarPlantillaInsumos` (autoria.ts), `descargarPlantillaPrecios` (insumos.ts); `Download` de `lucide-react`; `Button`, `toast` (ya importados en cada diálogo).
- Produces: UI (sin API nueva). Verificación por typecheck/build.

- [ ] **Step 1: `DialogoImportarApus.tsx`**

Añade imports:

```tsx
import { Download } from "lucide-react";
```

y agrega `descargarPlantillaApus` al import de `@/api/autoria`:

```tsx
import { previewImportarApus, aplicarImportarApus, descargarPlantillaApus } from "@/api/autoria";
```

Dentro del componente, antes del `return`, agrega el handler:

```tsx
  async function bajarPlantilla() {
    try {
      await descargarPlantillaApus();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "No se pudo descargar la plantilla.");
    }
  }
```

En la fila del input (`<div className="flex items-center gap-3">`, ~línea 116), agrega el botón como último hijo del div, después del `<input>` y el `<span>` de "procesando…":

```tsx
          <Button
            size="sm"
            variant="outline"
            type="button"
            onClick={bajarPlantilla}
            disabled={enAplicando}
            className="ml-auto"
          >
            <Download className="mr-1 h-3.5 w-3.5" />
            Descargar plantilla
          </Button>
```

- [ ] **Step 2: `DialogoImportarCrearInsumos.tsx`**

Añade imports:

```tsx
import { Download } from "lucide-react";
```

y agrega `descargarPlantillaInsumos` al import de `@/api/autoria`:

```tsx
import { previewImportarInsumos, aplicarImportarInsumos, descargarPlantillaInsumos } from "@/api/autoria";
```

Antes del `return`, agrega el handler:

```tsx
  async function bajarPlantilla() {
    try {
      await descargarPlantillaInsumos();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "No se pudo descargar la plantilla.");
    }
  }
```

En la fila del input (`<div className="flex items-center gap-3">`, ~línea 123), agrega como último hijo:

```tsx
          <Button
            size="sm"
            variant="outline"
            type="button"
            onClick={bajarPlantilla}
            disabled={enAplicando}
            className="ml-auto"
          >
            <Download className="mr-1 h-3.5 w-3.5" />
            Descargar plantilla
          </Button>
```

- [ ] **Step 3: `DialogoImportar.tsx`** (precios)

Añade imports:

```tsx
import { Download } from "lucide-react";
```

y agrega `descargarPlantillaPrecios` al import de `@/api/insumos`:

```tsx
import { aplicarCambios, importarPreview, descargarPlantillaPrecios } from "@/api/insumos";
```

Antes del `return`, agrega el handler:

```tsx
  async function bajarPlantilla() {
    try {
      await descargarPlantillaPrecios();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "No se pudo descargar la plantilla.");
    }
  }
```

En la fila del input (`<div className="flex items-center gap-3">`, ~línea 126), agrega como último hijo:

```tsx
          <Button
            size="sm"
            variant="outline"
            type="button"
            onClick={bajarPlantilla}
            disabled={enAplicando}
            className="ml-auto"
          >
            <Download className="mr-1 h-3.5 w-3.5" />
            Descargar plantilla
          </Button>
```

- [ ] **Step 4: Typecheck + build + tests + lint (no regressions)**

Run (desde `web/`):
```bash
npm run build
npm run test
npm run lint
```
Expected: build sin errores de tipos; tests PASS; lint sin errores nuevos.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/autoria/DialogoImportarApus.tsx web/src/components/autoria/DialogoImportarCrearInsumos.tsx web/src/components/insumos/DialogoImportar.tsx
git commit -m "feat(web): botón 'Descargar plantilla' en los 3 diálogos de importar"
```

---

## Self-Review

**Spec coverage:**
- Módulo `plantillas.py` con 3 generadores → Task 1. ✅
- 3 endpoints GET rol `editor` con `Content-Disposition` → Task 2. ✅
- 3 funciones de descarga frontend (clon/DRY de `descargarCuadro`) → Task 3. ✅
- Botón en cada uno de los 3 diálogos → Task 4. ✅
- Round-trip tests (candado) → Task 1; end-to-end round-trip vía endpoint → Task 2. ✅
- Tests de ruta (200, content-type, attachment, 403) → Task 2. ✅
- Test de descarga frontend → Task 3. ✅
- Invariante #1 / adición pura / sin cambios de esquema → respetado (no se tocan parsers/endpoints; sin DB). ✅

**Placeholder scan:** sin TBD/TODO; todo el código está presente. ✅

**Type consistency:** `descargarArchivo(path, filename)` definida en Task 3 y usada por las 3 funciones de API con esa firma; `plantilla_apus/plantilla_insumos_crear/plantilla_precios` definidas en Task 1 y consumidas en Task 2 con esos nombres exactos; endpoints con las mismas rutas en Task 2/Task 3. ✅

**Nota de orden de rutas:** `/apus/importar/plantilla` DEBE declararse antes de `/apus/{codigo}/{turno}` (Task 2, Step 3). Cubierto explícitamente.
