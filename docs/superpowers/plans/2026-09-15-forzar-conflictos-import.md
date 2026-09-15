# Forzar conflictos del import — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Poder decidir fila por fila que una importación actualice el precio de un insumo que ya existe, cuando el código coincide pero el nombre difiere por un typo.

**Architecture:** El preview resuelve, para cada conflicto de código, cuál de los insumos con ese código más se parece al nombre del archivo, y lo devuelve con su parecido y una sugerencia de premarcado. El usuario marca casillas; los `insumo_id` marcados viajan como `forzar_ids` al aplicar. Una fila forzada **no se escribe directo**: se despacha a `_upsert_o_invalida`, el mismo embudo de siempre, así que hereda el candado de los precios internos, el guard del $0 y la fuente declarada sin código nuevo.

**Tech Stack:** Python 3 + FastAPI (backend, sin dependencias nuevas — `re` y `collections` son stdlib), React + TypeScript + vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-09-15-forzar-conflictos-import-design.md`

---

## Estructura de archivos

| Archivo | Responsabilidad en este cambio |
|---|---|
| `apu_tool/config.py` | El umbral del premarcado, junto a `CRUCE_UMBRAL` (línea 73). |
| `apu_tool/servicio/autoria.py` | Resolver el candidato, el premarcado, y desviar la fila forzada al embudo. Único archivo con lógica nueva. |
| `apu_tool/servicio/rutas.py` | `forzar_ids` en los dos endpoints de import de insumos. |
| `web/src/lib/tipos.ts` | Campos nuevos de `ImportConflicto`. |
| `web/src/components/insumos/DialogoImportarInsumos.tsx` | La tabla con casillas y el envío de `forzar_ids`. |
| `tests/test_servicio_autoria.py`, `tests/test_api_autoria.py` | Pruebas de backend. |
| `web/src/components/insumos/DialogoImportarInsumos.test.tsx` | Pruebas de frontend. |

**Contexto que el implementador necesita saber:**

- **La identidad de un insumo es código + nombre normalizado.** `nucleo/texto.py::normalizar` ya perdona mayúsculas, tildes, puntuación y espacios de más; no perdona una palabra menos ni una letra distinta.
- **652 códigos del catálogo están repetidos** (1304 insumos, el 16%), y no son variantes: el código `10000` lo comparten un CHEVRON reflectivo y un PISO EN LOSETA. Por eso el conflicto tiene que decir contra CUÁL insumo se ofrece actualizar, y por eso la decisión viaja por `insumo_id` y nunca por código.
- **`_upsert_o_invalida` es el embudo.** Ahí vive el candado (`_protegida`: una importación pública no pisa un precio interno) y el enrutado a `invalida`. Todo lo que actualice un insumo existente tiene que pasar por ahí.
- **`aplicar_importar_insumos` recalcula el preview internamente** a partir del archivo; no recibe los baldes del frontend.
- Regla de negocio "nada en $0": un precio ≤ 0 es error, nunca se escribe.

---

### Task 1: El conflicto dice contra cuál insumo se ofrece

**Files:**
- Modify: `apu_tool/config.py` (constante nueva, junto a `CRUCE_UMBRAL` en la línea 73)
- Modify: `apu_tool/servicio/autoria.py` (imports, `_mismos_numeros`, `_mejor_candidato`, `preview_importar_insumos`)
- Test: `tests/test_servicio_autoria.py`

- [ ] **Step 1: Escribir las pruebas que fallan**

En `tests/test_servicio_autoria.py`, al final del bloque de import de insumos:

```python
def test_conflicto_de_codigo_trae_el_mejor_candidato(tmp_path):
    """Con 652 códigos repetidos en el catálogo real, "el código ya existe" no dice
    cuál insumo es. El conflicto tiene que nombrar contra cuál se ofrece actualizar."""
    alm = _alm(tmp_path)
    # dos insumos con el MISMO código y nombres muy distintos
    alm.precios.insert_insumos([
        Insumo("700", "CHEVRON 90 CM X 40 CM REFLECTIVO", "UN", "SEN", 330498, "PRECIO IDU"),
        Insumo("700", "PISO EN LOSETA PREFABRICADA A-50", "M2", "PAV", 135101, "PRECIO IDU")])
    # OJO con el nombre del archivo: `normalizar` convierte "A-50" en "A 50", así que un
    # nombre que solo cambie el guion haría MATCH de identidad y nunca llegaría a
    # conflicto. La diferencia tiene que ser una letra de verdad (LOSETA -> LOZETA).
    contenido = _xlsx_upsert_filas([["700", "PISO EN LOZETA PREFABRICADA A-50", "M2", "PAV", 140000]])
    prev = autoria.preview_importar_insumos(alm, contenido, "f.xlsx", "PRECIO IDU")

    assert len(prev["conflicto"]) == 1
    c = prev["conflicto"][0]
    assert c["campo"] == "codigo"
    assert c["nombre_actual"] == "PISO EN LOSETA PREFABRICADA A-50"   # el parecido, no el CHEVRON
    assert c["precio_actual"] == 135101
    assert c["parecido"] > 0.7      # medido: 74.8% contra el PISO, 10.0% contra el CHEVRON


def test_premarcado_no_marca_cuando_cambia_un_numero(tmp_path):
    """El parecido NO separa "es el mismo" de "es otro": con nombres largos, cambiar un
    dígito puntúa ~89%, igual que una letra distinta. Lo que separa son los números."""
    alm = _alm(tmp_path)
    alm.precios.insert_insumos([
        Insumo("800", "TUBERIA PVC SANITARIA DE 6 PULGADAS INCLUYE ACCESORIOS Y MANO DE OBRA",
               "ML", "MAT", 50000, "PRECIO IDU")])
    contenido = _xlsx_upsert_filas([
        ["800", "TUBERIA PVC SANITARIA DE 8 PULGADAS INCLUYE ACCESORIOS Y MANO DE OBRA",
         "ML", "MAT", 60000]])
    c = autoria.preview_importar_insumos(alm, contenido, "f.xlsx", "PRECIO IDU")["conflicto"][0]
    assert c["parecido"] > 0.80          # el parecido solo lo dejaría pasar
    assert c["premarcar"] is False       # los números lo frenan


def test_premarcado_si_marca_una_letra_distinta(tmp_path):
    alm = _alm(tmp_path)
    alm.precios.insert_insumos([
        Insumo("900", "CONCRETO 3000 PSI HECHO EN OBRA PARA REDES", "M3", "MAT",
               526100, "PRECIO IDU")])
    contenido = _xlsx_upsert_filas([
        ["900", "CONCRETO 3000 PSI HECHO EN OVRA PARA REDES", "M3", "MAT", 530000]])
    c = autoria.preview_importar_insumos(alm, contenido, "f.xlsx", "PRECIO IDU")["conflicto"][0]
    assert c["premarcar"] is True


# Los diez casos con los que se eligió la regla. El parecido SOLO no los separa: "una
# letra distinta" da 89.0% y "MR-42 vs MR-40" da 88.7%. Lo que los separa son los números.
# Los dos False del final de la lista de "sí quiere" son falsos negativos aceptados: no
# vienen marcados, pero el usuario los marca a mano. Ese error cuesta un clic; el
# contrario cuesta un precio equivocado.
@pytest.mark.parametrize("esperado,a,b", [
    (True,  "CONCRETO 3000 PSI HECHO EN OBRA PARA REDES", "CONCRETO 3000 PSI HECHO EN OVRA PARA REDES"),
    (True,  "SUBBASE GRANULAR CLASE C PARA VIA", "SUBBASE GRANULAR CLASE C"),
    (False, "PINTURA ACRILICA BASE AGUA PARA DEMARCACION DE VIAS", "PINTURA ACRILICA BASE AGUA"),
    (False, "SUMINISTRO E INSTALACION DE TUBERIA PVC SANITARIA 6 PULGADAS", "SUM E INST TUBERIA PVC SANITARIA 6 PULG"),
    (False, "CONCRETO 3000 PSI HECHO EN OBRA PARA REDES", "CONCRETO 2500 PSI HECHO EN OBRA PARA REDES"),
    (False, "SUMINISTRO Y COLOCACION DE CONCRETO HIDRAULICO MR-42 PARA LOSA DE PAVIMENTO RIGIDO INCLUYE JUNTAS",
            "SUMINISTRO Y COLOCACION DE CONCRETO HIDRAULICO MR-40 PARA LOSA DE PAVIMENTO RIGIDO INCLUYE JUNTAS"),
    (False, "TUBERIA PVC SANITARIA DE 6 PULGADAS INCLUYE ACCESORIOS Y MANO DE OBRA",
            "TUBERIA PVC SANITARIA DE 8 PULGADAS INCLUYE ACCESORIOS Y MANO DE OBRA"),
    (False, "ACERO DE REFUERZO FY=420 MPA PARA ESTRUCTURAS DE CONCRETO INCLUYE CORTE",
            "ACERO DE REFUERZO FY=240 MPA PARA ESTRUCTURAS DE CONCRETO INCLUYE CORTE"),
    (False, "LADRILLO TOLETE COMUN", "LADRILLO TOLETE PRENSADO"),
    (False, "CHEVRON 90 cm x 40 cm REFLECTIVO", "PISO EN LOSETA PREFABRICADA A-50"),
])
def test_regla_de_premarcado(esperado, a, b):
    """Ningún caso de 'cambió un número' se pre-marca. Es la propiedad que protege plata."""
    assert autoria._premarcar(a, b, similarity(a, b)) is esperado


def test_conflicto_de_nombre_no_trae_candidato(tmp_path):
    """El nombre ya existe bajo OTRO código: forzar ahí reasignaría el precio a un
    insumo con código distinto, y está fuera de alcance. Sin casilla."""
    alm = _alm(tmp_path)
    contenido = _xlsx_upsert_filas([["999", "CEMENTO GRIS", "KG", "MAT", 1200]])
    c = autoria.preview_importar_insumos(alm, contenido, "f.xlsx", "PRECIO IDU")["conflicto"][0]
    assert c["campo"] == "nombre"
    assert "insumo_id" not in c
```

El helper `_xlsx_upsert_filas` no existe todavía; agregalo junto a `_xlsx_upsert` (línea ~65):

```python
def _xlsx_upsert_filas(filas) -> bytes:
    """Excel con las columnas del importador y las filas que se le pasen."""
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["codigo", "nombre", "unidad", "grupo", "precio"])
    for f in filas:
        ws.append(f)
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()
```

- [ ] **Step 2: Correr y verificar que fallan**

```bash
python -m pytest tests/test_servicio_autoria.py -k "candidato or premarcado" -v
```

Esperado: FAIL con `KeyError: 'campo'`.

- [ ] **Step 3: El umbral en config**

En `apu_tool/config.py`, junto a `CRUCE_UMBRAL` (línea 73):

```python
# Parecido mínimo para PRE-MARCAR un conflicto de código en el import de insumos.
# Solo pre-marca: el usuario decide, y lo que se aplica es lo que él manda.
# Medido sobre nombres del estilo del catálogo: con 0.80 y el guard de los números,
# ninguno de los seis casos de "cambió un dígito" se pre-marca.
UMBRAL_PREMARCA_CONFLICTO = 0.80
```

- [ ] **Step 4: Los dos helpers**

En `apu_tool/servicio/autoria.py`, agregar a los imports de arriba:

```python
import re
from collections import Counter
```

y al bloque de imports del proyecto:

```python
from apu_tool.nucleo.relevancia import similarity
```

Después de `_match_identidad` (línea ~373), agregar:

```python
def _mismos_numeros(a: str, b: str) -> bool:
    """True si los dos nombres traen exactamente los mismos números, con las mismas
    repeticiones.

    Es lo que separa «una letra distinta» (el mismo insumo) de «MR-42 vs MR-40» (otro
    material), que el PARECIDO no separa: con nombres largos los dos puntúan ~89%.
    Medido: `TUBERIA … 6 PULGADAS` vs `8 PULGADAS` da 84%, `ACERO FY=420` vs `FY=240`
    da 86%, y `OBRA` vs `OVRA` da 89%. Solo los números los distinguen."""
    return Counter(re.findall(r"\d+", a or "")) == Counter(re.findall(r"\d+", b or ""))


def _mejor_candidato(alm: Almacen, codigo: str, nombre: str,
                     lista_id: Optional[int] = None):
    """`(insumo, parecido)` del insumo con ese código cuyo nombre más se parece al del
    archivo, o `(None, 0.0)` si el código no existe en la base.

    Hace falta porque 652 códigos del catálogo están repetidos (1304 insumos) y NO son
    variantes: el código 10000 lo comparten un CHEVRON reflectivo y un PISO EN LOSETA.
    "El código ya existe" no dice cuál."""
    cands = alm.precios.get_candidatos(codigo, lista_id=lista_id)
    if not cands:
        return None, 0.0
    sim, mejor = max(((similarity(nombre, c.nombre), c) for c in cands),
                     key=lambda par: par[0])
    return mejor, sim


def _premarcar(nombre_archivo: str, nombre_base: str, parecido: float) -> bool:
    """Si el conflicto conviene venir ya marcado en el diálogo.

    Es función con nombre —y no una expresión adentro de `_fila_conflicto`— porque es una
    decisión de DINERO que toma el servidor: merece estar donde se pueda leer y probar
    sola (ver `test_regla_de_premarcado`, que la fija contra los diez casos medidos)."""
    return parecido >= config.UMBRAL_PREMARCA_CONFLICTO and _mismos_numeros(
        nombre_archivo, nombre_base)
```

El `key=lambda par: par[0]` no es decorativo: sin él, dos candidatos con el mismo parecido
harían que `max` compare los `Insumo` entre sí y reviente con `TypeError`.

- [ ] **Step 5: Enriquecer el balde `conflicto`**

En `preview_importar_insumos`, la rama "con nombre" pasa de usar `_conflicto_insumo` a
`conflicto_insumo_detalle` (que ya es pública y devuelve `(campo, motivo)`), y arma la
entrada según el campo. Reemplazar este bloque:

```python
            motivo = _conflicto_insumo(alm, cod, nom, extra=reclamadas)
            if motivo:
                conflicto.append({**f, "motivo": motivo})
            else:
                crear.append(f)
                reclamadas.append((cod, nom, False))
```

por:

```python
            detalle = conflicto_insumo_detalle(alm, cod, nom, extra=reclamadas)
            if detalle:
                campo, motivo = detalle
                conflicto.append(_fila_conflicto(alm, f, campo, motivo, lista_id))
            else:
                crear.append(f)
                reclamadas.append((cod, nom, False))
```

Y agregar la función que arma la entrada, justo antes de `preview_importar_insumos`:

```python
def _fila_conflicto(alm: Almacen, f: dict, campo: str, motivo: str,
                    lista_id: Optional[int]) -> dict:
    """La entrada del balde `conflicto`.

    Un conflicto de CÓDIGO trae además el insumo contra el que se ofrece actualizar, su
    precio y fuente de hoy, el parecido de los nombres, y si conviene pre-marcarlo. Un
    conflicto de NOMBRE no trae nada de eso: forzarlo reasignaría el precio a un insumo
    con otro código, y está fuera de alcance (no lleva casilla en el diálogo).

    `insumo_id` ausente también cuando el choque es contra una fila anterior del MISMO
    archivo (`reclamadas`): ese insumo todavía no existe, no hay nada que actualizar."""
    fila = {**f, "motivo": motivo, "campo": campo}
    if campo != "codigo":
        return fila
    ins, sim = _mejor_candidato(alm, f["codigo"], f["nombre"], lista_id)
    if ins is None:
        return fila
    return {**fila, "insumo_id": ins.id, "nombre_actual": ins.nombre,
            "precio_actual": ins.precio, "fuente_actual": ins.fuente_precio,
            "parecido": round(sim, 3),
            "premarcar": _premarcar(f["nombre"], ins.nombre, sim)}
```

- [ ] **Step 6: Correr las pruebas**

`test_regla_de_premarcado` necesita el import del scorer arriba del archivo de pruebas:

```python
from apu_tool.nucleo.relevancia import similarity
```

```bash
python -m pytest tests/test_servicio_autoria.py -k "candidato or premarcado or conflicto_de_nombre" -v
```

Esperado: **14 passed** (4 pruebas con nombre + los 10 casos parametrizados).

- [ ] **Step 7: Correr la suite de importación**

```bash
python -m pytest tests/test_servicio_autoria.py tests/test_autoria_sin_duplicados.py tests/test_autoria_lista_precios_regresion.py tests/test_servicio_insumos_lista.py tests/test_api_autoria.py -q
```

Esperado: todo verde. `test_autoria_sin_duplicados.py` asserta sobre `prev["conflicto"][0]["motivo"]`, que no cambia — las claves nuevas se suman, ninguna se quita.

- [ ] **Step 8: Commit**

```bash
git add apu_tool/config.py apu_tool/servicio/autoria.py tests/test_servicio_autoria.py
git commit -m "feat(import): el conflicto de codigo dice contra cual insumo se ofrece

Con 652 codigos repetidos en el catalogo, 'el codigo ya existe' no dice
cual. El conflicto trae ahora el mejor candidato por parecido, su precio
y fuente, y si conviene pre-marcarlo.

El pre-marcado exige parecido >= 0.80 Y los mismos numeros: el parecido
solo no separa 'una letra distinta' (89%) de 'MR-42 vs MR-40' (88.7%).

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: La fila forzada entra por el embudo

**Files:**
- Modify: `apu_tool/servicio/autoria.py` (`preview_importar_insumos`, `aplicar_importar_insumos`)
- Test: `tests/test_servicio_autoria.py`

- [ ] **Step 1: Escribir las pruebas que fallan**

```python
def test_forzar_un_conflicto_actualiza_el_insumo_elegido(tmp_path):
    alm = _alm(tmp_path)
    alm.precios.insert_insumos([
        Insumo("900", "CONCRETO 3000 PSI HECHO EN OBRA", "M3", "MAT", 526100, "PRECIO IDU")])
    iid = alm.precios.get_candidatos("900")[0].id
    contenido = _xlsx_upsert_filas([["900", "CONCRETO 3000 PSI HECHO EN OVRA", "M3", "MAT", 530000]])

    # sin forzar: queda en conflicto y no se escribe
    res = autoria.aplicar_importar_insumos(alm, contenido, "f.xlsx", "PRECIO IDU")
    assert res["creados"] == 0 and res["actualizados"] == 0
    assert alm.precios.get_candidatos("900")[0].precio == 526100

    # forzando: se actualiza el que se eligió
    res = autoria.aplicar_importar_insumos(alm, contenido, "f.xlsx", "PRECIO IDU",
                                           forzar_ids={iid})
    assert res["actualizados"] == 1
    assert alm.precios.get_candidatos("900")[0].precio == 530000
    assert alm.precios.get_candidatos("900")[0].nombre == "CONCRETO 3000 PSI HECHO EN OBRA"


def test_forzar_no_es_un_permiso_el_candado_sigue(tmp_path):
    """Forzar resuelve una pregunta de IDENTIDAD, no de PERMISO. Una fila forzada sobre
    un insumo con precio interno, con importación pública, sigue protegida."""
    alm = _alm(tmp_path)
    alm.precios.insert_insumos([
        Insumo("901", "MANO DE OBRA OFICIAL DE PRIMERA", "HR", "MO", 25000, "COSTO INTERNO")])
    iid = alm.precios.get_candidatos("901")[0].id
    contenido = _xlsx_upsert_filas([["901", "MANO DE OBRA OFICIAL DE PRIMER", "HR", "MO", 9]])

    prev = autoria.preview_importar_insumos(alm, contenido, "f.xlsx", "PRECIO IDU",
                                            forzar_ids={iid})
    assert prev["conflicto"] == []                  # ya no es conflicto: se forzó
    assert prev["actualizar"] == []                 # pero tampoco se actualiza
    assert [p["codigo"] for p in prev["protegida"]] == ["901"]

    res = autoria.aplicar_importar_insumos(alm, contenido, "f.xlsx", "PRECIO IDU",
                                           forzar_ids={iid})
    assert res["protegidos"] == 1 and res["actualizados"] == 0
    assert alm.precios.get_candidatos("901")[0].precio == 25000


def test_forzar_un_id_que_no_resuelve_no_escribe(tmp_path):
    """El catálogo puede cambiar entre el preview y el aplicar: un id que ya no
    corresponde deja la fila en conflicto, sin error."""
    alm = _alm(tmp_path)
    alm.precios.insert_insumos([
        Insumo("902", "ARENA DE PEÑA LAVADA", "M3", "MAT", 50000, "PRECIO IDU")])
    contenido = _xlsx_upsert_filas([["902", "ARENA DE PENA LAVADA GRUESA", "M3", "MAT", 60000]])
    res = autoria.aplicar_importar_insumos(alm, contenido, "f.xlsx", "PRECIO IDU",
                                           forzar_ids={999999})
    assert res["actualizados"] == 0 and res["errores"] == []
    assert alm.precios.get_candidatos("902")[0].precio == 50000


def test_forzar_un_conflicto_de_nombre_no_hace_nada(tmp_path):
    """Solo se fuerzan conflictos de código (ver spec, fuera de alcance)."""
    alm = _alm(tmp_path)
    iid = alm.precios.get_candidatos("100")[0].id      # CEMENTO GRIS, código 100
    contenido = _xlsx_upsert_filas([["999", "CEMENTO GRIS", "KG", "MAT", 1200]])
    prev = autoria.preview_importar_insumos(alm, contenido, "f.xlsx", "PRECIO IDU",
                                            forzar_ids={iid})
    assert len(prev["conflicto"]) == 1 and prev["actualizar"] == []
```

- [ ] **Step 2: Correr y verificar que fallan**

```bash
python -m pytest tests/test_servicio_autoria.py -k "forzar" -v
```

Esperado: FAIL con `TypeError: preview_importar_insumos() got an unexpected keyword argument 'forzar_ids'`.

- [ ] **Step 3: El parámetro y el desvío**

En `preview_importar_insumos`, la firma gana el parámetro al final (después de `lista_id`, que es el que los llamadores pasan por keyword):

```python
def preview_importar_insumos(alm: Almacen, contenido: bytes, nombre_archivo: str,
                             fuente_import: str, lista_id: Optional[int] = None,
                             forzar_ids: Optional[set[int]] = None) -> dict:
```

Y al docstring, un párrafo al final:

```
    `forzar_ids` son los `insumo_id` que el usuario decidió aplicar igual, de entre los
    conflictos de código. La fila no se escribe directo: se despacha a
    `_upsert_o_invalida`, así que forzar resuelve una pregunta de IDENTIDAD y nunca una
    de PERMISO — el candado de los precios internos sigue mandando.
```

Dentro, antes del bucle:

```python
    forzados = set(forzar_ids or ())      # None y [] se tratan igual: no se fuerza nada
```

Y el bloque de la rama "con nombre" que la Task 1 dejó así:

```python
            detalle = conflicto_insumo_detalle(alm, cod, nom, extra=reclamadas)
            if detalle:
                campo, motivo = detalle
                conflicto.append(_fila_conflicto(alm, f, campo, motivo, lista_id))
```

pasa a:

```python
            detalle = conflicto_insumo_detalle(alm, cod, nom, extra=reclamadas)
            if detalle:
                campo, motivo = detalle
                fila = _fila_conflicto(alm, f, campo, motivo, lista_id)
                # Forzada: entra por el MISMO embudo que todo lo demás, no por un atajo.
                # Así hereda el candado, el enrutado a 'invalida' y el guard del $0 sin
                # una línea de código nueva.
                if fila.get("insumo_id") in forzados:
                    ins, _sim = _mejor_candidato(alm, cod, nom, lista_id)
                    _upsert_o_invalida(ins, f, fuente_import, actualizar, invalida,
                                       protegida)
                else:
                    conflicto.append(fila)
```

`fila.get("insumo_id")` devuelve `None` para los conflictos de nombre y para los choques
contra el propio archivo, y `None not in forzados` porque `forzados` solo tiene enteros:
esos casos nunca se fuerzan, sin un `if` extra.

- [ ] **Step 4: Pasarlo desde el aplicar**

```python
def aplicar_importar_insumos(alm: Almacen, contenido: bytes, nombre_archivo: str,
                             fuente_import: str, actor=None,
                             lista_id: Optional[int] = None,
                             forzar_ids: Optional[set[int]] = None) -> dict:
    prev = preview_importar_insumos(alm, contenido, nombre_archivo, fuente_import,
                                    lista_id, forzar_ids)
```

El resto del cuerpo **no cambia**: las filas forzadas ya llegan a `actualizar` (o a
`protegida`) y su bucle las recorre como a cualquier otra.

- [ ] **Step 5: Correr las pruebas**

```bash
python -m pytest tests/test_servicio_autoria.py -k "forzar" -v
```

Esperado: 4 passed.

- [ ] **Step 6: Correr la suite de importación**

```bash
python -m pytest tests/test_servicio_autoria.py tests/test_autoria_sin_duplicados.py tests/test_autoria_lista_precios_regresion.py tests/test_servicio_insumos_lista.py tests/test_api_autoria.py tests/test_plantillas.py tests/test_auditoria_servicios_precios.py -q
```

Esperado: todo verde.

- [ ] **Step 7: Commit**

```bash
git add apu_tool/servicio/autoria.py tests/test_servicio_autoria.py
git commit -m "feat(import): forzar un conflicto de codigo entra por el embudo

forzar_ids desvia la fila a _upsert_o_invalida en vez de escribirla
directo: forzar resuelve identidad, no permiso. El candado de los
precios internos sigue mandando sobre una fila forzada.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Los endpoints reciben `forzar_ids`

**Files:**
- Modify: `apu_tool/servicio/rutas.py:773-803`
- Test: `tests/test_api_autoria.py`

- [ ] **Step 1: Escribir la prueba que falla**

En `tests/test_api_autoria.py`, junto a las otras pruebas de import:

```python
def test_import_insumos_endpoint_forzar_ids(tmp_path):
    """El id marcado viaja como campo repetido del form y la fila se aplica."""
    cli, alm = _cli(tmp_path)
    iid = alm.precios.get_candidatos("100")[0].id      # CEMENTO GRIS, 1000, PRECIO IDU
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["codigo", "nombre", "precio"])
    ws.append(["100", "CEMENTO GRIZ", 1500])           # typo -> conflicto de código
    buf = io.BytesIO(); wb.save(buf); data = buf.getvalue()

    sin = cli.post("/api/insumos/importar/preview",
                   files={"archivo": ("f.xlsx", data, _XLSX)},
                   data={"fuente_import": "PRECIO IDU"})
    assert len(sin.json()["conflicto"]) == 1
    assert sin.json()["conflicto"][0]["insumo_id"] == iid

    con = cli.post("/api/insumos/importar",
                   files={"archivo": ("f.xlsx", data, _XLSX)},
                   data={"fuente_import": "PRECIO IDU", "forzar_ids": str(iid)})
    assert con.status_code == 200, con.text
    assert con.json()["actualizados"] == 1
    assert alm.precios.get_candidatos("100")[0].precio == 1500
```

- [ ] **Step 2: Correr y verificar que falla**

```bash
python -m pytest tests/test_api_autoria.py -k "forzar" -v
```

Esperado: FAIL — el endpoint ignora `forzar_ids` y `actualizados` es 0.

- [ ] **Step 3: Agregar el campo a los dos endpoints**

`apu_tool/servicio/rutas.py`, línea 773:

```python
@router.post("/insumos/importar/preview")
async def insumos_importar_preview(archivo: UploadFile = File(...),
                                   fuente_import: str = Form(...),
                                   lista_id: Optional[int] = Form(None),
                                   forzar_ids: list[int] = Form([]),
                                   alm: Almacen = Depends(get_almacen),
                                   _: object = Depends(requiere_rol("editor"))):
    _validar_lista(alm, lista_id)
    contenido = await archivo.read()
    try:
        return autoria.preview_importar_insumos(alm, contenido,
                                                archivo.filename or "insumos.xlsx",
                                                fuente_import, lista_id, set(forzar_ids))
```

Línea 789:

```python
@router.post("/insumos/importar")
async def insumos_importar(archivo: UploadFile = File(...),
                           fuente_import: str = Form(...),
                           lista_id: Optional[int] = Form(None),
                           forzar_ids: list[int] = Form([]),
                           alm: Almacen = Depends(get_almacen),
                           actor=Depends(requiere_rol("editor"))):
    _validar_lista(alm, lista_id)
    contenido = await archivo.read()
    try:
        return autoria.aplicar_importar_insumos(alm, contenido,
                                                archivo.filename or "insumos.xlsx",
                                                fuente_import, actor=actor,
                                                lista_id=lista_id,
                                                forzar_ids=set(forzar_ids))
```

Los bloques `except` no se tocan.

- [ ] **Step 4: Correr las pruebas**

```bash
python -m pytest tests/test_api_autoria.py -q
```

Esperado: todo verde.

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/rutas.py tests/test_api_autoria.py
git commit -m "feat(import): los endpoints reciben forzar_ids

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Las casillas en el diálogo

**Files:**
- Modify: `web/src/lib/tipos.ts` (`ImportConflicto`)
- Modify: `web/src/components/insumos/DialogoImportarInsumos.tsx`
- Test: `web/src/components/insumos/DialogoImportarInsumos.test.tsx`

- [ ] **Step 1: Escribir las pruebas que fallan**

En `DialogoImportarInsumos.test.tsx` (ya tiene los helpers `montar()`, `seleccionarFuente()` y `seleccionarArchivo()`):

```tsx
const CONFLICTO_CODIGO = {
  codigo: "900", nombre: "CONCRETO 3000 PSI HECHO EN OVRA",
  motivo: "El código 900 ya lo usa el insumo «CONCRETO 3000 PSI HECHO EN OBRA».",
  campo: "codigo" as const, insumo_id: 42,
  nombre_actual: "CONCRETO 3000 PSI HECHO EN OBRA",
  precio_actual: 526100, fuente_actual: "PRECIO IDU",
  parecido: 0.89, premarcar: true,
};

it("pre-marca los conflictos que el backend sugiere y los cuenta", async () => {
  previewImportarInsumos.mockResolvedValue({
    crear: [], actualizar: [], ambigua: [], no_encontrada: [], invalida: [],
    protegida: [], conflicto: [CONFLICTO_CODIGO], clasificacion_import: "publico",
  });
  montar();
  seleccionarFuente();
  seleccionarArchivo();

  const casilla = await screen.findByLabelText(/aplicar igual el 900/i) as HTMLInputElement;
  expect(casilla.checked).toBe(true);
  expect(screen.getByText("Aplicar (1)")).toBeTruthy();
});

it("manda en forzar_ids solo las casillas marcadas", async () => {
  previewImportarInsumos.mockResolvedValue({
    crear: [], actualizar: [], ambigua: [], no_encontrada: [], invalida: [],
    protegida: [], conflicto: [CONFLICTO_CODIGO], clasificacion_import: "publico",
  });
  montar();
  seleccionarFuente();
  seleccionarArchivo();
  fireEvent.click(await screen.findByText("Aplicar (1)"));

  await waitFor(() => expect(aplicarImportarInsumos).toHaveBeenCalled());
  const form = aplicarImportarInsumos.mock.calls[0][0] as FormData;
  expect(form.getAll("forzar_ids")).toEqual(["42"]);
});

it("desmarcar saca la fila de forzar_ids y del conteo", async () => {
  previewImportarInsumos.mockResolvedValue({
    crear: [], actualizar: [], ambigua: [], no_encontrada: [], invalida: [],
    protegida: [], conflicto: [CONFLICTO_CODIGO], clasificacion_import: "publico",
  });
  montar();
  seleccionarFuente();
  seleccionarArchivo();
  fireEvent.click(await screen.findByLabelText(/aplicar igual el 900/i));

  const boton = screen.getByText("Aplicar (0)") as HTMLButtonElement;
  expect(boton.disabled).toBe(true);
});

it("un conflicto de nombre no trae casilla", async () => {
  previewImportarInsumos.mockResolvedValue({
    crear: [], actualizar: [], ambigua: [], no_encontrada: [], invalida: [],
    protegida: [], clasificacion_import: "publico",
    conflicto: [{ codigo: "999", nombre: "CEMENTO GRIS", campo: "nombre" as const,
                  motivo: "Ese nombre ya lo usa el insumo 100." }],
  });
  montar();
  seleccionarFuente();
  seleccionarArchivo();

  expect(await screen.findByText(/Ese nombre ya lo usa/i)).toBeTruthy();
  expect(screen.queryByLabelText(/aplicar igual/i)).toBeNull();
});
```

- [ ] **Step 2: Correr y verificar que fallan**

```bash
cd web && npx vitest run src/components/insumos/DialogoImportarInsumos.test.tsx
```

Esperado: FAIL — no existe la casilla.

- [ ] **Step 3: Tipos**

`web/src/lib/tipos.ts`, `ImportConflicto` gana campos **opcionales** (la interfaz la comparte el import de APUs, que no los manda):

```ts
export interface ImportConflicto {
  codigo: string;
  nombre: string;
  turno?: string;   // solo en el import de APUs
  motivo: string;
  // Solo en los conflictos de CÓDIGO del import de insumos: el insumo contra el que se
  // ofrece actualizar, para poder aplicarlo igual desde el preview.
  campo?: "codigo" | "nombre";
  insumo_id?: number;
  nombre_actual?: string;
  precio_actual?: number;
  fuente_actual?: string;
  parecido?: number;
  premarcar?: boolean;
}
```

- [ ] **Step 4: El estado de las marcadas**

En `DialogoImportarInsumos.tsx`, junto a los otros `useState`:

```tsx
  // Los insumo_id de los conflictos que el usuario decidió aplicar igual. Es estado del
  // cliente: marcar NO re-dispara el preview, solo viaja al aplicar.
  const [forzados, setForzados] = useState<Set<number>>(new Set());
```

En `correrPreview`, al recibir el preview, sembrar con lo que el backend sugirió:

```tsx
      const prev = await previewImportarInsumos(form);
      fuentePreviewRef.current = f;
      setForzados(new Set((prev.conflicto ?? [])
        .filter((c) => c.premarcar && c.insumo_id !== undefined)
        .map((c) => c.insumo_id as number)));
      setEstado({ fase: "preview", prev });
```

En `resetear`, limpiarlo:

```tsx
    setForzados(new Set());
```

En `aplicar`, mandarlo (campo repetido, que es como FastAPI lee una `list[int]` de un form):

```tsx
      form.append("fuente_import", fuentePreviewRef.current);
      forzados.forEach((id) => form.append("forzar_ids", String(id)));
```

Y `nAcciones` suma las marcadas, porque van a escribir:

```tsx
  const nAcciones = prev ? prev.crear.length + prev.actualizar.length + forzados.size : 0;
```

- [ ] **Step 5: La tabla con casillas**

El componente `Tabla` local solo acepta `(string | number)[][]`, así que los conflictos de
código necesitan su propia tabla. Reemplazar la sección "En conflicto" por:

```tsx
            <SeccionConflictos conflictos={prev.conflicto ?? []} forzados={forzados}
                               onToggle={(id) => setForzados((s) => {
                                 const n = new Set(s);
                                 if (n.has(id)) n.delete(id); else n.add(id);
                                 return n;
                               })} />
```

Y agregar el componente al final del archivo, junto a `Seccion` y `Tabla`:

```tsx
function SeccionConflictos({ conflictos, forzados, onToggle }: {
  conflictos: ImportConflicto[];
  forzados: Set<number>;
  onToggle: (id: number) => void;
}) {
  const porCodigo = conflictos.filter((c) => c.insumo_id !== undefined);
  const porNombre = conflictos.filter((c) => c.insumo_id === undefined);
  const premarcados = porCodigo.filter((c) => c.premarcar).length;
  return (
    <>
      <div>
        <p className="text-xs font-semibold mb-1">
          El código ya existe con otro nombre — marca los que sean el mismo insumo
        </p>
        {porCodigo.length > 0 && (
          // El pre-marcado es una decisión de dinero que toma el servidor: que se VEA
          // cuántas vienen marcadas y con qué regla, en vez de ser un default invisible.
          <p className="text-xs text-muted-foreground mb-1">
            {premarcados} de {porCodigo.length} vienen marcadas (parecido ≥80% y los
            mismos números). Revisa las demás.
          </p>
        )}
        {porCodigo.length === 0 ? <p className="text-xs text-muted-foreground">Ninguno</p> : (
          <div className="overflow-x-hidden overflow-y-auto max-h-52 border rounded">
            <table className="w-full text-xs border-collapse">
              <thead className="sticky top-0 bg-muted/80 backdrop-blur z-10">
                <tr>
                  {["", "Código", "Nombre en el archivo", "Nombre en tu base", "Parecido", "Precio actual", "Precio nuevo"].map((c, i) => (
                    <th key={i} className="px-2 py-1 text-left font-medium text-muted-foreground border-b align-bottom">{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {porCodigo.map((c) => (
                  <tr key={c.insumo_id} className="hover:bg-muted/40 even:bg-muted/10">
                    <td className="px-2 py-0.5 align-top">
                      <input type="checkbox" aria-label={`Aplicar igual el ${c.codigo}`}
                             checked={forzados.has(c.insumo_id as number)}
                             onChange={() => onToggle(c.insumo_id as number)} />
                    </td>
                    <td className="px-2 py-0.5 align-top break-words">{c.codigo}</td>
                    <td className="px-2 py-0.5 align-top break-words">{c.nombre}</td>
                    <td className="px-2 py-0.5 align-top break-words">{c.nombre_actual}</td>
                    <td className="px-2 py-0.5 align-top">{Math.round((c.parecido ?? 0) * 100)}%</td>
                    <td className="px-2 py-0.5 align-top">{cop(c.precio_actual ?? 0)}</td>
                    <td className="px-2 py-0.5 align-top">{cop(c.precio ?? 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <Seccion titulo="En conflicto (no se crean)">
        <Tabla cols={["Código", "Nombre", "Motivo"]}
               filas={porNombre.map((c) => [c.codigo || "—", c.nombre || "—", c.motivo])} />
      </Seccion>
    </>
  );
}
```

`ImportConflicto` hay que agregarlo al `import type` de arriba del archivo. `c.precio` es
el precio que trae el archivo: viene en la entrada del conflicto porque el backend hace
`{**f, ...}` y `f` es la fila parseada.

- [ ] **Step 6: Correr las pruebas**

```bash
cd web && npx vitest run src/components/insumos/DialogoImportarInsumos.test.tsx
```

Esperado: 15 passed (las 11 de antes + 4 nuevas).

Después, la suite completa y el build:

```bash
cd web && npx vitest run
cd web && npm run build
```

`npm run build` corre `tsc -b`; **no uses `tsc --noEmit`**, no ve los errores de proyecto
compuesto (lección aprendida a la mala en este repo).

**Ojo con vitest:** en vitest 4 no se ve la consola de los tests que pasan; si necesitás
depurar, escribí a un archivo con `node:fs`. Un `import` dentro del cuerpo de un test se
come su timeout de 5 s.

- [ ] **Step 7: Commit**

```bash
git add web/src
git commit -m "feat(web): casillas para aplicar igual los conflictos de codigo

El pre-marcado del backend siembra la seleccion, y el conteo de cuantas
vienen marcadas se muestra arriba de la tabla: es una decision de dinero
que toma el servidor, tiene que verse.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Verificación final

**Files:** ninguno (solo se corre)

- [ ] **Step 1: Suite de Python completa**

```bash
python -m pytest tests/ -q
```

Línea base antes de esta rama: **1387 passed, 37 skipped, 0 failed**. Esperado: 1387 + las
pruebas nuevas, 0 fallos.

- [ ] **Step 2: Suite de vitest y build**

```bash
cd web && npx vitest run
cd web && npm run build
```

Línea base: **353 passed / 50 archivos**.

- [ ] **Step 3: Smoke en navegador**

Este repo tiene un antecedente: se mergeó un cambio de UI con 145 tests verdes y el modal
**se cerraba solo en el navegador**. La tabla nueva tiene 7 columnas (una más que la de
Actualizar, que ya se veía apretada) y casillas, que jsdom no renderiza de verdad.

Levantar la web y hacer una importación real:

```bash
SUPABASE_URL=https://hfjljzhgignngzooiwvl.supabase.co APU_ADMIN_EMAILS=$TU_CORREO python run_web.py
```

`APU_ADMIN_EMAILS` es el correo con el que se entra a la app: sin él, el token valida pero
no hay rol y todo `/api` responde 403. `SUPABASE_URL` sale de `web/.env.local`
(`VITE_SUPABASE_URL`) y solo se usa para validar el JWT contra el JWKS público — no es un
secreto y no da acceso de escritura a nada.

**Antes de correrlo, verificar que `DATABASE_URL` NO esté puesta** (`printenv DATABASE_URL`
y también en el entorno de Usuario y Máquina de Windows): con ella, la app escribe en la
Supabase de producción. Y **respaldar `data/precios.db`** antes de aplicar nada.

Qué mirar: que la tabla de 7 columnas se lea con nombres largos reales; que las casillas
premarcadas se vean; que el conteo del botón suba y baje al marcar; que el diálogo no se
cierre solo; y que después de aplicar, el insumo forzado tenga el precio nuevo y el nombre
viejo.

- [ ] **Step 4: Reportar**

Reportar los conteos reales de las tres verificaciones y lo que se vio en el navegador. Si
algo falla, arreglar antes de dar la tarea por terminada.

---

## Lo que este plan NO hace

- **No toca los conflictos por nombre.** Siguen listándose con su motivo, sin casilla.
- **No corrige nombres.** El nombre del catálogo no se toca nunca: el typo puede estar de
  los dos lados.
- **No hay "forzar todo"**, ni un selector para elegir un candidato distinto al mejor.
- **No cambia el candado.** Una fila forzada sobre un precio interno con importación
  pública sigue protegida — forzar es identidad, no permiso.
