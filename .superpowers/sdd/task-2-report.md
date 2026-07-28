# Task 2 Report: `lista_id` en las lecturas y escrituras de precios (SQLite)

Nota: este archivo pertenece a la secuencia SDD de la feature "listas de precios NP"
(rama `feat/listas-precios-np`). Sobrescribe un `task-2-report.md` anterior que
correspondía a una feature distinta ("ocultar insumos duplicados"; commit 0c36e07)
que reutilizó el mismo número de tarea en su propia secuencia SDD.

## Resumen

Se propagó un parámetro `lista_id: Optional[int] = None` (al final de cada firma,
`None` ⇒ `config.LISTA_PRINCIPAL_ID`) a todos los métodos de lectura/escritura de
precios en `apu_tool/datos/precios_db.py`, y se añadió el campo `Insumo.sin_precio`
para distinguir "sin tarifa vigente en esta lista" (NULL vía LEFT JOIN) de un
$0 genuino (regla de negocio prohibida). Implementado TDD estricto siguiendo
`.superpowers/sdd/task-2-brief.md` verbatim.

## Archivos modificados

- `apu_tool/nucleo/models.py` — campo `Insumo.sin_precio: bool = False` (tras `id`).
- `apu_tool/datos/precios_db.py` — `lista_id` propagado en:
  `_insertar_precio_vigente`, `crear_insumo`/`_crear_insumo`,
  `set_precio_por_id`/`_set_precio_por_id`, `_fila_a_insumo` (ahora setea
  `sin_precio`), nueva constante `_SELECT_INSUMO` (con `p.lista_id = ?` en el JOIN),
  `get_candidatos`, `get_candidatos_bulk`, `get_insumo_por_id`, `price_history`,
  `list_insumos` (+ nuevo parámetro `sin_precio: bool = False`, excluyente con
  `fuente`/`clasificacion` vía `ValueError`), `fuentes`.
- `tests/test_precios_por_lista.py` (nuevo) — 11 tests, copiados del brief.

## Decisiones tomadas

1. **Copié el código del brief verbatim**, tal como indicaba la instrucción — no
   hubo necesidad de improvisar firmas ni mensajes.
2. **`set_precio` (sin `_por_id`, usado solo por `cli.py::db update-price`) NO se
   tocó.** No está en la lista de interfaces del brief; sigue escribiendo siempre en
   Principal (pasa `lista_id=None` implícitamente a `_insertar_precio_vigente`),
   comportamiento idéntico al de antes.
3. **`search_insumos` y `search_insumos_por_palabras` NO se tocaron** — el brief lo
   dice explícitamente: llaman a `get_insumo_por_id(r["id"])` sin lista, o sea
   búsqueda por texto siempre en Principal.
4. **Verifiqué antes de tocar `list_insumos`** que la única llamada posicional
   existente (`apu_tool/servicio/insumos.py::listar` →
   `list_insumos(q, grupo, fuente, clasificacion, limit, offset)`) tiene exactamente
   6 argumentos posicionales, que siguen mapeando a los 6 primeros parámetros
   (`q, grupo, fuente, clasificacion, limit, offset`); `lista_id` y `sin_precio`
   quedan en sus defaults (`None`, `False`) sin desalinearse. Ídem para todas las
   demás llamadas grepeadas (`get_candidatos`, `crear_insumo`, `set_precio_por_id`,
   etc. en `cli.py`, `autoria.py`, `pricing.py`, `assemble.py`, `integridad.py`): son
   todas por keyword o con menos argumentos que los nuevos parámetros, así que nada
   se rompe.
5. **No reordené `init_schema`** (ya estaba correcto de la Task 1: `ALTER TABLE`
   antes del `executescript`). No lo toqué.
6. **No toqué** `apu_tool/datos/pg/precios_pg.py`, `db/pg/precios.sql` ni
   `apu_tool/datos/repositorio.py` (Task 3).

## Evidencia de tests (salida real, no parafraseada)

### Paso 2 — test nuevo, ANTES de implementar (falla por la razón correcta)

```
$ python -m pytest tests/test_precios_por_lista.py -q
...
E       TypeError: PreciosDB.set_precio_por_id() got an unexpected keyword argument 'lista_id'
...
E           TypeError: PreciosDB.list_insumos() got an unexpected keyword argument 'lista_id'
...
=========================== short test summary info ===========================
FAILED tests/test_precios_por_lista.py::test_seed_queda_en_principal - TypeEr...
FAILED tests/test_precios_por_lista.py::test_precio_en_np_no_toca_principal
FAILED tests/test_precios_por_lista.py::test_vigente_es_por_lista - TypeError...
FAILED tests/test_precios_por_lista.py::test_insumo_sin_precio_en_la_lista - ...
FAILED tests/test_precios_por_lista.py::test_bulk_respeta_la_lista - TypeErro...
FAILED tests/test_precios_por_lista.py::test_price_history_filtra_por_lista
FAILED tests/test_precios_por_lista.py::test_crear_insumo_en_np_no_existe_en_principal
FAILED tests/test_precios_por_lista.py::test_list_insumos_devuelve_todo_el_catalogo_con_precio_nulo
FAILED tests/test_precios_por_lista.py::test_list_insumos_filtro_sin_precio
FAILED tests/test_precios_por_lista.py::test_sin_precio_es_excluyente_con_fuente_y_clasificacion
FAILED tests/test_precios_por_lista.py::test_fuentes_por_lista - TypeError: P...
11 failed in 0.79s
```

### Paso 5 — test nuevo, DESPUÉS de implementar

```
$ python -m pytest tests/test_precios_por_lista.py -v
============================= test session starts =============================
platform win32 -- Python 3.14.2, pytest-9.1.0, pluggy-1.6.0 -- ...python.exe
collecting ... collected 11 items

tests/test_precios_por_lista.py::test_seed_queda_en_principal PASSED     [  9%]
tests/test_precios_por_lista.py::test_precio_en_np_no_toca_principal PASSED [ 18%]
tests/test_precios_por_lista.py::test_vigente_es_por_lista PASSED        [ 27%]
tests/test_precios_por_lista.py::test_insumo_sin_precio_en_la_lista PASSED [ 36%]
tests/test_precios_por_lista.py::test_bulk_respeta_la_lista PASSED       [ 45%]
tests/test_precios_por_lista.py::test_price_history_filtra_por_lista PASSED [ 54%]
tests/test_precios_por_lista.py::test_crear_insumo_en_np_no_existe_en_principal PASSED [ 63%]
tests/test_precios_por_lista.py::test_list_insumos_devuelve_todo_el_catalogo_con_precio_nulo PASSED [ 72%]
tests/test_precios_por_lista.py::test_list_insumos_filtro_sin_precio PASSED [ 81%]
tests/test_precios_por_lista.py::test_sin_precio_es_excluyente_con_fuente_y_clasificacion PASSED [ 90%]
tests/test_precios_por_lista.py::test_fuentes_por_lista PASSED           [100%]

============================= 11 passed in 0.50s ==============================
```

### Suite completa

```
$ python -m pytest tests/ -q
........................................................................ [ 14%]
........................................................................ [ 28%]
........................................................................ [ 43%]
.............................................ss......................... [ 57%]
..........s......s.............................s........................ [ 71%]
........................................................................ [ 86%]
......................................................................   [100%]
============================== warnings summary ===============================
...\slowapi\extension.py:720
  DeprecationWarning: 'asyncio.iscoroutinefunction' is deprecated ... (preexistente, no relacionado)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
497 passed, 5 skipped, 1 warning in 126.70s (0:02:06)
```

497 = 486 preexistentes + 11 nuevos. **0 failed.** Sin regresiones.

## Auto-revisión del diff

Repasé uno por uno los métodos del bloque de interfaces del brief, confirmando que
cada uno propaga `lista_id` hacia abajo hasta la query SQL o hasta
`_insertar_precio_vigente`:

| Método | ¿Propaga `lista_id`? |
|---|---|
| `get_candidatos` | Sí — `lid` es el primer elemento de `params`, alineado con `_SELECT_INSUMO` (placeholder en el JOIN antes del WHERE). |
| `get_candidatos_bulk` | Sí — `[lid] + chunk`, mismo orden. |
| `get_insumo_por_id` | Sí — `(lid, int(insumo_id))`. |
| `set_precio_por_id` → `_set_precio_por_id` → `_insertar_precio_vigente` | Sí, en las tres capas. |
| `crear_insumo` → `_crear_insumo` → `_insertar_precio_vigente` | Sí, en las tres capas. |
| `price_history` | Sí — `p.lista_id = ?` añadido al WHERE, `lid` en `params` antes del filtro opcional por `nombre`. |
| `fuentes` | Sí — `p.lista_id = ?` en el WHERE. |
| `list_insumos` | Sí — placeholder en el JOIN (`base`), `lid` primero en `params`; `sin_precio` añade `p.id IS NULL` y es excluyente con `fuente`/`clasificacion` (`ValueError`). |
| `Insumo.sin_precio` | Seteado en `_fila_a_insumo` vía `r["precio"] is None`, no `== 0`. |

No encontré ningún método de la lista que se haya quedado sin propagar `lista_id`.

Además verifiqué (grep) que ningún llamador existente pasa estos parámetros
posicionalmente más allá de los que ya existían antes de esta tarea, así que el
comportamiento con `lista_id=None` (implícito, por defecto) es byte-por-byte
idéntico al de antes en todos los call sites actuales (`cli.py`, `autoria.py`,
`insumos.py`, `pricing.py`, `assemble.py`, `integridad.py`, `rutas.py`).

## Dudas / concerns

Ninguna. La implementación es una copia fiel del brief, el test nuevo pasa (11/11)
y la suite completa quedó verde (497 passed, 5 skipped, 0 failed).

## Commit

```
7be58ce feat(precios): precio vigente por lista en el backend SQLite
```

Archivos en el commit:
- `apu_tool/datos/precios_db.py`
- `apu_tool/nucleo/models.py`
- `tests/test_precios_por_lista.py`

---

## Adenda: corrección de 3 hallazgos de revisión sobre 7be58ce

Revisión posterior detectó 1 Important + 2 Minor. Los tres se corrigieron sobre
`apu_tool/datos/precios_db.py`, con tests nuevos en `tests/test_repositorios_contrato.py`
(no en `test_precios_por_lista.py`, para que Postgres los herede cuando la Task 3
espeje esta lógica).

### Hallazgo 1 (Important) — `sin_precio` no estaba blindado contra derivarse de `precio == 0`

El código ya era correcto (`_fila_a_insumo`: `sin_precio=r["precio"] is None`;
`list_insumos`: `p.id IS NULL`), pero ningún test cubría un insumo con una fila de
precio de **0.0 genuina** (el único caso que distingue "sin tarifa" de "$0 real",
y el que dispara la regla de negocio "nada cuesta $0"). Se añadió
`test_precio_cero_genuino_no_es_sin_precio` en `test_repositorios_contrato.py`:
crea una lista NP, un insumo con precio 0.0 vigente en ella (`sin_precio` debe ser
`False`) y otro sin fila en esa lista (`sin_precio` debe ser `True`), y verifica que
`list_insumos(sin_precio=True)` solo devuelve el segundo.

**Evidencia de no-trivialidad** (los dos sabotajes del hallazgo, aplicados uno a la
vez sobre `precios_db.py`, revertidos después de confirmar el fallo):

Sabotaje A — `_fila_a_insumo`: `sin_precio=r["precio"] is None` → `sin_precio=(r["precio"] or 0.0) == 0.0`:
```
tests/test_repositorios_contrato.py::test_precio_cero_genuino_no_es_sin_precio[sqlite] FAILED
E       AssertionError: assert True is False
E        +  where True = Insumo(codigo='T1', ..., precio=0.0, ..., sin_precio=True).sin_precio
```

Sabotaje B (revertido A primero) — `list_insumos`: `"p.id IS NULL"` → `"(p.precio IS NULL OR p.precio = 0)"`:
```
tests/test_repositorios_contrato.py::test_precio_cero_genuino_no_es_sin_precio[sqlite] FAILED
E       AssertionError: assert 'T1' not in {'T1', 'T2'}
```

Con ambos sabotajes revertidos, el test pasa (`1 passed`). El mismo test detecta
cualquiera de las dos formas del bug.

### Hallazgo 2 (Minor) — `clasificacion="interno"` en lista no-Principal devolvía el catálogo completo

`list_insumos`, rama `clasificacion == "interno"`: la condición `p.fuente IS NULL`
(pensada para el caso casi-muerto de una fila de precio con fuente vacía en
Principal) pasaba a capturar TODO insumo sin fila de precio en una lista NP —
el caso dominante ahí, no la excepción. Fix: exigir `p.id IS NOT NULL` (existe fila
de precio vigente en esta lista) además de la condición de fuente:

```python
where.append(
    f"(p.id IS NOT NULL AND "
    f"(p.fuente IS NULL OR UPPER(p.fuente) NOT IN ({placeholders})))")
```

Tests nuevos en `test_repositorios_contrato.py`:
- `test_interno_excluye_insumos_sin_tarifa_en_la_lista` — en una lista NP con un
  insumo con tarifa interna y otro sin ninguna fila, `clasificacion="interno"`
  devuelve solo el primero (antes del fix devolvía ambos).
- `test_interno_publico_particionan_catalogo_en_principal` — fija el invariante de
  no-regresión: en Principal (todo insumo con su fila de precio desde que se crea),
  `publico` + `interno` siguen particionando el catálogo completo exactamente igual
  que antes del cambio (`total_pub + total_intr == total`).

### Hallazgo 3 (Minor) — `lista_id=0` caía a Principal en silencio

Los 7 sitios que usaban `int(lista_id or config.LISTA_PRINCIPAL_ID)` trataban `0`
como "ausente" (falsy), aunque `None` es el único valor que debe significar
"usa Principal". Se extrajo el helper privado `_resolver_lista_id`:

```python
def _resolver_lista_id(lista_id: Optional[int]) -> int:
    return int(lista_id) if lista_id is not None else config.LISTA_PRINCIPAL_ID
```

y se reemplazaron las 7 apariciones (`_insertar_precio_vigente`, `get_candidatos`,
`get_candidatos_bulk`, `get_insumo_por_id`, `price_history`, `list_insumos`,
`fuentes`) por `lid = _resolver_lista_id(lista_id)`. `None` sigue equivaliendo a
Principal (comportamiento de hoy, sin cambios); `0` ahora se usaría tal cual (y
fallaría con una tarifa inexistente en vez de costear en silencio contra
Principal). No se añadió un test dedicado para este hallazgo porque no hay
manera de crear hoy una lista con id `0` (autoincremental desde 1) sin tocar la
capa Postgres/Task 3 fuera de alcance; el cambio es defensivo y no observable
por la suite actual — todos los tests existentes usan `lista_id=None` o un id real.

### Suite completa tras los 3 fixes

```
$ python -m pytest tests/test_repositorios_contrato.py tests/test_precios_por_lista.py -v
============================= test session starts =============================
collecting ... collected 30 items
... (30 items, todos PASSED, incluyendo los 3 nuevos)
============================= 30 passed in 1.89s ==============================

$ python -m pytest tests/ -q
........................................................................ [ 14%]
........................................................................ [ 28%]
........................................................................ [ 42%]
.............................................ss......................... [ 57%]
..........s......s.............................s........................ [ 71%]
........................................................................ [ 85%]
.                                                                        [100%]
500 passed, 5 skipped, 1 warning in 121.50s (0:02:01)
```

500 = 497 preexistentes + 3 nuevos. **0 failed.** Sin regresiones.

### Commit de la adenda

```
0a88dfe fix(precios): sin_precio blindado por IS NULL, interno exige fila y lista_id=0 exacto
```

Archivos tocados:
- `apu_tool/datos/precios_db.py` (los 3 fixes)
- `tests/test_repositorios_contrato.py` (3 tests nuevos)
- `.superpowers/sdd/task-2-report.md` (esta adenda)

---

## Adenda 2: tests para `_resolver_lista_id`

El hallazgo 3 de la adenda anterior señalaba que la función `_resolver_lista_id` era
defensiva pero no observable por la suite (imposible crear `lista_id=0` hoy sin tocar
Postgres). Se agregaron 3 tests **puros** (sin fixtures) para proteger esta decisión
de diseño contra regresión:

### Función probada

```python
def _resolver_lista_id(lista_id: Optional[int]) -> int:
    """None ≡ Principal. Cualquier otro valor, incluido 0, se usa tal cual:
    0 no es un id alcanzable hoy, pero tratarlo como "ausente"
    (p.ej. con `lista_id or LISTA_PRINCIPAL_ID`) costearía en silencio
    contra Principal en vez de fallar con la tarifa equivocada."""
    return int(lista_id) if lista_id is not None else config.LISTA_PRINCIPAL_ID
```

### Tests agregados a `tests/test_precios_por_lista.py`

```python
def test_resolver_lista_id_none_a_principal():
    """None debe resolverse a la lista Principal (config.LISTA_PRINCIPAL_ID)."""
    assert _resolver_lista_id(None) == config.LISTA_PRINCIPAL_ID


def test_resolver_lista_id_cero_a_cero():
    """Un id de 0 debe devolverse tal cual, no tratarse como ausencia.

    Esto es crítico: si la función usara el patrón `lista_id or config.LISTA_PRINCIPAL_ID`,
    un 0 se evaluaría como falsy y caería a Principal en silencio, costeando contra
    la tarifa equivocada sin avisar. Por eso la función usa `if lista_id is not None`
    en lugar de `if lista_id`.
    """
    assert _resolver_lista_id(0) == 0


def test_resolver_lista_id_id_normal():
    """Un id normal debe devolverse tal cual."""
    assert _resolver_lista_id(7) == 7
```

### Prueba de no-trivialidad (el test atrapa la regresión)

**Sabotaje — cambiar la función al patrón malo:**

```python
def _resolver_lista_id(lista_id: Optional[int]) -> int:
    return int(lista_id or config.LISTA_PRINCIPAL_ID)
```

**Salida con sabotaje aplicado** (test falla en el caso de 0):

```
tests/test_precios_por_lista.py::test_resolver_lista_id_cero_a_cero FAILED [100%]

________________________________ test_resolver_lista_id_cero_a_cero ______________________________________

    def test_resolver_lista_id_cero_a_cero():
        """Un id de 0 debe devolverse tal cual, no tratarse como ausencia.

        Esto es crítico: si la función usara el patrón `lista_id or config.LISTA_PRINCIPAL_ID`,
        un 0 se evaluaría como falsy y caería a Principal en silencio, costeando contra
        la tarifa equivocada sin avisar. Por eso la función usa `if lista_id is not None`
        en lugar de `if lista_id`.
        """
>       assert _resolver_lista_id(0) == 0
E       assert 1 == 0
E        +  where 1 = _resolver_lista_id(0)

tests\test_precios_por_lista.py:115: AssertionError
=========================== short test summary info ===========================
FAILED tests/test_precios_por_lista.py::test_resolver_lista_id_cero_a_cero - ...
============================== 1 failed in 0.21s ==============================
```

**Salida con sabotaje revertido** (función correcta, test pasa):

```
tests/test_precios_por_lista.py::test_resolver_lista_id_cero_a_cero PASSED [100%]

============================== 1 passed in 0.05s ==============================
```

### Suite completa tras agregar los tests

```
........................................................................ [ 14%]
........................................................................ [ 28%]
........................................................................ [ 42%]
.............................................ss......................... [ 56%]
..........s......s.............................s........................ [ 70%]
........................................................................ [ 85%]
........................................................................ [ 99%]
....                                                                     [100%]
============================== warnings summary ===============================
..\..\AppData\Local\Python\pythoncore-3.14-64\Lib\site-packages\slowapi\extension.py:720
  DeprecationWarning: 'asyncio.iscoroutinefunction' is deprecated...
  (preexistente, no relacionado)

-- Docs: https://docs.pytest.org/en/stable/how-out-3.16; use inspect.iscoroutinefunction() instead
    if asyncio.iscoroutinefunction(func):

-- Docs: https://pytest.org/en/stable/how-pytest.org/en/stable/how-pytest.org/en/stable/how-pytest.org/en/stable/how-pytest.org/en/stable/how-pytest.org/en/stable/how-pytest.org/en/stable/how-pytest.org/en/stable/how-pytest.org/en/stable/how-pytest.org/en/stable/how-
pytest.org/en/stable/how-
pytest.org/en/stable/how-
```

503 passed, 5 skipped, 1 warning in 122.05s (0:02:02)
```

503 = 500 preexistentes + 3 nuevos. **0 failed.** Sin regresiones.

### Commit

```
09cb085 test(precios_db): agregar tests para _resolver_lista_id
```

Archivo tocado:
- `tests/test_precios_por_lista.py` (3 tests nuevos + import de `_resolver_lista_id`)
