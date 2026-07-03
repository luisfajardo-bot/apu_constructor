# Importador unificado de insumos (upsert) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reemplazar los dos importadores de insumos (crear / precios) por uno solo que hace upsert: con nombre → identidad código+nombre (crea o actualiza); sin nombre → actualiza precio por código.

**Architecture:** La lógica vive en `apu_tool/servicio/autoria.py` (clasifica cada fila en crear/actualizar/ambigua/no_encontrada/invalida y aplica). Un par de endpoints (`/insumos/importar/preview`, `/insumos/importar`) y un diálogo/botón únicos. Se elimina el código crear-solo y precios-solo que queda sin uso. Adición inversa + refactor quirúrgico.

**Tech Stack:** Python + FastAPI + openpyxl (backend); React + TypeScript + Vitest (frontend).

## Global Constraints

- **Invariante #1:** la IA nunca ve dinero. Esto es catálogo; NO toca el camino de la IA.
- **Español** en dominio/comentarios/mensajes.
- **Auditoría:** crear y actualizar registran vía `registrar_auditoria` (como hoy).
- **No tocar** `aplicar_cambios` (edición en tabla), corridas, ni el importador de APUs.
- Comando pruebas backend: `python -m pytest tests/ -q`. Frontend (desde `web/`): `npm run test`, `npm run build`, `npm run lint`.
- Identidad del sistema = `codigo` + `normalizar(nombre)` (`apu_tool.nucleo.texto.normalizar`).

---

### Task 1: Backend — servicio upsert en `autoria.py` + tests de servicio

**Files:**
- Modify: `apu_tool/servicio/autoria.py`
- Test: `tests/test_servicio_autoria.py`

**Interfaces:**
- Consumes: `_to_float`, `_norm_h` (de `insumos.py`, ya importados); `normalizar`; `alm.precios.get_candidatos/crear_insumo/set_precio_por_id/get_insumo_por_id`; `registrar_auditoria`, `nuevo_lote`; `Insumo`.
- Produces:
  - `preview_importar_insumos(alm, contenido: bytes, nombre_archivo: str) -> {crear, actualizar, ambigua, no_encontrada, invalida}`
  - `aplicar_importar_insumos(alm, contenido: bytes, nombre_archivo: str, actor=None) -> {creados, actualizados, errores}`

- [ ] **Step 1: Write the failing tests** — reescribe la sección "import insumos" de `tests/test_servicio_autoria.py`.

Reemplaza `_xlsx_insumos` y `test_import_insumos_preview_y_aplicar` (líneas ~64-83) por:

```python
def _xlsx_upsert() -> bytes:
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["codigo", "nombre", "unidad", "grupo", "precio", "fuente"])
    ws.append(["300", "GRAVA COMUN", "M3", "MAT", 80000, "PRECIO IDU"])   # con nombre, no existe -> crear
    ws.append(["100", "CEMENTO GRIS", "KG", "MAT", 1200, "PRECIO IDU"])   # con nombre, existe -> actualizar
    ws.append(["", "SIN CODIGO", "UN", "", 10, ""])                       # sin codigo -> invalida
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def _xlsx_solo_precio(filas) -> bytes:
    """Archivo estilo lista de precios: codigo, precio (sin nombre)."""
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["codigo", "precio", "fuente"])
    for f in filas:
        ws.append(f)
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def test_upsert_preview_con_nombre(tmp_path):
    alm = _alm(tmp_path)
    prev = autoria.preview_importar_insumos(alm, _xlsx_upsert(), "insumos.xlsx")
    assert [c["codigo"] for c in prev["crear"]] == ["300"]
    assert [c["codigo"] for c in prev["actualizar"]] == ["100"]
    assert prev["actualizar"][0]["precio_actual"] == 1000 and prev["actualizar"][0]["precio_nuevo"] == 1200
    assert len(prev["invalida"]) == 1


def test_upsert_aplicar_crea_y_actualiza(tmp_path):
    alm = _alm(tmp_path)
    res = autoria.aplicar_importar_insumos(alm, _xlsx_upsert(), "insumos.xlsx")
    assert res["creados"] == 1 and res["actualizados"] == 1
    assert any(i.codigo == "300" for i in alm.precios.get_candidatos("300"))
    assert alm.precios.get_candidatos("100")[0].precio == 1200   # precio actualizado


def test_upsert_sin_nombre_codigo_unico_actualiza(tmp_path):
    alm = _alm(tmp_path)
    prev = autoria.preview_importar_insumos(alm, _xlsx_solo_precio([["100", 1500, "COMPRAS"]]),
                                            "precios.xlsx")
    assert len(prev["actualizar"]) == 1 and prev["actualizar"][0]["precio_nuevo"] == 1500
    assert prev["crear"] == [] and prev["no_encontrada"] == []


def test_upsert_sin_nombre_codigo_repetido_ambiguo(tmp_path):
    alm = _alm(tmp_path)
    # dos insumos con el mismo código, distinto nombre
    alm.precios.insert_insumos([
        Insumo("100", "CEMENTO BLANCO", "KG", "MAT", 2000, "PRECIO IDU")])
    prev = autoria.preview_importar_insumos(alm, _xlsx_solo_precio([["100", 1500, "X"]]),
                                            "precios.xlsx")
    assert len(prev["ambigua"]) == 1 and prev["ambigua"][0]["codigo"] == "100"
    assert len(prev["ambigua"][0]["candidatos"]) == 2


def test_upsert_sin_nombre_codigo_inexistente_no_encontrada(tmp_path):
    alm = _alm(tmp_path)
    prev = autoria.preview_importar_insumos(alm, _xlsx_solo_precio([["999", 1500, "X"]]),
                                            "precios.xlsx")
    assert [n["codigo"] for n in prev["no_encontrada"]] == ["999"]


def test_upsert_precio_vacio_en_actualizacion_no_cambia(tmp_path):
    alm = _alm(tmp_path)
    prev = autoria.preview_importar_insumos(alm, _xlsx_solo_precio([["100", "", "NUEVA FUENTE"]]),
                                            "precios.xlsx")
    c = prev["actualizar"][0]
    assert c["precio_nuevo"] == 1000            # precio actual, no 0
    assert c["fuente_nueva"] == "NUEVA FUENTE"  # la fuente sí se cambia
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_servicio_autoria.py -q`
Expected: FAIL (el preview aún devuelve `ya_existe`, no `actualizar`; y `aplicar` no devuelve `actualizados`).

- [ ] **Step 3: Write the implementation** — en `apu_tool/servicio/autoria.py`.

3a. Relaja `_filas_insumos` para aceptar archivos sin columna de nombre y conservar si el precio venía informado. Reemplaza el cuerpo desde `if ci["codigo"] is None ...` hasta el `return out`:

```python
    if ci["codigo"] is None:
        raise ValueError("El archivo debe tener al menos una columna de código.")

    def g(r, i):
        return r[i] if (i is not None and i < len(r)) else None

    out = []
    for r in rows[1:]:
        raw_precio = g(r, ci["precio"])
        out.append({"codigo": str(g(r, ci["codigo"]) or "").strip(),
                    "nombre": str(g(r, ci["nombre"]) or "").strip(),
                    "unidad": str(g(r, ci["unidad"]) or "").strip(),
                    "grupo": str(g(r, ci["grupo"]) or "").strip(),
                    "precio": _to_float(raw_precio),
                    "tiene_precio": raw_precio not in (None, ""),
                    "fuente": str(g(r, ci["fuente"]) or "").strip()})
    return out
```

3b. Reemplaza `_existe_identidad`, `preview_importar_insumos` y `aplicar_importar_insumos` por:

```python
def _match_identidad(alm: Almacen, codigo: str, nombre: str):
    """Insumo con (codigo, nombre) exactos (nombre normalizado), o None."""
    nn = normalizar(nombre)
    for c in alm.precios.get_candidatos(codigo):
        if normalizar(c.nombre) == nn:
            return c
    return None


def _cambio_upsert(ins, f: dict) -> dict:
    precio_nuevo = f["precio"] if f["tiene_precio"] else ins.precio
    fuente_nueva = f["fuente"] or ins.fuente_precio
    return {"insumo_id": ins.id, "codigo": ins.codigo, "nombre": ins.nombre,
            "precio_actual": ins.precio, "precio_nuevo": precio_nuevo,
            "fuente_actual": ins.fuente_precio, "fuente_nueva": fuente_nueva}


def preview_importar_insumos(alm: Almacen, contenido: bytes, nombre_archivo: str) -> dict:
    """Upsert por fila. Con nombre: identidad código+nombre (crea o actualiza).
    Sin nombre: actualiza precio por código (único), o marca ambigua/no encontrada."""
    crear, actualizar, ambigua, no_encontrada, invalida = [], [], [], [], []
    for f in _filas_insumos(contenido, nombre_archivo):
        cod, nom = f["codigo"], f["nombre"]
        if not cod:
            invalida.append(f)
        elif nom:
            match = _match_identidad(alm, cod, nom)
            (actualizar.append(_cambio_upsert(match, f)) if match else crear.append(f))
        else:
            cands = alm.precios.get_candidatos(cod)
            if len(cands) == 1:
                actualizar.append(_cambio_upsert(cands[0], f))
            elif len(cands) > 1:
                ambigua.append({"codigo": cod,
                                "candidatos": [{"id": c.id, "nombre": c.nombre} for c in cands]})
            else:
                no_encontrada.append({"codigo": cod})
    return {"crear": crear, "actualizar": actualizar, "ambigua": ambigua,
            "no_encontrada": no_encontrada, "invalida": invalida}


def aplicar_importar_insumos(alm: Almacen, contenido: bytes, nombre_archivo: str,
                             actor=None) -> dict:
    prev = preview_importar_insumos(alm, contenido, nombre_archivo)
    creados, actualizados, errores = 0, 0, []
    lote = nuevo_lote()
    for f in prev["crear"]:
        try:
            ins = Insumo(codigo=f["codigo"], nombre=f["nombre"], unidad=f["unidad"],
                         grupo=f["grupo"], precio=f["precio"], fuente_precio=f["fuente"])
            with alm.transaccion("precios") as conn:
                iid = alm.precios.crear_insumo(ins, conn=conn,
                                               creado_por=(actor.user_id if actor else None))
                registrar_auditoria(
                    alm, conn, actor, "insumo.crear", "insumo", iid, antes=None,
                    despues={"codigo": ins.codigo, "nombre": ins.nombre, "unidad": ins.unidad,
                             "grupo": ins.grupo, "precio": ins.precio, "fuente": ins.fuente_precio},
                    contexto={"origen": "import", "lote_id": lote, "archivo": nombre_archivo})
            creados += 1
        except ValueError as e:
            errores.append({"codigo": f["codigo"], "error": str(e)})
    for c in prev["actualizar"]:
        if c["precio_nuevo"] == c["precio_actual"] and c["fuente_nueva"] == c["fuente_actual"]:
            continue                                   # no-op: nada cambió
        try:
            with alm.transaccion("precios") as conn:
                alm.precios.set_precio_por_id(c["insumo_id"], c["precio_nuevo"], c["fuente_nueva"],
                                              conn=conn,
                                              creado_por=(actor.user_id if actor else None))
                registrar_auditoria(
                    alm, conn, actor, "precio.editar", "insumo", c["insumo_id"],
                    antes={"precio": c["precio_actual"], "fuente": c["fuente_actual"]},
                    despues={"precio": c["precio_nuevo"], "fuente": c["fuente_nueva"]},
                    contexto={"origen": "import", "lote_id": lote, "archivo": nombre_archivo})
            actualizados += 1
        except Exception as e:
            errores.append({"codigo": c["codigo"], "error": str(e)})
    return {"creados": creados, "actualizados": actualizados, "errores": errores}
```

(Elimina la función `_existe_identidad` anterior: queda reemplazada por `_match_identidad`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_servicio_autoria.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/autoria.py tests/test_servicio_autoria.py
git commit -m "feat(autoria): importador de insumos unificado (upsert por fila)"
```

---

### Task 2: Backend — plantilla unificada

**Files:**
- Modify: `apu_tool/servicio/plantillas.py`
- Test: `tests/test_plantillas.py`

**Interfaces:**
- Produces: `plantilla_insumos() -> bytes` (reemplaza a `plantilla_insumos_crear`). Se elimina `plantilla_precios`.

- [ ] **Step 1: Update tests** — en `tests/test_plantillas.py`:

Reemplaza `test_plantilla_insumos_round_trip` y elimina `test_plantilla_precios_round_trip`:

```python
def test_plantilla_insumos_round_trip(tmp_path):
    from apu_tool.servicio import autoria
    alm = _alm(tmp_path)
    pv = autoria.preview_importar_insumos(alm, plantillas.plantilla_insumos(),
                                          "plantilla_insumos.xlsx")
    # la plantilla trae una fila con nombre (crear) y una sin nombre existente (actualizar)
    assert any(f["codigo"] == "EJEMPLO-1" for f in pv["crear"])
```

En `test_plantillas_abren_como_workbook_valido`, cambia la tupla de generadores a:

```python
    for gen in (plantillas.plantilla_apus, plantillas.plantilla_insumos):
```

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_plantillas.py -q`
Expected: FAIL (`plantilla_insumos` no existe / `plantilla_precios` referenciada).

- [ ] **Step 3: Implementation** — en `apu_tool/servicio/plantillas.py`, reemplaza `plantilla_insumos_crear` y `plantilla_precios` por una sola:

```python
def plantilla_insumos() -> bytes:
    """Plantilla del importador unificado. Columnas: codigo, nombre, unidad, grupo,
    precio, fuente. Con nombre crea o actualiza (por identidad); sin nombre solo
    actualiza precio por código."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["codigo", "nombre", "unidad", "grupo", "precio", "fuente"])
    ws.append(["EJEMPLO-1", "EJEMPLO — con nombre se crea o actualiza",
               "KG", "MAT", 1000, "COTIZACIÓN"])
    ws.append(["EJEMPLO-2", "", "", "", 2000, "COTIZACIÓN"])  # sin nombre = solo actualizar precio
    return _a_bytes(wb)
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_plantillas.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/plantillas.py tests/test_plantillas.py
git commit -m "feat(plantillas): plantilla unificada de insumos (reemplaza crear/precios)"
```

---

### Task 3: Backend — endpoints unificados + limpieza de código muerto + tests de ruta

**Files:**
- Modify: `apu_tool/servicio/rutas.py`, `apu_tool/servicio/insumos.py`
- Test: `tests/test_api_autoria.py`, `tests/test_api_insumos.py`, `tests/test_servicio_insumos.py`

**Interfaces:**
- Produces: `POST /insumos/importar/preview`, `POST /insumos/importar`, `GET /insumos/importar/plantilla` (unificados). Se eliminan `/insumos/importar-crear`, `/insumos/importar-crear/preview`, `/insumos/importar-crear/plantilla`.

- [ ] **Step 1: Update tests**

En `tests/test_api_autoria.py`, reemplaza `test_import_insumos_endpoint` (usa `/insumos/importar-crear*`) por:

```python
def test_import_insumos_endpoint(tmp_path):
    cli, _ = _cli(tmp_path)
    data = _xlsx_insumos()
    pv = cli.post("/api/insumos/importar/preview",
                  files={"archivo": ("insumos.xlsx", data, _XLSX)})
    assert pv.status_code == 200
    assert [c["codigo"] for c in pv.json()["crear"]] == ["300"]
    assert [c["codigo"] for c in pv.json()["actualizar"]] == ["100"]   # existía -> actualizar
    ap = cli.post("/api/insumos/importar",
                  files={"archivo": ("insumos.xlsx", data, _XLSX)})
    assert ap.status_code == 200
    assert ap.json()["creados"] == 1 and ap.json()["actualizados"] == 1
```

(El `_xlsx_insumos` de `test_api_autoria.py` ya trae `["300",...]` (crear) y `["100","CEMENTO GRIS",...]` (existe → ahora actualizar); su tercera fila `["100"...]` duplicada de "ya existe" pasa a actualizar. Deja `_xlsx_insumos` como está.)

En `test_plantilla_insumos_crear_endpoint`, cambia la ruta:

```python
    r = cli.get("/api/insumos/importar/plantilla")
```

En `test_plantillas_requieren_editor`, deja solo rutas vigentes:

```python
    assert cli.get("/api/apus/importar/plantilla").status_code == 403
    assert cli.get("/api/insumos/importar/plantilla").status_code == 403
```

En `tests/test_api_insumos.py`, reemplaza `test_importar_preview` por (nueva forma de respuesta):

```python
def test_importar_preview(tmp_path):
    cli, _ = _cli(tmp_path)
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["CODIGO", "PRECIO", "FUENTE"]); ws.append(["100", 390000, "COMPRAS"])
    buf = io.BytesIO(); wb.save(buf)
    r = cli.post("/api/insumos/importar/preview",
                 files={"archivo": ("l.xlsx", buf.getvalue(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200
    # "100" existe y es único -> actualizar precio
    assert len(r.json()["actualizar"]) == 1
    assert r.json()["actualizar"][0]["precio_nuevo"] == 390000
```

En `tests/test_servicio_insumos.py`, elimina lo que prueba código que se remueve: las funciones `test_preview_import_reconocido_y_no_encontrado`, `test_preview_import_ambiguos`, `test_parse_tabla_sin_codigo_lanza_valueerror`, y los helpers `_xlsx_bytes` y `_xlsx_bytes_headers` (quedan sin uso). Conserva `_alm`, `test_listar_y_clasificacion`, `test_detalle_con_historial`, `test_aplicar_cambios_ok_y_errores`.

- [ ] **Step 2: Run to verify fail**

Run: `python -m pytest tests/test_api_autoria.py tests/test_api_insumos.py -q`
Expected: FAIL (rutas viejas 404 / forma de respuesta distinta).

- [ ] **Step 3: Implementation**

3a. En `apu_tool/servicio/rutas.py`, reemplaza el endpoint de preview de precios (`/insumos/importar/preview`, que llamaba a `insumos_svc.preview_import`) y AGREGA el de aplicar. Reemplaza el bloque de `insumos_importar_preview`:

```python
@router.post("/insumos/importar/preview")
async def insumos_importar_preview(archivo: UploadFile = File(...),
                                   alm: Almacen = Depends(get_almacen),
                                   _: object = Depends(requiere_rol("editor"))):
    contenido = await archivo.read()
    try:
        return autoria.preview_importar_insumos(alm, contenido, archivo.filename or "insumos.xlsx")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (zipfile.BadZipFile, InvalidFileException):
        raise HTTPException(status_code=400, detail="El archivo no es un Excel válido o está corrupto.")


@router.post("/insumos/importar")
async def insumos_importar(archivo: UploadFile = File(...),
                           alm: Almacen = Depends(get_almacen),
                           actor=Depends(requiere_rol("editor"))):
    contenido = await archivo.read()
    try:
        return autoria.aplicar_importar_insumos(alm, contenido, archivo.filename or "insumos.xlsx",
                                                actor=actor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (zipfile.BadZipFile, InvalidFileException):
        raise HTTPException(status_code=400, detail="El archivo no es un Excel válido o está corrupto.")
```

3b. En `rutas.py`, elimina los 3 endpoints crear-solo: `@router.post("/insumos/importar-crear/preview")`, `@router.post("/insumos/importar-crear")` y `@router.get("/insumos/importar-crear/plantilla")` (funciones `insumos_importar_crear_preview`, `insumos_importar_crear`, `insumos_crear_plantilla`).

3c. En `rutas.py`, cambia el endpoint de plantilla de precios para servir la unificada:

```python
@router.get("/insumos/importar/plantilla")
def insumos_plantilla(_: object = Depends(requiere_rol("editor"))):
    return _descarga_xlsx(plantillas_svc.plantilla_insumos(), "plantilla_insumos.xlsx")
```

3d. En `apu_tool/servicio/insumos.py`, elimina `preview_import`, `_parse_tabla` y `_cambio` (quedan sin uso). Conserva `_insumo_out`, `listar`, `detalle`, `aplicar_cambios`, `_norm_h`, `_to_float`.

- [ ] **Step 4: Run to verify pass + suite completa**

Run: `python -m pytest tests/ -q`
Expected: PASS (todos menos los skips de Postgres).

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/rutas.py apu_tool/servicio/insumos.py tests/test_api_autoria.py tests/test_api_insumos.py tests/test_servicio_insumos.py
git commit -m "feat(api): endpoints unificados de import de insumos + limpieza de flujos viejos"
```

---

### Task 4: Frontend — diálogo/botón/API unificados + eliminar los viejos

**Files:**
- Create: `web/src/components/insumos/DialogoImportarInsumos.tsx`
- Delete: `web/src/components/insumos/DialogoImportar.tsx`, `web/src/components/autoria/DialogoImportarCrearInsumos.tsx`
- Modify: `web/src/pages/Insumos.tsx`, `web/src/api/insumos.ts`, `web/src/api/autoria.ts`, `web/src/lib/tipos.ts`

**Interfaces:**
- Consumes: endpoints unificados (Task 3); `descargarArchivo` (ya en client.ts); `Button`, `Dialog*`, `toast`.
- Produces: `previewImportarInsumos(form)`, `aplicarImportarInsumos(form)`, `descargarPlantillaInsumos()` (en `insumos.ts`); tipo `ImportInsumosUpsertPreview` y `ImportUpsertResultado` (en tipos.ts).

- [ ] **Step 1: Tipos** — en `web/src/lib/tipos.ts`, reemplaza `ImportarPreviewResponse` por:

```ts
export interface ImportInsumosUpsertPreview {
  crear: InsumoImportFila[];
  actualizar: CambioPreview[];
  ambigua: ImportAmbiguo[];
  no_encontrada: { codigo: string }[];
  invalida: InsumoImportFila[];
}

export interface ImportUpsertResultado {
  creados: number;
  actualizados: number;
  errores: { codigo: string; error: string }[];
}
```

(Conserva `CambioPreview`, `ImportAmbiguo`, `InsumoImportFila`. `ImportNoEncontrado` queda sin uso → elimínalo.)

- [ ] **Step 2: API** — en `web/src/api/insumos.ts`:

Cambia el import de tipos (quita `ImportarPreviewResponse`, agrega los nuevos) y reemplaza `importarPreview`:

```ts
import { apiGet, apiPost, descargarArchivo } from "@/api/client";
import type {
  ListaInsumos,
  InsumoDetalle,
  CambiosAplicados,
  ImportInsumosUpsertPreview,
  ImportUpsertResultado,
} from "@/lib/tipos";
```

Reemplaza `importarPreview` y `descargarPlantillaPrecios` por:

```ts
export function previewImportarInsumos(form: FormData): Promise<ImportInsumosUpsertPreview> {
  return apiPost<ImportInsumosUpsertPreview>("/insumos/importar/preview", form);
}

export function aplicarImportarInsumos(form: FormData): Promise<ImportUpsertResultado> {
  return apiPost<ImportUpsertResultado>("/insumos/importar", form);
}

export function descargarPlantillaInsumos(): Promise<void> {
  return descargarArchivo("/insumos/importar/plantilla", "plantilla_insumos.xlsx");
}
```

En `web/src/api/autoria.ts`, elimina las funciones crear-solo `previewImportarInsumos`, `aplicarImportarInsumos` y `descargarPlantillaInsumos` (ahora viven en `insumos.ts`), y quita `ImportInsumosPreview` del import de tipos si queda sin uso. Conserva las de APUs.

- [ ] **Step 3: Diálogo unificado** — crea `web/src/components/insumos/DialogoImportarInsumos.tsx`:

```tsx
import { useRef, useState } from "react";
import { toast } from "sonner";
import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import type { ImportInsumosUpsertPreview } from "@/lib/tipos";
import {
  previewImportarInsumos, aplicarImportarInsumos, descargarPlantillaInsumos,
} from "@/api/insumos";
import { cop } from "@/lib/moneda";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAplicado: () => void;
}

type Estado =
  | { fase: "idle" }
  | { fase: "cargando" }
  | { fase: "preview"; prev: ImportInsumosUpsertPreview }
  | { fase: "aplicando" };

export function DialogoImportarInsumos({ open, onOpenChange, onAplicado }: Props) {
  const fileRef = useRef<HTMLInputElement>(null);
  const archivoRef = useRef<File | null>(null);
  const [estado, setEstado] = useState<Estado>({ fase: "idle" });
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  function resetear() {
    setEstado({ fase: "idle" });
    setErrorMsg(null);
    archivoRef.current = null;
    if (fileRef.current) fileRef.current.value = "";
  }

  function handleOpenChange(v: boolean) {
    if (!v) resetear();
    onOpenChange(v);
  }

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const archivo = e.target.files?.[0];
    if (!archivo) return;
    archivoRef.current = archivo;
    setErrorMsg(null);
    setEstado({ fase: "cargando" });
    try {
      const form = new FormData();
      form.append("archivo", archivo);
      const prev = await previewImportarInsumos(form);
      setEstado({ fase: "preview", prev });
    } catch (e: unknown) {
      setErrorMsg(e instanceof Error ? e.message : "Error al procesar el archivo");
      setEstado({ fase: "idle" });
    }
  }

  async function bajarPlantilla() {
    try {
      await descargarPlantillaInsumos();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "No se pudo descargar la plantilla.");
    }
  }

  async function aplicar() {
    if (estado.fase !== "preview") return;
    const archivo = archivoRef.current;
    if (!archivo) return;
    setEstado({ fase: "aplicando" });
    try {
      const form = new FormData();
      form.append("archivo", archivo);
      const res = await aplicarImportarInsumos(form);
      const errCount = res.errores?.length ?? 0;
      const resumen = `${res.creados} creado(s), ${res.actualizados} actualizado(s)`;
      if (errCount === 0) toast.success(resumen);
      else toast.warning(`${resumen}, ${errCount} error(es): ` +
        res.errores.map((er) => `${er.codigo}: ${er.error}`).join("; "));
      handleOpenChange(false);
      onAplicado();
    } catch (e: unknown) {
      toast.error(`No se pudo aplicar: ${e instanceof Error ? e.message : "error"}`);
      setEstado({ fase: "idle" });
    }
  }

  const enPreview = estado.fase === "preview";
  const enAplicando = estado.fase === "aplicando";
  const prev = enPreview ? estado.prev : null;
  const nAcciones = prev ? prev.crear.length + prev.actualizar.length : 0;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle className="text-sm">Importar insumos (crear + actualizar precios)</DialogTitle>
        </DialogHeader>

        <p className="text-xs text-muted-foreground">
          Con nombre: crea el insumo o, si ya existe, actualiza su precio. Sin nombre: solo
          actualiza el precio por código.
        </p>

        <div className="flex items-center gap-3">
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx,.xls,.csv"
            onChange={handleFileChange}
            disabled={estado.fase === "cargando" || enAplicando}
            className="text-xs file:mr-2 file:rounded file:border file:border-border file:bg-muted file:px-2 file:py-0.5 file:text-xs file:font-medium file:cursor-pointer cursor-pointer disabled:opacity-50"
          />
          {estado.fase === "cargando" && (
            <span className="text-xs text-muted-foreground animate-pulse">procesando…</span>
          )}
          <Button size="sm" variant="outline" type="button" onClick={bajarPlantilla}
                  disabled={enAplicando} className="ml-auto">
            <Download className="mr-1 h-3.5 w-3.5" />
            Descargar plantilla
          </Button>
        </div>

        {errorMsg && <p className="text-xs text-destructive">{errorMsg}</p>}

        {prev && (
          <div className="space-y-3">
            <Seccion titulo="Crear">
              <Tabla cols={["Código", "Nombre", "Und", "Grupo", "Precio", "Fuente"]}
                     filas={prev.crear.map((f) => [f.codigo, f.nombre, f.unidad, f.grupo, cop(f.precio), f.fuente])} />
            </Seccion>
            <Seccion titulo="Actualizar precio">
              <Tabla cols={["Código", "Nombre", "Precio actual", "Precio nuevo", "Fuente nueva"]}
                     filas={prev.actualizar.map((c) => [c.codigo, c.nombre, cop(c.precio_actual), cop(c.precio_nuevo), c.fuente_nueva])} />
            </Seccion>
            <Seccion titulo="Ambiguas (código repetido, sin nombre)">
              <Tabla cols={["Código", "Candidatos"]}
                     filas={prev.ambigua.map((a) => [a.codigo, a.candidatos.map((c) => c.nombre).join(" · ")])} />
            </Seccion>
            <Seccion titulo="No encontradas (sin nombre, código inexistente)">
              <Tabla cols={["Código"]} filas={prev.no_encontrada.map((n) => [n.codigo])} />
            </Seccion>
            <Seccion titulo="Inválidas (sin código)">
              <Tabla cols={["Nombre"]} filas={prev.invalida.map((f) => [f.nombre])} />
            </Seccion>
          </div>
        )}

        <DialogFooter>
          <Button size="sm" variant="outline" onClick={() => handleOpenChange(false)} disabled={enAplicando}>
            Cancelar
          </Button>
          <Button size="sm" onClick={aplicar} disabled={!enPreview || nAcciones === 0 || enAplicando}>
            {enAplicando ? "Aplicando…" : `Aplicar (${nAcciones})`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Seccion({ titulo, children }: { titulo: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-xs font-semibold mb-1">{titulo}</p>
      {children}
    </div>
  );
}

function Tabla({ cols, filas }: { cols: string[]; filas: (string | number)[][] }) {
  if (filas.length === 0) return <p className="text-xs text-muted-foreground">Ninguno</p>;
  return (
    <div className="overflow-auto max-h-40 border rounded">
      <table className="w-full text-xs border-collapse">
        <thead className="sticky top-0 bg-muted/80 backdrop-blur z-10">
          <tr>
            {cols.map((c) => (
              <th key={c} className="px-2 py-1 text-left font-medium text-muted-foreground border-b">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {filas.map((fila, i) => (
            <tr key={i} className="hover:bg-muted/40 even:bg-muted/10">
              {fila.map((v, j) => (
                <td key={j} className="px-2 py-0.5">{v}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 4: Página** — en `web/src/pages/Insumos.tsx`:

Reemplaza los imports de los dos diálogos por el unificado:

```tsx
import { DialogoImportarInsumos } from "@/components/insumos/DialogoImportarInsumos";
```

(Quita `import { DialogoImportar } ...` y `import { DialogoImportarCrearInsumos } ...`.)

Reemplaza los dos estados `importarOpen`/`importarCrearOpen` por uno:

```tsx
  const [importarOpen, setImportarOpen] = useState(false);
```

(Quita la línea de `importarCrearOpen`.)

Reemplaza los dos botones ("Importar para crear" y "Importar") por uno solo. Sustituye el bloque de esos dos `<Button>`:

```tsx
            <Button
              size="xs"
              variant="outline"
              onClick={() => setImportarOpen(true)}
            >
              Importar
            </Button>
```

Reemplaza el render de los dos diálogos (`<DialogoImportar .../>` y `<DialogoImportarCrearInsumos .../>`) por:

```tsx
          <DialogoImportarInsumos
            open={importarOpen}
            onOpenChange={setImportarOpen}
            onAplicado={recargar}
          />
```

- [ ] **Step 5: Eliminar los diálogos viejos**

```bash
git rm web/src/components/insumos/DialogoImportar.tsx web/src/components/autoria/DialogoImportarCrearInsumos.tsx
```

- [ ] **Step 6: Typecheck + build + tests + lint**

Run (desde `web/`):
```bash
npm run build
npm run test
npm run lint
```
Expected: build sin errores; tests PASS; lint sin errores nuevos.

- [ ] **Step 7: Commit**

```bash
git add web/src/components/insumos/DialogoImportarInsumos.tsx web/src/pages/Insumos.tsx web/src/api/insumos.ts web/src/api/autoria.ts web/src/lib/tipos.ts
git commit -m "feat(web): diálogo/botón/API unificados de import de insumos; elimina los dos viejos"
```

---

## Self-Review

**Spec coverage:**
- Upsert por fila con 5 buckets → Task 1 (servicio) + Task 4 (UI). ✅
- Matching híbrido (con/sin nombre) + regla precio-vacío → Task 1 (`_match_identidad`, `_cambio_upsert`, `tiene_precio`). ✅
- Reemplazo de los dos importadores (un botón/diálogo/endpoint/plantilla) → Tasks 2-4. ✅
- Eliminar código muerto (`preview_import`/`_parse_tabla`/`_cambio`, diálogos viejos, funciones API) → Tasks 3-4. ✅
- Auditoría en crear+actualizar → Task 1. ✅
- Round-trip de plantilla + tests de ruta + 403 → Tasks 2-3. ✅
- No tocar `aplicar_cambios`, corridas, APUs, Invariante #1 → respetado. ✅

**Placeholder scan:** sin TBD/TODO; código completo en cada paso. ✅

**Type consistency:** `preview_importar_insumos`/`aplicar_importar_insumos` (Task 1) consumidos por endpoints (Task 3) y API frontend (Task 4) con las mismas formas `{crear, actualizar, ambigua, no_encontrada, invalida}` y `{creados, actualizados, errores}`. `plantilla_insumos` (Task 2) usada por el endpoint (Task 3). `ImportInsumosUpsertPreview`/`ImportUpsertResultado` (Task 4 tipos) usados por la API y el diálogo. ✅

**Orden de rutas:** `/insumos/importar` y `/insumos/importar/preview` no chocan con `/insumos/{insumo_id}` (más segmentos / distinto método). `/insumos/importar/plantilla` ya existía en esa posición. ✅
