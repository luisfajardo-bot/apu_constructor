> Espejo automático — no editar aquí. Fuente: `docs/superpowers/plans/2026-11-19-codigos-compartidos.md`

# Códigos compartidos en el alta de APUs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** que el alta de APUs (crear, editar, duplicar, aprobar composición) guarde la fila del catálogo que corresponde a código + nombre, y que cuando el nombre no alcance bloquee con las opciones para que el ingeniero escoja en la fila.

**Architecture:** una sola función de elección por nombre en `dominio/cruce.py` que usan el costeo, el alta, el validador de composición, la ficha de la mesa y el chat. El alta (`servicio/autoria.py::_componentes_de`) es el embudo único y lanza `CodigoCompartido` (422 con `conflictos`). La composición lleva `nombre` por componente; el validador emite `CODIGO_COMPARTIDO`; la web muestra un selector en la fila (diálogo de APU y mesa).

**Tech Stack:** Python 3 / FastAPI / SQLite + Postgres (psycopg), pytest; React + TypeScript + vitest + tailwind.

**Spec:** `docs/superpowers/specs/2026-11-19-codigos-compartidos-design.md` (léelo antes de empezar).

**Reglas del repo que aplican (CLAUDE.md):**
- La IA nunca ve dinero. `Insumo` lleva `precio`: todo lo que sale de un `Insumo` hacia la API de composición o hacia la IA se copia campo por campo (nombre, unidad, grupo, oculto), nunca el objeto.
- Persistencia solo en `apu_tool/datos/`; los dos backends (SQLite y `datos/pg/`) se cambian igual.
- Español en nombres, comentarios y mensajes. Mensajes al usuario en español colombiano de **tú**, sin voseo.
- Rama `fix/codigos-compartidos` (ya creada, con el spec commiteado). **No pushear.**

**Cómo correr las pruebas (OBLIGATORIO en esta máquina):** hay una `DATABASE_URL` de producción en el entorno. Siempre:
- Python: `env -u DATABASE_URL python -m pytest <ruta> -q` (desde Git Bash, en la raíz del repo).
- Web: `cd web && npx vitest run <ruta>`; build: `cd web && npm run build` (usa `tsc -b`; `tsc --noEmit` no alcanza).

---

## Mapa de archivos

| Archivo | Cambio |
|---|---|
| `apu_tool/nucleo/models.py` | `Insumo.oculto: bool = False` |
| `apu_tool/datos/precios_db.py`, `apu_tool/datos/pg/precios_pg.py` | leer `i.oculto` en `_SELECT_INSUMO` y en `list_insumos` |
| `apu_tool/dominio/cruce.py` | `elegir`, `elegir_fila`, `opciones`, `ficha`, `compartidos`; `resolver` usa `elegir` |
| `apu_tool/servicio/autoria.py` | `CodigoCompartido`; `_componentes_de` elige por nombre; `hist` por código+nombre |
| `apu_tool/servicio/rutas.py` | 422 con `conflictos` en crear/editar APU y en `_composicion_o_error` |
| `apu_tool/dominio/composicion.py` | `ComponentePropuesto.nombre`, `_MAX_NOMBRE` |
| `apu_tool/servicio/esquemas.py` | `ComponenteComposicionIn.nombre` |
| `apu_tool/dominio/validacion_composicion.py` | `candidatos_compartidos`, `CODIGO_COMPARTIDO`, unidad de la fila elegida |
| `apu_tool/dominio/composicion_agente.py` | arma `candidatos_compartidos`; grupo por fila elegida |
| `apu_tool/servicio/composicion.py` | `_con_lista_blanca` completa compartidos; `_catalogo_de` con `cruce.ficha`; `_componentes_para_autoria` manda nombre |
| `apu_tool/dominio/ai_assist.py` | esquema de Componer pide `nombre`; prompt; `PROMPT_VERSION = "composicion/v5"` |
| `apu_tool/dominio/composicion_chat.py` | se borra `_motivo_compartido`; `_respuesta` y `_catalogo` resuelven con `cruce` |
| `web/src/lib/tipos.ts` | `nombre?` en `ComponentePropuesto`; `OpcionInsumo`; `EntradaCatalogo.opciones?` |
| `web/src/components/SelectorCompartido.tsx` (nuevo) | el selector «¿Cuál de los dos?» |
| `web/src/components/autoria/DialogoAgregarApu.tsx` | 422 → selector en la fila |
| `web/src/pages/Composicion.tsx` | selector en la fila; buscador guarda nombre |
| `web/src/lib/cambiosAgente.ts` | `modificar` conserva el nombre |
| `CLAUDE.md` | reglas nuevas |

Nota sobre el spec: el prompt del chat **no** cambia (ya pide `nombre` y no menciona el candado), así que `PROMPT_VERSION_CHAT` se queda en `"chat/v4"`; solo cambia la lógica del servidor.

---

### Task 1: `Insumo.oculto` en el catálogo

Hace falta para marcar los ocultos en las opciones sin otra consulta, y deja de depender de `identidades_en_conflicto` en el chat.

**Files:**
- Modify: `apu_tool/nucleo/models.py` (dataclass `Insumo`)
- Modify: `apu_tool/datos/precios_db.py` (`_fila_a_insumo`, `_SELECT_INSUMO`, `campos` en `list_insumos`)
- Modify: `apu_tool/datos/pg/precios_pg.py` (los mismos tres puntos)
- Test: `tests/test_codigos_compartidos.py` (nuevo)

- [ ] **Step 1: Write the failing test**

Crear `tests/test_codigos_compartidos.py`:

```python
"""Códigos compartidos: un código del catálogo que es de dos insumos distintos."""
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Insumo


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo("7406", "REDUCCION HD E.L. D=12 x 10", "UN", "ACCESORIOS", 1785000,
               "PRECIO IDU"),
        Insumo("7406", "SEÑAL VERTICAL SR 90X30 INCLUYE POSTE", "UN", "SEÑALIZACION",
               468040, "PRECIO IDU"),
    ])
    return alm


def test_los_candidatos_traen_si_estan_ocultos(tmp_path):
    alm = _alm(tmp_path)
    reduccion = alm.precios.get_candidatos("7406")[0]
    alm.precios.set_oculto(reduccion.id, True)
    cands = alm.precios.get_candidatos("7406")
    assert [c.oculto for c in cands] == [True, False]
    assert [c.oculto for c in alm.precios.get_candidatos_bulk(["7406"])["7406"]] == [True, False]
    items, _ = alm.precios.list_insumos(q="SEÑAL VERTICAL")
    assert items and items[0].oculto is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `env -u DATABASE_URL python -m pytest tests/test_codigos_compartidos.py -q`
Expected: FAIL with `AttributeError: 'Insumo' object has no attribute 'oculto'`.
(Si `list_insumos` no acepta `q=` con esa firma, mira su definición en `precios_db.py` y ajusta la llamada del test; no cambies la firma.)

- [ ] **Step 3: Implement**

En `apu_tool/nucleo/models.py`, dentro de `Insumo`, después de `sin_precio: bool = False`:

```python
    # True = el insumo está oculto (eco de un APU sin uso real). No se borra: el costeo
    # lo sigue viendo, y por eso `get_candidatos` lo devuelve. Lo usan las opciones de
    # un código compartido para avisar que se está escogiendo uno oculto.
    oculto: bool = False
```

En `apu_tool/datos/precios_db.py` y en `apu_tool/datos/pg/precios_pg.py`, en `_fila_a_insumo` agregar el argumento (los dos devuelven `bool` porque en SQLite es INTEGER y en Postgres BOOLEAN):

```python
        return Insumo(codigo=r["codigo"], nombre=r["nombre"], unidad=r["unidad"] or "",
                      grupo=r["grupo"] or "", precio=r["precio"] or 0.0,
                      fuente_precio=r["fuente"] or "", id=r["id"],
                      sin_precio=r["precio"] is None, oculto=bool(r["oculto"]))
```

En los dos archivos, `_SELECT_INSUMO` pasa a seleccionar `i.oculto`:

```python
        "SELECT i.id, i.codigo, i.nombre, i.unidad, i.grupo, i.oculto, p.precio, p.fuente "
```

(SQLite: `FROM insumos i ...`; Postgres: `FROM precios.insumos i ...` — solo cambia la lista de columnas.)

En los dos `list_insumos`, la variable `campos`:

```python
        campos = "i.id, i.codigo, i.nombre, i.unidad, i.grupo, i.oculto, p.precio, p.fuente"
```

Verifica con `grep -n "_fila_a_insumo" apu_tool/datos/precios_db.py apu_tool/datos/pg/precios_pg.py` que todas las consultas que lo usan pasan por `_SELECT_INSUMO` o por `campos`.

- [ ] **Step 4: Run tests**

Run: `env -u DATABASE_URL python -m pytest tests/test_codigos_compartidos.py -q && env -u DATABASE_URL python -m pytest tests -q -k "insumo or precio or oculto"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apu_tool/nucleo/models.py apu_tool/datos/precios_db.py apu_tool/datos/pg/precios_pg.py tests/test_codigos_compartidos.py
git commit -m "feat(catalogo): Insumo trae si esta oculto"
```

---

### Task 2: elección por nombre en `dominio/cruce.py`

**Files:**
- Modify: `apu_tool/dominio/cruce.py`
- Test: `tests/test_cruce.py`

- [ ] **Step 1: Write the failing tests**

Agregar al final de `tests/test_cruce.py`:

```python
from apu_tool.dominio import cruce


def _i(cod, nom, unidad="UN", grupo="G", oculto=False):
    return Insumo(cod, nom, unidad, grupo, 100, "PRECIO IDU", id=1, oculto=oculto)


REDUCCION = _i("7406", "REDUCCION HD E.L. D=12 x 10", grupo="ACCESORIOS")
SENAL = _i("7406", "SEÑAL VERTICAL SR 90X30 INCLUYE POSTE", grupo="SEÑALIZACION",
           oculto=True)


def test_elegir_exacto_aproximado_y_ambiguo():
    nombres = [REDUCCION.nombre, SENAL.nombre]
    assert cruce.elegir(nombres, " señal vertical sr 90x30 incluye poste ")[0] == 1
    i, calidad, _ = cruce.elegir(nombres, "SEÑAL VERTICAL SR 90X30")
    assert (i, calidad) == (1, cruce.CalidadCruce.APROXIMADO)
    assert cruce.elegir(nombres, "")[0] is None
    assert cruce.elegir(nombres, "TORNILLO HEXAGONAL")[0] is None
    assert cruce.elegir([], "X") == (None, cruce.CalidadCruce.HUERFANO, 0.0)


def test_elegir_fila_con_un_solo_candidato_no_mira_el_nombre():
    """Igual que el alta de siempre: un código de un solo insumo es ese insumo."""
    assert cruce.elegir_fila([REDUCCION], "CUALQUIER COSA") is REDUCCION
    assert cruce.elegir_fila([], "X") is None
    assert cruce.elegir_fila([REDUCCION, SENAL], "SEÑAL VERTICAL SR 90X30 INCLUYE POSTE") is SENAL
    assert cruce.elegir_fila([REDUCCION, SENAL], "") is None


def test_ficha_sin_dinero_y_con_opciones_si_el_codigo_es_compartido():
    f = cruce.ficha([REDUCCION, SENAL], "")
    assert f == {"nombre": "", "unidad": "", "grupo": "", "opciones": [
        {"nombre": REDUCCION.nombre, "unidad": "UN", "oculto": False},
        {"nombre": SENAL.nombre, "unidad": "UN", "oculto": True}]}
    assert cruce.ficha([REDUCCION, SENAL], REDUCCION.nombre)["nombre"] == REDUCCION.nombre
    assert cruce.ficha([REDUCCION], "") == {
        "nombre": REDUCCION.nombre, "unidad": "UN", "grupo": "ACCESORIOS"}
    assert "precio" not in str(cruce.ficha([REDUCCION, SENAL], ""))


def test_compartidos_solo_los_codigos_con_dos_o_mas_filas():
    cat = {"7406": [REDUCCION, SENAL], "100": [_i("100", "CEMENTO", "KG")], "9": []}
    assert cruce.compartidos(cat) == {
        "7406": ((REDUCCION.nombre, "UN"), (SENAL.nombre, "UN"))}
```

Si el caso `"SEÑAL VERTICAL SR 90X30"` no llega a APROXIMADO con los umbrales de `config` (0,60 / 0,10), alarga el texto hasta que llegue: el test es del caso aproximado, no del umbral.

- [ ] **Step 2: Run to verify it fails**

Run: `env -u DATABASE_URL python -m pytest tests/test_cruce.py -q`
Expected: FAIL with `AttributeError: module 'apu_tool.dominio.cruce' has no attribute 'elegir'`.

- [ ] **Step 3: Implement**

En `apu_tool/dominio/cruce.py`, cambiar `from typing import Optional` por `from typing import Optional, Sequence` y reemplazar `resolver` por:

```python
def elegir(nombres: Sequence[str], objetivo: str
           ) -> tuple[Optional[int], CalidadCruce, float]:
    """Cuál de `nombres` (las filas de UN código, en orden de id) es `objetivo`.

    Devuelve (índice o None, calidad, score). Es la única regla de elección por nombre
    del repo: la usan el costeo (`resolver`), el alta de APUs, el validador de
    composición, la ficha de la mesa y el chat. Recibe nombres y no `Insumo` porque el
    validador de composición no tiene `Insumo` (lleva `precio`) y no debe tenerlo."""
    if not nombres:
        return None, CalidadCruce.HUERFANO, 0.0
    obj = normalizar(objetivo)
    # 1) Coincidencia exacta de nombre normalizado (única por UNIQUE(codigo, nombre_norm)).
    for i, n in enumerate(nombres):
        if normalizar(n) == obj:
            return i, CalidadCruce.EXACTO, 1.0
    # 2) Mejor coincidencia difusa, con margen sobre el segundo. `sorted` es estable:
    #    a igual score gana el de id menor, como antes.
    puntuados = sorted(((similarity(objetivo, n), i) for i, n in enumerate(nombres)),
                       key=lambda t: t[0], reverse=True)
    mejor_score, mejor = puntuados[0]
    segundo_score = puntuados[1][0] if len(puntuados) > 1 else 0.0
    if mejor_score >= config.CRUCE_UMBRAL and (mejor_score - segundo_score) >= config.CRUCE_MARGEN:
        return mejor, CalidadCruce.APROXIMADO, mejor_score
    return None, CalidadCruce.AMBIGUO, mejor_score


def resolver(candidatos: list[Insumo], nombre_apu: str) -> ResultadoCruce:
    i, calidad, score = elegir([c.nombre for c in candidatos], nombre_apu)
    return ResultadoCruce(candidatos[i] if i is not None else None, calidad, score)


def elegir_fila(candidatos: list[Insumo], nombre: str) -> Optional[Insumo]:
    """La fila que se ESCRIBE para (código, nombre). Un solo candidato es ese, sin
    mirar el nombre (el alta de siempre); con dos o más decide `elegir`, y None
    quiere decir que el nombre no alcanza: hay que preguntarle al ingeniero."""
    if len(candidatos) <= 1:
        return candidatos[0] if candidatos else None
    i, _calidad, _score = elegir([c.nombre for c in candidatos], nombre)
    return candidatos[i] if i is not None else None


def opciones(candidatos: list[Insumo]) -> list[dict]:
    """Las filas de un código compartido, para que el ingeniero escoja. Campo por
    campo: `Insumo` lleva `precio` y esto viaja por la API de composición."""
    return [{"nombre": c.nombre, "unidad": c.unidad, "oculto": c.oculto}
            for c in candidatos]


def ficha(candidatos: list[Insumo], nombre: str) -> dict:
    """Nombre, unidad y grupo de la fila que corresponde a `nombre` (vacíos si no
    resuelve) y, si el código es compartido, las `opciones`. Sin dinero."""
    f = elegir_fila(candidatos, nombre)
    out = ({"nombre": f.nombre, "unidad": f.unidad, "grupo": f.grupo} if f
           else {"nombre": "", "unidad": "", "grupo": ""})
    if len(candidatos) > 1:
        out["opciones"] = opciones(candidatos)
    return out


def compartidos(catalogo: dict[str, list[Insumo]]) -> dict[str, tuple[tuple[str, str], ...]]:
    """(nombre, unidad) de cada código con dos o más filas, a partir de lo que devuelve
    `get_candidatos_bulk`. Es lo que necesita el validador de composición, sin dinero."""
    return {cod: tuple((c.nombre, c.unidad) for c in cands)
            for cod, cands in catalogo.items() if len(cands) > 1}
```

- [ ] **Step 4: Run tests (incluye el costeo, que usa `resolver`)**

Run: `env -u DATABASE_URL python -m pytest tests/test_cruce.py tests/test_pricing_cruce.py tests/test_integridad.py -q`
Expected: PASS (los tests viejos de `resolver` no cambian).

- [ ] **Step 5: Commit**

```bash
git add apu_tool/dominio/cruce.py tests/test_cruce.py
git commit -m "feat(cruce): una sola regla de eleccion por nombre (elegir, ficha, opciones)"
```

---

### Task 3: el embudo del alta elige por nombre (`autoria._componentes_de`)

**Files:**
- Modify: `apu_tool/servicio/autoria.py:195-258` (`_mapas_de_componentes`, `_componentes_de`) y una clase nueva arriba de ellos
- Test: `tests/test_codigos_compartidos.py`, `tests/test_servicio_autoria.py:670-691`

- [ ] **Step 1: Write the failing tests**

Agregar a `tests/test_codigos_compartidos.py`:

```python
import pytest

from apu_tool.nucleo.models import Apu, ApuComponent
from apu_tool.servicio import autoria

SENAL = "SEÑAL VERTICAL SR 90X30 INCLUYE POSTE"
REDUCCION = "REDUCCION HD E.L. D=12 x 10"


def _crear(alm, componentes, codigo="N1"):
    return autoria.crear_apu(alm, {"codigo": codigo, "turno": "DIURNO", "nombre": "APU " + codigo,
                                   "unidad": "UN", "grupo": "G", "componentes": componentes})


def test_crear_con_la_senal_guarda_la_senal(tmp_path):
    alm = _alm(tmp_path)
    _crear(alm, [{"insumo_codigo": "7406", "insumo_nombre": SENAL, "rendimiento": 1}])
    (c,) = alm.apus.get_components("N1", "DIURNO")
    assert c.insumo_nombre == SENAL


def test_crear_sin_nombre_bloquea_con_las_dos_opciones(tmp_path):
    alm = _alm(tmp_path)
    with pytest.raises(autoria.CodigoCompartido) as e:
        _crear(alm, [{"insumo_codigo": "7406", "rendimiento": 1}])
    assert e.value.conflictos == [{"codigo": "7406", "opciones": [
        {"nombre": REDUCCION, "unidad": "UN", "oculto": False},
        {"nombre": SENAL, "unidad": "UN", "oculto": False}]}]
    assert "7406" in str(e.value) and "escoge" in str(e.value)
    assert alm.apus.get_apu("N1", "DIURNO") is None          # no escribió nada


def test_dos_codigos_ambiguos_salen_en_un_solo_error(tmp_path):
    alm = _alm(tmp_path)
    alm.precios.insert_insumos([
        Insumo("6092", "HERRAMIENTA MENOR", "GLB", "EQ", 2000, "PRECIO IDU"),
        Insumo("6092", "RELOCALIZACION DE MEDIDOR DE ACUEDUCTO", "UN", "REDES", 9, "PRECIO IDU")])
    with pytest.raises(autoria.CodigoCompartido) as e:
        _crear(alm, [{"insumo_codigo": "7406", "insumo_nombre": "TORNILLO", "rendimiento": 1},
                     {"insumo_codigo": "6092", "rendimiento": 1}])
    assert [c["codigo"] for c in e.value.conflictos] == ["7406", "6092"]


def test_un_codigo_de_un_solo_insumo_sigue_igual(tmp_path):
    alm = _alm(tmp_path)
    alm.precios.insert_insumos([Insumo("100", "CEMENTO GRIS", "KG", "MAT", 1000, "PRECIO IDU")])
    _crear(alm, [{"insumo_codigo": "100", "insumo_nombre": "OTRA COSA", "rendimiento": 2}])
    (c,) = alm.apus.get_components("N1", "DIURNO")
    assert c.insumo_nombre == "CEMENTO GRIS"


def test_editar_sin_cambios_conserva_la_segunda_fila(tmp_path):
    """El caso 4506 de producción: el APU usa la SEGUNDA fila del código y editarlo
    sin tocar nada la cambiaba por la primera, sin alerta."""
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("4506", "BACHEO", "M2", "DIURNO", "PAV")])
    alm.apus.insert_components([ApuComponent("4506", "DIURNO", "7406", SENAL, "UN", 1.0, 468040)])
    autoria.editar_apu(alm, "4506", "DIURNO", {
        "nombre": "BACHEO", "unidad": "M2", "grupo": "PAV",
        "componentes": [{"insumo_codigo": "7406", "insumo_nombre": SENAL, "rendimiento": 1.0}]})
    (c,) = alm.apus.get_components("4506", "DIURNO")
    assert c.insumo_nombre == SENAL
    assert c.precio_unitario_hist == 468040            # su histórico, no el de la otra


def test_cambiar_de_fila_no_hereda_el_historico_de_la_otra(tmp_path):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("4506", "BACHEO", "M2", "DIURNO", "PAV")])
    alm.apus.insert_components([ApuComponent("4506", "DIURNO", "7406", SENAL, "UN", 1.0, 468040)])
    autoria.editar_apu(alm, "4506", "DIURNO", {
        "nombre": "BACHEO", "unidad": "M2", "grupo": "PAV",
        "componentes": [{"insumo_codigo": "7406", "insumo_nombre": REDUCCION, "rendimiento": 1.0}]})
    (c,) = alm.apus.get_components("4506", "DIURNO")
    assert c.insumo_nombre == REDUCCION
    assert c.precio_unitario_hist == autoria.PISO_HIST


def test_un_sub_apu_no_pasa_por_la_eleccion_de_insumos(tmp_path):
    """Los componentes tipo "apu" se resuelven contra la biblioteca: un código de
    sub-APU que choca con un insumo compartido no se bloquea."""
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("7406", "SUB APU", "UN", "DIURNO", "G")])
    _crear(alm, [{"insumo_codigo": "7406", "rendimiento": 1, "tipo": "apu",
                  "ref_shift": "DIURNO"}])
    (c,) = alm.apus.get_components("N1", "DIURNO")
    assert c.tipo == "apu"


def test_un_nombre_aproximado_resuelve_a_su_fila(tmp_path):
    """Los 4 casos aproximados de producción (5225/5241 D y N): el nombre guardado es
    una variante del catálogo. Resuelven a SU fila y quedan con el nombre canónico."""
    catalogo = "TARIFA DIA - ALQUILER DE VEHICULO: CAMPERO, PICK-UP, CAMIONETA. INCLUYE CONDUCTOR"
    guardado = "TARIFA DIA - ALQUILER DE VEHICULO: CAMPERO, PICK-UP, CAMIONETA"
    alm = _alm(tmp_path)
    alm.precios.insert_insumos([
        Insumo("8324", catalogo, "DIA", "EQ", 1, "PRECIO IDU"),
        Insumo("8324", "EMPATE ORTOGONAL PVC-PVC 12X8 INCLUYE SUMINISTRO", "UN", "REDES", 1,
               "PRECIO IDU")])
    _crear(alm, [{"insumo_codigo": "8324", "insumo_nombre": guardado, "rendimiento": 1}])
    (c,) = alm.apus.get_components("N1", "DIURNO")
    assert c.insumo_nombre == catalogo
```

Antes de dar por bueno el caso aproximado, comprueba que `cruce.elegir([catalogo, "EMPATE…"], guardado)` da APROXIMADO; si el ejemplo no llega al umbral 0,60, ajusta `guardado` hasta que sí.

En `tests/test_servicio_autoria.py`, actualizar las dos pruebas de `_mapas_de_componentes` (el histórico pasa a indexarse por código + nombre normalizado). En `test_mapas_de_componentes_devuelve_marcas_y_historico`:

```python
    assert hist == {("100", "CEMENTO GRIS"): 900.0, ("200", "ARENA"): 48000.0}
```

y en `test_mapas_de_componentes_codigo_repetido_gana_el_de_tipo_apu`:

```python
    assert hist[("100", "X")] == 700.0
```

(Si `normalizar` cambia el texto de esos nombres —tildes, mayúsculas—, usa `normalizar(...)` en la clave del assert.) `test_componentes_de_hereda_el_historico_del_mapa` y `test_componentes_de_sube_al_piso_un_historico_en_cero` pasan `hist={"100": ...}` (clave por código) y **no se tocan**: el respaldo por código para un código NO compartido tiene que seguir funcionando.

- [ ] **Step 2: Run to verify they fail**

Run: `env -u DATABASE_URL python -m pytest tests/test_codigos_compartidos.py tests/test_servicio_autoria.py -q`
Expected: FAIL (`AttributeError: ... CodigoCompartido`, y la señal guardada como reducción).

- [ ] **Step 3: Implement**

En `apu_tool/servicio/autoria.py`, agregar el import `from apu_tool.dominio import cruce` junto a los demás. Arriba de `_mapas_de_componentes`:

```python
class CodigoCompartido(ValueError):
    """Uno o más componentes citan un código que es de varios insumos del catálogo y
    el nombre no dice cuál. No se escribe nada: el ingeniero escoge en la fila.

    `conflictos` = [{"codigo", "opciones": [{"nombre", "unidad", "oculto"}]}], sin
    dinero (sale por la API). Es `ValueError` para que los llamadores que ya atrapan
    `ValueError` no se rompan; las rutas la atrapan ANTES para responder 422 con las
    opciones."""

    def __init__(self, conflictos: list[dict]):
        cods = ", ".join(c["codigo"] for c in conflictos)
        super().__init__(
            f"El código {cods} es de varios insumos distintos: escoge cuál va en la fila."
            if len(conflictos) == 1 else
            f"Los códigos {cods} son de varios insumos distintos: escoge cuál va en cada fila.")
        self.conflictos = conflictos
```

`_mapas_de_componentes`: el histórico por (código, nombre normalizado). Reemplazar el cuerpo del bucle:

```python
    for c in comps:
        if c.insumo_codigo not in previos or c.tipo == "apu":
            previos[c.insumo_codigo] = (c.tipo, c.ref_shift)
        clave = (c.insumo_codigo, normalizar(c.insumo_nombre))
        if clave not in hist or c.tipo == "apu":
            hist[clave] = c.precio_unitario_hist
    return previos, hist
```

(ajusta la anotación a `hist: dict[tuple[str, str], float] = {}` y el docstring: el histórico es por código + nombre porque el selector deja cambiar de fila dentro del mismo código.)

Agregar un helper debajo:

```python
def _hist_de(hist: dict, cod: str, nombre: str, compartido: bool) -> float:
    """El histórico heredado para (código, nombre). Un código NO compartido cae al
    respaldo por código (el contrato viejo: hay llamadores que pasan `{codigo: valor}`);
    uno compartido NO, porque sería el histórico de otro insumo."""
    h = hist.get((cod, normalizar(nombre)))
    if h is None and not compartido:
        h = hist.get(cod)
        if h is None:
            h = next((v for k, v in hist.items()
                      if isinstance(k, tuple) and k[0] == cod), None)
    return max(PISO_HIST, h or 0.0)
```

Reemplazar el bucle de `_componentes_de` (desde `for c in comp_dicts:` hasta `return comps`) por:

```python
    dudas: list[dict] = []
    for c in comp_dicts:
        cod = str(c.get("insumo_codigo", "") or "").strip()
        rend = _to_float(c.get("rendimiento"))
        if not cod:
            raise ValueError("Cada componente necesita un código de insumo.")
        if rend <= 0:
            raise ValueError(f"El rendimiento del insumo {cod} debe ser mayor que 0.")
        tipo_in = c.get("tipo")
        if tipo_in:
            tipo, ref_shift = str(tipo_in), str(c.get("ref_shift", "") or "")
        elif cod in previos:
            tipo, ref_shift = previos[cod]
        else:
            tipo, ref_shift = "insumo", ""
        nombre_in = str(c.get("insumo_nombre", "") or "")
        cands = alm.precios.get_candidatos(cod)
        compartido = tipo != "apu" and len(cands) > 1
        if compartido:
            # Código de dos o más insumos: la fila la decide el NOMBRE (la misma regla
            # con la que se costea). Antes se guardaba `cands[0]` y se perdía el insumo
            # que la persona había elegido, sin alerta (caso 4506 / 7406).
            fila = cruce.elegir_fila(cands, nombre_in)
            if fila is None:
                dudas.append({"codigo": cod, "opciones": cruce.opciones(cands)})
                continue
            nombre, unidad = fila.nombre, fila.unidad
        elif cands:
            # Un solo insumo (o un sub-APU): como siempre, nombre/unidad del catálogo.
            nombre, unidad = cands[0].nombre, cands[0].unidad
        else:
            # No existe: se guarda lo que venga (enlace blando -> cruce huérfano al costear).
            nombre = nombre_in
            unidad = str(c.get("unidad", "") or "")
        comps.append(ApuComponent(
            apu_codigo="", shift=shift, insumo_codigo=cod, insumo_nombre=nombre,
            unidad=unidad, rendimiento=rend,
            precio_unitario_hist=_hist_de(hist, cod, nombre, compartido),
            tipo=tipo, ref_shift=ref_shift))
    if dudas:
        raise CodigoCompartido(dudas)
    return comps
```

Ojo: el comportamiento para sub-APU (`tipo == "apu"`) es el de antes, a propósito (`cands[0]` si el código choca con un insumo); no lo "arregles" en esta tarea.

- [ ] **Step 4: Run tests**

Run: `env -u DATABASE_URL python -m pytest tests/test_codigos_compartidos.py tests/test_servicio_autoria.py tests/test_autoria_sin_duplicados.py tests/test_api_autoria.py tests/test_autoria_lista_precios_regresion.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/autoria.py tests/test_codigos_compartidos.py tests/test_servicio_autoria.py
git commit -m "fix(autoria): el alta elige la fila de un codigo compartido por nombre"
```

---

### Task 4: 422 con `conflictos` en las rutas

**Files:**
- Modify: `apu_tool/servicio/rutas.py` (`crear_apu` ~línea 1040, `editar_apu` ~línea 1091, `_composicion_o_error` ~línea 405)
- Test: `tests/test_codigos_compartidos.py`

- [ ] **Step 1: Write the failing tests**

```python
from apu_tool.servicio.app import create_app
from tests.conftest import cliente


def test_la_ruta_responde_422_con_las_opciones(tmp_path):
    alm = _alm(tmp_path)
    cli = cliente(create_app(almacen=alm), rol="admin")
    r = cli.post("/api/apus/crear", json={
        "codigo": "N1", "turno": "DIURNO", "nombre": "APU N1", "unidad": "UN", "grupo": "G",
        "componentes": [{"insumo_codigo": "7406", "rendimiento": 1}]})
    assert r.status_code == 422, r.text
    d = r.json()["detail"]
    assert "escoge" in d["mensaje"]
    assert [o["nombre"] for o in d["conflictos"][0]["opciones"]] == [REDUCCION, SENAL]
    assert "precio" not in r.text


def test_editar_responde_422_con_las_opciones(tmp_path):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("A1", "X", "UN", "DIURNO", "G")])
    cli = cliente(create_app(almacen=alm), rol="admin")
    r = cli.put("/api/apus/A1/DIURNO", json={
        "nombre": "X", "unidad": "UN", "grupo": "G",
        "componentes": [{"insumo_codigo": "7406", "insumo_nombre": "", "rendimiento": 1}]})
    assert r.status_code == 422 and r.json()["detail"]["conflictos"][0]["codigo"] == "7406"
```

- [ ] **Step 2: Run to verify they fail**

Run: `env -u DATABASE_URL python -m pytest tests/test_codigos_compartidos.py -q -k "ruta or editar_responde"`
Expected: FAIL (status 400 con detail string).

- [ ] **Step 3: Implement**

En `rutas.py`, un helper cerca de las rutas de APU:

```python
def _http_codigo_compartido(e: autoria.CodigoCompartido) -> HTTPException:
    """422 con las opciones: la web las muestra en la fila para que el ingeniero
    escoja. `detail.mensaje` es lo que ya lee `mensajeDeError` del cliente."""
    return HTTPException(status_code=422,
                         detail={"mensaje": str(e), "conflictos": e.conflictos})
```

En `crear_apu` y en `editar_apu`, antes de `except ValueError`:

```python
    except autoria.CodigoCompartido as e:
        raise _http_codigo_compartido(e)
```

En `_composicion_o_error`, antes de `except (composicion_svc.ComposicionInvalida, ValueError)`:

```python
    except autoria.CodigoCompartido as e:
        raise _http_codigo_compartido(e)
```

(Verifica que `rutas.py` ya importa `autoria`: `grep -n "autoria" apu_tool/servicio/rutas.py | head -3`. Si el helper queda definido debajo de `_composicion_o_error`, no importa: se resuelve en tiempo de llamada.)

- [ ] **Step 4: Run tests**

Run: `env -u DATABASE_URL python -m pytest tests/test_codigos_compartidos.py tests/test_api_autoria.py tests/test_api_composicion.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/rutas.py tests/test_codigos_compartidos.py
git commit -m "feat(api): 422 con las opciones cuando un codigo compartido no resuelve"
```

---

### Task 5: `nombre` en el contrato de composición y en el PUT de la mesa

**Files:**
- Modify: `apu_tool/dominio/composicion.py` (`ComponentePropuesto`, `to_dict`, `_componente_desde`, `_MAX_NOMBRE` y el comentario de `_MAX_TEXTO`)
- Modify: `apu_tool/servicio/esquemas.py:205-217` (`ComponenteComposicionIn`)
- Test: `tests/test_composicion_contrato.py`, `tests/test_api_composicion.py`

- [ ] **Step 1: Write the failing tests**

En `tests/test_composicion_contrato.py` (`propuesta_desde_json` vive en `apu_tool.dominio.composicion`; impórtalo si el archivo no lo hace):

```python
def test_el_nombre_viaja_y_no_se_recorta_a_500():
    largo = "TUBERIA PVC " * 75                     # ~900 caracteres, como los reales
    p = propuesta_desde_json({"componentes": [{"codigo": "7406", "nombre": largo,
                                               "rendimiento": 1}]})
    assert len(p.componentes[0].nombre) > 800
    assert p.componentes[0].to_dict()["nombre"] == p.componentes[0].nombre


def test_una_version_vieja_sin_nombre_sigue_cargando():
    p = propuesta_desde_json({"componentes": [{"codigo": "4279", "rendimiento": 1}]})
    assert p.componentes[0].nombre == ""
```

En `tests/test_api_composicion.py`, después de `test_put_guarda_una_version_nueva_y_revalida`:

```python
def test_put_conserva_el_nombre_del_componente(app_alm, corrida):
    """Sin `nombre` en el esquema del PUT, Pydantic lo bota y el selector de la mesa
    nunca se guarda."""
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    comps = [dict(COMPONENTES[0], nombre="CUADRILLA")]
    r = cliente(app, "editor").put(f"/api/corridas/{corrida}/composicion/1",
                                   json={"version_base": 1, "componentes": comps})
    assert r.status_code == 200
    assert r.json()["vigente"]["propuesta"]["componentes"][0]["nombre"] == "CUADRILLA"
```

- [ ] **Step 2: Run to verify they fail**

Run: `env -u DATABASE_URL python -m pytest tests/test_composicion_contrato.py tests/test_api_composicion.py -q`
Expected: FAIL (`AttributeError: ... 'nombre'` / `KeyError: 'nombre'`).

- [ ] **Step 3: Implement**

`apu_tool/dominio/composicion.py`:
- Reemplazar el comentario de `_MAX_TEXTO` (líneas ~160-164, el que avisa «OJO con _MAX_TEXTO si algún día se parsea un NOMBRE…») y agregar el tope nuevo:

```python
# Medido contra las bases reales del repo: el código más largo del catálogo tiene 7
# caracteres ("10016 N") y el `shift` más largo 8 ("NOCTURNO"), así que 40 sobra.
# Los NOMBRES de insumo reales llegan a 830 caracteres (`insumos.nombre`): por eso el
# `nombre` de un componente tiene tope propio. Recortarlo a `_MAX_TEXTO` lo haría
# imposible de cruzar EXACTO con el catálogo, que es justo para lo que viaja.
_MAX_TEXTO = 500
_MAX_NOMBRE = 1000
_MAX_CODIGO = 40
```

- En `ComponentePropuesto`, último campo (con default, para no romper constructores posicionales):

```python
    # Nombre del insumo en el catálogo. Un código puede ser de DOS insumos (652 en el
    # catálogo real): sin el nombre, el alta no sabe cuál. "" en las versiones viejas.
    nombre: str = ""
```

- En `to_dict`, agregar `"nombre": self.nombre,`.
- En `_componente_desde`, agregar `nombre=_texto(v.get("nombre"), _MAX_NOMBRE),`.

`apu_tool/servicio/esquemas.py`, en `ComponenteComposicionIn`, último campo:

```python
    nombre: str = ""
```

- [ ] **Step 4: Run tests**

Run: `env -u DATABASE_URL python -m pytest tests/test_composicion_contrato.py tests/test_api_composicion.py tests/test_composicion_privacidad.py tests/test_composiciones_db.py tests/test_composiciones_paridad.py -q`
Expected: PASS. Si algún test compara un `to_dict()` completo contra un dict literal, agrégale `"nombre": ""`.

- [ ] **Step 5: Commit**

```bash
git add apu_tool/dominio/composicion.py apu_tool/servicio/esquemas.py tests/test_composicion_contrato.py tests/test_api_composicion.py
git commit -m "feat(composicion): el componente lleva el nombre del insumo"
```

---

### Task 6: el validador marca `CODIGO_COMPARTIDO`

**Files:**
- Modify: `apu_tool/dominio/validacion_composicion.py` (`ContextoValidacion`, helper nuevo, `_validar_componente`)
- Test: `tests/test_validacion_composicion.py`

- [ ] **Step 1: Write the failing tests**

En `tests/test_validacion_composicion.py` (usa los helpers `comp`, `ctx` y `codigos` que ya tiene; mira cómo arman la `Propuesta` los tests existentes y copia esa forma):

```python
COMPARTIDOS = {"6092": (("HERRAMIENTA MENOR", "GLB"),
                        ("RELOCALIZACION DE MEDIDOR DE ACUEDUCTO", "UN"))}


def _prop(*cs):
    return Propuesta(componentes=tuple(cs), supuestos=(), incertidumbre_declarada=0.3,
                     justificacion="j")


def test_un_codigo_compartido_sin_nombre_es_error():
    r = validar(_prop(comp(codigo="6092", funcion="herramienta", nombre="")),
                ctx(candidatos_compartidos=COMPARTIDOS))
    assert "CODIGO_COMPARTIDO" in codigos(r.errores)
    assert not r.valido


def test_un_codigo_compartido_con_nombre_que_resuelve_no_es_error():
    r = validar(_prop(comp(codigo="6092", funcion="herramienta",
                           nombre="HERRAMIENTA MENOR")),
                ctx(candidatos_compartidos=COMPARTIDOS))
    assert "CODIGO_COMPARTIDO" not in codigos(r.errores)


def test_sin_compartidos_en_el_contexto_no_cambia_nada():
    assert "CODIGO_COMPARTIDO" not in codigos(validar(_prop(comp()), ctx()).errores)
```

(Si `validar` devuelve una tupla o el resultado se llama distinto, adáptalo a como lo usan los demás tests del archivo.)

- [ ] **Step 2: Run to verify they fail**

Run: `env -u DATABASE_URL python -m pytest tests/test_validacion_composicion.py -q`
Expected: FAIL (`unexpected keyword argument 'candidatos_compartidos'`).

- [ ] **Step 3: Implement**

En `ContextoValidacion`, al final:

```python
    # (nombre, unidad) de cada código del catálogo que es de DOS o más insumos, en
    # orden de id. Solo nombres: el validador no ve `Insumo` (lleva precio). Vacío =
    # nadie lo armó (contextos viejos de tests): no se valida, como antes.
    candidatos_compartidos: dict[str, tuple[tuple[str, str], ...]] = field(
        default_factory=dict)
```

Importar `from apu_tool.dominio.cruce import elegir` arriba. Agregar un helper antes de `_validar_componente`:

```python
def _fila_compartida(c: ComponentePropuesto, ctx: ContextoValidacion
                     ) -> tuple[bool, str | None]:
    """(es_compartido, unidad de la fila elegida o None si el nombre no resuelve)."""
    opciones = ctx.candidatos_compartidos.get(c.codigo)
    if not opciones:
        return False, None
    i, _calidad, _score = elegir([n for n, _u in opciones], c.nombre)
    return True, (opciones[i][1] if i is not None else None)
```

En `_validar_componente`, en la rama de insumo (la `else:` que hoy emite `CODIGO_INEXISTENTE`, ~línea 238), después del `if c.codigo not in ctx.unidades_catalogo: ...`:

```python
        compartido, unidad_fila = _fila_compartida(c, ctx)
        if compartido:
            reglas += 1
            if unidad_fila is None:
                # Destrabable en la mesa (el ingeniero escoge cuál): pasa la prueba
                # de CLAUDE.md para ser error. Sin esto, aprobar guardaría una fila del
                # código que nadie eligió.
                err.append(Hallazgo(
                    "CODIGO_COMPARTIDO",
                    f"El código {cod} es de varios insumos distintos y el nombre no "
                    f"dice cuál: escoge cuál en la fila.", cod))
```

En el chequeo de unidad (~línea 307), reemplazar `unidad_cat = ctx.unidades_catalogo.get(c.codigo)` por:

```python
        compartido, unidad_fila = _fila_compartida(c, ctx)
        # Código compartido: la unidad es la de la fila que eligió el nombre, no la de
        # la primera fila del código (sería la de otro insumo).
        unidad_cat = (unidad_fila if compartido and unidad_fila is not None
                      else ctx.unidades_catalogo.get(c.codigo))
```

- [ ] **Step 4: Run tests**

Run: `env -u DATABASE_URL python -m pytest tests/test_validacion_composicion.py tests/test_confianza_composicion.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apu_tool/dominio/validacion_composicion.py tests/test_validacion_composicion.py
git commit -m "feat(composicion): el validador marca CODIGO_COMPARTIDO"
```

---

### Task 7: armar `candidatos_compartidos`, ficha de la mesa y aprobar con nombre

**Files:**
- Modify: `apu_tool/dominio/composicion_agente.py` (`recuperar`, ~líneas 41-90)
- Modify: `apu_tool/servicio/composicion.py` (`_catalogo_de` ~196, `_con_lista_blanca` ~444, `_componentes_para_autoria` ~465)
- Test: `tests/test_api_composicion.py`

- [ ] **Step 1: Write the failing tests**

En `tests/test_api_composicion.py` (al final). El fixture `app_alm` ya tiene 6092 HERRAMIENTA MENOR; se le agrega el homónimo:

```python
def _homonimo(alm):
    alm.precios.insert_insumos([Insumo("6092", "RELOCALIZACION DE MEDIDOR DE ACUEDUCTO",
                                       "UN", "REDES", 9, "PRECIO IDU")])


HERRAMIENTA = dict(COMPONENTES[0], codigo="6092", funcion="herramienta", rendimiento=1.0,
                   origen="supuesto_tecnico", referencias=[])


def test_la_ficha_de_un_codigo_compartido_trae_las_opciones(app_alm, corrida):
    app, alm = app_alm
    _homonimo(alm)
    _sembrar(alm, corrida, version=1, componentes=COMPONENTES + [HERRAMIENTA])
    d = cliente(app, "consulta").get(f"/api/corridas/{corrida}/composicion/1").json()
    f = d["catalogo"]["6092"]
    assert f["nombre"] == "" and len(f["opciones"]) == 2
    assert "precio" not in str(f)


def test_put_de_un_codigo_compartido_sin_nombre_es_error_y_con_nombre_no(app_alm, corrida):
    app, alm = app_alm
    _homonimo(alm)
    _sembrar(alm, corrida, version=1)
    c = cliente(app, "editor")
    r = c.put(f"/api/corridas/{corrida}/composicion/1",
              json={"version_base": 1, "componentes": COMPONENTES + [HERRAMIENTA]})
    errores = {e["codigo"] for e in r.json()["vigente"]["validacion"]["errores"]}
    assert "CODIGO_COMPARTIDO" in errores
    con_nombre = dict(HERRAMIENTA, nombre="HERRAMIENTA MENOR")
    r = c.put(f"/api/corridas/{corrida}/composicion/1",
              json={"version_base": 2, "componentes": COMPONENTES + [con_nombre]})
    errores = {e["codigo"] for e in r.json()["vigente"]["validacion"]["errores"]}
    assert "CODIGO_COMPARTIDO" not in errores
    assert r.json()["catalogo"]["6092"]["nombre"] == "HERRAMIENTA MENOR"


def test_aprobar_guarda_la_fila_que_dice_el_nombre(app_alm, corrida):
    """Nombra la SEGUNDA fila del código (la de id mayor): sin el arreglo, el alta
    guardaba la primera (HERRAMIENTA MENOR) y este test falla."""
    app, alm = app_alm
    _homonimo(alm)
    _sembrar(alm, corrida, version=1, componentes=COMPONENTES + [
        dict(HERRAMIENTA, nombre="RELOCALIZACION DE MEDIDOR DE ACUEDUCTO")])
    r = cliente(app, "editor").post(f"/api/corridas/{corrida}/composicion/1/aprobar",
                                    json=APROBAR)
    assert r.status_code == 200, r.text
    nombres = {c.insumo_codigo: c.insumo_nombre
               for c in alm.apus.get_components("9001", "DIURNO")}
    assert nombres["6092"] == "RELOCALIZACION DE MEDIDOR DE ACUEDUCTO"


def test_aprobar_un_codigo_compartido_sin_nombre_es_422(app_alm, corrida):
    app, alm = app_alm
    _homonimo(alm)
    _sembrar(alm, corrida, version=1, componentes=COMPONENTES + [HERRAMIENTA])
    r = cliente(app, "editor").post(f"/api/corridas/{corrida}/composicion/1/aprobar",
                                    json=APROBAR)
    assert r.status_code == 422
    assert alm.apus.get_apu("9001", "DIURNO") is None
```

(El `_sembrar` deja `codigos_permitidos=["4279"]`; `_lista_blanca` suma los códigos de la propuesta, así que 6092 entra a la lista blanca al revalidar. Si algún test falla por `CODIGO_NO_AUTORIZADO`, pasa `antecedentes` con 6092 en `_sembrar` en vez de tocar el código de producción.)

- [ ] **Step 2: Run to verify they fail**

Run: `env -u DATABASE_URL python -m pytest tests/test_api_composicion.py -q`
Expected: FAIL (`KeyError: 'opciones'`, sin `CODIGO_COMPARTIDO`, aprobar guarda la otra fila).

- [ ] **Step 3: Implement**

`apu_tool/dominio/composicion_agente.py`, en `recuperar`: importar `from apu_tool.dominio import cruce` y reemplazar el bucle de `grupos/unidades`:

```python
    catalogo = almacen.precios.get_candidatos_bulk(codigos)
    nombre_de = {i.codigo: i.nombre for i in insumos}
    grupos, unidades = {}, {}
    for cod, cands in catalogo.items():
        if cands:
            # Código compartido: el grupo es el de la fila que el candidato nombra
            # (la que vio el modelo), no el de la primera fila del código.
            fila = cruce.elegir_fila(cands, nombre_de.get(cod, "")) or cands[0]
            grupos[cod] = fila.grupo or ""
            unidades[cod] = cands[0].unidad or ""
```

y en la construcción de `ContextoValidacion(...)` (~línea 89) agregar:

```python
        candidatos_compartidos=cruce.compartidos(catalogo),
```

`apu_tool/servicio/composicion.py`, importar `from apu_tool.dominio import cruce` y:

- `_con_lista_blanca`: completar compartidos con los códigos agregados:

```python
    faltan = sorted(c for c in blanca if c and c not in ctx.unidades_catalogo)
    unidades = dict(ctx.unidades_catalogo)
    compartidos = dict(ctx.candidatos_compartidos)
    if faltan:
        bulk = alm.precios.get_candidatos_bulk(faltan)
        for cod, cands in bulk.items():
            if cands:
                unidades[cod] = cands[0].unidad or ""
        # Un código agregado por una persona (buscador o chat) también puede ser
        # compartido: sin esto el validador no lo vería.
        compartidos.update(cruce.compartidos(bulk))
    return replace(ctx, codigos_permitidos=blanca, unidades_catalogo=unidades,
                   candidatos_compartidos=compartidos)
```

- `_catalogo_de`: resolver por componente (actualiza el docstring: la ficha es por código + nombre y trae `opciones` si el código es compartido; un código fuera del catálogo sigue sin aparecer):

```python
    comps = ((v.propuesta or {}).get("componentes") or []) if v else []
    codigos = [str(c.get("codigo", "")) for c in comps if c.get("codigo")]
    if not codigos:
        return {}
    bulk = alm.precios.get_candidatos_bulk(codigos)
    out: dict[str, dict] = {}
    for c in comps:
        cod = str(c.get("codigo", ""))
        cands = bulk.get(cod) or []
        if cands:
            out[cod] = cruce.ficha(cands, str(c.get("nombre", "") or ""))
    return out
```

- `_componentes_para_autoria`: agregar `"insumo_nombre": c.get("nombre", "") or "",` al dict, y en el docstring cambiar «Nombre y unidad NO se mandan» por: «El nombre SÍ se manda: es lo que le dice al alta cuál de las filas de un código compartido va. La unidad la pone el catálogo.»

- [ ] **Step 4: Run tests**

Run: `env -u DATABASE_URL python -m pytest tests/test_api_composicion.py tests/test_composicion_motor.py tests/test_composicion_privacidad.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apu_tool/dominio/composicion_agente.py apu_tool/servicio/composicion.py tests/test_api_composicion.py
git commit -m "feat(composicion): ficha con opciones, validacion de compartidos y aprobar con nombre"
```

---

### Task 8: el modelo de Componer manda `nombre`

**Files:**
- Modify: `apu_tool/dominio/ai_assist.py` (esquema de composición ~líneas 145-206, `_SISTEMA_COMPOSICION` ~88, `PROMPT_VERSION` línea 87)
- Test: `tests/test_composicion_advisor.py`

- [ ] **Step 1: Write the failing test**

Mira cómo se llama la constante del esquema (`grep -n "^_ESQUEMA" apu_tool/dominio/ai_assist.py`) y agrega a `tests/test_composicion_advisor.py` (reemplaza `_ESQUEMA_COMPOSICION` por el nombre real):

```python
from apu_tool.dominio import ai_assist


def test_el_esquema_de_componer_pide_el_nombre_del_insumo():
    item = ai_assist._ESQUEMA_COMPOSICION["properties"]["componentes"]["items"]
    assert item["properties"]["nombre"] == {"type": "string"}
    assert "nombre" in item["required"]
    assert ai_assist.PROMPT_VERSION == "composicion/v5"
    assert "`nombre`" in ai_assist._SISTEMA_COMPOSICION
```

- [ ] **Step 2: Run to verify it fails**

Run: `env -u DATABASE_URL python -m pytest tests/test_composicion_advisor.py -q`
Expected: FAIL (`KeyError: 'nombre'`).

- [ ] **Step 3: Implement**

- `PROMPT_VERSION = "composicion/v5"`.
- En `properties` del ítem de componente, después de `"codigo": {"type": "string"},`:

```python
                    # Varios insumos comparten código (652 en el catálogo real): el
                    # nombre es lo que le dice al alta cuál es.
                    "nombre": {"type": "string"},
```

- En `required` del ítem, agregar `"nombre"` después de `"codigo"`.
- En `_SISTEMA_COMPOSICION`, en "Reglas estrictas", después de la regla de los códigos:

```
- En cada componente manda `nombre`: el nombre del insumo copiado TAL CUAL aparece en
  la lista de insumos disponibles. Varios insumos distintos comparten código, y sin el
  nombre la plataforma no sabe cuál quieres.
```

- [ ] **Step 4: Run tests**

Run: `env -u DATABASE_URL python -m pytest tests/test_composicion_advisor.py tests/test_composicion_motor.py -q`
Expected: PASS. Si un test fija `"composicion/v4"` como versión vigente del prompt, actualízalo a v5 (no los que siembran expedientes viejos con v4).

- [ ] **Step 5: Commit**

```bash
git add apu_tool/dominio/ai_assist.py tests/test_composicion_advisor.py
git commit -m "feat(composicion): Componer pide el nombre del insumo (composicion/v5)"
```

---

### Task 9: el chat deja el candado provisional y resuelve con `cruce`

**Files:**
- Modify: `apu_tool/dominio/composicion_chat.py` (borrar `_motivo_compartido` y `MIN_PARECIDO_NOMBRE`; reescribir `_catalogo` y `_respuesta`; llamada en `conversar` ~línea 291)
- Test: `tests/test_composicion_chat_motor.py` (líneas 200-256 y 324-354)

- [ ] **Step 1: Rewrite the tests**

En `tests/test_composicion_chat_motor.py`:

Reemplazar `test_descarta_un_alta_con_codigo_compartido_por_dos_insumos` por:

```python
def test_un_codigo_compartido_entra_con_el_nombre_que_dice_el_agente(alm):
    """Smoke 2026-11-19: el agente propuso «7406 SEÑAL VERTICAL» y la tabla mostró la
    REDUCCION. Ahora el alta elige por nombre, así que la señal entra como señal."""
    alm.precios.insert_insumos([
        Insumo("8001", "REDUCCION HD E.L. D=12 x 10", "UN", "ACCESORIOS", 1000,
               "PRECIO IDU"),
        Insumo("8001", "SEÑAL VERTICAL SR 90X30 INCLUYE POSTE", "UN", "SEÑALIZACION",
               2000, "PRECIO IDU"),
    ])
    a = AdvisorGuion([resp_final("Te agrego la señal.", [
        {"op": "agregar", "codigo": "8001", "nombre": "SEÑAL VERTICAL SR 90X30 INCLUYE POSTE",
         "componente": componente("8001")}])])
    resp = correr(alm, a, charla("agrega la señal"))[-1][1]
    (c,) = resp["cambios"]
    assert c["componente"]["nombre"] == "SEÑAL VERTICAL SR 90X30 INCLUYE POSTE"
    assert resp["catalogo"]["8001"]["nombre"] == "SEÑAL VERTICAL SR 90X30 INCLUYE POSTE"
    assert resp["descartados"] == []
```

Reemplazar `test_un_codigo_compartido_pasa_si_el_agente_quiere_el_que_guarda_el_alta` por:

```python
def test_el_nombre_guardado_es_el_del_catalogo_no_el_del_agente(alm):
    alm.precios.insert_insumos([
        Insumo("8001", "REDUCCION HD E.L. D=12 x 10", "UN", "ACCESORIOS", 1000,
               "PRECIO IDU"),
        Insumo("8001", "SEÑAL VERTICAL SR 90X30 INCLUYE POSTE", "UN", "SEÑALIZACION",
               2000, "PRECIO IDU"),
    ])
    a = AdvisorGuion([resp_final("Te agrego la reducción.", [
        {"op": "agregar", "codigo": "8001", "nombre": "REDUCCION HD E.L. D=12\" x 10\"",
         "componente": componente("8001")}])])
    resp = correr(alm, a, charla("agrega la reducción"))[-1][1]
    assert resp["cambios"][0]["componente"]["nombre"] == "REDUCCION HD E.L. D=12 x 10"
```

Reemplazar `test_un_codigo_compartido_sin_nombre_se_descarta` por:

```python
def test_un_codigo_compartido_sin_nombre_entra_y_lo_escoge_el_ingeniero(alm):
    alm.precios.insert_insumos([
        Insumo("8001", "REDUCCION HD E.L. D=12 x 10", "UN", "ACCESORIOS", 1000,
               "PRECIO IDU"),
        Insumo("8001", "SEÑAL VERTICAL SR 90X30 INCLUYE POSTE", "UN", "SEÑALIZACION",
               2000, "PRECIO IDU"),
    ])
    a = AdvisorGuion([resp_final("Ahí va.", [
        {"op": "agregar", "codigo": "8001", "componente": componente("8001")}])])
    resp = correr(alm, a, charla("agrega el 8001"))[-1][1]
    (c,) = resp["cambios"]
    assert c["componente"]["nombre"] == ""
    assert len(resp["catalogo"]["8001"]["opciones"]) == 2
```

Reemplazar `test_un_alta_cuyo_homonimo_oculto_va_primero_se_descarta` por:

```python
def test_un_alta_con_homonimo_oculto_entra_si_nombra_el_visible(alm):
    alm.precios.insert_insumos([
        Insumo("8000", "NOMBRE VIEJO OCULTO", "UN", "EQ", 10, "COSTO INTERNO"),
        Insumo("8000", "NOMBRE VISIBLE", "UN", "EQ", 10, "COSTO INTERNO"),
    ])
    alm.precios.set_oculto(alm.precios.search_insumos("NOMBRE VIEJO OCULTO")[0].id, True)
    a = AdvisorGuion([resp_final("Ahí va.", [
        {"op": "agregar", "codigo": "8000", "nombre": "NOMBRE VISIBLE",
         "componente": componente("8000")}])])
    resp = correr(alm, a, charla("agrega el 8000"))[-1][1]
    assert resp["cambios"][0]["componente"]["nombre"] == "NOMBRE VISIBLE"


def test_un_alta_que_nombra_el_oculto_se_descarta(alm):
    alm.precios.insert_insumos([
        Insumo("8000", "NOMBRE VIEJO OCULTO", "UN", "EQ", 10, "COSTO INTERNO"),
        Insumo("8000", "NOMBRE VISIBLE", "UN", "EQ", 10, "COSTO INTERNO"),
    ])
    alm.precios.set_oculto(alm.precios.search_insumos("NOMBRE VIEJO OCULTO")[0].id, True)
    a = AdvisorGuion([resp_final("Ahí va.", [
        {"op": "agregar", "codigo": "8000", "nombre": "NOMBRE VIEJO OCULTO",
         "componente": componente("8000")}])])
    resp = correr(alm, a, charla("agrega el 8000"))[-1][1]
    assert resp["cambios"] == [] and "oculto" in resp["descartados"][0]["motivo"]
```

Reemplazar `test_las_altas_repetidas_consultan_la_visibilidad_una_vez_por_codigo` por un test que pruebe que `_respuesta` hace UNA consulta al catálogo por respuesta (no una por cambio). Llama directo a la función para no contar la consulta del contexto de la mesa:

```python
def test_la_respuesta_consulta_el_catalogo_una_sola_vez(alm, monkeypatch):
    from apu_tool.dominio import composicion_chat
    llamadas = []
    original = alm.precios.get_candidatos_bulk
    monkeypatch.setattr(alm.precios, "get_candidatos_bulk",
                        lambda cods, *a, **k: llamadas.append(list(cods)) or original(cods, *a, **k))
    composicion_chat._respuesta(alm, {"texto": "Ok.", "cambios": [
        {"op": "agregar", "codigo": "6092", "componente": componente("6092")},
        {"op": "agregar", "codigo": "6092", "componente": componente("6092", 2.0)},
    ]}, "m")
    assert llamadas == [["6092"]]
```

- [ ] **Step 2: Run to verify they fail**

Run: `env -u DATABASE_URL python -m pytest tests/test_composicion_chat_motor.py -q`
Expected: FAIL en los tests nuevos.

- [ ] **Step 3: Implement**

En `apu_tool/dominio/composicion_chat.py`:
- Borrar `MIN_PARECIDO_NOMBRE` y `_motivo_compartido`. Importar `from apu_tool.dominio import cruce`. En `from apu_tool.nucleo.relevancia import _tokens, similarity` deja solo lo que se siga usando (verifica con `grep -n "similarity" apu_tool/dominio/composicion_chat.py`).
- Reemplazar `_catalogo`:

```python
def _catalogo(almacen: Almacen, componentes) -> dict[str, dict]:
    """Ficha (nombre, unidad, grupo y, si el código es compartido, opciones) de cada
    componente de la mesa, en UNA consulta. El nombre que manda el cliente solo se usa
    para ESCOGER la fila: lo que se muestra y viaja al agente es el del catálogo (el
    del cliente es texto libre y podría traer un monto)."""
    comps = [c for c in componentes if isinstance(c, dict) and c.get("codigo")]
    if not comps:
        return {}
    bulk = almacen.precios.get_candidatos_bulk(sorted({str(c["codigo"]) for c in comps}))
    out = {}
    for c in comps:
        cod = str(c["codigo"])
        if bulk.get(cod):
            out[cod] = cruce.ficha(bulk[cod], str(c.get("nombre", "") or ""))
    return out
```

- En `conversar`, la llamada pasa a `catalogo = _catalogo(almacen, componentes)`.
- Reemplazar el cuerpo de `_respuesta` (desde `data = data if ...` hasta el `return`), y actualizar su docstring (ya no hay candado por código compartido: el nombre decide, y si no alcanza el componente entra sin nombre y la mesa pide escoger):

```python
    data = data if isinstance(data, dict) else {}
    crudos = [c for c in (data.get("cambios") or []) if isinstance(c, dict)]
    codigos = [str(c.get("codigo", "") or "").strip()[:40] for c in crudos]
    # UNA consulta por respuesta: `Insumo.oculto` trae la visibilidad, así que ya no
    # hace falta una consulta por código (el egress de Supabase ya fue un problema).
    validos = sorted({c for c in codigos if c})
    bulk = almacen.precios.get_candidatos_bulk(validos) if validos else {}
    catalogo: dict[str, dict] = {}
    cambios, descartados = [], []
    for c, cod in zip(crudos, codigos):
        op = c.get("op")
        if op not in OPS_CHAT or not cod:
            descartados.append({"codigo": cod, "motivo": "Cambio ilegible."})
            continue
        cands = bulk.get(cod) or []
        nombre = str(c.get("nombre", "") or "")
        fila = cruce.elegir_fila(cands, nombre)
        if op == "agregar":
            if not cands or all(x.oculto for x in cands):
                descartados.append({"codigo": cod,
                                    "motivo": "No está en el catálogo (o está oculto)."})
                continue
            if fila is not None and fila.oculto:
                descartados.append({"codigo": cod,
                                    "motivo": f"«{fila.nombre[:60]}» está oculto en el "
                                              "catálogo."})
                continue
        if cands:
            catalogo[cod] = cruce.ficha(cands, nombre)
        comp = None
        if op != "quitar":
            p = propuesta_desde_json({"componentes": [c.get("componente")]})
            if not p.componentes:
                descartados.append({"codigo": cod,
                                    "motivo": "El agente no mandó el componente."})
                continue
            # El nombre que se guarda es el del CATÁLOGO (la fila que eligió el nombre
            # del agente), nunca el texto del agente. Si no resolvió, va vacío y la
            # mesa le pide al ingeniero que escoja (CODIGO_COMPARTIDO).
            comp = replace(p.componentes[0], codigo=cod,
                           nombre=fila.nombre if fila else "").to_dict()
        cambios.append({"op": op, "codigo": cod, "componente": comp})
    return {"texto": str(data.get("texto", "") or "")[:2000], "cambios": cambios,
            "descartados": descartados, "catalogo": catalogo, "modelo": modelo,
            "prompt_version": PROMPT_VERSION_CHAT}
```

Ojo: `privacy.componente_mesa_to_dict` toma nombre y unidad de `catalogo` (ya son las de la fila elegida): no hace falta tocarla, y **no** le agregues el `nombre` del cliente.

- [ ] **Step 4: Run tests**

Run: `env -u DATABASE_URL python -m pytest tests/test_composicion_chat_motor.py tests/test_api_composicion_chat.py tests/test_privacy_chat.py tests/test_composicion_chat_advisor.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apu_tool/dominio/composicion_chat.py tests/test_composicion_chat_motor.py
git commit -m "fix(chat): el codigo compartido lo decide el nombre, no un candado"
```

---

### Task 10: tipos y selector compartido (web)

**Files:**
- Modify: `web/src/lib/tipos.ts` (`ComponentePropuesto` ~83, `EntradaCatalogo` ~163)
- Create: `web/src/components/SelectorCompartido.tsx`
- Test: `web/src/components/SelectorCompartido.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import SelectorCompartido from "./SelectorCompartido";

const OPCIONES = [
  { nombre: "REDUCCION HD", unidad: "UN", oculto: false },
  { nombre: "SEÑAL VERTICAL", unidad: "UN", oculto: true },
];

test("sin elegir muestra la pregunta y al escoger devuelve la opción", () => {
  const onElegir = vi.fn();
  render(<SelectorCompartido codigo="7406" opciones={OPCIONES} valor="" onElegir={onElegir} />);
  const sel = screen.getByLabelText("Insumo del código 7406") as HTMLSelectElement;
  expect(sel.value).toBe("");
  expect(screen.getByText(/¿Cuál de los/)).toBeTruthy();
  expect(screen.getByText(/SEÑAL VERTICAL · UN \(oculto\)/)).toBeTruthy();
  fireEvent.change(sel, { target: { value: "1" } });
  expect(onElegir).toHaveBeenCalledWith(OPCIONES[1]);
});

test("con un nombre que coincide queda seleccionado", () => {
  render(<SelectorCompartido codigo="7406" opciones={OPCIONES} valor="reduccion hd"
                             onElegir={() => {}} />);
  expect((screen.getByLabelText("Insumo del código 7406") as HTMLSelectElement).value).toBe("0");
});

test("deshabilitado no deja cambiar", () => {
  render(<SelectorCompartido codigo="7406" opciones={OPCIONES} valor="" onElegir={() => {}}
                             deshabilitado />);
  expect((screen.getByLabelText("Insumo del código 7406") as HTMLSelectElement).disabled)
    .toBe(true);
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npx vitest run src/components/SelectorCompartido.test.tsx`
Expected: FAIL (no existe el módulo).

- [ ] **Step 3: Implement**

`web/src/lib/tipos.ts`:
- En `ComponentePropuesto`, último campo:

```ts
  /** Nombre del insumo en el catálogo: un código puede ser de dos insumos. Ausente
   *  o "" en las versiones viejas del expediente. */
  nombre?: string;
```

- Reemplazar `EntradaCatalogo` por:

```ts
/** Una de las filas de un código compartido. Sin precio a propósito. */
export interface OpcionInsumo {
  nombre: string;
  unidad: string;
  oculto: boolean;
}

export interface EntradaCatalogo {
  nombre: string;          // "" si el código es compartido y el nombre no dice cuál
  unidad: string;
  grupo: string;
  /** Solo si el código es de dos o más insumos: para que el ingeniero escoja. */
  opciones?: OpcionInsumo[];
}
```

`web/src/components/SelectorCompartido.tsx` (busca `normalizarNombre` en `@/lib/duplicarApu`; si normaliza igual que `nucleo/texto.normalizar` —sin tildes, mayúsculas, espacios colapsados—, reúsalo en vez de `norm`):

```tsx
import type { OpcionInsumo } from "@/lib/tipos";

/** Mismo criterio que `nucleo/texto.normalizar`: sin tildes, mayúsculas, espacios
 *  colapsados. Solo para reconocer cuál opción ya está elegida. */
function norm(s: string): string {
  return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toUpperCase()
    .replace(/\s+/g, " ").trim();
}

interface Props {
  codigo: string;
  opciones: OpcionInsumo[];
  /** El nombre que tiene hoy la fila ("" = sin elegir). */
  valor: string;
  onElegir: (o: OpcionInsumo) => void;
  deshabilitado?: boolean;
}

/** Un código del catálogo que es de varios insumos: el ingeniero escoge cuál.
 *  Se usa en el diálogo de APU (tras un 422) y en la mesa de composición. */
export default function SelectorCompartido({
  codigo, opciones, valor, onElegir, deshabilitado = false,
}: Props) {
  const i = opciones.findIndex((o) => norm(o.nombre) === norm(valor));
  return (
    <select
      aria-label={`Insumo del código ${codigo}`}
      className={"h-7 w-full max-w-[22rem] rounded border bg-transparent px-1 text-xs "
        + (i < 0 ? "border-destructive" : "border-border")}
      value={i < 0 ? "" : String(i)}
      disabled={deshabilitado}
      onChange={(e) => {
        const o = opciones[Number(e.target.value)];
        if (o) onElegir(o);
      }}
    >
      <option value="" disabled>
        {`¿Cuál de los ${opciones.length}? El código ${codigo} es de varios insumos`}
      </option>
      {opciones.map((o, j) => (
        <option key={j} value={String(j)}>
          {`${o.nombre} · ${o.unidad}${o.oculto ? " (oculto)" : ""}`}
        </option>
      ))}
    </select>
  );
}
```

- [ ] **Step 4: Run tests**

Run: `cd web && npx vitest run src/components/SelectorCompartido.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/tipos.ts web/src/components/SelectorCompartido.tsx web/src/components/SelectorCompartido.test.tsx
git commit -m "feat(web): selector para escoger el insumo de un codigo compartido"
```

---

### Task 11: el diálogo de APU muestra el selector tras un 422

**Files:**
- Modify: `web/src/components/autoria/DialogoAgregarApu.tsx` (estado nuevo, `handleOpenChange`, `guardar` ~327-357, celda del insumo ~514-541)
- Test: `web/src/components/autoria/DialogoAgregarApu.test.tsx`

- [ ] **Step 1: Write the failing test**

Al final del archivo de test (usa los mocks de arriba). `ErrorApi` es real y se importa de `@/api/client`; si importar ese módulo arrastra `@/lib/supabase` y se cae sin envs, mockea `@/lib/supabase` con `vi.mock("@/lib/supabase", () => ({ supabase: { auth: { getSession: vi.fn(), signOut: vi.fn() } } }))`:

```tsx
import { editarApu } from "@/api/autoria";
import { listarInsumos } from "@/api/insumos";
import { ErrorApi } from "@/api/client";

test("un 422 de código compartido muestra el selector en la fila y reintenta", async () => {
  const opciones = [
    { nombre: "CEMENTO", unidad: "KG", oculto: false },
    { nombre: "CEMENTO BLANCO", unidad: "BULTO", oculto: false },
  ];
  vi.mocked(editarApu)
    .mockRejectedValueOnce(new ErrorApi("El código C1 es de varios insumos distintos", 422, {
      mensaje: "El código C1 es de varios insumos distintos",
      conflictos: [{ codigo: "C1", opciones }],
    }))
    .mockResolvedValueOnce({} as never);
  vi.mocked(listarInsumos).mockResolvedValueOnce({
    items: [{ id: 2, codigo: "C1", nombre: "CEMENTO BLANCO", unidad: "BULTO", grupo: "M",
              precio: 3000, fuente: "", clasificacion: "", sin_precio: false }],
    total: 1, limit: 15, offset: 0,
  } as never);
  render(<DialogoAgregarApu open onOpenChange={() => {}} onCreado={() => {}}
    modo="editar" inicial={inicialDemo as never} />);
  fireEvent.click(await screen.findByRole("button", { name: /Guardar cambios/ }));
  const sel = await screen.findByLabelText("Insumo del código C1") as HTMLSelectElement;
  fireEvent.change(sel, { target: { value: "1" } });
  await waitFor(() => expect(screen.getByText("BULTO")).toBeTruthy());
  fireEvent.click(screen.getByRole("button", { name: /Guardar cambios/ }));
  await waitFor(() => expect(vi.mocked(editarApu)).toHaveBeenLastCalledWith(
    "100", "DIURNO", expect.objectContaining({
      componentes: [expect.objectContaining({ insumo_codigo: "C1",
                                              insumo_nombre: "CEMENTO BLANCO" })],
    })));
});
```

(Si el botón Guardar no queda habilitado en modo editar con `inicialDemo` —por grupo o vocabulario—, mira cómo lo resuelven los tests de modo editar que ya existen en el archivo, ~líneas 78-110, y copia su preparación.)

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npx vitest run src/components/autoria/DialogoAgregarApu.test.tsx`
Expected: FAIL (no aparece el selector).

- [ ] **Step 3: Implement**

En `DialogoAgregarApu.tsx`:
- Imports: `import SelectorCompartido from "@/components/SelectorCompartido";`, `import { ErrorApi } from "@/api/client";`, y `OpcionInsumo` en el `import type` de `@/lib/tipos` que ya existe (o uno nuevo).
- Estado nuevo junto a los demás:

```tsx
  // Códigos que el backend no pudo resolver (422 `conflictos`): código -> opciones.
  // Se limpia la entrada de un código cuando el ingeniero escoge.
  const [dudas, setDudas] = useState<Record<string, OpcionInsumo[]>>({});
```

- En `handleOpenChange`, donde se resetea el estado al cerrar (junto a `setConflicto(null)`): `setDudas({});`.
- En el `catch` de `guardar`, antes del `toast.error`:

```tsx
      const det = e instanceof ErrorApi ? (e.detail as { conflictos?: unknown } | null) : null;
      if (det && Array.isArray(det.conflictos)) {
        const mapa: Record<string, OpcionInsumo[]> = {};
        for (const c of det.conflictos as { codigo: string; opciones: OpcionInsumo[] }[]) {
          mapa[c.codigo] = c.opciones;
        }
        setDudas(mapa);
      }
```

- Un handler que fija la fila y trae su precio (el 422 no trae dinero a propósito; el costo de la fila sale del listado de insumos, que el diálogo ya usa):

```tsx
  async function elegirOpcion(uid: number, codigo: string, o: OpcionInsumo) {
    setFila(uid, { insumo_nombre: o.nombre, unidad: o.unidad });
    setDudas((prev) => {
      const { [codigo]: _quitado, ...resto } = prev;
      return resto;
    });
    try {
      const res = await listarInsumos({ q: codigo, limit: 15 });
      const ins = res.items.find((x) => x.codigo === codigo && x.nombre === o.nombre);
      if (ins) setFila(uid, { precio: ins.precio });
    } catch {
      /* sin precio: el costo de la fila se ve desactualizado hasta guardar */
    }
  }
```

(Verifica la firma real de `listarInsumos` en `web/src/api/insumos.ts` y ajusta los parámetros.)

- En la celda del insumo, la condición `f.tipo === "apu" ? <SubApuFila .../> : <BuscadorInsumo .../>` pasa a tener una rama intermedia:

```tsx
                        {f.tipo === "apu" ? (
                          <SubApuFila ...igual que hoy... />
                        ) : dudas[f.insumo_codigo] ? (
                          <SelectorCompartido
                            codigo={f.insumo_codigo}
                            opciones={dudas[f.insumo_codigo]}
                            valor=""
                            onElegir={(o) => elegirOpcion(f.uid, f.insumo_codigo, o)}
                          />
                        ) : (
                          <BuscadorInsumo ...igual que hoy... />
                        )}
```

(`valor=""` porque el nombre que tenía la fila es justo el que no resolvió.)

- [ ] **Step 4: Run tests**

Run: `cd web && npx vitest run src/components/autoria/ src/components/corrida/DialogoArmarApu.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/autoria/DialogoAgregarApu.tsx web/src/components/autoria/DialogoAgregarApu.test.tsx
git commit -m "feat(web): el dialogo de APU deja escoger el insumo de un codigo compartido"
```

---

### Task 12: la mesa de composición muestra el selector

**Files:**
- Modify: `web/src/pages/Composicion.tsx` (`componenteNuevo` ~79, celda de nombre ~535-551, unidad ~558, desplegable ~601, `BuscadorInsumo` de agregar ~656-664)
- Modify: `web/src/lib/cambiosAgente.ts` (rama `modificar`)
- Test: `web/src/pages/Composicion.test.tsx`, `web/src/lib/cambiosAgente.test.ts` (si no existe, créalo)

- [ ] **Step 1: Write the failing tests**

En `web/src/pages/Composicion.test.tsx` (usa `vista`, `version`, `COMPONENTE`, `CATALOGO`, `montar` y `boton` que ya existen):

```tsx
test("un código compartido muestra el selector y escoger se guarda con el nombre", async () => {
  getComposicion.mockResolvedValueOnce(vista(version(), {
    ...CATALOGO,
    "4279": { nombre: "", unidad: "", grupo: "", opciones: [
      { nombre: "CUADRILLA OFICIAL MAS AYUDANTES", unidad: "HR", oculto: false },
      { nombre: "TUBERIA PVC", unidad: "ML", oculto: false }] },
  }));
  montar();
  const sel = await screen.findByLabelText("Insumo del código 4279") as HTMLSelectElement;
  fireEvent.change(sel, { target: { value: "0" } });
  fireEvent.click(boton(/Guardar cambios/));
  await waitFor(() => expect(guardarComposicion).toHaveBeenCalledWith(
    1, 3, 2, [{ ...COMPONENTE, nombre: "CUADRILLA OFICIAL MAS AYUDANTES" }], false));
});
```

Además, busca en el archivo el test existente que agrega 8801 desde el buscador de la mesa y extiende su aserción para exigir `nombre: "OFICIAL DE OBRA"` en el componente nuevo (con `expect.objectContaining` si compara el objeto entero).

En `web/src/lib/cambiosAgente.test.ts`:

```ts
import { expect, test } from "vitest";
import { aplicarCambios } from "./cambiosAgente";

const BASE = { codigo: "6092", tipo: "insumo" as const, funcion: "herramienta",
  rendimiento: 1, origen: "supuesto_tecnico", referencias: [], hipotesis: {},
  calculo: null, justificacion: "", nivel_evidencia: "bajo" as const, ref_shift: "",
  nombre: "HERRAMIENTA MENOR" };

test("modificar sin nombre conserva el nombre que ya tenía la fila", () => {
  const { componentes } = aplicarCambios([BASE], [
    { op: "modificar", codigo: "6092", componente: { ...BASE, rendimiento: 2, nombre: "" } },
  ] as never);
  expect(componentes[0]).toMatchObject({ rendimiento: 2, nombre: "HERRAMIENTA MENOR" });
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd web && npx vitest run src/pages/Composicion.test.tsx src/lib/cambiosAgente.test.ts`
Expected: FAIL.

- [ ] **Step 3: Implement**

`web/src/lib/cambiosAgente.ts`, rama `modificar`:

```ts
        // El agente puede mandar el componente sin nombre (el chat no lo pide al
        // modificar): se conserva el que la fila ya tenía, o un código compartido
        // volvería a quedar sin escoger.
        out = out.map((x, j) => (j === i
          ? { ...nuevo, codigo: c.codigo, nombre: nuevo.nombre || x.nombre }
          : x));
```

`web/src/pages/Composicion.tsx`:
- `function componenteNuevo(codigo: string, nombre = "")` y agregar `nombre,` al objeto que devuelve.
- En el `BuscadorInsumo` de agregar: `...filasDe([componenteNuevo(ins.codigo, ins.nombre)])`.
- Importar `SelectorCompartido` y, en la celda del nombre, reemplazar `{ficha ? (<span>{ficha.nombre}</span>) : (...no está en el catálogo...)}` por:

```tsx
                        {ficha?.opciones ? (
                          <SelectorCompartido
                            codigo={f.c.codigo}
                            opciones={ficha.opciones}
                            valor={f.c.nombre ?? ""}
                            deshabilitado={soloLectura}
                            onElegir={(o) => setFilas((prev) => prev.map((x) =>
                              x.uid === f.uid ? { ...x, c: { ...x.c, nombre: o.nombre } } : x))}
                          />
                        ) : ficha ? (
                          <span>{ficha.nombre}</span>
                        ) : (
                          <span className="font-medium text-destructive">
                            no está en el catálogo
                          </span>
                        )}
```

Para que la celda no trunque el `select`, la clase de esa `TableCell` pasa a `className={"max-w-[22rem] text-xs align-top" + (ficha?.opciones ? "" : " truncate")}` (como expresión, no como atributo partido en dos líneas: regla de CLAUDE.md).
- Unidad: `{ficha?.opciones?.find((o) => o.nombre === f.c.nombre)?.unidad || ficha?.unidad || "—"}`.
- En el desplegable de la fila, `{ficha && <span className="font-medium text-foreground">{f.c.nombre || ficha.nombre}</span>}`.

- [ ] **Step 4: Run tests**

Run: `cd web && npx vitest run src/pages/Composicion.test.tsx src/lib/ src/components/composicion/`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/Composicion.tsx web/src/pages/Composicion.test.tsx web/src/lib/cambiosAgente.ts web/src/lib/cambiosAgente.test.ts
git commit -m "feat(web): la mesa deja escoger el insumo de un codigo compartido"
```

---

### Task 13: CLAUDE.md y verificación completa

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update CLAUDE.md**

En "No hacer", reemplazar el ítem que empieza «No dejes que el chat agregue un código compartido (586 en el catálogo)…» por:

```markdown
- No vuelvas a elegir la fila de un código por `get_candidatos(cod)[0]`. 652 códigos del
  catálogo son de DOS insumos (la hoja `INSUMOS_IDU-INT` pega el listado de insumos y el
  de ítems de obra del IDU, cada uno con su numeración). La fila la decide código +
  nombre con `dominio/cruce.py::elegir` —la misma regla del costeo—, y el alta
  (`autoria._componentes_de`) es el embudo: si el nombre no alcanza lanza
  `CodigoCompartido` (422 con `conflictos`) y el ingeniero escoge en la fila (diálogo de
  APU y mesa). En la composición el componente lleva `nombre` (tope propio de 1000: los
  reales llegan a 830) y el validador emite `CODIGO_COMPARTIDO`. El nombre que manda el
  agente o el cliente solo ESCOGE la fila: lo que se guarda y se muestra es el del
  catálogo. Pendiente conocido: los sub-APU (`tipo="apu"`) siguen tomando `cands[0]` si
  su código choca con un insumo.
```

En el párrafo "Chat con el agente (2026-11)", si menciona el candado de códigos compartidos, cámbialo por: «un código compartido lo resuelve el `nombre` que manda el agente (`cruce.elegir`); si no alcanza, el componente entra sin nombre y la mesa pide escoger».

- [ ] **Step 2: Full backend suite**

Run: `env -u DATABASE_URL python -m pytest tests/ -q`
Expected: todo PASS (antes de esta rama eran ~1780). Si falla algo fuera de los archivos tocados, investiga antes de seguir: no des por "preexistente" un fallo sin comprobarlo en `master`.

- [ ] **Step 3: Postgres (si hay un Postgres desechable local)**

Correr la suite contra un Postgres desechable (receta en la memoria del proyecto: binarios portables en el puerto 55433), **nunca** contra la `DATABASE_URL` de producción. Si no está disponible, dilo en el reporte: el CI de master corre Postgres 17 y lo cubre al pushear.

- [ ] **Step 4: Frontend**

Run: `cd web && npx vitest run && npm run build`
Expected: todo PASS y build sin errores.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: codigos compartidos en CLAUDE.md"
```

- [ ] **Step 6: Navegador (antes de cualquier push)**

Verificar en el navegador (banco estático o la app local) el selector en el diálogo de APU tras un 422 y en la mesa con un código compartido. **No pushear**: el push a master necesita OK explícito del usuario.
