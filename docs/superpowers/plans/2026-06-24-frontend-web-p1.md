# Frontend Web Proyecto 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar el frontend web del Armador de APUs (Vite + React + shadcn, servido por FastAPI) con el flujo de corrida sobre el backend v1 y la edición de insumos (precio + fuente) individual y en batch, más los endpoints de insumos que la edición necesita.

**Architecture:** Fase A agrega el backend de insumos (capa `datos` + `servicio` + API), todo testeable con pytest. Fases B–D construyen el frontend en `web/` (scaffold + shell, flujo de corrida, módulo de insumos) consumiendo `/api`. El dominio NO se toca; el módulo de insumos no roza la IA.

**Tech Stack:** Backend: Python, FastAPI, SQLite (stdlib), openpyxl (parseo import). Frontend: Vite, React, TypeScript, Tailwind, shadcn/ui; Vitest + React Testing Library.

## Convención de tareas

- **Backend (Tasks A1–A5):** TDD estricto con código completo (test que falla → implementación → test que pasa → commit).
- **Frontend (Tasks B1–D4):** cada tarea da (1) archivos a crear, (2) contrato preciso — props, endpoints consumidos con su shape exacto, estados, criterios de aceptación —, (3) código completo para lógica/infra (cliente API, hooks, config), y (4) un paso de **verificación ejecutando** (build y/o dev server). Para componentes de vista se da el contrato + snippets clave; el implementador escribe React idiomático y lo verifica corriendo. Esto NO es un placeholder: el contrato y los criterios de aceptación son exactos.

## Global Constraints

- Español en nombres de dominio, comentarios y mensajes de usuario.
- Toda la persistencia nueva vive en `apu_tool/datos/`; sin SQL crudo fuera de esa capa.
- El dominio (`apu_tool/dominio/`) NO se modifica.
- **Invariante #1:** ningún archivo en `apu_tool/servicio/` contiene la cadena `"ai_assist"`; el módulo de insumos no abre ningún camino hacia la IA.
- Edición de precios por **id** de insumo (los códigos se repiten); cada cambio crea fila de historial (`vigente` 0→1), igual que `set_precio` hoy.
- Backend sin dependencias pesadas nuevas (reusa `openpyxl`). Frontend: solo dependencias de build en `web/`, aisladas; no afectan el runtime de Python.
- UI **densa, table-first, sin cards**; dinero monoespaciado alineado a la derecha, formato COP `$1,234,567`.
- `python -m pytest tests/ -q` debe seguir verde tras cada tarea de backend.

---

## File Structure

```
apu_tool/datos/precios_db.py    # + _insertar_precio_vigente, set_precio_por_id, list_insumos, grupos, fuentes
apu_tool/datos/repositorio.py   # + esos métodos en RepositorioPrecios (Protocol)
apu_tool/servicio/insumos.py    # [nuevo] listar, detalle, aplicar_cambios, preview_import, preview_transformar
apu_tool/servicio/esquemas.py   # + CambioIn, CambiosIn, TransformarIn
apu_tool/servicio/rutas.py      # + endpoints /api/insumos*
tests/test_insumos_db.py        # [nuevo]
tests/test_servicio_insumos.py  # [nuevo]
tests/test_api_insumos.py       # [nuevo]

web/                            # [nuevo] Vite + React + TS + Tailwind + shadcn
├── package.json vite.config.ts tsconfig.json index.html components.json
├── src/main.tsx src/App.tsx src/index.css
├── src/api/      client.ts corridas.ts insumos.ts
├── src/lib/      moneda.ts tipos.ts useDirtyRows.ts
├── src/components/ Layout.tsx  corrida/*  insumos/*
└── src/pages/    CorridasInicio.tsx Corrida.tsx Insumos.tsx
```

---

## FASE A — Backend de insumos

### Task A1: `set_precio_por_id` (edición por id, con historial)

**Files:**
- Modify: `apu_tool/datos/precios_db.py`
- Modify: `apu_tool/datos/repositorio.py`
- Test: `tests/test_insumos_db.py`

**Interfaces:**
- Consumes: `Insumo`, `config.classify_price_source`, el patrón `connect()` de `PreciosDB`.
- Produces:
  - `PreciosDB._insertar_precio_vigente(conn, insumo_id: int, precio: float, fuente: str, fecha: str) -> None`
  - `PreciosDB.set_precio_por_id(insumo_id: int, precio: float, fuente: str = "", fecha: Optional[str] = None) -> None` (lanza `ValueError` si el id no existe)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_insumos_db.py
import pytest
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Insumo


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo("100", "Concreto 3000 PSI", "M3", "CONCRETOS", 350000.0, "COSTO INTERNO"),
        Insumo("200", "Acero de refuerzo", "KG", "ACEROS", 4500.0, "PRECIO IDU")])
    return alm


def test_set_precio_por_id_crea_historial(tmp_path):
    alm = _alm(tmp_path)
    ins = alm.precios.get_candidatos("100")[0]
    alm.precios.set_precio_por_id(ins.id, 400000.0, "COMPRAS 2026")
    actual = alm.precios.get_insumo_por_id(ins.id)
    assert actual.precio == 400000.0 and actual.fuente_precio == "COMPRAS 2026"
    hist = alm.precios.price_history("100")
    assert len(hist) == 2                       # original + nuevo
    assert sum(1 for h in hist if h["vigente"]) == 1


def test_set_precio_por_id_id_inexistente(tmp_path):
    alm = _alm(tmp_path)
    with pytest.raises(ValueError):
        alm.precios.set_precio_por_id(99999, 1.0, "X")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_insumos_db.py -q`
Expected: FAIL con `AttributeError: 'PreciosDB' object has no attribute 'set_precio_por_id'`.

- [ ] **Step 3: Implement**

En `apu_tool/datos/precios_db.py`, agrega el helper y el método, y refactoriza `set_precio` para reusar el helper (DRY). Reemplaza el método `set_precio` actual por:

```python
    def _insertar_precio_vigente(self, conn, insumo_id: int, precio: float,
                                 fuente: str, fecha: str) -> None:
        conn.execute("UPDATE insumo_precios SET vigente=0 WHERE insumo_id=?", (int(insumo_id),))
        conn.execute(
            "INSERT INTO insumo_precios "
            "(insumo_id, precio, fuente, clasificacion, fecha, vigente) "
            "VALUES (?,?,?,?,?,1)",
            (int(insumo_id), float(precio), fuente,
             config.classify_price_source(fuente), fecha))

    def set_precio(self, codigo: str, precio: float, fuente: str = "",
                   fecha: Optional[str] = None, nombre: Optional[str] = None) -> None:
        fecha = fecha or date.today().isoformat()
        with self.connect() as conn:
            ids = self._ids_de(conn, codigo, nombre)
            if len(ids) != 1:
                raise ValueError(
                    f"Código {codigo} resuelve a {len(ids)} insumos; "
                    f"especifica el nombre exacto para desambiguar.")
            self._insertar_precio_vigente(conn, ids[0], precio, fuente, fecha)

    def set_precio_por_id(self, insumo_id: int, precio: float, fuente: str = "",
                          fecha: Optional[str] = None) -> None:
        fecha = fecha or date.today().isoformat()
        with self.connect() as conn:
            r = conn.execute("SELECT id FROM insumos WHERE id=?", (int(insumo_id),)).fetchone()
            if r is None:
                raise ValueError(f"No existe el insumo id={insumo_id}.")
            self._insertar_precio_vigente(conn, int(insumo_id), precio, fuente, fecha)
```

En `apu_tool/datos/repositorio.py`, agrega a `RepositorioPrecios` (Protocol):

```python
    def set_precio_por_id(self, insumo_id: int, precio: float, fuente: str = "",
                          fecha: Optional[str] = None) -> None: ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_insumos_db.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add apu_tool/datos/precios_db.py apu_tool/datos/repositorio.py tests/test_insumos_db.py
git commit -m "feat(datos): set_precio_por_id (edición por id con historial)"
```

---

### Task A2: `list_insumos`, `grupos`, `fuentes`

**Files:**
- Modify: `apu_tool/datos/precios_db.py`
- Modify: `apu_tool/datos/repositorio.py`
- Test: `tests/test_insumos_db.py` (se amplía)

**Interfaces:**
- Consumes: `_fila_a_insumo`, `connect()`.
- Produces:
  - `PreciosDB.list_insumos(q: Optional[str]=None, grupo: Optional[str]=None, fuente: Optional[str]=None, limit: int=100, offset: int=0) -> tuple[list[Insumo], int]` (devuelve la página y el total)
  - `PreciosDB.grupos() -> list[str]`
  - `PreciosDB.fuentes() -> list[str]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_insumos_db.py  (agregar)
def test_list_insumos_filtros_y_total(tmp_path):
    alm = _alm(tmp_path)
    items, total = alm.precios.list_insumos(limit=10, offset=0)
    assert total == 2 and len(items) == 2
    items, total = alm.precios.list_insumos(q="acero")
    assert total == 1 and items[0].codigo == "200"
    items, total = alm.precios.list_insumos(grupo="CONCRETOS")
    assert total == 1 and items[0].codigo == "100"
    items, total = alm.precios.list_insumos(fuente="PRECIO IDU")
    assert total == 1 and items[0].codigo == "200"


def test_list_insumos_paginacion(tmp_path):
    alm = _alm(tmp_path)
    items, total = alm.precios.list_insumos(limit=1, offset=0)
    assert total == 2 and len(items) == 1
    items2, _ = alm.precios.list_insumos(limit=1, offset=1)
    assert items[0].id != items2[0].id


def test_grupos_y_fuentes(tmp_path):
    alm = _alm(tmp_path)
    assert set(alm.precios.grupos()) == {"ACEROS", "CONCRETOS"}
    assert set(alm.precios.fuentes()) == {"COSTO INTERNO", "PRECIO IDU"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_insumos_db.py -q`
Expected: FAIL con `AttributeError: ... 'list_insumos'`.

- [ ] **Step 3: Implement**

Agrega a `apu_tool/datos/precios_db.py` (sección lectura):

```python
    def list_insumos(self, q=None, grupo=None, fuente=None,
                     limit: int = 100, offset: int = 0):
        base = ("FROM insumos i LEFT JOIN insumo_precios p "
                "ON p.insumo_id = i.id AND p.vigente = 1")
        where, params = [], []
        if q:
            where.append("(i.nombre LIKE ? OR i.codigo LIKE ?)")
            like = f"%{q.strip()}%"
            params += [like, like]
        if grupo:
            where.append("i.grupo = ?")
            params.append(grupo)
        if fuente:
            where.append("p.fuente = ?")
            params.append(fuente)
        wsql = (" WHERE " + " AND ".join(where)) if where else ""
        with self.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) {base}{wsql}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT i.id, i.codigo, i.nombre, i.unidad, i.grupo, p.precio, p.fuente "
                f"{base}{wsql} ORDER BY i.codigo, i.id LIMIT ? OFFSET ?",
                params + [int(limit), int(offset)]).fetchall()
        return [self._fila_a_insumo(r) for r in rows], int(total)

    def grupos(self) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT grupo FROM insumos "
                "WHERE grupo IS NOT NULL AND grupo <> '' ORDER BY grupo").fetchall()
        return [r["grupo"] for r in rows]

    def fuentes(self) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT fuente FROM insumo_precios "
                "WHERE vigente = 1 AND fuente IS NOT NULL AND fuente <> '' "
                "ORDER BY fuente").fetchall()
        return [r["fuente"] for r in rows]
```

En `repositorio.py`, agrega a `RepositorioPrecios`:

```python
    def list_insumos(self, q=None, grupo=None, fuente=None,
                     limit: int = 100, offset: int = 0): ...
    def grupos(self) -> list[str]: ...
    def fuentes(self) -> list[str]: ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_insumos_db.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add apu_tool/datos/precios_db.py apu_tool/datos/repositorio.py tests/test_insumos_db.py
git commit -m "feat(datos): list_insumos filtrable + grupos/fuentes"
```

---

### Task A3: Servicio de insumos — listar, detalle, aplicar_cambios

**Files:**
- Create: `apu_tool/servicio/insumos.py`
- Test: `tests/test_servicio_insumos.py`

**Interfaces:**
- Consumes: `Almacen.precios` (A1, A2), `config.classify_price_source`, `price_history`, `get_insumo_por_id`.
- Produces:
  - `_insumo_out(ins) -> dict` con claves `{id, codigo, nombre, unidad, grupo, precio, fuente, clasificacion}`
  - `listar(alm, q=None, grupo=None, fuente=None, limit=100, offset=0) -> dict` → `{items, total, limit, offset}`
  - `detalle(alm, insumo_id) -> Optional[dict]` → `{insumo, historial}`
  - `aplicar_cambios(alm, cambios: list[dict]) -> dict` → `{aplicados, errores}` (errores: `[{insumo_id, error}]`)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_servicio_insumos.py
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Insumo
from apu_tool.servicio import insumos as svc


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo("100", "Concreto 3000 PSI", "M3", "CONCRETOS", 350000.0, "COSTO INTERNO"),
        Insumo("200", "Acero de refuerzo", "KG", "ACEROS", 4500.0, "PRECIO IDU")])
    return alm


def test_listar_y_clasificacion(tmp_path):
    alm = _alm(tmp_path)
    out = svc.listar(alm)
    assert out["total"] == 2
    by_cod = {i["codigo"]: i for i in out["items"]}
    assert by_cod["200"]["clasificacion"] == "publico"      # PRECIO IDU
    assert by_cod["100"]["clasificacion"] == "interno"      # COSTO INTERNO


def test_detalle_con_historial(tmp_path):
    alm = _alm(tmp_path)
    iid = alm.precios.get_candidatos("100")[0].id
    d = svc.detalle(alm, iid)
    assert d["insumo"]["codigo"] == "100" and len(d["historial"]) >= 1
    assert svc.detalle(alm, 99999) is None


def test_aplicar_cambios_ok_y_errores(tmp_path):
    alm = _alm(tmp_path)
    iid = alm.precios.get_candidatos("100")[0].id
    res = svc.aplicar_cambios(alm, [
        {"insumo_id": iid, "precio": 380000.0, "fuente": "COMPRAS"},
        {"insumo_id": 99999, "precio": 1.0, "fuente": "X"},      # id malo
        {"insumo_id": iid, "precio": -5.0, "fuente": "Y"}])      # precio inválido
    assert res["aplicados"] == 1 and len(res["errores"]) == 2
    assert alm.precios.get_insumo_por_id(iid).precio == 380000.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_servicio_insumos.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'apu_tool.servicio.insumos'`.

- [ ] **Step 3: Implement**

`apu_tool/servicio/insumos.py`:

```python
"""
Lógica de servicio para la edición de insumos (precio + fuente).

Edición de catálogo/precios pura: NO toca la IA. Ve dinero (es para el equipo),
pero no abre ningún camino hacia la IA. Edita por id (los códigos se repiten) y
cada cambio crea historial vía PreciosDB.set_precio_por_id.
"""
from __future__ import annotations

from typing import Optional

from apu_tool import config
from apu_tool.datos.almacen import Almacen


def _insumo_out(ins) -> dict:
    return {"id": ins.id, "codigo": ins.codigo, "nombre": ins.nombre,
            "unidad": ins.unidad, "grupo": ins.grupo, "precio": ins.precio,
            "fuente": ins.fuente_precio,
            "clasificacion": config.classify_price_source(ins.fuente_precio)}


def listar(alm: Almacen, q: Optional[str] = None, grupo: Optional[str] = None,
           fuente: Optional[str] = None, limit: int = 100, offset: int = 0) -> dict:
    items, total = alm.precios.list_insumos(q, grupo, fuente, limit, offset)
    return {"items": [_insumo_out(i) for i in items], "total": total,
            "limit": limit, "offset": offset}


def detalle(alm: Almacen, insumo_id: int) -> Optional[dict]:
    ins = alm.precios.get_insumo_por_id(insumo_id)
    if ins is None:
        return None
    return {"insumo": _insumo_out(ins),
            "historial": alm.precios.price_history(ins.codigo, nombre=ins.nombre)}


def aplicar_cambios(alm: Almacen, cambios: list[dict]) -> dict:
    aplicados, errores = 0, []
    for c in cambios:
        try:
            precio = float(c["precio"])
            if precio < 0:
                raise ValueError("El precio no puede ser negativo.")
            alm.precios.set_precio_por_id(int(c["insumo_id"]), precio,
                                          str(c.get("fuente", "") or ""))
            aplicados += 1
        except (ValueError, KeyError, TypeError) as e:
            errores.append({"insumo_id": c.get("insumo_id"), "error": str(e)})
    return {"aplicados": aplicados, "errores": errores}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_servicio_insumos.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/insumos.py tests/test_servicio_insumos.py
git commit -m "feat(servicio): insumos listar/detalle/aplicar_cambios"
```

---

### Task A4: Servicio de insumos — preview de importación y transformación

**Files:**
- Modify: `apu_tool/servicio/insumos.py`
- Test: `tests/test_servicio_insumos.py` (se amplía)

**Interfaces:**
- Consumes: `alm.precios.get_candidatos`, `listar`/`list_insumos`.
- Produces:
  - `_parse_tabla(contenido: bytes, nombre: str) -> list[dict]` (filas `{codigo, precio, fuente}`; lanza `ValueError` si no hay columnas código/precio)
  - `preview_import(alm, contenido: bytes, nombre: str) -> dict` → `{cambios, ambiguos, no_encontrados}`
  - `preview_transformar(alm, filtro: dict, operacion: dict) -> dict` → `{cambios, afectados}`
  - Forma de un `cambio`: `{insumo_id, codigo, nombre, precio_actual, precio_nuevo, fuente_actual, fuente_nueva}`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_servicio_insumos.py  (agregar)
import io
import openpyxl


def _xlsx_bytes(filas):
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["CODIGO", "PRECIO", "FUENTE"])
    for f in filas:
        ws.append(f)
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def test_preview_import_reconocido_y_no_encontrado(tmp_path):
    alm = _alm(tmp_path)
    contenido = _xlsx_bytes([["100", 390000, "COMPRAS"], ["999", 10, "X"]])
    out = svc.preview_import(alm, contenido, "lista.xlsx")
    assert len(out["cambios"]) == 1 and out["cambios"][0]["codigo"] == "100"
    assert out["cambios"][0]["precio_nuevo"] == 390000
    assert len(out["no_encontrados"]) == 1 and out["no_encontrados"][0]["codigo"] == "999"


def test_preview_transformar_operaciones(tmp_path):
    alm = _alm(tmp_path)
    out = svc.preview_transformar(alm, {"grupo": "CONCRETOS"},
                                  {"tipo": "precio_pct", "valor": 10})
    assert out["afectados"] == 1
    c = out["cambios"][0]
    assert c["codigo"] == "100" and c["precio_nuevo"] == 385000.0    # 350000 * 1.10

    out2 = svc.preview_transformar(alm, {"fuente": "PRECIO IDU"},
                                   {"tipo": "fuente", "valor": "IDU 2026"})
    assert out2["afectados"] == 1 and out2["cambios"][0]["fuente_nueva"] == "IDU 2026"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_servicio_insumos.py -q`
Expected: FAIL con `AttributeError: module ... has no attribute 'preview_import'`.

- [ ] **Step 3: Implement**

Agrega a `apu_tool/servicio/insumos.py`:

```python
import csv
import io
import unicodedata

import openpyxl


def _norm_h(s: str) -> str:
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


def _parse_tabla(contenido: bytes, nombre: str) -> list[dict]:
    if nombre.lower().endswith((".xlsx", ".xlsm")):
        wb = openpyxl.load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
        ws = wb.active
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
    else:
        text = contenido.decode("utf-8-sig", errors="replace")
        rows = [r for r in csv.reader(io.StringIO(text))]
    rows = [r for r in rows if any(c not in (None, "") for c in r)]
    if not rows:
        return []
    headers = [_norm_h(c) for c in rows[0]]

    def col(*keys):
        for i, h in enumerate(headers):
            if any(k == h or k in h for k in keys):
                return i
        return None
    c_cod = col("codigo", "cod", "code")
    c_pre = col("precio", "valor", "price")
    c_fue = col("fuente", "source")
    if c_cod is None or c_pre is None:
        raise ValueError("El archivo debe tener columnas de código y precio.")
    out = []
    for r in rows[1:]:
        def g(i):
            return r[i] if (i is not None and i < len(r)) else None
        cod = str(g(c_cod) or "").strip()
        if not cod:
            continue
        out.append({"codigo": cod, "precio": _to_float(g(c_pre)),
                    "fuente": str(g(c_fue) or "").strip()})
    return out


def _cambio(ins, precio_nuevo: float, fuente_nueva: str) -> dict:
    return {"insumo_id": ins.id, "codigo": ins.codigo, "nombre": ins.nombre,
            "precio_actual": ins.precio, "precio_nuevo": precio_nuevo,
            "fuente_actual": ins.fuente_precio, "fuente_nueva": fuente_nueva}


def preview_import(alm: Almacen, contenido: bytes, nombre: str) -> dict:
    filas = _parse_tabla(contenido, nombre)
    cambios, ambiguos, no_encontrados = [], [], []
    for f in filas:
        cands = alm.precios.get_candidatos(f["codigo"])
        if len(cands) == 1:
            ins = cands[0]
            cambios.append(_cambio(ins, f["precio"], f["fuente"] or ins.fuente_precio))
        elif len(cands) > 1:
            ambiguos.append({"codigo": f["codigo"], "precio": f["precio"],
                             "candidatos": [{"id": c.id, "nombre": c.nombre} for c in cands]})
        else:
            no_encontrados.append({"codigo": f["codigo"], "precio": f["precio"]})
    return {"cambios": cambios, "ambiguos": ambiguos, "no_encontrados": no_encontrados}


def preview_transformar(alm: Almacen, filtro: dict, operacion: dict) -> dict:
    items, _ = alm.precios.list_insumos(
        q=filtro.get("q"), grupo=filtro.get("grupo"), fuente=filtro.get("fuente"),
        limit=1_000_000, offset=0)
    tipo, valor = operacion.get("tipo"), operacion.get("valor")
    cambios = []
    for ins in items:
        nuevo_precio, nueva_fuente = ins.precio, ins.fuente_precio
        if tipo == "fuente":
            nueva_fuente = str(valor)
        elif tipo == "precio_factor":
            nuevo_precio = round(ins.precio * float(valor), 2)
        elif tipo == "precio_pct":
            nuevo_precio = round(ins.precio * (1 + float(valor) / 100), 2)
        elif tipo == "precio_set":
            nuevo_precio = float(valor)
        else:
            raise ValueError(f"Operación desconocida: {tipo}")
        cambios.append(_cambio(ins, nuevo_precio, nueva_fuente))
    return {"cambios": cambios, "afectados": len(cambios)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_servicio_insumos.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/insumos.py tests/test_servicio_insumos.py
git commit -m "feat(servicio): preview de importación y transformación de insumos"
```

---

### Task A5: Endpoints `/api/insumos*`

**Files:**
- Modify: `apu_tool/servicio/rutas.py`
- Modify: `apu_tool/servicio/esquemas.py`
- Test: `tests/test_api_insumos.py`

**Interfaces:**
- Consumes: `servicio.insumos` (A3, A4), `get_almacen`.
- Produces los endpoints: `GET /api/insumos`, `GET /api/insumos/grupos`, `GET /api/insumos/fuentes`, `GET /api/insumos/{id}`, `POST /api/insumos/cambios`, `POST /api/insumos/importar/preview`, `POST /api/insumos/transformar/preview`.
- DTOs nuevos: `CambioIn{insumo_id:int, precio:float, fuente:str=""}`, `CambiosIn{cambios:list[CambioIn]}`, `TransformarIn{filtro:dict, operacion:dict}`.

> Nota de orden de rutas: define `/insumos/grupos` y `/insumos/fuentes` ANTES de `/insumos/{id}` para que `{id}` (int) no capture esas rutas. (FastAPI valida `{id}` como int, así que igual no colisiona, pero declararlas antes lo hace explícito.)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_insumos.py
from fastapi.testclient import TestClient
import io, openpyxl

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Insumo
from apu_tool.servicio.app import create_app


def _cli(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo("100", "Concreto 3000 PSI", "M3", "CONCRETOS", 350000.0, "COSTO INTERNO"),
        Insumo("200", "Acero de refuerzo", "KG", "ACEROS", 4500.0, "PRECIO IDU")])
    return TestClient(create_app(almacen=alm)), alm


def test_listar_filtros_grupos_fuentes(tmp_path):
    cli, _ = _cli(tmp_path)
    r = cli.get("/api/insumos?q=acero")
    assert r.status_code == 200 and r.json()["total"] == 1
    assert "ACEROS" in cli.get("/api/insumos/grupos").json()
    assert "PRECIO IDU" in cli.get("/api/insumos/fuentes").json()


def test_cambios_y_detalle(tmp_path):
    cli, alm = _cli(tmp_path)
    iid = alm.precios.get_candidatos("100")[0].id
    r = cli.post("/api/insumos/cambios", json={"cambios": [
        {"insumo_id": iid, "precio": 410000.0, "fuente": "COMPRAS"}]})
    assert r.status_code == 200 and r.json()["aplicados"] == 1
    d = cli.get(f"/api/insumos/{iid}")
    assert d.status_code == 200 and d.json()["insumo"]["precio"] == 410000.0
    assert cli.get("/api/insumos/99999").status_code == 404


def test_importar_y_transformar_preview(tmp_path):
    cli, _ = _cli(tmp_path)
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["CODIGO", "PRECIO", "FUENTE"]); ws.append(["100", 390000, "COMPRAS"])
    buf = io.BytesIO(); wb.save(buf)
    r = cli.post("/api/insumos/importar/preview",
                 files={"archivo": ("l.xlsx", buf.getvalue(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200 and len(r.json()["cambios"]) == 1
    t = cli.post("/api/insumos/transformar/preview",
                 json={"filtro": {"grupo": "CONCRETOS"},
                       "operacion": {"tipo": "precio_pct", "valor": 10}})
    assert t.status_code == 200 and t.json()["afectados"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api_insumos.py -q`
Expected: FAIL (404 en `/api/insumos`).

- [ ] **Step 3: Implement DTOs**

Agrega a `apu_tool/servicio/esquemas.py`:

```python
class CambioIn(BaseModel):
    insumo_id: int
    precio: float
    fuente: str = ""


class CambiosIn(BaseModel):
    cambios: list[CambioIn]


class TransformarIn(BaseModel):
    filtro: dict
    operacion: dict
```

- [ ] **Step 4: Implement endpoints**

Agrega a `apu_tool/servicio/rutas.py` (imports + endpoints). En los imports añade `from typing import Optional` (si falta) y `from apu_tool.servicio import insumos as insumos_svc`, y `from apu_tool.servicio.esquemas import CambiosIn, TransformarIn`. Agrega:

```python
@router.get("/insumos")
def listar_insumos(q: Optional[str] = None, grupo: Optional[str] = None,
                   fuente: Optional[str] = None, limit: int = 100, offset: int = 0,
                   alm: Almacen = Depends(get_almacen)):
    return insumos_svc.listar(alm, q, grupo, fuente, limit, offset)


@router.get("/insumos/grupos")
def insumos_grupos(alm: Almacen = Depends(get_almacen)):
    return alm.precios.grupos()


@router.get("/insumos/fuentes")
def insumos_fuentes(alm: Almacen = Depends(get_almacen)):
    return alm.precios.fuentes()


@router.get("/insumos/{insumo_id}")
def insumo_detalle(insumo_id: int, alm: Almacen = Depends(get_almacen)):
    d = insumos_svc.detalle(alm, insumo_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Insumo no encontrado.")
    return d


@router.post("/insumos/cambios")
def insumos_cambios(body: CambiosIn, alm: Almacen = Depends(get_almacen)):
    return insumos_svc.aplicar_cambios(alm, [c.model_dump() for c in body.cambios])


@router.post("/insumos/importar/preview")
async def insumos_importar_preview(archivo: UploadFile = File(...),
                                   alm: Almacen = Depends(get_almacen)):
    contenido = await archivo.read()
    try:
        return insumos_svc.preview_import(alm, contenido, archivo.filename or "lista.xlsx")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/insumos/transformar/preview")
def insumos_transformar_preview(body: TransformarIn, alm: Almacen = Depends(get_almacen)):
    try:
        return insumos_svc.preview_transformar(alm, body.filtro, body.operacion)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

(Asegúrate de que `UploadFile`, `File`, `HTTPException`, `Depends` ya estén importados en `rutas.py` — lo están del backend v1.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_api_insumos.py -q`
Expected: PASS (3 tests).

- [ ] **Step 6: Run full suite**

Run: `python -m pytest tests/ -q`
Expected: PASS (todo verde, incluye backend v1).

- [ ] **Step 7: Commit**

```bash
git add apu_tool/servicio/rutas.py apu_tool/servicio/esquemas.py tests/test_api_insumos.py
git commit -m "feat(api): endpoints /api/insumos (listar, cambios, importar, transformar)"
```

---

## FASE B — Frontend: scaffold + shell

> A partir de aquí las tareas son frontend (estilo contrato + verificación ejecutando). Trabaja en `web/`. Node debe estar disponible (`node -v`, `npm -v`). La estética es **densa, table-first, sin cards**.

### Task B1: Scaffold del proyecto web

**Files:**
- Create: `web/` (Vite React-TS + Tailwind + shadcn) — `package.json`, `vite.config.ts`, `tsconfig*.json`, `index.html`, `src/main.tsx`, `src/App.tsx`, `src/index.css`, `components.json`.

**Contrato / pasos:**
- [ ] **Step 1: Crear el proyecto Vite React-TS dentro de `web/`**

Desde la raíz del repo:
```bash
npm create vite@latest web -- --template react-ts
cd web && npm install
```

- [ ] **Step 2: Instalar y configurar Tailwind + shadcn**

Sigue la guía vigente de shadcn para Vite (versiones actuales): instalar Tailwind, configurar `tailwind.config`/`index.css`, alias `@` en `tsconfig` y `vite.config.ts`, y `npx shadcn@latest init`. Instala los componentes base que se usarán: `button input table dialog select badge sonner` (`npx shadcn@latest add ...`). Adapta a la versión real de las herramientas; el criterio es que `npm run build` y `npm run dev` funcionen y los componentes shadcn importen desde `@/components/ui/*`.

- [ ] **Step 3: Configurar el proxy de `/api` en `vite.config.ts`**

`server.proxy` debe enrutar `/api` → `http://127.0.0.1:8000`:
```ts
// vite.config.ts (extracto)
server: { proxy: { "/api": "http://127.0.0.1:8000" } }
```

- [ ] **Step 4: Verificar build y dev**

Run: `cd web && npm run build`
Expected: build sin errores; genera `web/dist`.
Run (manual, opcional): `npm run dev` y abrir `http://localhost:5173` — la app base de Vite carga.

- [ ] **Step 5: Commit**

```bash
git add web/ .gitignore
git commit -m "chore(web): scaffold Vite + React + TS + Tailwind + shadcn"
```
(Asegura que `web/node_modules` y `web/dist` estén en `.gitignore`.)

**Aceptación:** `npm run build` produce `web/dist`; shadcn components importan desde `@/components/ui`; el proxy `/api` apunta a :8000.

---

### Task B2: Cliente API tipado

**Files:**
- Create: `web/src/api/client.ts`, `web/src/api/corridas.ts`, `web/src/api/insumos.ts`, `web/src/lib/tipos.ts`, `web/src/lib/moneda.ts`

**Interfaces / contrato (shapes EXACTOS que devuelve el backend):**
- `GET /api/status` → `{insumos:number, apus:number, ia:boolean}`
- `POST /api/sample` → `{id:number, resumen:Totales}`
- `POST /api/corridas` (multipart: `turno`, `use_ai`, `archivo`) → `{id, resumen}`
- `GET /api/corridas/{id}` → `{id, archivo, estado, items:ItemCuadro[], totales:Totales}`
  - `Totales = {contractual, costo, margen, margen_pct, n_items, n_revision}`
  - `ItemCuadro = {seq, item, descripcion, unidad, cantidad, apu_codigo, apu_nombre, status, confianza, precio_contractual, costo_unitario, margen_unitario, margen_pct, contractual_total, costo_total, margen_total}`
- `GET /api/corridas/{id}/items/{seq}` → `{seq, descripcion, apu_codigo, apu_nombre, status, explicacion, candidatos:{apu_codigo,apu_nombre,score,motivo}[], composicion:{insumo_codigo,insumo_nombre,unidad,rendimiento,precio_unitario,fuente_precio,costo,calidad_cruce}[], costo_unitario}`
- `POST /api/corridas/{id}/items/{seq}/confirmar` `{apu_codigo, shift?}` → vista de corrida actualizada
- `GET /api/corridas/{id}/cuadro` → descarga xlsx (abrir en nueva pestaña / `window.open`)
- `GET /api/insumos?q&grupo&fuente&limit&offset` → `{items:Insumo[], total, limit, offset}`
  - `Insumo = {id, codigo, nombre, unidad, grupo, precio, fuente, clasificacion}`
- `GET /api/insumos/grupos` → `string[]`; `GET /api/insumos/fuentes` → `string[]`
- `GET /api/insumos/{id}` → `{insumo:Insumo, historial:{precio,fuente,clasificacion,fecha,vigente}[]}`
- `POST /api/insumos/cambios` `{cambios:{insumo_id,precio,fuente}[]}` → `{aplicados, errores:{insumo_id,error}[]}`
- `POST /api/insumos/importar/preview` (multipart `archivo`) → `{cambios:CambioPreview[], ambiguos[], no_encontrados[]}`
  - `CambioPreview = {insumo_id, codigo, nombre, precio_actual, precio_nuevo, fuente_actual, fuente_nueva}`
- `POST /api/insumos/transformar/preview` `{filtro, operacion}` → `{cambios:CambioPreview[], afectados}`

- [ ] **Step 1: Implementar `client.ts`** (fetch base con manejo de error)

```ts
// web/src/api/client.ts
const BASE = "/api";
export async function apiGet<T>(path: string): Promise<T> {
  const r = await fetch(BASE + path);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}
export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(BASE + path, {
    method: "POST",
    headers: body instanceof FormData ? undefined : { "Content-Type": "application/json" },
    body: body instanceof FormData ? body : JSON.stringify(body ?? {}),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}
```

- [ ] **Step 2: Implementar `lib/tipos.ts`** con las interfaces de los shapes de arriba (Totales, ItemCuadro, Insumo, CambioPreview, etc.).

- [ ] **Step 3: Implementar `lib/moneda.ts`**

```ts
// web/src/lib/moneda.ts
export const cop = (n: number) =>
  "$" + Math.round(n ?? 0).toLocaleString("es-CO");
export const pct = (x: number) => ((x ?? 0) * 100).toFixed(1) + "%";
```

- [ ] **Step 4: Implementar `corridas.ts` e `insumos.ts`** — funciones tipadas que llaman a `apiGet`/`apiPost` para cada endpoint del contrato (p. ej. `getStatus()`, `crearSample()`, `crearCorrida(form)`, `getCorrida(id)`, `getItem(id,seq)`, `confirmar(id,seq,apu)`, `listarInsumos(params)`, `getGrupos()`, `getFuentes()`, `getInsumo(id)`, `aplicarCambios(cambios)`, `importarPreview(form)`, `transformarPreview(body)`).

- [ ] **Step 5: Verificar typecheck/build**

Run: `cd web && npm run build`
Expected: compila sin errores de tipos.

- [ ] **Step 6: Commit**

```bash
git add web/src/api web/src/lib
git commit -m "feat(web): cliente API tipado + helpers de moneda"
```

**Aceptación:** todas las funciones del contrato existen y tipan; `npm run build` pasa.

---

### Task B3: Layout/shell + routing + chip de estado

**Files:**
- Create: `web/src/components/Layout.tsx`; Modify: `web/src/App.tsx`, `web/src/main.tsx`
- Add dep: `react-router-dom` (`cd web && npm i react-router-dom`)

**Contrato:**
- `App.tsx` define rutas: `/` (redirige a `/corridas`), `/corridas`, `/corridas/:id`, `/insumos`.
- `Layout.tsx`: barra superior delgada con el nombre "Armador de APUs" + chip de estado a la derecha que consume `getStatus()` y muestra `N insumos · N APUs · IA: habilitada|fallback`. Navegación lateral compacta (links a Corridas e Insumos, resaltando el activo). Área de contenido a ancho completo. **Sin cards** — usa una barra/sidebar simples.
- Densidad: tipografía base pequeña-media, paddings ajustados.

- [ ] **Step 1:** Instalar router, montar `<BrowserRouter>` en `main.tsx`, definir rutas en `App.tsx` dentro de `<Layout>`.
- [ ] **Step 2:** Implementar `Layout.tsx` (nav + header + `<Outlet/>`); el chip de estado carga `getStatus()` en un `useEffect`.
- [ ] **Step 3: Verificar**

Run: `cd web && npm run build`
Expected: compila. Manual (`npm run dev` con el backend corriendo en :8000): el chip muestra los conteos reales.

- [ ] **Step 4: Commit**

```bash
git add web/src web/package.json web/package-lock.json
git commit -m "feat(web): shell con navegación y chip de estado"
```

**Aceptación:** navegación entre Corridas e Insumos; el chip muestra conteos e IA desde `/api/status`.

---

## FASE C — Frontend: flujo de corrida

### Task C1: Página Inicio / Nueva corrida

**Files:**
- Create: `web/src/pages/CorridasInicio.tsx`

**Contrato:**
- Zona de carga: input file (`.xlsx,.csv`), selector de turno (DIURNO/NOCTURNO), toggle "usar IA". Botón "Armar" → `crearCorrida(FormData{archivo,turno,use_ai})` → `navigate('/corridas/'+id)`.
- Botón secundario "Usar ejemplo" → `crearSample()` → navega a la corrida.
- Spinner mientras arma; muestra error (toast) si falla.
- Sin cards: un formulario simple y compacto.

- [ ] **Step 1:** Implementar la página con los dos caminos (subir / ejemplo) y navegación al resultado.
- [ ] **Step 2: Verificar** (`npm run build`; manual con backend: "Usar ejemplo" crea corrida y navega).
- [ ] **Step 3: Commit**
```bash
git add web/src/pages/CorridasInicio.tsx
git commit -m "feat(web): página nueva corrida (subir / ejemplo)"
```
**Aceptación:** crear corrida por archivo y por ejemplo navega a `/corridas/:id`.

---

### Task C2: Página Corrida (cuadro) + panel de revisión

**Files:**
- Create: `web/src/pages/Corrida.tsx`, `web/src/components/corrida/TablaItems.tsx`, `web/src/components/corrida/PanelRevision.tsx`, `web/src/components/corrida/EstadoBadge.tsx`

**Contrato:**
- `Corrida.tsx` carga `getCorrida(id)`. Barra de totales arriba (contractual, costo, margen, margen %) usando `cop`/`pct`. 
- `TablaItems`: tabla **densa** (shadcn `Table`): columnas descripción · und · cantidad · APU (código) · estado (`EstadoBadge`) · contractual · costo · margen · %. Números monoespaciados, alineados a la derecha. Filtro "solo revisión" (status `review`/`new`) con contador "N por revisar". Click en fila REVIEW/NEW abre `PanelRevision`.
- `EstadoBadge`: badge de color pequeño — AUTO verde, REVIEW ámbar, NEW gris, CONFIRMED azul. (No card.)
- `PanelRevision` (shadcn `Dialog`/drawer): carga `getItem(id,seq)`; muestra descripción, APU propuesto + explicación, lista de candidatos con score (botón "Elegir" por candidato), y la composición costeada (tabla densa: insumo · und · rend · precio · costo · cruce). "Elegir/Confirmar" → `confirmar(id,seq,apu_codigo)` → refresca la corrida (totales + tabla).
- Botón "Descargar cuadro" → `window.open('/api/corridas/'+id+'/cuadro')`.

- [ ] **Step 1:** Implementar `EstadoBadge` + `TablaItems` (tabla densa, filtro, totales).
- [ ] **Step 2:** Implementar `PanelRevision` (candidatos + composición + confirmar) y `Corrida.tsx` que los une.
- [ ] **Step 3: Verificar** (`npm run build`; manual con backend: crear corrida por ejemplo → ver cuadro → abrir un ítem → confirmar → totales se actualizan → descargar xlsx).
- [ ] **Step 4: Commit**
```bash
git add web/src/pages/Corrida.tsx web/src/components/corrida
git commit -m "feat(web): cuadro de corrida + panel de revisión (confirmar/recostear)"
```
**Aceptación:** flujo de corrida completo desde la UI; confirmar recostea; descarga el Excel.

---

## FASE D — Frontend: módulo de insumos

### Task D1: Hook `useDirtyRows` + tabla editable de insumos (individual + batch)

**Files:**
- Create: `web/src/lib/useDirtyRows.ts`, `web/src/pages/Insumos.tsx`, `web/src/components/insumos/TablaInsumos.tsx`, `web/src/components/insumos/BarraFiltros.tsx`
- Test: `web/src/lib/useDirtyRows.test.ts` (Vitest)

**Contrato:**
- `useDirtyRows`: estado `{[insumo_id]: {precio?, fuente?}}` con `setCampo(id, campo, valor)`, `descartar()`, `cambios()` → `{insumo_id,precio,fuente}[]` (mezcla el valor editado con el actual de la fila), `count`.
- `BarraFiltros`: búsqueda `q` (debounced), dropdown grupo (`getGrupos()`), dropdown fuente (`getFuentes()`), filtro público/interno. Paginación (limit 100, prev/next por offset; muestra `total`).
- `TablaInsumos`: tabla **densa** — código · nombre · unidad · grupo · **precio (input numérico)** · **fuente (input/combobox)** · clasificación. Editar marca la fila sucia (resaltada). Barra de acción fija abajo: "N cambios sin guardar — [Guardar] [Descartar]". Guardar → `aplicarCambios(cambios())` → toast con `aplicados`/`errores`, recarga la lista y limpia dirty.
- Click en una fila (zona no editable) → detalle con historial (`getInsumo(id)`) en un drawer denso.

- [ ] **Step 1: Test del hook (Vitest)**

```ts
// web/src/lib/useDirtyRows.test.ts
import { renderHook, act } from "@testing-library/react";
import { useDirtyRows } from "./useDirtyRows";

test("marca, cuenta y produce cambios; descarta", () => {
  const filas = [{ id: 1, precio: 100, fuente: "A" }, { id: 2, precio: 200, fuente: "B" }];
  const { result } = renderHook(() => useDirtyRows(filas));
  act(() => result.current.setCampo(1, "precio", 150));
  expect(result.current.count).toBe(1);
  expect(result.current.cambios()).toEqual([{ insumo_id: 1, precio: 150, fuente: "A" }]);
  act(() => result.current.descartar());
  expect(result.current.count).toBe(0);
});
```

- [ ] **Step 2: Run test (fails)** — `cd web && npx vitest run src/lib/useDirtyRows.test.ts` → FAIL (no existe el hook).
- [ ] **Step 3: Implementar `useDirtyRows`** según el contrato (mezcla el campo editado con los valores actuales de `filas` al producir `cambios()`).
- [ ] **Step 4: Run test (passes).**
- [ ] **Step 5: Implementar `BarraFiltros`, `TablaInsumos`, `Insumos.tsx`** según el contrato.
- [ ] **Step 6: Verificar** (`npm run build`; manual con backend: filtrar, editar precio/fuente en varias filas, Guardar → toast, recarga; abrir detalle e historial).
- [ ] **Step 7: Commit**
```bash
git add web/src/lib/useDirtyRows.ts web/src/lib/useDirtyRows.test.ts web/src/pages/Insumos.tsx web/src/components/insumos
git commit -m "feat(web): grid editable de insumos (individual + batch) con historial"
```
**Aceptación:** filtrar/paginar; editar una o varias filas y Guardar aplica el batch con reporte; el historial refleja el cambio.

---

### Task D2: Diálogo "Transformar por filtro"

**Files:**
- Create: `web/src/components/insumos/DialogoTransformar.tsx`; Modify: `web/src/pages/Insumos.tsx` (botón que lo abre)

**Contrato:**
- Botón "Transformar" en `Insumos.tsx` abre el diálogo, pasándole el filtro actual.
- Diálogo: elegir operación — fuente → X (input texto), o precio: ×factor / +% / = valor (selector + input). "Previsualizar" → `transformarPreview({filtro, operacion})` → muestra `afectados` + tabla densa (código · nombre · precio_actual → precio_nuevo · fuente_actual → fuente_nueva). "Aplicar" → `aplicarCambios(preview.cambios.map(c => ({insumo_id:c.insumo_id, precio:c.precio_nuevo, fuente:c.fuente_nueva})))` → toast, cierra, recarga.

- [ ] **Step 1:** Implementar el diálogo (operación → preview → aplicar) y el botón en Insumos.
- [ ] **Step 2: Verificar** (`npm run build`; manual: transformar un grupo ±% y aplicar; los precios cambian).
- [ ] **Step 3: Commit**
```bash
git add web/src/components/insumos/DialogoTransformar.tsx web/src/pages/Insumos.tsx
git commit -m "feat(web): transformación masiva de insumos por filtro"
```
**Aceptación:** preview muestra afectados; aplicar persiste vía `/cambios`.

---

### Task D3: Diálogo "Importar Excel/CSV"

**Files:**
- Create: `web/src/components/insumos/DialogoImportar.tsx`; Modify: `web/src/pages/Insumos.tsx` (botón)

**Contrato:**
- Botón "Importar" abre el diálogo. Subir archivo → `importarPreview(FormData{archivo})` → tres secciones (tablas densas): **Reconocidos** (código · nombre · precio_actual → precio_nuevo · fuente_nueva), **Ambiguos** (código + candidatos), **No encontrados** (código). Botón "Aplicar los N reconocidos" → `aplicarCambios(reconocidos.map(...))` → toast, cierra, recarga. Ambiguos/no encontrados se muestran, no se aplican.

- [ ] **Step 1:** Implementar el diálogo (subir → preview tri-sección → aplicar reconocidos).
- [ ] **Step 2: Verificar** (`npm run build`; manual: importar un xlsx con un código válido y uno inexistente; aplica solo el válido).
- [ ] **Step 3: Commit**
```bash
git add web/src/components/insumos/DialogoImportar.tsx web/src/pages/Insumos.tsx
git commit -m "feat(web): importación de precios por Excel/CSV con preview"
```
**Aceptación:** preview separa reconocidos/ambiguos/no encontrados; aplica solo reconocidos.

---

### Task D4: Integración build + verificación end-to-end

**Files:**
- Modify: `.gitignore` (si hace falta), docs si aplica. (`web/dist` se genera, no se commitea.)

**Contrato:** confirmar que FastAPI sirve el frontend compilado y que el flujo completo corre en un proceso.

- [ ] **Step 1: Build del frontend**

Run: `cd web && npm run build`
Expected: genera `web/dist`.

- [ ] **Step 2: Levantar el server y verificar servido del SPA**

Run (raíz): `python run_web.py` (o `python -m uvicorn apu_tool.servicio.app:app --port 8000`).
Verifica: `GET /` devuelve el `index.html` del SPA (no 404); `GET /api/status` responde JSON; navegando, las dos secciones cargan.

- [ ] **Step 3: Smoke end-to-end (manual)**

Corrida: nueva corrida por ejemplo → cuadro → confirmar un ítem → descargar xlsx.
Insumos: filtrar → editar 2 precios → Guardar → ver historial; transformar un grupo ±% → aplicar; importar un xlsx pequeño → aplicar reconocidos.

- [ ] **Step 4: Suite Python**

Run: `python -m pytest tests/ -q`
Expected: verde.

- [ ] **Step 5: Commit (si hubo cambios de integración)**

```bash
git add -A
git commit -m "chore(web): integración build + verificación end-to-end"
```

**Aceptación:** un solo `python run_web.py` sirve la app en `/`; el flujo de corrida y los tres mecanismos de edición de insumos funcionan end-to-end.

---

## Self-Review

**1. Spec coverage:**
- Backend insumos (datos + servicio + endpoints): A1–A5. ✓
- `set_precio_por_id` por id + historial: A1. ✓
- `list_insumos`/grupos/fuentes: A2. ✓
- listar/detalle/aplicar_cambios: A3. ✓ preview import/transform: A4. ✓ endpoints: A5. ✓
- Frontend shell + nav + status: B1–B3. ✓
- Flujo de corrida (inicio, cuadro, panel revisión): C1–C2. ✓
- Insumos grid individual+batch: D1. ✓ transformar: D2. ✓ importar: D3. ✓
- Servido por FastAPI + run_web: D4. ✓
- Privacidad (servicio insumos sin `ai_assist`, sin IA): garantizado por el código de A3 (no importa ai_assist) y cubierto por el test existente `test_servicio_no_importa_ai_assist`. ✓
- Estética densa/sin cards: contrato en B3, C2, D1–D3. ✓
- Composición de APUs: explícitamente FUERA (Proyecto 2). ✓

**2. Placeholder scan:** backend con código completo; frontend con contrato + código de lógica/infra completo + criterios de aceptación + verificación ejecutando (convención declarada arriba, no vaguedad). Sin "TBD/TODO".

**3. Type consistency:** los shapes del contrato del cliente (B2) coinciden con lo que devuelven el backend v1 (`vista_corrida`, `detalle_item`) y los endpoints de insumos (A3–A5): `Insumo{id,codigo,nombre,unidad,grupo,precio,fuente,clasificacion}`, `CambioPreview{insumo_id,codigo,nombre,precio_actual,precio_nuevo,fuente_actual,fuente_nueva}`, `{aplicados,errores}`, `{cambios,ambiguos,no_encontrados}`, `{cambios,afectados}`. `aplicarCambios` consume `{insumo_id,precio,fuente}` igual que `CambioIn`. Consistente A↔B↔C↔D.
