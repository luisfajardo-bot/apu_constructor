> Espejo automático — no editar aquí. Fuente: `docs/superpowers/plans/2026-08-10-alta-sin-duplicados.md`

# Alta sin duplicados (insumos y APUs) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que el alta de un insumo o de un APU rechace el código repetido y el nombre repetido, con una excepción para el par día/noche, tanto desde el formulario como desde el import de Excel.

**Architecture:** La regla vive en `apu_tool/servicio/autoria.py` como tres helpers que devuelven **el motivo en español o `None`** (`_base_codigo`, `_conflicto_insumo`, `_conflicto_apu`). Una sola implementación sirve a los dos backends y al mismo tiempo deja fuera al `seed`, que tiene que poder seguir cargando el histórico —que ya trae 652 códigos repetidos—. Los helpers aceptan las filas ya leídas (`extra` / `index`) para que un import haga una lectura en total, no una por fila.

**Tech Stack:** Python 3 + FastAPI + SQLite/psycopg (dos backends espejo), pytest; React 19 + TypeScript + vitest.

**Spec:** `docs/superpowers/specs/2026-08-10-sin-duplicados-alta-design.md`

## Global Constraints

- **Rama:** `feat/alta-sin-duplicados`, creada desde `master`. No se hace push a `master` sin aprobación explícita del usuario (auto-despliega).
- **Español** en nombres de dominio, comentarios y mensajes de usuario.
- **Sin dependencias nuevas.** Nada de librerías: stdlib + lo que ya está.
- **Los dos backends van juntos.** Todo método nuevo del repositorio se agrega al `Protocol` de `apu_tool/datos/repositorio.py` y se implementa en SQLite **y** en Postgres. `tests/test_paridad_backends.py` compara firmas contra el Protocol y falla en CI si falta uno.
- **No se toca** `seed`, `insert_insumos`, ni el check de `(codigo, nombre_norm)` que ya está en `precios_db._crear_insumo` / `precios_pg._crear_insumo` (es la última red).
- **No se toca la identidad de los datos existentes.** Cero migraciones, cero limpieza de los 652 códigos repetidos.
- `normalizar` es siempre `apu_tool.nucleo.texto.normalizar`. Nunca `.upper()` a mano.
- `ValueError` en `autoria.py` → 400 ya cableado en `rutas.py`. No hay que tocar rutas.
- Verificación de cada tarea: `python -m pytest tests/ -q`. Las tareas de frontend además: `cd web && npm run build` (es `tsc -b`, no `tsc --noEmit`) y `npx vitest run`.

---

### Task 1: `identidades_en_conflicto` en el contrato y los dos backends

Una consulta que responde los dos lados del chequeo (código y nombre) y devuelve
`oculto`, que `get_candidatos` no puede dar porque el modelo `Insumo` no tiene ese campo.

**Files:**
- Modify: `apu_tool/datos/repositorio.py` (dentro de `class RepositorioPrecios`, después de `todos_no_ocultos`, línea 65-67)
- Modify: `apu_tool/datos/precios_db.py` (después de `todos_no_ocultos`, línea 226-230)
- Modify: `apu_tool/datos/pg/precios_pg.py` (en el mismo lugar relativo: después de su `todos_no_ocultos`)
- Test: `tests/test_repositorios_contrato.py` (la batería corre contra SQLite siempre y contra Postgres si hay `TEST_DATABASE_URL`)

**Interfaces:**
- Consumes: nada.
- Produces: `RepositorioPrecios.identidades_en_conflicto(codigo: str, nombre_norm: str) -> list[tuple[str, str, bool]]`, cada tupla `(codigo, nombre, oculto)`.

- [ ] **Step 1: Crear la rama**

```bash
git checkout master
git checkout -b feat/alta-sin-duplicados
```

- [ ] **Step 2: Escribir los tests que fallan**

En `tests/test_repositorios_contrato.py`, agregar el import que falta arriba del archivo:

```python
from apu_tool.nucleo.texto import normalizar
```

y los tests al final del archivo:

```python
def test_identidades_en_conflicto_por_codigo_y_por_nombre(repos):
    p, _a = repos
    p.insert_insumos([
        Insumo("100", "CEMENTO GRIS", "KG", "MAT", 1000, "PRECIO IDU"),
        Insumo("200", "ARENA DE PEÑA", "M3", "MAT", 50000, "PRECIO IDU")])
    # choca por código, aunque el nombre no tenga nada que ver
    assert p.identidades_en_conflicto("100", normalizar("OTRA COSA")) == [
        ("100", "CEMENTO GRIS", False)]
    # choca por nombre normalizado: tildes y caso plegados
    assert p.identidades_en_conflicto("999", normalizar("arena de peña")) == [
        ("200", "ARENA DE PEÑA", False)]
    # no choca con nada
    assert p.identidades_en_conflicto("999", normalizar("NADA QUE VER")) == []


def test_identidades_en_conflicto_incluye_los_ocultos(repos):
    """El motor de precios ve los ocultos (get_candidatos no filtra `oculto`), así que
    un código repetido con uno oculto deja el cruce ambiguo igual que con uno visible."""
    p, _a = repos
    p.insert_insumos([Insumo("300", "TRANSPORTE DE MATERIAL", "M3K", "TRA", 500, "PRECIO IDU")])
    iid = p.get_candidatos("300")[0].id
    p.set_oculto(iid, True)
    assert p.identidades_en_conflicto("300", normalizar("X")) == [
        ("300", "TRANSPORTE DE MATERIAL", True)]
```

- [ ] **Step 3: Correr los tests y verificar que fallan**

Run: `python -m pytest tests/test_repositorios_contrato.py -k identidades -v`
Expected: FAIL con `AttributeError: 'PreciosDB' object has no attribute 'identidades_en_conflicto'`

- [ ] **Step 4: Agregar el método al Protocol**

En `apu_tool/datos/repositorio.py`, dentro de `class RepositorioPrecios`, justo después de `todos_no_ocultos`:

```python
    def identidades_en_conflicto(self, codigo: str,
                                 nombre_norm: str) -> list[tuple[str, str, bool]]:
        """`(codigo, nombre, oculto)` de los insumos cuyo código O `nombre_norm` coincide.

        Los dos lados del chequeo de duplicados del alta (`servicio/autoria.py`) en una
        sola consulta. Incluye los ocultos a propósito: `get_candidatos` no filtra
        `oculto`, o sea que el motor de precios los ve, y un código repetido con uno
        oculto deja el cruce igual de ambiguo que con uno visible."""
        ...
```

- [ ] **Step 5: Implementar en SQLite**

En `apu_tool/datos/precios_db.py`, después de `todos_no_ocultos`:

```python
    def identidades_en_conflicto(self, codigo: str,
                                 nombre_norm: str) -> list[tuple[str, str, bool]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT codigo, nombre, oculto FROM insumos "
                "WHERE codigo = ? OR nombre_norm = ? ORDER BY id",
                (str(codigo), nombre_norm)).fetchall()
        # `oculto` es INTEGER en SQLite y BOOLEAN en Postgres: se normaliza acá para que
        # el contrato devuelva lo mismo en los dos backends.
        return [(r["codigo"], r["nombre"], bool(r["oculto"])) for r in rows]
```

- [ ] **Step 6: Implementar en Postgres**

En `apu_tool/datos/pg/precios_pg.py`, en el mismo lugar relativo:

```python
    def identidades_en_conflicto(self, codigo: str,
                                 nombre_norm: str) -> list[tuple[str, str, bool]]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT codigo, nombre, oculto FROM precios.insumos "
                "WHERE codigo = %s OR nombre_norm = %s ORDER BY id",
                (str(codigo), nombre_norm)).fetchall()
        return [(r["codigo"], r["nombre"], bool(r["oculto"])) for r in rows]
```

- [ ] **Step 7: Correr los tests y verificar que pasan**

Run: `python -m pytest tests/test_repositorios_contrato.py tests/test_paridad_backends.py -q`
Expected: PASS. `test_paridad_backends.py` confirma que el método existe con la misma firma en los dos backends.

- [ ] **Step 8: Commit**

```bash
git add apu_tool/datos/repositorio.py apu_tool/datos/precios_db.py apu_tool/datos/pg/precios_pg.py tests/test_repositorios_contrato.py
git commit -m "feat(datos): identidades_en_conflicto para el chequeo de duplicados del alta"
```

---

### Task 2: la regla, y el alta individual de insumos

**Files:**
- Modify: `apu_tool/servicio/autoria.py` (helpers nuevos después de `PISO_HIST`, línea 34; y `crear_insumo`, línea 38-59)
- Test: `tests/test_autoria_sin_duplicados.py` (nuevo)

**Interfaces:**
- Consumes: `alm.precios.identidades_en_conflicto(codigo, nombre_norm)` de Task 1.
- Produces:
  - `_base_codigo(codigo: str) -> str`
  - `_es_gemelo_nocturno(codigo_nuevo: str, codigo_existente: str) -> bool`
  - `_corto(texto: str, n: int = 60) -> str`
  - `_conflicto_insumo(alm, codigo: str, nombre: str, extra: Sequence[tuple[str, str, bool]] = ()) -> Optional[str]`

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_autoria_sin_duplicados.py`:

```python
"""Alta sin duplicados: el código y el nombre no se repiten, salvo el par día/noche.

Spec: docs/superpowers/specs/2026-08-10-sin-duplicados-alta-design.md
"""
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, Insumo
from apu_tool.servicio import autoria


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo("4859", "BORDE CONTENEDOR DE RAICES A 70", "ML", "SARD", 90000, "PRECIO IDU"),
        Insumo("10014", "USO DEL PENETROMETRO DINAMICO DE CONO", "UN", "ENS", 5000, "PRECIO IDU")])
    return alm


def _nuevo(codigo, nombre):
    return {"codigo": codigo, "nombre": nombre, "unidad": "ML", "grupo": "SARD",
            "precio": 1000, "fuente": "PRECIO IDU"}


def test_codigo_tomado_rechaza_aunque_el_nombre_sea_otro(tmp_path):
    """El caso real: 10014 es a la vez el penetrómetro y la estabilización de subrasante.
    Hoy la identidad es (código, nombre), así que esto se creaba."""
    alm = _alm(tmp_path)
    with pytest.raises(ValueError, match="10014"):
        autoria.crear_insumo(alm, _nuevo("10014", "ESTABILIZACION DE SUBRASANTE CON RAJON"))


def test_codigo_tomado_por_un_insumo_oculto_tambien_rechaza(tmp_path):
    alm = _alm(tmp_path)
    iid = alm.precios.get_candidatos("10014")[0].id
    alm.precios.set_oculto(iid, True)
    with pytest.raises(ValueError, match="oculto"):
        autoria.crear_insumo(alm, _nuevo("10014", "OTRA COSA DISTINTA"))


def test_nombre_tomado_con_codigo_sin_relacion_rechaza(tmp_path):
    alm = _alm(tmp_path)
    with pytest.raises(ValueError, match="4859"):
        autoria.crear_insumo(alm, _nuevo("7777", "BORDE CONTENEDOR DE RAICES A 70"))


def test_nombre_tomado_ignora_tildes_y_caso(tmp_path):
    alm = _alm(tmp_path)
    with pytest.raises(ValueError):
        autoria.crear_insumo(alm, _nuevo("7777", "borde contenedor de raíces a 70"))


def test_gemelo_nocturno_puede_repetir_el_nombre(tmp_path):
    """4859 y 4859 N son el mismo trabajo de día y de noche: se llaman igual a propósito."""
    alm = _alm(tmp_path)
    out = autoria.crear_insumo(alm, _nuevo("4859 N", "BORDE CONTENEDOR DE RAICES A 70"))
    assert out["codigo"] == "4859 N"


def test_el_mensaje_del_nombre_sugiere_el_codigo_nocturno(tmp_path):
    alm = _alm(tmp_path)
    with pytest.raises(ValueError, match="7777 N"):
        autoria.crear_insumo(alm, _nuevo("7777", "BORDE CONTENEDOR DE RAICES A 70"))
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `python -m pytest tests/test_autoria_sin_duplicados.py -v`
Expected: FAIL. Los de código/nombre tomado no lanzan nada (hoy se crean); el del oculto tampoco.

- [ ] **Step 3: Escribir los helpers**

En `apu_tool/servicio/autoria.py`, justo después de `PISO_HIST = 1.0` (línea 34). Agregar
`Sequence` al import de typing de la cabecera (`from typing import Optional, Sequence`):

```python
# ------------------------------------------------ unicidad de código y de nombre
# Regla del alta: ni el código ni el nombre se repiten. La excepción es el par
# nocturno, que comparte nombre A PROPÓSITO: el insumo "4859 N" es la tarifa de noche
# del "4859" y se llama igual (hay ~500 pares así en la base, y 499 pares
# DIURNO/NOCTURNO entre los APUs). Ver
# docs/superpowers/specs/2026-08-10-sin-duplicados-alta-design.md
#
# El `seed` NO pasa por acá, y es a propósito: el histórico trae 652 códigos
# repetidos y tiene que poder seguir cargándose.


def _base_codigo(codigo: str) -> str:
    """El código sin la marca nocturna: "4859 N" -> "4859". Idempotente.

    OJO: a diferencia de `baseDe()` en web/src/lib/duplicarApu.ts, esto NO quita el
    sufijo de copia "-2". Si lo quitara, un "3454-2" podría reclamar el nombre del
    "3454" y la excepción dejaría de significar "el gemelo nocturno" para significar
    "cualquier copia"."""
    c = str(codigo or "").strip()
    return c[:-2].rstrip() if c.upper().endswith(" N") else c


def _es_gemelo_nocturno(codigo_nuevo: str, codigo_existente: str) -> bool:
    """True si los dos códigos son el par día/noche del mismo trabajo ("4859" y
    "4859 N"), el único caso en que se permite repetir el nombre."""
    a, b = str(codigo_nuevo or "").strip(), str(codigo_existente or "").strip()
    return (a.upper() != b.upper()
            and _base_codigo(a).upper() == _base_codigo(b).upper())


def _corto(texto: str, n: int = 60) -> str:
    """Nombre recortado para el mensaje: los del catálogo pasan de 200 caracteres y
    el mensaje termina en un toast."""
    t = " ".join(str(texto or "").split())
    return t if len(t) <= n else t[:n - 1].rstrip() + "…"


def _conflicto_insumo(alm: Almacen, codigo: str, nombre: str,
                      extra: Sequence[tuple[str, str, bool]] = ()) -> Optional[str]:
    """El motivo en español si el alta choca con un insumo existente, o None.

    Devuelve el motivo y no un bool porque el mismo texto lo usan el 400 del
    formulario y el balde `conflicto` del preview del import: se escribe una vez.

    `extra` son filas `(codigo, nombre, oculto)` que todavía no están en la base pero
    ya se van a crear —las filas anteriores del mismo Excel—, para que el preview no
    diga "crear 2" cuando el aplicar va a crear 1."""
    cod = str(codigo or "").strip()
    nn = normalizar(nombre)
    filas = list(alm.precios.identidades_en_conflicto(cod, nn))
    filas += [r for r in extra if r[0] == cod or normalizar(r[1]) == nn]
    por_nombre = None
    for c, nom, oculto in filas:
        if c == cod:
            que = "un insumo oculto:" if oculto else "el insumo"
            return f"El código {cod} ya lo usa {que} «{_corto(nom)}»."
        if normalizar(nom) == nn and not _es_gemelo_nocturno(cod, c):
            por_nombre = por_nombre or c
    if por_nombre:
        return (f"Ese nombre ya lo usa el insumo {por_nombre}. "
                f"Si es la tarifa nocturna, usa el código {_base_codigo(por_nombre)} N.")
    return None
```

- [ ] **Step 4: Engancharlo en `crear_insumo`**

En `apu_tool/servicio/autoria.py::crear_insumo`, después de la validación del precio y
antes de construir el `Insumo`:

```python
    precio = _to_float(datos.get("precio"))
    if precio <= 0:
        raise ValueError(MSG_PRECIO_POSITIVO)
    # Después de las validaciones locales: si el payload es basura no vale un viaje a la base.
    motivo = _conflicto_insumo(alm, codigo, nombre)
    if motivo:
        raise ValueError(motivo)
    ins = Insumo(codigo=codigo, nombre=nombre,
```

- [ ] **Step 5: Correr los tests y verificar que pasan**

Run: `python -m pytest tests/test_autoria_sin_duplicados.py -v`
Expected: PASS los 6.

- [ ] **Step 6: Correr la suite completa**

Run: `python -m pytest tests/ -q`
Expected: PASS. Si algún test existente crea dos insumos que chocan entre sí (buscar
`crear_insumo` en `tests/test_servicio_autoria.py`, `tests/test_api_autoria.py`,
`tests/test_servicio_insumos_lista.py`), corregir **el test** para usar códigos y nombres
distintos: la regla nueva es el comportamiento correcto, no el test.

- [ ] **Step 7: Commit**

```bash
git add apu_tool/servicio/autoria.py tests/test_autoria_sin_duplicados.py
git commit -m "feat(autoria): el alta de insumos rechaza codigo y nombre repetidos"
```

---

### Task 3: el alta individual de APUs

**Files:**
- Modify: `apu_tool/servicio/autoria.py` (`_conflicto_apu` nuevo junto a los helpers de Task 2; `_origen_duplicado` línea 128-148; `crear_apu` línea 151-175)
- Test: `tests/test_autoria_sin_duplicados.py`

**Interfaces:**
- Consumes: `_base_codigo`, `_es_gemelo_nocturno`, `_corto` de Task 2; `alm.apus.apu_index() -> list[tuple[str, str, str]]` con `(codigo, nombre, turno)`, que ya existe en los dos backends.
- Produces: `_conflicto_apu(alm, codigo: str, turno: str, nombre: str, index: Optional[list[tuple[str, str, str]]] = None) -> Optional[str]`

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `tests/test_autoria_sin_duplicados.py`:

```python
# ------------------------------------------------------------------------- APUs
def _alm_apus(tmp_path):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("3010", "EXCAVACION MANUAL EN MATERIAL COMUN", "M3",
                              "DIURNO", "EXCAVACIONES Y RELLENOS")])
    return alm


def _apu_nuevo(codigo, turno, nombre):
    return {"codigo": codigo, "turno": turno, "nombre": nombre, "unidad": "M3",
            "grupo": "EXCAVACIONES Y RELLENOS", "componentes": []}


def test_apu_codigo_repetido_en_el_otro_turno_rechaza(tmp_path):
    """Hoy la identidad es (código, turno), así que 3010 NOCTURNO se creaba al lado del
    DIURNO con el código pelado — el mismo bug que ya se arregló en el importador."""
    alm = _alm_apus(tmp_path)
    with pytest.raises(ValueError, match="3010 N"):
        autoria.crear_apu(alm, _apu_nuevo("3010", "NOCTURNO", "OTRO NOMBRE CUALQUIERA"))


def test_apu_gemelo_nocturno_puede_repetir_el_nombre(tmp_path):
    alm = _alm_apus(tmp_path)
    out = autoria.crear_apu(alm, _apu_nuevo("3010 N", "NOCTURNO",
                                            "EXCAVACION MANUAL EN MATERIAL COMUN"))
    assert out["codigo"] == "3010 N" and out["turno"] == "NOCTURNO"


def test_apu_nombre_repetido_con_codigo_sin_relacion_rechaza(tmp_path):
    alm = _alm_apus(tmp_path)
    with pytest.raises(ValueError, match="3010"):
        autoria.crear_apu(alm, _apu_nuevo("9999", "NOCTURNO",
                                          "EXCAVACION MANUAL EN MATERIAL COMUN"))


def test_apu_nombre_repetido_en_el_mismo_turno_rechaza(tmp_path):
    """El gemelo es del OTRO turno. Mismo nombre, mismo turno, sigue siendo duplicado."""
    alm = _alm_apus(tmp_path)
    with pytest.raises(ValueError):
        autoria.crear_apu(alm, _apu_nuevo("3010 N", "DIURNO",
                                          "EXCAVACION MANUAL EN MATERIAL COMUN"))
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `python -m pytest tests/test_autoria_sin_duplicados.py -k apu -v`
Expected: FAIL — hoy los cuatro se crean sin protestar.

- [ ] **Step 3: Escribir `_conflicto_apu`**

En `apu_tool/servicio/autoria.py`, después de `_conflicto_insumo`:

```python
def _conflicto_apu(alm: Almacen, codigo: str, turno: str, nombre: str,
                   index: Optional[list[tuple[str, str, str]]] = None) -> Optional[str]:
    """El motivo en español si el alta de APU choca, o None.

    `index` es el resultado de `alm.apus.apu_index()` ya leído. Los imports lo leen UNA
    vez y lo pasan en cada vuelta —y le van agregando los APUs que aceptan, para que el
    archivo se vea a sí mismo con la misma regla—. Sin eso, un Excel de 200 APUs haría
    200 viajes de 1182 filas a Postgres, justo lo contrario de la optimización de
    round-trips que ya está en producción."""
    cod = str(codigo or "").strip()
    nn = normalizar(nombre)
    filas = alm.apus.apu_index() if index is None else index
    por_nombre = None
    for c, nom, sh in filas:
        if c == cod:
            pista = (f" Si es el nocturno, usa {_base_codigo(cod)} N."
                     if turno == config.SHIFT_NOCTURNO and sh != turno else "")
            return f"El código {cod} ya lo usa el APU {sh} «{_corto(nom)}».{pista}"
        if normalizar(nom) == nn and not (_es_gemelo_nocturno(cod, c) and sh != turno):
            por_nombre = por_nombre or (c, sh)
    if por_nombre:
        return f"Ese nombre ya lo usa el APU {por_nombre[0]} en turno {por_nombre[1]}."
    return None
```

- [ ] **Step 4: Engancharlo en `crear_apu`**

En `apu_tool/servicio/autoria.py::crear_apu`, **después** de `_origen_duplicado` (sus
mensajes son específicos de la copia y tienen que ganar) y antes de armar los componentes:

```python
    previos, hist, origen = _origen_duplicado(
        alm, datos.get("duplicado_de"), codigo, turno, nombre)
    motivo = _conflicto_apu(alm, codigo, turno, nombre)
    if motivo:
        raise ValueError(motivo)
    comps = _componentes_de(alm, datos.get("componentes", []) or [], turno,
```

- [ ] **Step 5: Anotar el techo conocido en `_origen_duplicado`**

En el docstring de `_origen_duplicado`, agregar al final:

```python
    # ponytail: duplicar sigue exigiendo un nombre distinto, y `codigoSugerido` del
    # frontend propone "3454-2 N" en vez de "3454 N" — o sea que el gemelo nocturno con
    # el MISMO nombre no se puede crear duplicando, hay que usar el alta normal. Es el
    # comportamiento de antes de la regla de unicidad, no una regresión, pero es el
    # camino que la gente intenta primero. Upgrade si molesta: que `codigoSugerido`
    # proponga `base + " N"` cuando cambia el turno y ese código está libre, y que este
    # guard y `nombreEsDistinto` deleguen la excepción en `_es_gemelo_nocturno`.
```

- [ ] **Step 6: Correr los tests y verificar que pasan**

Run: `python -m pytest tests/test_autoria_sin_duplicados.py -v`
Expected: PASS los 10.

- [ ] **Step 7: Correr la suite completa**

Run: `python -m pytest tests/ -q`
Expected: PASS. Ojo con los tests que crean varios APUs seguidos con nombres iguales o
códigos que solo difieren en el turno (`tests/test_servicio_autoria.py`,
`tests/test_api_autoria.py`, `tests/test_apus_*`): si alguno falla, la regla tiene razón
y se corrige el test con códigos `X` / `X N`.

- [ ] **Step 8: Commit**

```bash
git add apu_tool/servicio/autoria.py tests/test_autoria_sin_duplicados.py
git commit -m "feat(autoria): el alta de APUs exige codigo unico en cualquier turno"
```

---

### Task 4: import de insumos — balde `conflicto`

**Files:**
- Modify: `apu_tool/servicio/autoria.py` (`preview_importar_insumos`, línea 329-353)
- Test: `tests/test_autoria_sin_duplicados.py`

**Interfaces:**
- Consumes: `_conflicto_insumo(alm, codigo, nombre, extra=...)` de Task 2.
- Produces: `preview_importar_insumos` devuelve además `"conflicto": list[dict]`, cada dict es la fila del archivo más `"motivo": str`.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `tests/test_autoria_sin_duplicados.py` (arriba, junto a los imports, agregar
`import io` y `import openpyxl`):

```python
# --------------------------------------------------------------- import insumos
def _excel_insumos(filas):
    """Excel con las columnas que lee `_filas_insumos`."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["codigo", "nombre", "unidad", "grupo", "precio", "fuente"])
    for f in filas:
        ws.append(f)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_import_insumos_codigo_tomado_va_a_conflicto(tmp_path):
    alm = _alm(tmp_path)
    contenido = _excel_insumos([["10014", "ESTABILIZACION CON RAJON", "M3", "SUB", 7000, "PRECIO IDU"]])
    prev = autoria.preview_importar_insumos(alm, contenido, "x.xlsx")
    assert prev["crear"] == []
    assert len(prev["conflicto"]) == 1
    assert "10014" in prev["conflicto"][0]["motivo"]
    res = autoria.aplicar_importar_insumos(alm, contenido, "x.xlsx")
    assert res["creados"] == 0


def test_import_insumos_dos_filas_del_mismo_codigo_la_segunda_es_conflicto(tmp_path):
    """Sin el chequeo contra el propio archivo, el preview diría "crear 2" y el aplicar
    crearía 1 con un error: el preview mentiría."""
    alm = _alm(tmp_path)
    contenido = _excel_insumos([
        ["7777", "GRAVA COMUN", "M3", "MAT", 8000, "PRECIO IDU"],
        ["7777", "OTRA COSA DISTINTA", "M3", "MAT", 9000, "PRECIO IDU"]])
    prev = autoria.preview_importar_insumos(alm, contenido, "x.xlsx")
    assert len(prev["crear"]) == 1 and len(prev["conflicto"]) == 1
    res = autoria.aplicar_importar_insumos(alm, contenido, "x.xlsx")
    assert res["creados"] == 1 and res["errores"] == []


def test_import_insumos_el_gemelo_nocturno_del_archivo_si_se_crea(tmp_path):
    alm = _alm(tmp_path)
    contenido = _excel_insumos([
        ["8888", "GRAVA COMUN", "M3", "MAT", 8000, "PRECIO IDU"],
        ["8888 N", "GRAVA COMUN", "M3", "MAT", 9000, "PRECIO IDU"]])
    prev = autoria.preview_importar_insumos(alm, contenido, "x.xlsx")
    assert len(prev["crear"]) == 2 and prev["conflicto"] == []
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `python -m pytest tests/test_autoria_sin_duplicados.py -k import_insumos -v`
Expected: FAIL con `KeyError: 'conflicto'`.

- [ ] **Step 3: Reescribir `preview_importar_insumos`**

Reemplazar el cuerpo de `preview_importar_insumos` en `apu_tool/servicio/autoria.py`:

```python
def preview_importar_insumos(alm: Almacen, contenido: bytes, nombre_archivo: str,
                             lista_id: Optional[int] = None) -> dict:
    """Upsert por fila CONTRA `lista_id` (None = Principal). Con nombre: identidad
    código+nombre (crea o actualiza). Sin nombre: actualiza precio por código (único),
    o marca ambigua/no encontrada. Lo que crearía un duplicado va a 'conflicto'."""
    crear, actualizar, ambigua, no_encontrada, invalida, conflicto = [], [], [], [], [], []
    # Filas que este mismo archivo ya va a crear, con la forma de
    # `identidades_en_conflicto`: así una fila choca contra las anteriores del archivo
    # con exactamente la misma regla (incluida la excepción del gemelo nocturno).
    reclamadas: list[tuple[str, str, bool]] = []
    for f in _filas_insumos(contenido, nombre_archivo):
        cod, nom = f["codigo"], f["nombre"]
        if not cod:
            invalida.append(f)
        elif nom:
            match = _match_identidad(alm, cod, nom, lista_id)
            if match:
                _upsert_o_invalida(match, f, actualizar, invalida)
                continue
            motivo = _conflicto_insumo(alm, cod, nom, extra=reclamadas)
            if motivo:
                conflicto.append({**f, "motivo": motivo})
            else:
                crear.append(f)
                reclamadas.append((cod, nom, False))
        else:
            cands = alm.precios.get_candidatos(cod, lista_id=lista_id)
            if len(cands) == 1:
                _upsert_o_invalida(cands[0], f, actualizar, invalida)
            elif len(cands) > 1:
                ambigua.append({"codigo": cod,
                                "candidatos": [{"id": c.id, "nombre": c.nombre} for c in cands]})
            else:
                no_encontrada.append({"codigo": cod})
    return {"crear": crear, "actualizar": actualizar, "ambigua": ambigua,
            "no_encontrada": no_encontrada, "invalida": invalida, "conflicto": conflicto}
```

`aplicar_importar_insumos` **no se toca**: itera `prev["crear"]`, que ya viene filtrado.

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `python -m pytest tests/test_autoria_sin_duplicados.py -k import_insumos -v`
Expected: PASS los 3.

- [ ] **Step 5: Correr la suite completa**

Run: `python -m pytest tests/ -q`
Expected: PASS. Revisar `tests/test_api_autoria.py` y `tests/test_servicio_insumos_lista.py`
por asserts que comparen el dict del preview completo (`assert prev == {...}`): ahora
trae una clave más.

- [ ] **Step 6: Commit**

```bash
git add apu_tool/servicio/autoria.py tests/test_autoria_sin_duplicados.py
git commit -m "feat(autoria): el import de insumos manda los duplicados a conflicto"
```

---

### Task 5: import de APUs — balde `conflicto` y no-regresión del par día/noche

`aplicar_importar_apus` **sí** necesita su propio chequeo: no usa los baldes del preview,
recorre los APUs parseados y solo saltea los que ya existen con ese `(codigo, shift)`.

**Files:**
- Modify: `apu_tool/servicio/autoria.py` (`preview_importar_apus` línea 442-455; `aplicar_importar_apus` línea 458-482)
- Test: `tests/test_autoria_sin_duplicados.py`

**Interfaces:**
- Consumes: `_conflicto_apu(alm, codigo, turno, nombre, index=...)` de Task 3.
- Produces: `preview_importar_apus` devuelve además `"conflicto": list[dict]` (el mismo `info` de `crear`/`ya_existe` más `"motivo": str`).

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `tests/test_autoria_sin_duplicados.py`. El Excel tiene que tener el formato que
lee `_read_apus` del seed; el helper es la versión parametrizada del `_xlsx_apus()` que ya
existe en `tests/test_servicio_autoria.py`:

```python
# ------------------------------------------------------------------ import APUs
def _excel_apus(cabeceras):
    """Hoja 'APUS' del formato del histórico. `cabeceras` son (codigo, turno, nombre, unidad).

    Columnas: actividad(0) cod_idu(1) unidad(2) insumo(3) cod(4) und(5)
              rendimiento(6) inv(7) precio(8) costo(9) turno(10)   — ver seed.APUS_COLS.
    Cada APU lleva un componente para que no quede vacío."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "APUS"
    ws.append(["ACTIVIDAD", "COD IDU", "UN", "INSUMO", "COD", "UND", "RENDIMIENTO",
               "INV", "PRECIO", "COSTO", "TURNO"])
    for codigo, turno, nombre, unidad in cabeceras:
        ws.append([nombre, codigo, unidad, "", "", "", "", "", "", "", turno])
        ws.append(["", "", "", "CEMENTO", "100", "KG", 1.0, "", 900, "", ""])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()



def test_import_apus_el_par_diurno_nocturno_del_historico_sigue_entrando(tmp_path):
    """LA no-regresión: el importador convierte el nocturno en "3010 N" antes de
    cualquier chequeo (no choca por código) y el nombre repetido cae en la excepción
    del gemelo. Los 499 pares del histórico tienen que seguir importándose."""
    alm = _alm(tmp_path)                     # biblioteca de APUs vacía
    contenido = _excel_apus([
        ("3010", "DIURNO", "EXCAVACION MANUAL", "M3"),
        ("3010", "NOCTURNO", "EXCAVACION MANUAL", "M3")])
    prev = autoria.preview_importar_apus(alm, contenido)
    assert len(prev["crear"]) == 2 and prev["conflicto"] == []
    res = autoria.aplicar_importar_apus(alm, contenido)
    assert res["creados"] == 2 and res["errores"] == []
    assert alm.apus.get_apu("3010", "DIURNO") is not None
    assert alm.apus.get_apu("3010 N", "NOCTURNO") is not None


def test_import_apus_nombre_de_otro_apu_va_a_conflicto(tmp_path):
    alm = _alm_apus(tmp_path)                # ya tiene 3010 DIURNO "EXCAVACION MANUAL EN MATERIAL COMUN"
    contenido = _excel_apus([
        ("9999", "DIURNO", "EXCAVACION MANUAL EN MATERIAL COMUN", "M3")])
    prev = autoria.preview_importar_apus(alm, contenido)
    assert prev["crear"] == [] and len(prev["conflicto"]) == 1
    res = autoria.aplicar_importar_apus(alm, contenido)
    assert res["creados"] == 0 and len(res["errores"]) == 1
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `python -m pytest tests/test_autoria_sin_duplicados.py -k import_apus -v`
Expected: los dos FALLAN con `KeyError: 'conflicto'` (la clave todavía no existe). Ojo:
el primero es la **no-regresión** — su parte importante es que `crear` tenga 2 y que los
dos APUs terminen en la biblioteca, y eso ya funciona hoy; lo único que le falta es la
clave nueva. Si después de implementar ese test falla por otra razón, la regla está
rompiendo el import del histórico y hay que **parar y avisar**, no ajustar el test.

- [ ] **Step 3: Reescribir `preview_importar_apus`**

```python
def preview_importar_apus(alm: Almacen, contenido: bytes) -> dict:
    apus, comps_por = _parse_apus(contenido)
    index = alm.apus.apu_index()          # UNA lectura para todo el archivo
    crear, ya_existe, conflicto, crear_apus = [], [], [], []
    for a in apus:
        info = {"codigo": a.codigo, "turno": a.shift, "nombre": a.nombre,
                "unidad": a.unidad, "grupo": a.grupo,
                "n_componentes": len(comps_por.get((a.codigo, a.shift), []))}
        if alm.apus.get_apu(a.codigo, a.shift):
            ya_existe.append(info)
            continue
        motivo = _conflicto_apu(alm, a.codigo, a.shift, a.nombre, index=index)
        if motivo:
            conflicto.append({**info, "motivo": motivo})
            continue
        crear.append(info)
        crear_apus.append(a)
        index.append((a.codigo, a.nombre, a.shift))   # el archivo se ve a sí mismo
    subapus = detectar_subapus_lote(alm, apus, comps_por, solo=crear_apus)
    return {"crear": crear, "ya_existe": ya_existe, "conflicto": conflicto,
            "subapus": subapus}
```

- [ ] **Step 4: Agregar el chequeo a `aplicar_importar_apus`**

En `apu_tool/servicio/autoria.py::aplicar_importar_apus`, leer el índice una vez antes
del loop y chequear dentro:

```python
def aplicar_importar_apus(alm: Almacen, contenido: bytes, actor=None) -> dict:
    apus, comps_por = _parse_apus(contenido)
    mapa = mapa_codigos_apu(alm, apus)
    nombres = nombres_apu(alm, apus)
    # `aplicar` no usa los baldes del preview: recorre los APUs parseados. Sin este
    # chequeo acá, las filas en conflicto se crearían igual.
    index = alm.apus.apu_index()
    creados, subapus_marcados, errores = 0, 0, []
    lote = nuevo_lote()
    for a in apus:
        if alm.apus.get_apu(a.codigo, a.shift):
            continue                                   # ya existe: no se pisa
        motivo = _conflicto_apu(alm, a.codigo, a.shift, a.nombre, index=index)
        if motivo:
            errores.append({"codigo": a.codigo, "turno": a.shift, "error": motivo})
            continue
        try:
            comps = comps_por.get((a.codigo, a.shift), [])
            comps, n_sub = marcar_comps_subapu(comps, a.shift, mapa, nombres)
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
            index.append((a.codigo, a.nombre, a.shift))
        except ValueError as e:
            errores.append({"codigo": a.codigo, "turno": a.shift, "error": str(e)})
    return {"creados": creados, "subapus_marcados": subapus_marcados, "errores": errores}
```

- [ ] **Step 5: Correr los tests y verificar que pasan**

Run: `python -m pytest tests/test_autoria_sin_duplicados.py -v`
Expected: PASS todos.

- [ ] **Step 6: Correr la suite completa, con atención al import de sub-APUs**

Run: `python -m pytest tests/ -q`
Expected: PASS. `tests/test_subapus_import.py` es el que más riesgo tiene: si alguno de
sus Excel de prueba trae dos APUs con el mismo nombre y códigos sin relación, ahora uno
va a conflicto. Revisar caso por caso si el Excel de prueba es realista (arreglar el
test) o si la regla es demasiado estricta (parar y avisar).

- [ ] **Step 7: Commit**

```bash
git add apu_tool/servicio/autoria.py tests/test_autoria_sin_duplicados.py
git commit -m "feat(autoria): el import de APUs manda los duplicados a conflicto"
```

---

### Task 6: los dos diálogos de import muestran el conflicto

Los formularios individuales **no se tocan**: `DialogoAgregarInsumo.tsx:88-90` y
`DialogoAgregarApu.tsx:308-310` ya hacen `toast.error(msg)` con el detalle del 400.

**Files:**
- Modify: `web/src/lib/tipos.ts`
- Modify: `web/src/components/insumos/DialogoImportarInsumos.tsx:136-161`
- Modify: `web/src/components/autoria/DialogoImportarApus.tsx:20-30, 60-70, 155-165`
- Test: `web/src/components/insumos/DialogoImportarInsumos.test.tsx`

**Interfaces:**
- Consumes: `conflicto` de los previews (Task 4 y Task 5).
- Produces: `ImportConflicto` en `tipos.ts`.

- [ ] **Step 1: Escribir el test que falla**

En `web/src/components/insumos/DialogoImportarInsumos.test.tsx`, dentro del `describe`
existente. El archivo ya tiene `previewImportarInsumos` mockeado y los helpers
`archivoDemo()` / `seleccionarArchivo()`; este test sobreescribe el preview del
`beforeEach`:

```tsx
  it("muestra las filas en conflicto con su motivo y no las cuenta para aplicar", async () => {
    previewImportarInsumos.mockResolvedValue({
      crear: [], actualizar: [], ambigua: [], no_encontrada: [], invalida: [],
      conflicto: [{
        codigo: "10014", nombre: "ESTABILIZACION CON RAJON",
        motivo: "El código 10014 ya lo usa el insumo «USO DEL PENETROMETRO».",
      }],
    });
    render(
      <DialogoImportarInsumos
        open onOpenChange={() => {}} listaId={7} listaNombre="NP Calle 13" onAplicado={() => {}}
      />
    );
    seleccionarArchivo();

    expect(await screen.findByText(/En conflicto/i)).toBeInTheDocument();
    expect(screen.getByText(/ya lo usa el insumo/i)).toBeInTheDocument();
    // el botón cuenta crear + actualizar: las filas en conflicto no lo habilitan
    expect(screen.getByText("Aplicar (0)")).toBeDisabled();
  });
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `cd web && npx vitest run src/components/insumos/DialogoImportarInsumos.test.tsx`
Expected: FAIL — no existe el texto "En conflicto".

- [ ] **Step 3: Agregar el tipo**

En `web/src/lib/tipos.ts`, junto a `ImportAmbiguo`:

```ts
export interface ImportConflicto {
  codigo: string;
  nombre: string;
  turno?: string;   // solo en el import de APUs
  motivo: string;
}
```

y en las dos interfaces de preview, **opcional** (igual que el `res.ya_existe ?? []` que
ya usa `DialogoImportarApus.tsx:64`: así los fixtures de los tests que no la traen siguen
compilando):

```ts
export interface ImportInsumosUpsertPreview {
  crear: InsumoImportFila[];
  actualizar: CambioPreview[];
  ambigua: ImportAmbiguo[];
  no_encontrada: { codigo: string }[];
  invalida: InsumoImportFila[];
  conflicto?: ImportConflicto[];
}

export interface ImportApusPreview {
  crear: ApuResumen[];
  ya_existe: ApuResumen[];
  conflicto?: ImportConflicto[];
  subapus: VinculoSubApu[];
}
```

- [ ] **Step 4: La sección en el diálogo de insumos**

En `web/src/components/insumos/DialogoImportarInsumos.tsx`, entre la sección
"No encontradas" y "Inválidas":

```tsx
            <Seccion titulo="En conflicto (no se crean)">
              <Tabla cols={["Código", "Nombre", "Motivo"]}
                     filas={(prev.conflicto ?? []).map((c) => [
                       c.codigo || "—", c.nombre || "—", c.motivo])} />
            </Seccion>
```

`nAcciones` (línea 98) no cambia: sigue siendo `crear.length + actualizar.length`, así
que las filas en conflicto no habilitan el botón.

- [ ] **Step 5: La sección en el diálogo de APUs**

En `web/src/components/autoria/DialogoImportarApus.tsx`: agregar `conflicto` al estado de
la fase preview (línea 24), llenarlo con `res.conflicto ?? []` (junto a la línea 64),
derivarlo con los otros (`const conflicto = enPreview ? estado.conflicto : [];`),
renderizarlo después de "Ya existen", e importar el tipo:

```tsx
            <SeccionConflictos filas={conflicto} />
```

y al final del archivo, junto a `SeccionApus`:

```tsx
function SeccionConflictos({ filas }: { filas: ImportConflicto[] }) {
  if (filas.length === 0) return null;
  return (
    <div>
      <p className="text-xs font-semibold mb-1">
        En conflicto{" "}
        <span className="font-normal text-muted-foreground">({filas.length})</span>
        <span className="ml-2 font-normal text-muted-foreground">
          — no se crean: el código o el nombre ya están en uso
        </span>
      </p>
      <div className="overflow-x-auto overflow-y-auto max-h-40 border rounded">
        <table className="w-full text-xs border-collapse">
          <tbody>
            {filas.map((f, i) => (
              <tr key={`${f.codigo}-${i}`} className="even:bg-muted/10">
                <td className="px-2 py-0.5 font-mono">{f.codigo}</td>
                <td className="px-2 py-0.5 text-muted-foreground">({f.turno})</td>
                <td className="px-2 py-0.5 align-top break-words">{f.motivo}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Correr los tests del frontend**

Run: `cd web && npx vitest run`
Expected: PASS.

- [ ] **Step 7: Compilar de verdad**

Run: `cd web && npm run build`
Expected: sin errores. **`npm run build` es `tsc -b`; `tsc --noEmit` no alcanza** (ya nos
costó un hotfix una vez).

- [ ] **Step 8: Commit**

```bash
git add web/src/lib/tipos.ts web/src/components/insumos/DialogoImportarInsumos.tsx web/src/components/insumos/DialogoImportarInsumos.test.tsx web/src/components/autoria/DialogoImportarApus.tsx
git commit -m "feat(web): los diagolos de import muestran las filas en conflicto"
```

---

### Task 7: verificación en el navegador y cierre

- [ ] **Step 1: Suite completa**

Run: `python -m pytest tests/ -q && cd web && npx vitest run && npm run build`
Expected: todo verde.

- [ ] **Step 2: Levantar la web en local**

Necesita `SUPABASE_URL` y `APU_ADMIN_EMAILS` en el entorno, o todo `/api` responde 401
(receta en la memoria del proyecto: "Levantar la web en local").

- [ ] **Step 3: Probar a mano los cuatro casos**

- Crear un insumo con el código `10014` → mensaje que nombra el insumo que ya lo usa.
- Crear un insumo con el nombre de un `4859` existente y otro código → mensaje que sugiere
  `<código> N`.
- Crear un APU NOCTURNO con un código que ya exista en DIURNO → mensaje que sugiere `X N`.
- Crear el gemelo: APU `X N` NOCTURNO con el mismo nombre del `X` DIURNO → **se crea**.
- Importar un Excel de APUs con un par DIURNO/NOCTURNO → entran los dos.

- [ ] **Step 4: Actualizar la memoria del proyecto y pedir aprobación para el push**

Escribir la memoria de la feature y **preguntar** antes de mergear a `master`: `master`
auto-despliega a producción.

---

## Notas de la auto-revisión

- **Cobertura del spec:** la regla (Task 2 y 3), los ocultos (Task 1 y 2), la excepción
  día/noche (Task 2 y 3), las dos puertas del import (Task 4 y 5), el `index` leído una
  vez (Task 3 y 5), el conflicto intra-archivo (Task 4 y 5), el frontend (Task 6), el
  techo de duplicar (Task 3, Step 5), la verificación en navegador (Task 7). El `seed` y
  la edición quedan fuera por diseño, declarado en el spec.
- **Consistencia de nombres:** `_base_codigo`, `_es_gemelo_nocturno`, `_corto`,
  `_conflicto_insumo(alm, codigo, nombre, extra)`, `_conflicto_apu(alm, codigo, turno,
  nombre, index)`, `identidades_en_conflicto(codigo, nombre_norm)`, `ImportConflicto`.
  Los mismos nombres en todas las tareas.
- **Riesgo conocido:** los tests existentes que crean insumos o APUs colisionantes entre
  sí. Los steps 6/5/6 de las tareas 2, 4 y 5 lo dicen explícitamente y dan el criterio:
  la regla gana, se arregla el test — salvo que el caso del test sea realista, y entonces
  hay que parar y avisar.
