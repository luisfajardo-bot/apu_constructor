# Corridas: turno requerido, lista, vivo, composición — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Exigir turno por fila, agregar lista "mis corridas" con eliminar, dejar la corrida viva (re-costeo con precio vigente, sin bloqueo), y permitir desplegar la composición inline de cualquier ítem — sin tocar la lógica de matching/costeo.

**Architecture:** Backend: `read_licitacion` gana `require_turno` (retrocompatible); `CorridasDB` gana `listar_corridas`/`eliminar_corrida`; endpoints `GET /api/corridas` y `DELETE /api/corridas/{cid}`; los endpoints de armado piden `require_turno=True`. Frontend: `/corridas` pasa a ser la lista (formulario en `/corridas/nueva`); cada fila del cuadro se despliega inline mostrando su composición (unificando el panel de revisión).

**Tech Stack:** Python, FastAPI, SQLite; React/TS, Vite. Sin dependencias nuevas.

## Global Constraints

- **CERO regresiones.** No se toca la lógica de matching ni de costeo. El re-costeo (`_costear_row`/`cost_components`) no cambia.
- `read_licitacion` retrocompatible: `require_turno` por defecto `False`; otros llamadores sin cambio.
- Endpoints existentes (`POST /api/corridas`, `/sample`, `/corridas/stream`, `/sample/stream`, `GET /corridas/{cid}`, `/items/{seq}`, `confirmar`, `cuadro`) se conservan.
- Persistencia solo en `apu_tool/datos/`; sin SQL crudo fuera. Invariante #1: sin `ai_assist` en `servicio/`.
- UI densa, table-first, sin cards; imports `@/`.
- `python -m pytest tests/ -q` verde tras cada tarea de backend; frontend `npm run build` 0 errores TS.

---

## File Structure

```
apu_tool/dominio/licitacion.py     # + param require_turno en read_licitacion
apu_tool/datos/corridas_db.py      # + listar_corridas, eliminar_corrida (+ _row_to_meta)
apu_tool/datos/repositorio.py      # + esos métodos en RepositorioCorridas (Protocol)
apu_tool/servicio/corridas.py      # + svc.listar_corridas, svc.eliminar_corrida
apu_tool/servicio/rutas.py         # + GET /corridas, DELETE /corridas/{cid}; require_turno=True en armado
tests/test_licitacion_turno.py     # [nuevo]
tests/test_corridas_db.py          # + tests listar/eliminar
tests/test_api_corridas.py         # + tests GET lista, DELETE, 400 sin turno

web/src/lib/tipos.ts               # + CorridaResumen
web/src/api/corridas.ts            # + listarCorridas, eliminarCorrida
web/src/App.tsx                    # rutas: /corridas=lista, /corridas/nueva=form, /corridas/:id=cuadro
web/src/components/Layout.tsx      # nav "Corridas" -> /corridas
web/src/pages/MisCorridas.tsx      # [nuevo] lista + eliminar + nueva
web/src/pages/CorridasInicio.tsx   # quitar selector global de turno
web/src/components/corrida/TablaItems.tsx  # desplegable inline por fila (composición + candidatos/confirmar)
web/src/pages/Corrida.tsx          # pasa corridaId/onConfirmed; retira PanelRevision
web/src/components/corrida/PanelRevision.tsx  # se elimina (unificado en el desplegable)
```

---

## FASE BACKEND

### Task 1: `read_licitacion(require_turno=True)`

**Files:**
- Modify: `apu_tool/dominio/licitacion.py`
- Test: `tests/test_licitacion_turno.py`

**Interfaces:**
- Produces: `read_licitacion(path, default_shift=config.SHIFT_DIURNO, require_turno: bool = False) -> list[LicitacionItem]`. Con `require_turno=True`: lanza `ValueError` si no hay columna de turno o si alguna fila con descripción no resuelve a DIURNO/NOCTURNO.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_licitacion_turno.py
import openpyxl
import pytest
from apu_tool.dominio.licitacion import read_licitacion


def _xlsx(tmp_path, headers, filas):
    p = tmp_path / "lic.xlsx"
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(headers)
    for f in filas:
        ws.append(f)
    wb.save(p)
    return p


def test_require_turno_sin_columna(tmp_path):
    p = _xlsx(tmp_path, ["ITEM", "DESCRIPCION", "UNIDAD", "CANTIDAD", "PRECIO"],
              [["1", "Concreto", "M3", 10, 400000]])
    with pytest.raises(ValueError):
        read_licitacion(p, require_turno=True)


def test_require_turno_por_fila_ok(tmp_path):
    p = _xlsx(tmp_path, ["ITEM", "DESCRIPCION", "UNIDAD", "CANTIDAD", "PRECIO", "TURNO"],
              [["1", "Concreto", "M3", 10, 400000, "DIURNO"],
               ["2", "Excavacion", "M3", 5, 200000, "NOCTURNO"]])
    items = read_licitacion(p, require_turno=True)
    assert [it.shift for it in items] == ["DIURNO", "NOCTURNO"]


def test_require_turno_fila_sin_valor(tmp_path):
    p = _xlsx(tmp_path, ["ITEM", "DESCRIPCION", "UNIDAD", "CANTIDAD", "PRECIO", "TURNO"],
              [["1", "Concreto", "M3", 10, 400000, "DIURNO"],
               ["2", "Excavacion", "M3", 5, 200000, ""]])
    with pytest.raises(ValueError):
        read_licitacion(p, require_turno=True)


def test_sin_require_turno_retrocompatible(tmp_path):
    p = _xlsx(tmp_path, ["ITEM", "DESCRIPCION", "UNIDAD", "CANTIDAD", "PRECIO"],
              [["1", "Concreto", "M3", 10, 400000]])
    items = read_licitacion(p, default_shift="DIURNO")
    assert items and items[0].shift == "DIURNO"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_licitacion_turno.py -q`
Expected: FAIL (require_turno no existe / no se valida).

- [ ] **Step 3: Implement**

En `apu_tool/dominio/licitacion.py`, cambia la firma y agrega la validación. Reemplaza la cabecera de `read_licitacion` y su validación de columnas, y agrega la verificación por fila:

```python
def read_licitacion(path: Path | str, default_shift: str = config.SHIFT_DIURNO,
                    require_turno: bool = False) -> list[LicitacionItem]:
    path = Path(path)
    rows = _rows_from_xlsx(path) if path.suffix.lower() in (".xlsx", ".xlsm") \
        else _rows_from_csv(path)
    rows = [r for r in rows if any(c not in (None, "") for c in r)]
    if not rows:
        return []

    headers = [str(c) if c is not None else "" for c in rows[0]]
    mapping = _map_headers(headers)
    if "descripcion" not in mapping:
        raise ValueError(
            "No se encontró la columna de descripción/actividad en la lista. "
            f"Encabezados detectados: {headers}"
        )
    if require_turno and "shift" not in mapping:
        raise ValueError(
            "La lista debe incluir una columna de turno (DIURNO/NOCTURNO) por ítem.")

    items: list[LicitacionItem] = []
    sin_turno: list[str] = []
    for i, row in enumerate(rows[1:], start=1):
        def get(field, default=""):
            idx = mapping.get(field)
            if idx is None or idx >= len(row):
                return default
            return row[idx]

        desc = str(get("descripcion") or "").strip()
        if not desc:
            continue
        raw_turno = str(get("shift", "") or "").strip()
        if require_turno and _shift_value(raw_turno, "?") == "?":
            sin_turno.append(str(get("item", i) or i))
            continue
        shift = _shift_value(raw_turno, default_shift)
        items.append(LicitacionItem(
            item=str(get("item", i) or i).strip(),
            descripcion=desc,
            unidad=str(get("unidad", "") or "").strip(),
            cantidad=_to_float(get("cantidad", 1)) or 1.0,
            precio_contractual=_to_float(get("precio_contractual", 0)),
            shift=shift,
        ))
    if require_turno and sin_turno:
        raise ValueError(
            "Estos ítems no tienen turno (DIURNO/NOCTURNO): "
            + ", ".join(sin_turno[:20]))
    return items
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_licitacion_turno.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Run full suite (regresión)**

Run: `python -m pytest tests/ -q`
Expected: PASS (read_licitacion sin require_turno se comporta igual).

- [ ] **Step 6: Commit**

```bash
git add apu_tool/dominio/licitacion.py tests/test_licitacion_turno.py
git commit -m "feat(licitacion): require_turno por fila en read_licitacion (retrocompatible)"
```

---

### Task 2: `CorridasDB.listar_corridas` + `eliminar_corrida` + servicio

**Files:**
- Modify: `apu_tool/datos/corridas_db.py`, `apu_tool/datos/repositorio.py`, `apu_tool/servicio/corridas.py`
- Test: `tests/test_corridas_db.py` (se amplía)

**Interfaces:**
- Produces:
  - `CorridasDB.listar_corridas() -> list[CorridaMeta]` (orden `creada_en DESC, id DESC`)
  - `CorridasDB.eliminar_corrida(corrida_id: int) -> bool` (cascade borra `corrida_item`)
  - `svc.listar_corridas(alm) -> list[dict]` → por corrida `{id, archivo, creada_en, estado, n_items, n_revision}`
  - `svc.eliminar_corrida(alm, corrida_id) -> bool`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_corridas_db.py  (agregar; reutiliza _almacen_tmp y _fila ya existentes)
def test_listar_y_eliminar_corridas(tmp_path):
    alm = _almacen_tmp(tmp_path)
    c1 = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-06-25T10:00:00", archivo="a.xlsx",
        turno_def="DIURNO", use_ai=False, estado="en_revision"))
    c2 = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-06-25T11:00:00", archivo="b.xlsx",
        turno_def="DIURNO", use_ai=False, estado="en_revision"))
    alm.corridas.guardar_items(c2, [_fila(0)])

    metas = alm.corridas.listar_corridas()
    assert [m.id for m in metas] == [c2, c1]          # más reciente primero
    assert metas[0].archivo == "b.xlsx"

    assert alm.corridas.eliminar_corrida(c2) is True
    assert alm.corridas.get_corrida(c2) is None       # se fue
    assert alm.corridas.get_items(c2) == []           # cascade borró los ítems
    assert [m.id for m in alm.corridas.listar_corridas()] == [c1]
    assert alm.corridas.eliminar_corrida(99999) is False
```

(En el servicio, agrega también un test en `tests/test_servicio_corridas.py` reutilizando `_almacen_seed`:)

```python
# tests/test_servicio_corridas.py  (agregar)
def test_svc_listar_y_eliminar(tmp_path):
    alm = _almacen_seed(tmp_path)
    items = [LicitacionItem(item="1", descripcion="Concreto clase D", unidad="M3",
                            cantidad=10.0, precio_contractual=400000.0, shift="DIURNO")]
    cid = svc.construir_corrida(alm, "lic.xlsx", items, "DIURNO", False)
    lista = svc.listar_corridas(alm)
    assert lista and lista[0]["id"] == cid
    assert lista[0]["n_items"] == 1 and "creada_en" in lista[0]
    assert svc.eliminar_corrida(alm, cid) is True
    assert svc.listar_corridas(alm) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_corridas_db.py tests/test_servicio_corridas.py -q`
Expected: FAIL (`listar_corridas`/`eliminar_corrida` no existen).

- [ ] **Step 3: Implement — datos**

En `apu_tool/datos/corridas_db.py`, sección lectura, agrega un helper y los dos métodos (refactoriza `get_corrida` para reusar el helper — comportamiento idéntico):

```python
    def _row_to_meta(self, r: sqlite3.Row) -> CorridaMeta:
        return CorridaMeta(
            id=r["id"], creada_en=r["creada_en"], archivo=r["archivo"],
            turno_def=r["turno_def"],
            use_ai=None if r["use_ai"] is None else bool(r["use_ai"]),
            estado=r["estado"], cuadro_path=r["cuadro_path"])

    def get_corrida(self, corrida_id: int) -> Optional[CorridaMeta]:
        with self.connect() as conn:
            r = conn.execute("SELECT * FROM corrida WHERE id=?", (corrida_id,)).fetchone()
        return self._row_to_meta(r) if r else None

    def listar_corridas(self) -> list[CorridaMeta]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM corrida ORDER BY creada_en DESC, id DESC").fetchall()
        return [self._row_to_meta(r) for r in rows]

    def eliminar_corrida(self, corrida_id: int) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM corrida WHERE id=?", (int(corrida_id),))
            return cur.rowcount > 0
```

(Reemplaza el `get_corrida` actual por esta versión que usa `_row_to_meta`; el cuerpo es equivalente.)

En `apu_tool/datos/repositorio.py`, agrega a `RepositorioCorridas`:

```python
    def listar_corridas(self) -> list[CorridaMeta]: ...
    def eliminar_corrida(self, corrida_id: int) -> bool: ...
```

- [ ] **Step 4: Implement — servicio**

En `apu_tool/servicio/corridas.py`, agrega:

```python
def listar_corridas(alm: Almacen) -> list[dict]:
    out: list[dict] = []
    for meta in alm.corridas.listar_corridas():
        items = alm.corridas.get_items(meta.id)
        n_rev = sum(1 for it in items if it.status in ("review", "new"))
        out.append({"id": meta.id, "archivo": meta.archivo, "creada_en": meta.creada_en,
                    "estado": meta.estado, "n_items": len(items), "n_revision": n_rev})
    return out


def eliminar_corrida(alm: Almacen, corrida_id: int) -> bool:
    return alm.corridas.eliminar_corrida(corrida_id)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_corridas_db.py tests/test_servicio_corridas.py -q`
Expected: PASS. Luego `python -m pytest tests/ -q` → verde.

- [ ] **Step 6: Commit**

```bash
git add apu_tool/datos/corridas_db.py apu_tool/datos/repositorio.py apu_tool/servicio/corridas.py tests/test_corridas_db.py tests/test_servicio_corridas.py
git commit -m "feat(corridas): listar y eliminar corridas (datos + servicio)"
```

---

### Task 3: Endpoints `GET /api/corridas`, `DELETE /api/corridas/{cid}` + require_turno en armado

**Files:**
- Modify: `apu_tool/servicio/rutas.py`
- Test: `tests/test_api_corridas.py` (se amplía)

**Interfaces:**
- Consumes: `svc.listar_corridas`, `svc.eliminar_corrida`, `read_licitacion(require_turno=True)`.
- Produces: `GET /api/corridas` (lista) y `DELETE /api/corridas/{cid}` (404 si no existe). Los endpoints de armado por archivo (`/corridas`, `/corridas/stream`) pasan `require_turno=True`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_api_corridas.py  (agregar; reutiliza _cli, _xlsx_lic)
import openpyxl


def test_listar_corridas_endpoint(tmp_path):
    cli, _ = _cli(tmp_path)
    lic = _xlsx_lic(tmp_path)
    with open(lic, "rb") as f:
        cli.post("/api/corridas", data={"turno": "DIURNO", "use_ai": "false"},
                 files={"archivo": ("lic.xlsx", f,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    r = cli.get("/api/corridas")
    assert r.status_code == 200
    body = r.json()
    assert len(body) >= 1 and "creada_en" in body[0] and "n_items" in body[0]


def test_eliminar_corrida_endpoint(tmp_path):
    cli, _ = _cli(tmp_path)
    lic = _xlsx_lic(tmp_path)
    with open(lic, "rb") as f:
        cid = cli.post("/api/corridas", data={"turno": "DIURNO", "use_ai": "false"},
                       files={"archivo": ("lic.xlsx", f, "application/octet-stream")}).json()["id"]
    assert cli.delete(f"/api/corridas/{cid}").status_code == 200
    assert cli.get(f"/api/corridas/{cid}").status_code == 404
    assert cli.delete(f"/api/corridas/{cid}").status_code == 404


def test_corridas_sin_turno_400(tmp_path):
    cli, _ = _cli(tmp_path)
    p = tmp_path / "noturno.xlsx"
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["ITEM", "DESCRIPCION", "UNIDAD", "CANTIDAD", "PRECIO"])
    ws.append(["1", "Concreto clase D", "M3", 10, 400000]); wb.save(p)
    with open(p, "rb") as f:
        r = cli.post("/api/corridas", data={"turno": "DIURNO"},
                     files={"archivo": ("noturno.xlsx", f, "application/octet-stream")})
    assert r.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api_corridas.py -q`
Expected: FAIL (404 en GET /api/corridas; y el 400 no se dispara porque aún no se exige turno).

- [ ] **Step 3: Implement**

En `apu_tool/servicio/rutas.py`:

1. Agrega los dos endpoints (junto a los de corridas). Declara `GET /corridas` **antes** de `GET /corridas/{cid}` para que quede explícito:

```python
@router.get("/corridas")
def listar_corridas(alm: Almacen = Depends(get_almacen)):
    return svc.listar_corridas(alm)


@router.delete("/corridas/{cid}")
def eliminar_corrida(cid: int, alm: Almacen = Depends(get_almacen)):
    if not svc.eliminar_corrida(alm, cid):
        raise HTTPException(status_code=404, detail="Corrida no encontrada.")
    return {"eliminada": cid}
```

2. En `crear_corrida` y `crear_corrida_stream`, cambia la lectura para exigir turno:

de `items = read_licitacion(tmp_path, default_shift=turno)`
a `items = read_licitacion(tmp_path, default_shift=turno, require_turno=True)`

(NO cambies `crear_sample` ni `crear_sample_stream`: el ejemplo siempre trae turno y no debe exigirlo.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_api_corridas.py -q`
Expected: PASS.

- [ ] **Step 5: Run full suite**

Run: `python -m pytest tests/ -q`
Expected: PASS (los tests que suben archivo usan `write_sample_licitacion`, que incluye TURNO).

- [ ] **Step 6: Commit**

```bash
git add apu_tool/servicio/rutas.py tests/test_api_corridas.py
git commit -m "feat(api): GET/DELETE corridas + require_turno en el armado por archivo"
```

---

## FASE FRONTEND

> Convención: contrato preciso + código de lógica/infra + verificación con `npm run build` (0 TS). No `npm run dev`. Imports `@/`. UI densa, sin cards.

### Task 4: Lista "mis corridas" + navegación + quitar selector de turno

**Files:**
- Modify: `web/src/lib/tipos.ts`, `web/src/api/corridas.ts`, `web/src/App.tsx`, `web/src/components/Layout.tsx`, `web/src/pages/CorridasInicio.tsx`
- Create: `web/src/pages/MisCorridas.tsx`

**Contrato:**
- `tipos.ts`: `export interface CorridaResumen { id:number; archivo:string; creada_en:string; estado:string; n_items:number; n_revision:number }`.
- `api/corridas.ts`: `listarCorridas(): Promise<CorridaResumen[]>` (`apiGet("/corridas")`); `eliminarCorrida(id:number): Promise<void>` (`apiDelete("/corridas/"+id)`). Si `client.ts` no tiene `apiDelete`, agrégalo (igual a `apiGet` pero `method:"DELETE"`, tolerante a respuesta vacía/JSON).
- `App.tsx`: rutas → `/corridas` = `MisCorridas`, `/corridas/nueva` = `CorridasInicio`, `/corridas/:id` = `Corrida`. `/` sigue redirigiendo a `/corridas`.
- `Layout.tsx`: el link "Corridas" apunta a `/corridas` (la lista). El resaltado activo debe seguir funcionando para `/corridas` y subrutas (usa `NavLink` con `end` solo donde aplique).
- `MisCorridas.tsx`: al montar carga `listarCorridas()`. Tabla densa: **Nombre** (`{archivo} — {fecha legible}` a partir de `creada_en`) · nº ítems · nº por revisar · estado · acciones. Botón **"Nueva corrida"** (→ `/corridas/nueva`). Clic en fila → `navigate('/corridas/'+id)`. Botón **Eliminar** por fila → `window.confirm(...)` → `eliminarCorrida(id)` → recarga la lista (toast de resultado). Estado vacío: "No hay corridas; crea una nueva."
- `CorridasInicio.tsx`: **quita el selector de turno** (el `<select>` de turno y su estado) y **deja de enviar** `turno` en el `FormData`. Mantiene el archivo, el toggle "usar IA" y el flujo de progreso (crearCorridaStream) que navega a `/corridas/:id`. (El backend exige turno por fila ahora.)

- [ ] **Step 1:** Implementar `apiDelete` (si falta), `CorridaResumen`, `listarCorridas`/`eliminarCorrida`.
- [ ] **Step 2:** Reestructurar rutas en `App.tsx` y el link en `Layout.tsx`.
- [ ] **Step 3:** Implementar `MisCorridas.tsx` (lista + nueva + eliminar con confirmación).
- [ ] **Step 4:** Quitar el selector de turno de `CorridasInicio.tsx` (UI + estado + campo del FormData).
- [ ] **Step 5: Verificar build**

Run: `cd web && npm run build`
Expected: 0 errores TS.

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/tipos.ts web/src/api/corridas.ts web/src/App.tsx web/src/components/Layout.tsx web/src/pages/MisCorridas.tsx web/src/pages/CorridasInicio.tsx
git commit -m "feat(web): lista mis-corridas + navegación + quitar selector de turno"
```

**Aceptación:** `/corridas` lista las corridas (nombre = archivo + fecha) con nº ítems/por revisar/estado; "Nueva corrida" abre el formulario; clic abre el cuadro; eliminar (confirmación) la quita; ya no hay selector global de turno.

---

### Task 5: Composición desplegable inline por fila (unifica el panel de revisión)

**Files:**
- Modify: `web/src/components/corrida/TablaItems.tsx`, `web/src/pages/Corrida.tsx`
- Delete: `web/src/components/corrida/PanelRevision.tsx`

**Contrato:**
- `TablaItems` recibe además `corridaId: number` y `onConfirmado: (corridaActualizada: CorridaDetalle) => void` (reemplaza el `onSelectItem` actual).
- Cada fila gana un control de **desplegar** (chevron en una primera columna estrecha). Estado local `expandido: Record<number, DetalleItem | "cargando" | undefined>` por `seq`.
- Al expandir una fila por primera vez: `getItem(corridaId, seq)` (de `@/api/corridas`); mientras carga muestra "cargando…"; al volver, renderiza **inline debajo de la fila** (un `<TableRow>` extra con `<TableCell colSpan=...>`) una tabla densa de composición: insumo · unidad · rendimiento · precio vigente · costo · cruce (de `detalle.composicion`).
- Si la fila es **review/new**: el área expandida **además** muestra la explicación, los `detalle.candidatos` (con score) y un botón **Confirmar** por candidato (y/o "Confirmar APU actual") → `confirmar(corridaId, seq, apu_codigo)` (de `@/api/corridas`) → `onConfirmado(corridaActualizada)`. Esto reemplaza el `PanelRevision`.
- Toda fila es expandible (cualquier estado), no solo review/new.
- `Corrida.tsx`: pasa `corridaId={id}` y `onConfirmado={(c)=>setCorrida(c)}` a `TablaItems`; elimina el uso de `PanelRevision` (import, estado del dialog, render). Borra el archivo `PanelRevision.tsx`.
- Tipos en `@/lib/tipos`: `DetalleItem` (con `candidatos`, `composicion`), `CorridaDetalle` — ya existen.

- [ ] **Step 1:** En `TablaItems.tsx`: agregar la columna de chevron, el estado `expandido`, el fetch `getItem` perezoso, el render inline de composición, y (para review/new) candidatos + confirmar. Quitar el `onSelectItem`/`clickable` previo.
- [ ] **Step 2:** En `Corrida.tsx`: pasar `corridaId`/`onConfirmado`, quitar `PanelRevision`. Borrar `web/src/components/corrida/PanelRevision.tsx`.
- [ ] **Step 3: Verificar build**

Run: `cd web && npm run build`
Expected: 0 errores TS (sin referencias colgantes a PanelRevision).

- [ ] **Step 4: Commit**

```bash
git add web/src/components/corrida/TablaItems.tsx web/src/pages/Corrida.tsx
git rm web/src/components/corrida/PanelRevision.tsx
git commit -m "feat(web): composición desplegable inline por fila (unifica panel de revisión)"
```

- [ ] **Step 5: Verificación en vivo (controlador)**

`cd web && npm run build`; levantar `run_web.py`; con una corrida (subir lista con TURNO por fila o usar ejemplo): (a) `/corridas` lista y permite eliminar; (b) abrir el cuadro y **desplegar** un ítem AUTO muestra su composición; (c) un ítem REVIEW/NEW despliega candidatos + confirmar y recostea; (d) editar un precio en Insumos y reabrir la corrida muestra el costo actualizado. `python -m pytest tests/ -q` verde.

**Aceptación:** cualquier fila del cuadro se despliega inline con su composición; review/new traen candidatos + confirmar en el mismo desplegable; `PanelRevision` retirado; build verde.

---

## Self-Review

**1. Spec coverage:**
- Turno requerido por fila → T1 (read_licitacion) + T3 (wiring en endpoints + 400 test). ✓
- Lista mis-corridas (listar/eliminar, datos+servicio+API) → T2 + T3. ✓
- Frontend lista + nav + nombre archivo+fecha + eliminar + quitar selector turno → T4. ✓
- Corrida viva (re-costeo vigente, sin bloqueo) → ya en backend; T5 verificación en vivo (editar precio → reabrir). Sin cambio de costeo. ✓
- Composición desplegable inline cualquier estado + unificar panel → T5. ✓
- Cero regresiones: read_licitacion retrocompatible (T1), endpoints conservados, get_corrida refactor equivalente (T2), matcher/costeo intactos. ✓

**2. Placeholder scan:** backend con código completo; frontend con contrato + código de infra (apiDelete/api fns/tipos) + criterios. Sin TBD/TODO.

**3. Type consistency:** `CorridaMeta` reusado (listar/get vía `_row_to_meta`); `listar_corridas` servicio devuelve `{id,archivo,creada_en,estado,n_items,n_revision}` = `CorridaResumen` del frontend (T2↔T4); `eliminar_corrida -> bool` consistente datos↔servicio↔endpoint (200/404); `TablaItems(corridaId, onConfirmado)` y `getItem`/`confirmar`/`DetalleItem`/`CorridaDetalle` ya existentes (T5). Consistente.
