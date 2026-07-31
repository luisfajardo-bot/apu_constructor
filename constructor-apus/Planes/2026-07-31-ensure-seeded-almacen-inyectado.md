> Espejo automático — no editar aquí. Fuente: `docs/superpowers/plans/2026-07-31-ensure-seeded-almacen-inyectado.md`

# `ensure_seeded` sobre el almacén inyectado — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que el auto-seed de la API trabaje sobre la misma base que el request en curso, y que cuando no pueda semillar responda un 409 entendible en vez de un 500.

**Architecture:** `dominio/pipeline.ensure_seeded()` gana un primer parámetro opcional `alm`; si viene, usa ese `Almacen` en vez de armarse uno con las rutas por defecto de `config`. Los 5 puntos que hoy lo llaman sin pasarlo (4 en `servicio/rutas.py`, 1 dentro de `generate_sample`) pasan el suyo. Cuando `seed()` no encuentra el Excel histórico, `ensure_seeded` levanta una excepción propia del dominio (`BibliotecaVacia`) que `rutas.py` traduce a HTTP 409 mediante un helper, siguiendo el patrón de `_validar_lista`.

**Tech Stack:** Python 3.12+, FastAPI, pytest. Sin dependencias nuevas.

**Spec:** `docs/superpowers/specs/2026-07-31-ensure-seeded-almacen-inyectado-design.md`

## Global Constraints

- **Invariante #1:** esto no toca la IA. No se construye ni modifica ningún payload hacia el modelo, no se agrega ningún campo monetario, `dominio/privacy.py` no se toca.
- **Español** en nombres de dominio, comentarios y mensajes de usuario.
- **CLI y GUI intactos:** los otros 5 llamados a `ensure_seeded()` (`run_pipeline`, `build_desde_presupuesto`, `cli.py:153`, `cli.py:160`, `cli.py:230`) NO se modifican. El default `alm=None` existe exactamente para que sigan funcionando igual.
- **Sin cambios de esquema, migraciones ni SQL.** No se toca `counts()`, ni el guard de `seed()`, ni el parche de tests de `bd5fece`.
- **No se toca el llamado duplicado** del camino `/sample` (el endpoint llama a `ensure_seeded` y `generate_sample` lo vuelve a llamar por dentro): es inofensivo porque cuando el primero termina la biblioteca ya no está vacía.
- **Mensaje exacto** de `BibliotecaVacia` (lo lee el usuario en la web, el frontend muestra el `detail` del backend):
  `La biblioteca de APUs está vacía y no hay Excel histórico en el servidor. Semilla la base antes de armar corridas (run_cli.py seed, o la variable APU_SOURCE_XLSX).`
- **Rama:** `fix/ensure-seeded-almacen-inyectado` (ya creada, con el spec commiteado).

## Estructura de archivos

| Archivo | Responsabilidad | Acción |
|---|---|---|
| `apu_tool/dominio/pipeline.py` | Orquestación de alto nivel. Acá viven `ensure_seeded`, `generate_sample` y la excepción nueva. | Modificar (Tasks 1 y 2) |
| `apu_tool/servicio/rutas.py` | Único `APIRouter`. Acá vive la traducción a HTTP. | Modificar (Task 3) |
| `tests/test_auto_seed_almacen_inyectado.py` | Toda la cobertura del defecto: nivel dominio (Tasks 1-2) y nivel HTTP (Task 3). | Crear (Task 1), extender (Tasks 2 y 3) |

No hay cambios de documentación: verificado que ni `CLAUDE.md` ni `docs/ARQUITECTURA.md` describen `ensure_seeded`.

---

### Task 1: `ensure_seeded` recibe el almacén y levanta `BibliotecaVacia`

**Files:**
- Create: `tests/test_auto_seed_almacen_inyectado.py`
- Modify: `apu_tool/dominio/pipeline.py:39-44`

**Interfaces:**
- Consumes: `Almacen` (`apu_tool.datos.almacen`), `seed` (`apu_tool.datos.seed`) — ya importados en `pipeline.py`.
- Produces:
  - `class BibliotecaVacia(Exception)` en `apu_tool/dominio/pipeline.py`
  - `ensure_seeded(alm: Optional[Almacen] = None, xlsx_path: Optional[Path] = None) -> dict`
  Task 2 y Task 3 dependen de esos dos nombres exactos.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_auto_seed_almacen_inyectado.py` con este contenido completo:

```python
"""El auto-seed trabaja sobre la base del request, no sobre una que se arma sola.

`ensure_seeded()` se construía su propio `Almacen()` con las rutas por defecto de
`config`, así que el guard (`alm.counts()["apus"] == 0`) preguntaba por una base y el
seed escribía en otra. Consecuencias reales: 4 tests de API en rojo en CI (bd5fece), un
pool de conexiones huérfano por disparo en producción, y la posibilidad de armar una
corrida contra una biblioteca vacía sin que nada avise.

Ver docs/superpowers/specs/2026-07-31-ensure-seeded-almacen-inyectado-design.md
"""
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.dominio import pipeline


def _alm_vacio(tmp_path) -> Almacen:
    """Almacén temporal SIN insumos ni APUs: es la condición que dispara el auto-seed
    (`ensure_seeded` solo semilla si las dos cuentas están en cero)."""
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def test_ensure_seeded_semilla_sobre_el_almacen_recibido(tmp_path, monkeypatch):
    alm = _alm_vacio(tmp_path)
    recibidos = []

    def fake_seed(almacen, **kwargs):
        recibidos.append(almacen)
        return {"apus": 0, "insumos": 0}

    monkeypatch.setattr(pipeline, "seed", fake_seed)

    pipeline.ensure_seeded(alm)

    assert recibidos, "no se llamó a seed"
    assert recibidos[0] is alm, "seed recibió otro almacén, no el que se le pasó"


def test_ensure_seeded_sin_almacen_usa_el_global(tmp_path, monkeypatch):
    """El default sigue existiendo: es lo que usan CLI y GUI, y no debe cambiar."""
    global_alm = _alm_vacio(tmp_path)
    monkeypatch.setattr(pipeline, "get_almacen", lambda: global_alm)
    recibidos = []
    monkeypatch.setattr(pipeline, "seed",
                        lambda almacen, **kw: (recibidos.append(almacen),
                                               {"apus": 0, "insumos": 0})[1])

    pipeline.ensure_seeded()

    assert recibidos[0] is global_alm


def test_sin_excel_historico_levanta_biblioteca_vacia(tmp_path, monkeypatch):
    """Sin fuente de la que semillar, el error tiene que ser explícito y del dominio.

    Antes salía un `FileNotFoundError` crudo que la API devolvía como 500.
    """
    monkeypatch.delenv("APU_SOURCE_XLSX", raising=False)   # detect_source_xlsx() -> None
    alm = _alm_vacio(tmp_path)

    with pytest.raises(pipeline.BibliotecaVacia) as exc:
        pipeline.ensure_seeded(alm)

    assert "biblioteca de APUs está vacía" in str(exc.value)


def test_biblioteca_poblada_no_semilla(tmp_path, monkeypatch):
    """No-regresión: con APUs en la biblioteca, ni se intenta semillar."""
    from apu_tool.nucleo.models import Apu
    alm = _alm_vacio(tmp_path)
    alm.apus.insert_apus([Apu("A1", "EXCAVACION", "M3", "DIURNO", "MT")])

    def explota(*a, **kw):
        raise AssertionError("no debía llamar a seed")

    monkeypatch.setattr(pipeline, "seed", explota)

    assert pipeline.ensure_seeded(alm)["apus"] == 1
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `python -m pytest tests/test_auto_seed_almacen_inyectado.py -v`

Expected: FAIL.
- `test_ensure_seeded_semilla_sobre_el_almacen_recibido` → `TypeError: ensure_seeded() takes ... positional arguments` (hoy el primer parámetro es `xlsx_path`).
- `test_sin_excel_historico_levanta_biblioteca_vacia` → `AttributeError: module 'apu_tool.dominio.pipeline' has no attribute 'BibliotecaVacia'`.

- [ ] **Step 3: Implementar en `apu_tool/dominio/pipeline.py`**

Reemplazar la función `ensure_seeded` (líneas 39-44) por la excepción + la función nuevas:

```python
class BibliotecaVacia(Exception):
    """La biblioteca de APUs está vacía y no hay Excel histórico del que semillarla."""


def ensure_seeded(alm: Optional[Almacen] = None,
                  xlsx_path: Optional[Path] = None) -> dict:
    """Semilla si las bases están vacías; si no, devuelve los conteos actuales.

    `alm` es la base sobre la que trabajar. Los endpoints DEBEN pasar la del request
    (`Depends(get_almacen)`): antes esta función se armaba su propio `Almacen()` con las
    rutas por defecto de `config`, así que el guard preguntaba por una base y el seed
    escribía en otra — eso dejó 4 tests en rojo en CI y, en producción, un pool de
    conexiones huérfano por cada disparo. Sin `alm` se arma el global, que es lo correcto
    para CLI y GUI.
    """
    alm = alm or get_almacen()
    if alm.counts()["apus"] == 0 and alm.counts()["insumos"] == 0:
        try:
            return seed(alm, xlsx_path=xlsx_path)
        except FileNotFoundError as e:
            # Semillar necesita el Excel histórico, que no existe en el servidor: el
            # error tiene que decir qué hacer, no ser un 500 con un traceback.
            raise BibliotecaVacia(
                "La biblioteca de APUs está vacía y no hay Excel histórico en el "
                "servidor. Semilla la base antes de armar corridas "
                "(run_cli.py seed, o la variable APU_SOURCE_XLSX).") from e
    return alm.counts()
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `python -m pytest tests/test_auto_seed_almacen_inyectado.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 5: Correr la suite completa (no debe romperse nada del CLI)**

Run: `python -m pytest tests/ -q`
Expected: PASS. Referencia antes de empezar: 652 passed (o 646 passed + 6 skipped si no hay `TEST_DATABASE_URL`).

- [ ] **Step 6: Commit**

```bash
git add tests/test_auto_seed_almacen_inyectado.py apu_tool/dominio/pipeline.py
git commit -m "fix(pipeline): ensure_seeded semilla sobre el almacén recibido"
```

---

### Task 2: `generate_sample` pasa su almacén al llamado interno

**Files:**
- Modify: `apu_tool/dominio/pipeline.py:109-110`
- Test: `tests/test_auto_seed_almacen_inyectado.py` (agregar un test al final)

**Interfaces:**
- Consumes: `pipeline.ensure_seeded(alm=None, xlsx_path=None)` y `pipeline.BibliotecaVacia` de la Task 1; `pipeline.generate_sample(n=15, margen=0.18, seed=7, out_path=None, alm=None)`, que ya existe con esa firma.
- Produces: nada nuevo. Solo corrige el llamado interno.

- [ ] **Step 1: Escribir el test que falla**

Agregar al final de `tests/test_auto_seed_almacen_inyectado.py`:

```python
def test_generate_sample_pasa_su_almacen_al_auto_seed(tmp_path, monkeypatch):
    """`generate_sample` recibe un almacén (los endpoints le pasan el del request) y
    decide con `db_is_empty(alm)`, pero llamaba a `ensure_seeded()` sin pasarlo: misma
    divergencia guard/acción. Se corta la ejecución en el propio ensure_seeded para no
    depender de nada de lo que hace generate_sample después.
    """
    class Corte(Exception):
        pass

    recibidos = []

    def fake_ensure(alm=None, xlsx_path=None):
        recibidos.append(alm)
        raise Corte

    monkeypatch.setattr(pipeline, "ensure_seeded", fake_ensure)
    alm = _alm_vacio(tmp_path)          # 0 APUs -> db_is_empty(alm) es True

    with pytest.raises(Corte):
        pipeline.generate_sample(out_path=tmp_path / "sample.xlsx", alm=alm)

    assert recibidos == [alm], "generate_sample no le pasó su almacén a ensure_seeded"
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python -m pytest tests/test_auto_seed_almacen_inyectado.py::test_generate_sample_pasa_su_almacen_al_auto_seed -v`
Expected: FAIL con `assert [None] == [<Almacen...>]` (hoy llama a `ensure_seeded()` sin argumentos, así que el espía recibe `None`).

- [ ] **Step 3: Implementar**

En `apu_tool/dominio/pipeline.py`, dentro de `generate_sample`, cambiar la línea 110:

```python
    alm = alm or get_almacen()
    if db_is_empty(alm):
        ensure_seeded(alm)       # ← antes: ensure_seeded()
```

- [ ] **Step 4: Correr el test y la suite**

Run: `python -m pytest tests/test_auto_seed_almacen_inyectado.py -v`
Expected: PASS, 5 tests.

Run: `python -m pytest tests/ -q`
Expected: PASS, sin fallos nuevos.

- [ ] **Step 5: Commit**

```bash
git add tests/test_auto_seed_almacen_inyectado.py apu_tool/dominio/pipeline.py
git commit -m "fix(pipeline): generate_sample pasa su almacén al auto-seed"
```

---

### Task 3: La API semilla sobre la base del request y responde 409

**Files:**
- Modify: `apu_tool/servicio/rutas.py` — el import de la línea 20, los 4 llamados (líneas 140-141, 165-166, 206-207, 232-233) y un helper nuevo junto a `_validar_lista` (después de la línea 356)
- Test: `tests/test_auto_seed_almacen_inyectado.py` (agregar bloque de tests de API)

**Interfaces:**
- Consumes: `pipeline.ensure_seeded(alm)` y `pipeline.BibliotecaVacia` (Task 1); `cliente()` de `tests/conftest.py`; `create_app(almacen=...)` de `apu_tool.servicio.app`.
- Produces: `_asegurar_biblioteca(alm: Almacen) -> None` en `apu_tool/servicio/rutas.py` (privado del módulo; nadie más la consume).

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de `tests/test_auto_seed_almacen_inyectado.py`:

```python
# --------------------------------------------------------------------- nivel HTTP
from apu_tool.dominio.licitacion import write_sample_licitacion          # noqa: E402
from apu_tool.nucleo.models import LicitacionItem                        # noqa: E402
from apu_tool.servicio.app import create_app                             # noqa: E402
from tests.conftest import cliente                                       # noqa: E402

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _cli_vacio(tmp_path, monkeypatch):
    """Cliente HTTP contra un almacén vacío y sin Excel histórico a la vista."""
    monkeypatch.delenv("APU_SOURCE_XLSX", raising=False)
    alm = _alm_vacio(tmp_path)
    return cliente(create_app(almacen=alm), rol="admin"), alm


def _xlsx_lic(tmp_path):
    p = tmp_path / "lic.xlsx"
    write_sample_licitacion(p, [LicitacionItem(
        item="1", descripcion="EXCAVACION MANUAL", unidad="M3", cantidad=10.0,
        precio_contractual=400000.0, shift="DIURNO")])
    return p


def _post_corrida(cli, tmp_path, ruta="/api/corridas"):
    obra = cli.post("/api/carpetas", json={"nombre": "Obra"}).json()
    with open(_xlsx_lic(tmp_path), "rb") as f:
        return cli.post(ruta,
                        data={"turno": "DIURNO", "use_ai": "false",
                              "carpeta_id": str(obra["id"])},
                        files={"archivo": ("lic.xlsx", f, _XLSX)})


def test_post_corridas_biblioteca_vacia_da_409(tmp_path, monkeypatch):
    cli, _ = _cli_vacio(tmp_path, monkeypatch)
    r = _post_corrida(cli, tmp_path)
    assert r.status_code == 409, r.text
    assert "biblioteca de APUs está vacía" in r.json()["detail"]


def test_post_corridas_stream_biblioteca_vacia_da_409(tmp_path, monkeypatch):
    cli, _ = _cli_vacio(tmp_path, monkeypatch)
    r = _post_corrida(cli, tmp_path, ruta="/api/corridas/stream")
    assert r.status_code == 409, r.text


def test_post_sample_biblioteca_vacia_da_409(tmp_path, monkeypatch):
    cli, _ = _cli_vacio(tmp_path, monkeypatch)
    r = cli.post("/api/sample")
    assert r.status_code == 409, r.text


def test_post_sample_stream_biblioteca_vacia_da_409(tmp_path, monkeypatch):
    cli, _ = _cli_vacio(tmp_path, monkeypatch)
    r = cli.post("/api/sample/stream")
    assert r.status_code == 409, r.text


def test_api_semilla_sobre_el_almacen_del_request(tmp_path, monkeypatch):
    """EL test que faltaba: el que habría atrapado el rojo de CI de bd5fece.

    Con un Excel disponible, el seed que dispara la API tiene que caer en la base del
    request — no en `data/*.db`, que es la del desarrollador (y en CI no existe).
    """
    cli, alm = _cli_vacio(tmp_path, monkeypatch)
    recibidos = []
    monkeypatch.setattr(pipeline, "seed",
                        lambda almacen, **kw: (recibidos.append(almacen),
                                               {"apus": 0, "insumos": 0})[1])

    _post_corrida(cli, tmp_path)

    assert recibidos, "la API no intentó semillar"
    assert recibidos[0] is alm, "semilló sobre otra base, no la del request"
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `python -m pytest tests/test_auto_seed_almacen_inyectado.py -v -k "409 or request"`

Expected: FAIL, los 5. Ojo con **cómo** fallan, porque depende del entorno:
- Con `data/*.db` semillada (máquina del dev): los de 409 llegan **200** (el auto-seed se fue a `data/`, que tiene datos, y no levantó nada), y `test_api_semilla_sobre_el_almacen_del_request` falla con `recibidos == []` (nunca llamó a seed, porque la base global no estaba vacía).
- Con `data/` vacía (CI): los de 409 llegan **500** (`FileNotFoundError`).
En ninguno de los dos casos hay un 409: eso es lo que el arreglo trae.

- [ ] **Step 3: Implementar en `apu_tool/servicio/rutas.py`**

3a. Cambiar el import de la línea 20:

```python
from apu_tool.dominio.pipeline import BibliotecaVacia, ensure_seeded, generate_sample
```

3b. Agregar el helper inmediatamente después de `_validar_lista` (que termina en la línea 356):

```python
def _asegurar_biblioteca(alm: Almacen) -> None:
    """Auto-seed sobre LA base del request, y 409 si no hay de dónde semillar.

    `ensure_seeded` sin argumentos se armaba su propio `Almacen()` con las rutas por
    defecto de config: el guard preguntaba por esta base y el seed escribía en otra. El
    409 (no 500) es porque no es un pedido mal formado ni un fallo del servidor: es que
    el estado del sistema todavía no permite la operación."""
    if alm.counts().get("apus", 0) != 0:
        return
    try:
        ensure_seeded(alm)
    except BibliotecaVacia as e:
        raise HTTPException(status_code=409, detail=str(e))
```

3c. Reemplazar los 4 llamados. En cada uno de los cuatro endpoints (`crear_corrida` ~línea 140, `crear_sample` ~165, `crear_corrida_stream` ~206, `crear_sample_stream` ~232), cambiar estas dos líneas:

```python
    if alm.counts().get("apus", 0) == 0:
        ensure_seeded()
```

por esta una:

```python
    _asegurar_biblioteca(alm)
```

Cuidado: son 4 ocurrencias idénticas del mismo par de líneas, así que hay que reemplazarlas una por una (no con un replace global a ciegas) y confirmar al final que quedaron 4 llamados a `_asegurar_biblioteca` y ninguno a `ensure_seeded()` sin argumentos en ese archivo:

```bash
grep -n "_asegurar_biblioteca\|ensure_seeded" apu_tool/servicio/rutas.py
```
Expected: la definición del helper, 4 llamados a `_asegurar_biblioteca(alm)`, el import, y el `ensure_seeded(alm)` de dentro del helper. Ningún `ensure_seeded()` pelado.

- [ ] **Step 4: Correr los tests nuevos y verificar que pasan**

Run: `python -m pytest tests/test_auto_seed_almacen_inyectado.py -v`
Expected: PASS, 10 tests.

- [ ] **Step 5: Correr la suite completa**

Run: `python -m pytest tests/ -q`
Expected: PASS. Atención a `tests/test_api_corridas.py`, `test_api_lista_invalida.py` y `test_api_lista_wiring.py`: son los que ejercitan estos 4 endpoints y no deben moverse.

- [ ] **Step 6: Commit**

```bash
git add tests/test_auto_seed_almacen_inyectado.py apu_tool/servicio/rutas.py
git commit -m "fix(api): auto-seed sobre la base del request y 409 si no puede semillar"
```

---

### Task 4: Verificación final en las condiciones de CI

**Files:** ninguno (solo verificación). Si algo falla, se arregla en la task correspondiente.

**Interfaces:**
- Consumes: todo lo anterior.
- Produces: nada.

- [ ] **Step 1: Backend con Postgres real, como CI**

CI corre con `TEST_DATABASE_URL` apuntando a un Postgres efímero. Si hay uno a mano:

Run: `TEST_DATABASE_URL='postgresql://postgres@127.0.0.1:55433/apu_test' python -m pytest tests/ -q`
Expected: PASS, 0 skipped. (Sin Postgres: `python -m pytest tests/ -q` y esperar 14 skipped, todos de Postgres.)

- [ ] **Step 2: Backend con el almacén por defecto VACÍO (la condición que rompió CI)**

En la máquina del desarrollador `data/*.db` está semillada y tapa esta clase de bug. Para reproducir CI **sin borrar ni mover `data/`**, crear este plugin de pytest en una carpeta temporal (NO en el repo):

```python
# plugin_ci_vacio.py
import tempfile
from pathlib import Path

import apu_tool.datos.almacen as almacen_mod

_d = Path(tempfile.mkdtemp(prefix="ci_vacio_"))
almacen_mod.Almacen.__init__.__defaults__ = (
    _d / "precios.db", _d / "apus.db", _d / "corridas.db")
```

(Los defaults se ligan en tiempo de import, así que monkeypatchear `config` no alcanza.)

Run: `PYTHONPATH=<carpeta del plugin> python -m pytest -p plugin_ci_vacio tests/ -q`
Expected: PASS. Este paso es el que prueba que el arreglo es real: con la base global vacía, los tests de API tienen que seguir en verde porque ya no la tocan.

- [ ] **Step 3: Frontend, los 3 pasos del job (no debería cambiar nada, pero CI los corre)**

```bash
cd web && npx vitest run && npm run build && npx oxlint
```
Expected: vitest 126 passed, build OK, oxlint exit 0.

- [ ] **Step 4: Confirmar que CLI y GUI no se movieron**

Run: `grep -n "ensure_seeded" apu_tool/interfaz/cli.py apu_tool/dominio/pipeline.py`
Expected: los 3 llamados de `cli.py` (líneas ~153, ~160, ~230) y los 2 de `pipeline.py` (`run_pipeline`, `build_desde_presupuesto`) siguen **sin argumentos**, tal como estaban. El único llamado con argumento dentro de `pipeline.py` es el de `generate_sample`.

Run: `python run_cli.py status`
Expected: corre sin error y muestra los conteos.

- [ ] **Step 5: Commit (solo si hubo que ajustar algo)**

```bash
git add -A && git commit -m "test: verificación final del auto-seed sobre el almacén inyectado"
```

---

## Antes de mergear

1. Los 4 pasos de `.github/workflows/ci.yml` en verde localmente (Task 4).
2. Revisión del diff completo: `git diff master...fix/ensure-seeded-almacen-inyectado`.
3. **Aprobación explícita del usuario** antes de mergear a `master` y antes de pushear: `master` auto-despliega a producción en Render.
4. No hay migración ni paso manual en Supabase: este cambio no toca esquema.
