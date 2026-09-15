> Espejo automático — no editar aquí. Fuente: `docs/superpowers/plans/2026-09-15-import-insumos-proteger-internos.md`

# Importar insumos sin pisar los precios internos — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que una importación de insumos declarada como pública (`PRECIO IDU`) nunca pise un precio interno, y que la fuente que el usuario declara en el diálogo sea la que queda rotulada en la base.

**Architecture:** El importador recibe un `fuente_import` obligatorio. `_filas_insumos` lo estampa en TODAS las filas (la columna `fuente` del archivo deja de usarse), así que la declaración es el único origen de la etiqueta. Un candado nuevo en `_upsert_o_invalida` —el embudo por donde pasan los dos caminos de match— desvía a un balde `protegida` las filas cuyo insumo tiene hoy un precio interno cuando la importación es pública. `aplicar_importar_insumos` recalcula el mismo preview, así que no hay dos reglas que se puedan desincronizar.

**Tech Stack:** Python 3 + FastAPI + openpyxl (backend, sin dependencias nuevas), React + TypeScript + vitest (frontend), pytest.

**Spec:** `docs/superpowers/specs/2026-09-15-import-insumos-proteger-internos-design.md`

---

## Estructura de archivos

| Archivo | Responsabilidad en este cambio |
|---|---|
| `apu_tool/servicio/autoria.py` | La declaración de fuente y el candado. Único archivo con lógica nueva. |
| `apu_tool/servicio/rutas.py` | Los dos endpoints de import de insumos exigen el campo nuevo. |
| `apu_tool/servicio/plantillas.py` | La plantilla pierde la columna `fuente`. |
| `web/src/lib/tipos.ts` | Tipos del balde nuevo y del contador. |
| `web/src/components/insumos/DialogoImportarInsumos.tsx` | Campo de fuente, sección "Protegidas", columna "Fuente actual". |
| `web/src/pages/Insumos.tsx` | Le pasa al diálogo las `fuentes` que ya tiene cargadas. |
| `tests/test_servicio_autoria.py` | Las pruebas nuevas del servicio (8). |
| `tests/test_api_autoria.py` | Las pruebas nuevas del contrato HTTP (2) + la existente actualizada. |
| 5 archivos más de `tests/` + `DialogoImportarInsumos.test.tsx` | Llamados existentes actualizados. |

**Contexto que el implementador necesita saber:**

- `config.classify_price_source(fuente)` devuelve `"publico"` solo si la fuente está en `config.PUBLIC_PRICE_SOURCES` (hoy `{"PRECIO IDU"}`); todo lo demás, incluida la cadena vacía, es `"interno"`.
- `Insumo.sin_precio` es `True` cuando el insumo **no tiene tarifa en la lista consultada**. En ese caso `precio` es `0.0` y `fuente_precio` es `""` por el LEFT JOIN: son artefactos de la ausencia, no datos. Ver el docstring en `apu_tool/nucleo/models.py`.
- `aplicar_importar_insumos` **recalcula** el preview internamente a partir del archivo; no recibe los baldes del preview del frontend.
- Regla de negocio "nada en $0": un precio ≤ 0 es error, nunca se escribe.

---

### Task 1: La fuente declarada manda

Es una tarea grande porque el cambio **es atómico**: `rutas.py` pasa hoy `lista_id` en 4ª posición (`preview_importar_insumos(alm, contenido, filename, lista_id)`), así que agregar el parámetro nuevo ahí rompe los endpoints en silencio si no se tocan en el mismo paso. Un parámetro obligatorio no se puede agregar a medias.

**Files:**
- Modify: `apu_tool/servicio/autoria.py` (`_filas_insumos`, `_cambio_upsert`, `preview_importar_insumos`, `aplicar_importar_insumos`)
- Modify: `apu_tool/servicio/rutas.py:773-803`
- Modify: `apu_tool/servicio/plantillas.py:88-98`
- Test: `tests/test_servicio_autoria.py`, `tests/test_api_autoria.py` + los 21 llamados existentes

- [ ] **Step 1: Escribir la prueba que falla**

En `tests/test_servicio_autoria.py`, al final del bloque `# ---- import insumos` (después de `test_upsert_precio_vacio_en_actualizacion_no_cambia`, línea ~132), agregar:

```python
def test_fuente_declarada_gana_sobre_la_columna_del_archivo(tmp_path):
    """La fuente la declara la importación, no el archivo. Antes, un archivo sin
    columna `fuente` dejaba el precio nuevo con la etiqueta vieja: un precio del IDU
    rotulado COSTO INTERNO."""
    alm = _alm(tmp_path)
    # El archivo dice "FUENTE DEL ARCHIVO"; la importación declara "COTIZACION 2026".
    contenido = _xlsx_solo_precio([["100", 1500, "FUENTE DEL ARCHIVO"]])
    prev = autoria.preview_importar_insumos(alm, contenido, "precios.xlsx",
                                            "COTIZACION 2026")
    assert prev["actualizar"][0]["fuente_nueva"] == "COTIZACION 2026"

    # también al crear
    prev2 = autoria.preview_importar_insumos(alm, _xlsx_upsert(), "insumos.xlsx",
                                             "COTIZACION 2026")
    assert prev2["crear"][0]["fuente"] == "COTIZACION 2026"


def test_fuente_declarada_vacia_se_rechaza(tmp_path):
    """Sin declaración no hay importación: un default silencioso es exactamente
    cómo nació el bug de la etiqueta."""
    alm = _alm(tmp_path)
    with pytest.raises(ValueError, match="fuente"):
        autoria.preview_importar_insumos(alm, _xlsx_upsert(), "insumos.xlsx", "   ")
```

- [ ] **Step 2: Correr la prueba y verificar que falla**

```bash
python -m pytest tests/test_servicio_autoria.py::test_fuente_declarada_gana_sobre_la_columna_del_archivo -v
```

Esperado: FAIL con `TypeError: preview_importar_insumos() takes 3 positional arguments but 4 were given`.

- [ ] **Step 3: Estampar la fuente declarada en el parser**

En `apu_tool/servicio/autoria.py`, cambiar la firma y el docstring de `_filas_insumos` (línea ~414) y la construcción de cada fila:

```python
def _filas_insumos(contenido: bytes, nombre_archivo: str, fuente_import: str) -> list[dict]:
    """Lee una tabla con columnas codigo, nombre, unidad, grupo, precio.

    `fuente_import` es la fuente que declaró la importación y se estampa en TODAS las
    filas: es el ÚNICO origen de la etiqueta. Si el archivo trae una columna `fuente`
    (los archivos viejos y la plantilla anterior la traen), se ignora — antes ganaba
    el archivo y, cuando venía vacía, se heredaba la etiqueta del insumo, dejando un
    precio del IDU rotulado COSTO INTERNO."""
```

Dentro de la función, borrar la entrada `"fuente"` del diccionario `ci` (la columna deja de leerse) y cambiar el `out.append(...)` para que estampe la declarada:

```python
    ci = {"codigo": col("codigo", "cod", "code"),
          "nombre": col("nombre", "descripcion", "name"),
          "unidad": col("unidad", "und", "unit"),
          "grupo": col("grupo", "group"),
          "precio": col("precio", "valor", "price")}
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
                    "fuente": fuente_import})
    return out
```

- [ ] **Step 4: Matar el `or` de `_cambio_upsert`**

En la misma `autoria.py`, en `_cambio_upsert` (línea ~391), reemplazar la línea de la fuente:

```python
    precio_nuevo = f["precio"] if f["tiene_precio"] else ins.precio
    # `f["fuente"]` es la fuente declarada por la importación, nunca vacía (la validan
    # `preview_importar_insumos` y el endpoint). No hay `or ins.fuente_precio`: ese
    # fallback era el que dejaba un precio nuevo con la etiqueta vieja.
    fuente_nueva = f["fuente"]
```

Y en el docstring de `_cambio_upsert`, borrar la mención al `or` si la hubiera (no la hay hoy; no tocar el resto del docstring).

- [ ] **Step 5: Firma nueva en las dos funciones públicas**

`preview_importar_insumos` (línea ~470): agregar el parámetro **obligatorio** en 4ª posición, validarlo, y pasarlo al parser:

```python
MSG_FUENTE_OBLIGATORIA = ("La importación debe declarar su fuente de precio "
                          "(p. ej. PRECIO IDU).")


def preview_importar_insumos(alm: Almacen, contenido: bytes, nombre_archivo: str,
                             fuente_import: str, lista_id: Optional[int] = None) -> dict:
    """Upsert por fila CONTRA `lista_id` (None = Principal). Con nombre: identidad
    código+nombre (crea o actualiza). Sin nombre: actualiza precio por código (único),
    o marca ambigua/no encontrada. Lo que crearía un duplicado va a 'conflicto'.

    `fuente_import` es la fuente declarada: se estampa en todas las filas y decide el
    candado (ver `_protegida`)."""
    fuente_import = (fuente_import or "").strip()
    if not fuente_import:
        raise ValueError(MSG_FUENTE_OBLIGATORIA)
    crear, actualizar, ambigua, no_encontrada, invalida, conflicto = [], [], [], [], [], []
```

Y el bucle pasa a leer `_filas_insumos(contenido, nombre_archivo, fuente_import)`.

`aplicar_importar_insumos` (línea ~508): mismo parámetro, y se lo pasa al preview:

```python
def aplicar_importar_insumos(alm: Almacen, contenido: bytes, nombre_archivo: str,
                             fuente_import: str, actor=None,
                             lista_id: Optional[int] = None) -> dict:
    prev = preview_importar_insumos(alm, contenido, nombre_archivo, fuente_import, lista_id)
```

`MSG_FUENTE_OBLIGATORIA` va junto a las otras constantes de mensaje del módulo (arriba de `_cambio_upsert`, donde vive `MOTIVO_SIN_PRECIO_EN_LISTA`).

- [ ] **Step 5b: Los dos endpoints exigen el campo**

⚠️ **Sin este paso el árbol queda roto:** hoy `rutas.py` pasa `lista_id` posicionalmente en la 4ª posición, que ahora es `fuente_import`. Un `int` caería en el parámetro equivocado y `lista_id` quedaría en `None` — la importación escribiría en Principal en vez de la lista elegida.

`apu_tool/servicio/rutas.py`, línea 773:

```python
@router.post("/insumos/importar/preview")
async def insumos_importar_preview(archivo: UploadFile = File(...),
                                   fuente_import: str = Form(...),
                                   lista_id: Optional[int] = Form(None),
                                   alm: Almacen = Depends(get_almacen),
                                   _: object = Depends(requiere_rol("editor"))):
    _validar_lista(alm, lista_id)
    contenido = await archivo.read()
    try:
        return autoria.preview_importar_insumos(alm, contenido,
                                                archivo.filename or "insumos.xlsx",
                                                fuente_import, lista_id)
```

Línea 789:

```python
@router.post("/insumos/importar")
async def insumos_importar(archivo: UploadFile = File(...),
                           fuente_import: str = Form(...),
                           lista_id: Optional[int] = Form(None),
                           alm: Almacen = Depends(get_almacen),
                           actor=Depends(requiere_rol("editor"))):
    _validar_lista(alm, lista_id)
    contenido = await archivo.read()
    try:
        return autoria.aplicar_importar_insumos(alm, contenido,
                                                archivo.filename or "insumos.xlsx",
                                                fuente_import, actor=actor,
                                                lista_id=lista_id)
```

Los bloques `except` de cada función no se tocan: el `ValueError` de `MSG_FUENTE_OBLIGATORIA` ya cae en el `except ValueError` que devuelve 400.

- [ ] **Step 5c: La plantilla suelta la columna**

`apu_tool/servicio/plantillas.py`, `plantilla_insumos`:

```python
def plantilla_insumos() -> bytes:
    """Plantilla del importador unificado. Columnas: codigo, nombre, unidad, grupo,
    precio. Con nombre crea o actualiza (por identidad código+nombre); sin nombre solo
    actualiza precio por código.

    NO lleva columna `fuente`: la fuente la declara la importación en el diálogo y se
    aplica a todo el archivo. Un archivo viejo que traiga la columna sube igual — el
    parser la ignora."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["codigo", "nombre", "unidad", "grupo", "precio"])
    ws.append(["EJEMPLO-1", "EJEMPLO — con nombre se crea o actualiza", "KG", "MAT", 1000])
    ws.append(["EJEMPLO-2", "", "", "", 2000])  # sin nombre = solo actualizar precio
    return _a_bytes(wb)
```

- [ ] **Step 6: Correr las dos pruebas nuevas**

```bash
python -m pytest tests/test_servicio_autoria.py -k "fuente_declarada" -v
```

Esperado: 2 passed.

- [ ] **Step 7: Actualizar los 21 llamados existentes**

Cada llamado gana la fuente declarada en 4ª posición. **No pongas `"PRECIO IDU"` en todos**: tres tests quedarían con el candado activado y cambiarían de significado. Esta es la lista completa, con la fuente que preserva la intención de cada uno:

| Archivo:línea | Fuente a pasar | Por qué |
|---|---|---|
| `test_auditoria_servicios_precios.py:64` | `"PRECIO IDU"` | crea un insumo nuevo, no pisa nada |
| `test_plantillas.py:42` | `"PRECIO IDU"` | base vacía, solo crea |
| `test_autoria_lista_precios_regresion.py:55` | `"PRECIO IDU"` | 6140 sin tarifa en NP → `sin_precio` → no se protege |
| `test_autoria_lista_precios_regresion.py:71` y `:75` | `"NUEVA FUENTE"` | era la fuente que traía la columna del archivo |
| `test_autoria_lista_precios_regresion.py:86` | `"PRECIO IDU"` | 6140 sin tarifa en NP → llega al guard del $0 |
| `test_autoria_lista_precios_regresion.py:101` | **`"ACTA NP"`** | ⚠️ el insumo YA tiene tarifa `ACTA NP` (interna) en la lista. Con `"PRECIO IDU"` la fila quedaría protegida y el test fallaría. La intención del test es actualizar la tarifa NP, y eso es una importación interna. |
| `test_autoria_lista_precios_regresion.py:125` | `"PRECIO IDU"` | insumo 100 es público → no se protege → llega al guard del $0 |
| `test_autoria_sin_duplicados.py:154, 158, 169, 171, 180` | `"PRECIO IDU"` | todos son caminos de `crear`/`conflicto` |
| `test_servicio_autoria.py:85, 94` | `"PRECIO IDU"` | el insumo 100 es público → público sobre público, permitido |
| `test_servicio_autoria.py:102` | `"COMPRAS"` | era la fuente de la columna; interna sobre pública, permitido |
| `test_servicio_autoria.py:112, 120` | `"PRECIO IDU"` | caminos `ambigua` / `no_encontrada`, el candado no interviene |
| `test_servicio_autoria.py:127` | **`"NUEVA FUENTE"`** | el test asserta `fuente_nueva == "NUEVA FUENTE"`; ahora eso lo prueba la declaración, que es el punto |
| `test_servicio_insumos_lista.py:81, 90, 100` | `"ACTA NP"` | era la fuente de la columna; interna, no dispara el candado |

Ejemplo del patrón (todas las llamadas usan keyword después del 3er argumento, así que el nuevo entra posicional sin romper nada):

```python
# antes
prev = autoria.preview_importar_insumos(alm, contenido, "f.xlsx", lista_id=lid)
# después
prev = autoria.preview_importar_insumos(alm, contenido, "f.xlsx", "PRECIO IDU", lista_id=lid)
```

En `test_servicio_autoria.py:127`, actualizar además el comentario del assert:

```python
def test_upsert_precio_vacio_en_actualizacion_no_cambia(tmp_path):
    alm = _alm(tmp_path)
    prev = autoria.preview_importar_insumos(alm, _xlsx_solo_precio([["100", "", "IGNORADA"]]),
                                            "precios.xlsx", "NUEVA FUENTE")
    c = prev["actualizar"][0]
    assert c["precio_nuevo"] == 1000            # precio actual, no 0
    assert c["fuente_nueva"] == "NUEVA FUENTE"  # la declarada, no la columna del archivo
```

- [ ] **Step 7b: Los llamados por HTTP**

`tests/test_api_autoria.py` ya tiene `test_import_insumos_endpoint` (línea 64), que hoy postea sin el campo nuevo. Actualizarlo y agregar la prueba del 422 al lado, con el mismo helper `_cli(tmp_path)` que usa todo ese archivo:

```python
def test_import_insumos_endpoint(tmp_path):
    cli, _ = _cli(tmp_path)
    data = _xlsx_insumos()
    pv = cli.post("/api/insumos/importar/preview",
                  files={"archivo": ("insumos.xlsx", data, _XLSX)},
                  data={"fuente_import": "PRECIO IDU"})
    assert pv.status_code == 200
    assert [c["codigo"] for c in pv.json()["crear"]] == ["300"]
    assert [c["codigo"] for c in pv.json()["actualizar"]] == ["100"]   # existía -> actualizar
    ap = cli.post("/api/insumos/importar",
                  files={"archivo": ("insumos.xlsx", data, _XLSX)},
                  data={"fuente_import": "PRECIO IDU"})
    assert ap.status_code == 200
    assert ap.json()["creados"] == 1 and ap.json()["actualizados"] == 1


def test_import_insumos_sin_fuente_es_422(tmp_path):
    """El campo es obligatorio en el contrato HTTP: no hay default silencioso."""
    cli, _ = _cli(tmp_path)
    r = cli.post("/api/insumos/importar/preview",
                 files={"archivo": ("insumos.xlsx", _xlsx_insumos(), _XLSX)})
    assert r.status_code == 422
```

(La prueba de que el candado llega hasta el HTTP va en la Task 2, cuando el candado exista.)

- [ ] **Step 8: Correr toda la suite de importación**

```bash
python -m pytest tests/test_servicio_autoria.py tests/test_autoria_lista_precios_regresion.py tests/test_autoria_sin_duplicados.py tests/test_servicio_insumos_lista.py tests/test_auditoria_servicios_precios.py tests/test_plantillas.py tests/test_api_autoria.py -q
```

Esperado: todos pasan. `test_plantillas.py::test_plantilla_insumos_round_trip` sigue verde con la plantilla sin columna `fuente`: solo asserta que `EJEMPLO-1` cae en `crear`.

- [ ] **Step 9: Commit**

```bash
git add apu_tool/servicio/autoria.py apu_tool/servicio/rutas.py apu_tool/servicio/plantillas.py tests/
git commit -m "feat(import): la importacion de insumos declara su fuente

La fuente declarada se estampa en todas las filas y la columna 'fuente'
del archivo se ignora. Muere el 'f[fuente] or ins.fuente_precio', que
dejaba un precio nuevo con la etiqueta vieja. Los dos endpoints la
exigen (Form obligatorio) y la plantilla suelta la columna.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: El candado (preview)

**Files:**
- Modify: `apu_tool/servicio/autoria.py` (`_protegida` nueva, `_upsert_o_invalida`, `preview_importar_insumos`)
- Test: `tests/test_servicio_autoria.py`

- [ ] **Step 1: Escribir las pruebas que fallan**

En `tests/test_servicio_autoria.py`, después de las dos pruebas de la Task 1:

```python
def _alm_con_interno(tmp_path):
    """Base con un insumo de costo interno (el que hay que proteger)."""
    alm = _alm(tmp_path)
    alm.precios.insert_insumos([
        Insumo("500", "MANO DE OBRA OFICIAL", "HR", "MO", 25000, "COSTO INTERNO")])
    return alm


def test_import_publico_no_pisa_un_precio_interno(tmp_path):
    """El caso del usuario: subir la lista del visor IDU no puede pisar los costos
    internos de la empresa."""
    alm = _alm_con_interno(tmp_path)
    contenido = _xlsx_solo_precio([["100", 1200, ""], ["500", 9, ""]])
    prev = autoria.preview_importar_insumos(alm, contenido, "idu.xlsx", "PRECIO IDU")

    assert [c["codigo"] for c in prev["actualizar"]] == ["100"]   # el público sí
    assert len(prev["protegida"]) == 1
    p = prev["protegida"][0]
    assert p["codigo"] == "500" and p["fuente_actual"] == "COSTO INTERNO"
    assert p["precio_actual"] == 25000 and p["precio_archivo"] == 9


def test_import_interno_si_pisa_un_precio_interno(tmp_path):
    """La regla es asimétrica: una tanda interna es curada y deliberada."""
    alm = _alm_con_interno(tmp_path)
    contenido = _xlsx_solo_precio([["500", 27000, ""]])
    prev = autoria.preview_importar_insumos(alm, contenido, "compras.xlsx",
                                            "COMPRAS ALMACEN 2026")
    assert prev["protegida"] == []
    assert prev["actualizar"][0]["precio_nuevo"] == 27000


def test_insumo_sin_tarifa_en_la_lista_no_se_protege(tmp_path):
    """El falso positivo: sin tarifa en la lista consultada, `fuente_precio` es "" por
    el LEFT JOIN, no porque el precio sea interno. Sin el `not ins.sin_precio`, una
    importación pública contra una lista de NP quedaría bloqueada entera."""
    alm = _alm(tmp_path)
    np = alm.precios.crear_lista("NP Calle 13")
    contenido = _xlsx_solo_precio([["100", 1200, ""]])
    prev = autoria.preview_importar_insumos(alm, contenido, "np.xlsx", "PRECIO IDU",
                                            lista_id=np)
    assert prev["protegida"] == []
    assert prev["actualizar"][0]["precio_nuevo"] == 1200


def test_import_publico_protege_aunque_el_archivo_no_traiga_precio(tmp_path):
    """Una fila sin precio le cambiaría SOLO la etiqueta al insumo interno: es el bug
    de rotulado al revés, y también se protege."""
    alm = _alm_con_interno(tmp_path)
    contenido = _xlsx_solo_precio([["500", "", ""]])
    prev = autoria.preview_importar_insumos(alm, contenido, "idu.xlsx", "PRECIO IDU")
    assert len(prev["protegida"]) == 1
    assert prev["protegida"][0]["precio_archivo"] is None
    assert prev["actualizar"] == [] and prev["invalida"] == []
```

- [ ] **Step 2: Correr las pruebas y verificar que fallan**

```bash
python -m pytest tests/test_servicio_autoria.py -k "protege or pisa" -v
```

Esperado: FAIL con `KeyError: 'protegida'`.

- [ ] **Step 3: Escribir el candado**

En `apu_tool/servicio/autoria.py`, justo antes de `_upsert_o_invalida` (línea ~459):

```python
def _protegida(ins, fuente_import: str) -> bool:
    """Una importación pública no pisa un precio interno.

    La regla es ASIMÉTRICA a propósito: una tanda pública es masiva y automática
    (miles de filas del visor del IDU) y no puede llevarse por delante un costo
    interno curado; una tanda interna es deliberada y sí puede pisar lo que sea,
    incluido "ascender" un insumo que hoy tiene precio IDU a costo interno propio.

    `not ins.sin_precio` evita el falso positivo: sin tarifa en la lista consultada,
    `fuente_precio` es "" por el LEFT JOIN (ver `Insumo.sin_precio`), no porque el
    precio sea interno. Sin ese término, una importación pública contra una lista de
    NP recién creada quedaría bloqueada entera.

    Una fuente vacía CON precio real sí cuenta como interna: no sabemos qué es ese
    precio, así que la fila queda visible en el balde en vez de pisarse callada.
    """
    return (config.classify_price_source(fuente_import) == "publico"
            and not ins.sin_precio
            and config.classify_price_source(ins.fuente_precio) == "interno")
```

- [ ] **Step 4: Desviar la fila en el embudo**

Reemplazar `_upsert_o_invalida` completa:

```python
def _upsert_o_invalida(ins, f: dict, fuente_import: str,
                       actualizar: list, invalida: list, protegida: list) -> None:
    """Enruta una fila que hizo match contra un insumo existente.

    Es el ÚNICO embudo de los dos caminos de match (con nombre → identidad
    código+nombre; sin nombre → código único), así que el candado vive acá y no
    repetido en cada rama.

    El candado va PRIMERO. Hoy los dos casos son excluyentes (`_protegida` exige
    `not ins.sin_precio` y el de abajo exige `ins.sin_precio`), pero el orden queda
    fijado para que mañana no dependa de esa coincidencia.
    """
    if _protegida(ins, fuente_import):
        protegida.append({"codigo": ins.codigo, "nombre": ins.nombre,
                          "fuente_actual": ins.fuente_precio,
                          "precio_actual": ins.precio,
                          "precio_archivo": f["precio"] if f["tiene_precio"] else None})
        return
    cambio = _cambio_upsert(ins, f)
    if cambio is not None:
        actualizar.append(cambio)
    else:
        invalida.append({**f, "motivo": MOTIVO_SIN_PRECIO_EN_LISTA})
```

- [ ] **Step 5: Sumar el balde al preview**

En `preview_importar_insumos`, agregar la lista, pasarla a las tres llamadas y devolverla:

```python
    crear, actualizar, ambigua, no_encontrada, invalida, conflicto = [], [], [], [], [], []
    protegida: list[dict] = []
```

Las dos llamadas a `_upsert_o_invalida` pasan a:

```python
                _upsert_o_invalida(match, f, fuente_import, actualizar, invalida, protegida)
```

```python
                _upsert_o_invalida(cands[0], f, fuente_import, actualizar, invalida, protegida)
```

Y el `return`:

```python
    return {"crear": crear, "actualizar": actualizar, "ambigua": ambigua,
            "no_encontrada": no_encontrada, "invalida": invalida, "conflicto": conflicto,
            "protegida": protegida}
```

- [ ] **Step 6: Correr las pruebas**

```bash
python -m pytest tests/test_servicio_autoria.py -k "protege or pisa" -v
```

Esperado: 4 passed.

- [ ] **Step 7: El candado llega hasta el HTTP**

En `tests/test_api_autoria.py`, junto a las dos pruebas de la Task 1:

```python
def test_import_insumos_endpoint_protege_el_interno(tmp_path):
    """El insumo 100 pasa a costo interno; una importación declarada pública deja de
    poder pisarlo, y el balde viaja en la respuesta."""
    cli, alm = _cli(tmp_path)
    iid = alm.precios.get_candidatos("100")[0].id
    alm.precios.set_precio_por_id(iid, 1000, "COSTO INTERNO")
    r = cli.post("/api/insumos/importar/preview",
                 files={"archivo": ("insumos.xlsx", _xlsx_insumos(), _XLSX)},
                 data={"fuente_import": "PRECIO IDU"})
    assert r.status_code == 200
    body = r.json()
    assert body["actualizar"] == []
    assert [p["codigo"] for p in body["protegida"]] == ["100"]
```

- [ ] **Step 8: Correr la suite de importación completa**

```bash
python -m pytest tests/test_servicio_autoria.py tests/test_autoria_lista_precios_regresion.py tests/test_autoria_sin_duplicados.py tests/test_servicio_insumos_lista.py tests/test_api_autoria.py -q
```

Esperado: todos pasan. Si `test_import_preview_solo_codigo_lee_precio_actual_de_la_lista` falla, es que quedó con `"PRECIO IDU"` en vez de `"ACTA NP"` (ver la tabla de la Task 1, Step 7).

- [ ] **Step 9: Commit**

```bash
git add apu_tool/servicio/autoria.py tests/
git commit -m "feat(import): una importacion publica no pisa un precio interno

Candado en _upsert_o_invalida, el embudo de los dos caminos de match.
Las filas protegidas van a un balde propio del preview con su fuente y
precio actuales.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Aplicar no escribe las protegidas y las cuenta

**Files:**
- Modify: `apu_tool/servicio/autoria.py` (`aplicar_importar_insumos`)
- Test: `tests/test_servicio_autoria.py`

- [ ] **Step 1: Escribir la prueba que falla**

```python
def test_aplicar_no_escribe_las_protegidas_y_las_cuenta(tmp_path):
    alm = _alm_con_interno(tmp_path)
    contenido = _xlsx_solo_precio([["100", 1200, ""], ["500", 9, ""]])
    res = autoria.aplicar_importar_insumos(alm, contenido, "idu.xlsx", "PRECIO IDU")

    assert res == {"creados": 0, "actualizados": 1, "protegidos": 1, "errores": []}
    interno = alm.precios.get_candidatos("500")[0]
    assert interno.precio == 25000 and interno.fuente_precio == "COSTO INTERNO"
    assert alm.precios.get_candidatos("100")[0].precio == 1200


def test_las_protegidas_no_dejan_auditoria(tmp_path):
    """No cambió nada: no hay evento que registrar."""
    alm = _alm_con_interno(tmp_path)
    autoria.aplicar_importar_insumos(alm, _xlsx_solo_precio([["500", 9, ""]]),
                                     "idu.xlsx", "PRECIO IDU")
    _items, total = alm.auditoria.listar(accion="precio.editar")
    assert total == 0
```

- [ ] **Step 2: Correr y verificar que falla**

```bash
python -m pytest tests/test_servicio_autoria.py -k "protegidas" -v
```

Esperado: FAIL — el dict del resultado no tiene la clave `protegidos`.

- [ ] **Step 3: Devolver el contador**

En `aplicar_importar_insumos`, la última línea:

```python
    # Las protegidas no se recorren: `preview_importar_insumos` nunca las puso en
    # 'actualizar'. No dejan auditoría porque no cambió nada; se miran en el preview.
    return {"creados": creados, "actualizados": actualizados,
            "protegidos": len(prev["protegida"]), "errores": errores}
```

- [ ] **Step 4: Correr las pruebas**

```bash
python -m pytest tests/test_servicio_autoria.py -k "protegidas" -v
```

Esperado: 2 passed.

- [ ] **Step 5: Arreglar los asserts de igualdad de dict**

`tests/test_autoria_lista_precios_regresion.py` compara el resultado completo con `==` en dos lugares (líneas 56 y 76). Agregar la clave nueva:

```python
    assert res == {"creados": 0, "actualizados": 1, "protegidos": 0, "errores": []}
```

```python
    assert res == {"creados": 0, "actualizados": 0, "protegidos": 0, "errores": []}
```

- [ ] **Step 6: Correr la suite de backend completa**

```bash
python -m pytest tests/ -q
```

Esperado: todo verde, backend completo. Desde acá el backend está terminado: lo que sigue es solo frontend.

- [ ] **Step 7: Commit**

```bash
git add apu_tool/servicio/autoria.py tests/
git commit -m "feat(import): aplicar reporta cuantas filas quedaron protegidas

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: El diálogo declara la fuente

**Files:**
- Modify: `apu_tool/servicio/autoria.py` (`preview_importar_insumos`: devolver `clasificacion_import`)
- Modify: `web/src/lib/tipos.ts:432-445`
- Modify: `web/src/components/insumos/DialogoImportarInsumos.tsx`
- Modify: `web/src/pages/Insumos.tsx:211-216`
- Test: `tests/test_servicio_autoria.py`, `web/src/components/insumos/DialogoImportarInsumos.test.tsx`

**Agregado después de la revisión de la Task 2 — el hueco de la fuente mal escrita:**

`config.classify_price_source` es *fail-open* para el candado: todo lo que no esté exactamente en `PUBLIC_PRICE_SOURCES` clasifica `interno`, y una importación interna puede pisar lo que sea. Medido sobre el código real:

```
fuente_import='PRECIO IDU 2026'  ->  actualizar: ['500','600','700']   protegida: []
fuente_import='PRECIOS IDU'      ->  actualizar: ['500']               protegida: []
```

Fechar la tanda o escribirla en plural es exactamente lo que hace una persona, y el resultado es el daño que la feature existe para evitar, sin nada que lo delate. **La decisión tomada (el usuario escogió esta opción): hacer visible la clasificación, no adivinarla.** Nada de matching difuso contra `PUBLIC_PRICE_SOURCES` — "PRECIOS IDU" ≈ "PRECIO IDU" sería una fuente nueva de sorpresas. Hacerlo visible, no hacerlo listo.

- [ ] **Step 0: El backend dice cómo clasificó la fuente**

En `apu_tool/servicio/autoria.py`, `preview_importar_insumos` agrega una clave al dict de retorno:

```python
    return {"crear": crear, "actualizar": actualizar, "ambigua": ambigua,
            "no_encontrada": no_encontrada, "invalida": invalida, "conflicto": conflicto,
            "protegida": protegida,
            # Cómo clasificó el backend la fuente declarada. Se pinta en el diálogo
            # porque `classify_price_source` es fail-open: "PRECIO IDU 2026" clasifica
            # INTERNO y el candado no se dispara. Que la persona lo VEA antes de
            # aplicar es la protección; adivinar la intención sería peor.
            "clasificacion_import": config.classify_price_source(fuente_import)}
```

Y una prueba en `tests/test_servicio_autoria.py`:

```python
def test_preview_dice_como_clasifico_la_fuente(tmp_path):
    """El candado es fail-open: una fuente pública mal escrita clasifica interna y no
    protege nada. El diálogo pinta esta clave para que se vea antes de aplicar."""
    alm = _alm(tmp_path)
    contenido = _xlsx_solo_precio([["100", 1200, ""]])
    assert autoria.preview_importar_insumos(
        alm, contenido, "f.xlsx", "PRECIO IDU")["clasificacion_import"] == "publico"
    assert autoria.preview_importar_insumos(
        alm, contenido, "f.xlsx", "PRECIO IDU 2026")["clasificacion_import"] == "interno"
```

- [ ] **Step 1: Escribir las pruebas que fallan**

En `DialogoImportarInsumos.test.tsx`, agregar el helper y las pruebas nuevas, y arreglar las tres existentes (que hoy seleccionan archivo sin declarar fuente). El helper y el render compartido:

```tsx
function seleccionarFuente(valor = "PRECIO IDU") {
  const input = screen.getByLabelText(/Fuente de esta importación/i);
  fireEvent.change(input, { target: { value: valor } });
  fireEvent.blur(input);
}

function montar() {
  return render(
    <DialogoImportarInsumos
      open onOpenChange={() => {}} listaId={7} listaNombre="NP Calle 13"
      fuentes={["PRECIO IDU", "COSTO INTERNO"]} onAplicado={() => {}}
    />
  );
}
```

Las tres pruebas existentes pasan a usar `montar()` y a llamar `seleccionarFuente()` **antes** de `seleccionarArchivo()`. Pruebas nuevas:

```tsx
it("no deja escoger archivo hasta declarar la fuente", () => {
  montar();
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  expect(input.disabled).toBe(true);
  seleccionarFuente();
  expect(input.disabled).toBe(false);
});

it("manda la fuente declarada en el preview y en el aplicar", async () => {
  montar();
  seleccionarFuente("COSTO INTERNO");
  seleccionarArchivo();

  await waitFor(() => expect(previewImportarInsumos).toHaveBeenCalled());
  expect((previewImportarInsumos.mock.calls[0][0] as FormData).get("fuente_import"))
    .toBe("COSTO INTERNO");

  fireEvent.click(await screen.findByText("Aplicar (1)"));
  await waitFor(() => expect(aplicarImportarInsumos).toHaveBeenCalled());
  expect((aplicarImportarInsumos.mock.calls[0][0] as FormData).get("fuente_import"))
    .toBe("COSTO INTERNO");
});

it("recalcula el preview si cambia la fuente con un archivo ya elegido", async () => {
  montar();
  seleccionarFuente("PRECIO IDU");
  seleccionarArchivo();
  await waitFor(() => expect(previewImportarInsumos).toHaveBeenCalledTimes(1));

  seleccionarFuente("COSTO INTERNO");
  await waitFor(() => expect(previewImportarInsumos).toHaveBeenCalledTimes(2));
  expect((previewImportarInsumos.mock.calls[1][0] as FormData).get("fuente_import"))
    .toBe("COSTO INTERNO");
});

it("avisa cuando la fuente declarada clasifica como interna", async () => {
  // El caso del typo: "PRECIO IDU 2026" clasifica INTERNO y el candado no protege
  // nada. El aviso es lo único que lo delata antes de aplicar.
  previewImportarInsumos.mockResolvedValue({
    crear: [], actualizar: [], ambigua: [], no_encontrada: [], invalida: [],
    protegida: [], clasificacion_import: "interno",
  });
  montar();
  seleccionarFuente("PRECIO IDU 2026");
  seleccionarArchivo();

  expect(await screen.findByText(/INTERNA/)).toBeTruthy();
});
```

- [ ] **Step 2: Correr y verificar que fallan**

```bash
cd web && npx vitest run src/components/insumos/DialogoImportarInsumos.test.tsx
```

Esperado: FAIL — no existe el campo con ese label.

- [ ] **Step 3: Tipos**

`web/src/lib/tipos.ts`:

```ts
export interface ImportProtegida {
  codigo: string;
  nombre: string;
  fuente_actual: string;
  precio_actual: number;
  precio_archivo: number | null;
}

export interface ImportInsumosUpsertPreview {
  crear: InsumoImportFila[];
  actualizar: CambioPreview[];
  ambigua: ImportAmbiguo[];
  no_encontrada: { codigo: string }[];
  invalida: InsumoImportFila[];
  conflicto?: ImportConflicto[];
  // Filas que una importación pública NO pisa por tener hoy un precio interno.
  protegida?: ImportProtegida[];
  // Cómo clasificó el backend la fuente declarada. Se pinta para que se vea que
  // "PRECIO IDU 2026" clasifica interno y por lo tanto NO protege nada.
  clasificacion_import?: "publico" | "interno";
}

export interface ImportUpsertResultado {
  creados: number;
  actualizados: number;
  protegidos?: number;
  errores: { codigo: string; error: string }[];
}
```

- [ ] **Step 4: El campo en el diálogo**

En `DialogoImportarInsumos.tsx`: agregar `fuentes: string[]` a `Props`, el estado, el ref y el preview compartido. Reemplazar `resetear`, `handleFileChange` y `aplicar`:

```tsx
interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  listaId: number;
  listaNombre: string;
  fuentes: string[];
  onAplicado: () => void;
}
```

```tsx
  const [fuente, setFuente] = useState("");
  // La fuente con la que se corrió el preview vigente: es la que se manda al aplicar,
  // para que no se pueda aplicar con una declaración distinta a la que se vio.
  const fuentePreviewRef = useRef("");

  function resetear() {
    setEstado({ fase: "idle" });
    setErrorMsg(null);
    setFuente("");
    fuentePreviewRef.current = "";
    archivoRef.current = null;
    if (fileRef.current) fileRef.current.value = "";
  }

  async function correrPreview(archivo: File, f: string) {
    setErrorMsg(null);
    setEstado({ fase: "cargando" });
    try {
      const form = new FormData();
      form.append("archivo", archivo);
      form.append("lista_id", String(listaId));
      form.append("fuente_import", f);
      const prev = await previewImportarInsumos(form);
      fuentePreviewRef.current = f;
      setEstado({ fase: "preview", prev });
    } catch (e: unknown) {
      setErrorMsg(e instanceof Error ? e.message : "Error al procesar el archivo");
      setEstado({ fase: "idle" });
    }
  }

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const archivo = e.target.files?.[0];
    if (!archivo) return;
    archivoRef.current = archivo;
    await correrPreview(archivo, fuente.trim());
  }

  // El preview depende de la fuente declarada (decide qué queda protegido), así que
  // cambiarla con un archivo ya elegido obliga a recalcularlo. Va en el blur y no en
  // cada tecla: es un input de texto con datalist.
  function handleFuenteBlur() {
    const f = fuente.trim();
    if (!f || !archivoRef.current || f === fuentePreviewRef.current) return;
    void correrPreview(archivoRef.current, f);
  }

  async function aplicar() {
    if (estado.fase !== "preview") return;
    const archivo = archivoRef.current;
    if (!archivo) return;
    setEstado({ fase: "aplicando" });
    try {
      const form = new FormData();
      form.append("archivo", archivo);
      form.append("lista_id", String(listaId));
      form.append("fuente_import", fuentePreviewRef.current);
      const res = await aplicarImportarInsumos(form);
      const errCount = res.errores?.length ?? 0;
      const protegidos = res.protegidos ?? 0;
      const resumen = `${res.creados} creado(s), ${res.actualizados} actualizado(s)` +
        (protegidos > 0 ? `, ${protegidos} protegido(s)` : "");
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
```

En el JSX, arriba del bloque del input de archivo, el campo nuevo (usa `<datalist>`, el mismo patrón nativo que ya usa `TablaInsumos.tsx`):

```tsx
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor="fuente-import" className="text-xs font-medium">
            Fuente de esta importación
          </label>
          <input
            id="fuente-import"
            type="text"
            list="fuentes-import-list"
            value={fuente}
            onChange={(e) => setFuente(e.target.value)}
            onBlur={handleFuenteBlur}
            disabled={enAplicando}
            placeholder="PRECIO IDU"
            className="h-7 rounded border border-border bg-background px-2 text-xs"
          />
          <datalist id="fuentes-import-list">
            {fuentes.map((f) => <option key={f} value={f} />)}
          </datalist>
        </div>
        <p className="text-xs text-muted-foreground">
          Queda rotulada en todas las filas del archivo. Si declaras una fuente pública
          (PRECIO IDU), los precios internos no se tocan.
        </p>
```

Y justo debajo, la clasificación que devolvió el backend (solo hay preview cuando ya se
eligió archivo, que es el momento anterior a aplicar — que es lo que importa):

```tsx
        {prev?.clasificacion_import && (
          <p className={`text-xs font-medium ${
            prev.clasificacion_import === "publico" ? "text-muted-foreground" : "text-amber-600 dark:text-amber-500"
          }`}>
            {prev.clasificacion_import === "publico"
              ? "Esta importación es PÚBLICA: no puede pisar precios internos."
              : "Esta importación es INTERNA: puede pisar cualquier precio, incluidos los internos."}
          </p>
        )}
```

El caso interno va resaltado a propósito: es el que puede hacer daño, y es el que se ve
cuando alguien escribió "PRECIO IDU 2026" creyendo que declaraba algo público.

Y el input de archivo gana el candado:

```tsx
            disabled={!fuente.trim() || estado.fase === "cargando" || enAplicando}
```

- [ ] **Step 5: Pasar las fuentes desde la página**

`web/src/pages/Insumos.tsx`, línea ~211, agregar la prop al `<DialogoImportarInsumos>` (el estado `fuentes` ya existe en esa página y ya se recarga al cambiar de lista):

```tsx
          <DialogoImportarInsumos
            ...
            listaId={filtros.lista}
            listaNombre={listaActivaNombre}
            fuentes={fuentes}
            ...
```

- [ ] **Step 6: Correr las pruebas**

```bash
cd web && npx vitest run src/components/insumos/DialogoImportarInsumos.test.tsx
```

Esperado: 6 passed.

- [ ] **Step 7: Commit**

```bash
git add web/src
git commit -m "feat(web): el dialogo de import declara la fuente de la importacion

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: El preview muestra lo protegido

**Files:**
- Modify: `web/src/components/insumos/DialogoImportarInsumos.tsx`
- Test: `web/src/components/insumos/DialogoImportarInsumos.test.tsx`

- [ ] **Step 1: Escribir la prueba que falla**

```tsx
it("muestra las filas protegidas y no las cuenta para aplicar", async () => {
  previewImportarInsumos.mockResolvedValue({
    crear: [], actualizar: [], ambigua: [], no_encontrada: [], invalida: [],
    protegida: [{
      codigo: "500", nombre: "MANO DE OBRA OFICIAL",
      fuente_actual: "COSTO INTERNO", precio_actual: 25000, precio_archivo: 9,
    }],
  });
  montar();
  seleccionarFuente();
  seleccionarArchivo();

  expect(await screen.findByText(/Protegidas/i)).toBeTruthy();
  expect(screen.getByText("COSTO INTERNO")).toBeTruthy();
  expect((screen.getByText("Aplicar (0)") as HTMLButtonElement).disabled).toBe(true);
});
```

- [ ] **Step 2: Correr y verificar que falla**

```bash
cd web && npx vitest run src/components/insumos/DialogoImportarInsumos.test.tsx
```

Esperado: FAIL — no existe la sección.

- [ ] **Step 3: Pintar la sección y la columna que faltaba**

En el bloque `{prev && (...)}`, la sección de Actualizar gana **Fuente actual** (el backend ya la mandaba y el diálogo nunca la pintó), y se agrega la sección nueva justo después:

```tsx
            <Seccion titulo="Actualizar precio">
              <Tabla cols={["Código", "Nombre", "Precio actual", "Precio nuevo", "Fuente actual", "Fuente nueva"]}
                     filas={prev.actualizar.map((c) => [c.codigo, c.nombre, cop(c.precio_actual), cop(c.precio_nuevo), c.fuente_actual || "—", c.fuente_nueva])} />
            </Seccion>
            <Seccion titulo="Protegidas — no se tocan (precio interno)">
              <Tabla cols={["Código", "Nombre", "Fuente actual", "Precio actual", "Precio del archivo"]}
                     filas={(prev.protegida ?? []).map((p) => [
                       p.codigo, p.nombre, p.fuente_actual || "(sin fuente)",
                       cop(p.precio_actual),
                       p.precio_archivo === null ? "—" : cop(p.precio_archivo)])} />
            </Seccion>
```

`nAcciones` no cambia: ya cuenta solo `crear + actualizar`, así que las protegidas no habilitan el botón.

- [ ] **Step 4: Correr las pruebas**

```bash
cd web && npx vitest run src/components/insumos/DialogoImportarInsumos.test.tsx
```

Esperado: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add web/src
git commit -m "feat(web): el preview del import muestra las filas protegidas

Y la tabla de actualizar gana la columna 'Fuente actual', que el backend
ya mandaba y el dialogo nunca pinto.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Documentar y verificación final

**Files:** `CLAUDE.md`

- [ ] **Step 0: Documentar la regla en `CLAUDE.md`**

`CLAUDE.md` no menciona el importador de insumos en ninguna parte. Esto es una frontera de dinero, con una regla asimétrica y deliberadamente sin escape: exactamente lo que alguien "simplifica" en seis meses. Agregar a la sección **No hacer**:

```markdown
- No hagas simétrico el candado del importador de insumos ni le agregues una casilla de
  "forzar". Una importación cuya fuente clasifique como **pública** (`PRECIO IDU`) no
  pisa un precio **interno**: esas filas van al balde `protegida` del preview y no se
  escriben (`dominio`… en realidad `servicio/autoria.py::_protegida`). Al revés sí se
  puede, y es a propósito: una tanda pública es masiva y automática (miles de filas del
  visor del IDU), una interna es curada. Si hay que cambiar un interno, se edita por
  insumo, que ya se puede. Ojo con el término `not ins.sin_precio`: sin él, una
  importación pública contra una lista de NP recién creada queda bloqueada entera,
  porque sin tarifa en esa lista `fuente_precio` es `""` (LEFT JOIN) y `""` clasifica
  como interno.
- No le devuelvas al archivo el mando sobre la etiqueta de fuente en el importador de
  insumos. La fuente la declara la importación (`fuente_import`, obligatoria en los dos
  endpoints) y se estampa en TODAS las filas; la columna `fuente` del Excel se ignora.
  El `fuente_nueva = f["fuente"] or ins.fuente_precio` que había antes dejaba el precio
  nuevo con la etiqueta vieja: un precio del IDU rotulado `COSTO INTERNO`, tratado como
  confidencial por `config.classify_price_source` sin que nada lo avisara.
- No conviertas en "listo" el aviso de clasificación del diálogo de importación.
  `classify_price_source` es fail-open: `PRECIO IDU 2026` clasifica **interno** y el
  candado no se dispara. La protección es que el diálogo **muestre** cómo se clasificó
  la fuente antes de aplicar, no que el sistema adivine que quisiste decir `PRECIO IDU`.
  Un matching difuso ahí sería una fuente nueva de sorpresas.
```

Ajustá el texto a lo que quedó realmente implementado (nombres de funciones y de claves), y ponelo en el orden que tenga sentido dentro de la sección.

- [ ] **Step 1: Suite de Python completa**

```bash
python -m pytest tests/ -q
```

Esperado: todo verde, 0 fallos.

- [ ] **Step 2: Suite de vitest completa**

```bash
cd web && npx vitest run
```

Esperado: todo verde.

- [ ] **Step 3: Build del frontend**

```bash
cd web && npm run build
```

Esperado: build OK. **Es `npm run build` (corre `tsc -b`), no `tsc --noEmit`**: es la lección de la rama de nombre/alias de corridas — `--noEmit` no ve los errores de proyecto compuesto.

- [ ] **Step 4: Commit de la documentación**

```bash
git add CLAUDE.md
git commit -m "docs: la regla del candado del importador de insumos

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 5: Reportar**

Reportar las tres salidas (conteos reales, no "pasan todos"). Si algo falla, arreglar antes de dar la tarea por terminada.

---

## Lo que este plan NO hace

- **No toca el importador de APUs.** `aplicar_importar_apus` ya salta los APUs existentes.
- **No toca la edición manual de precios** (`servicio/insumos.py::aplicar_cambios`).
- **No hay forma de forzar** una fila protegida desde el import en lote. Para cambiar un interno se edita por insumo, que ya se puede.
- **No agrega fuentes públicas.** `config.PUBLIC_PRICE_SOURCES` sigue siendo `{"PRECIO IDU"}`; si mañana entra otra entidad se agrega ahí y el candado la respeta solo.
