> Espejo automático — no editar aquí. Fuente: `docs/superpowers/plans/2026-09-11-ruta-idu-formulario-1.md`

# Ruta IDU — Formulario 1 · Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que el usuario pueda elegir la entidad de origen de una licitación, subir el Formulario 1 de Presupuesto Oficial del IDU tal como lo publica la entidad, confirmar la estructura detectada (capítulos y actividades) antes de crear la corrida, y ver el contractual y el costo interno agrupados por capítulo hasta el cuadro de Excel.

**Architecture:** El parser de capítulos ya existe (`dominio/presupuesto.py`) y ya da 14 capítulos / 1939 actividades sobre el archivo real. Este plan le agrega alrededor: detección de hoja y de encabezado, mapeo de columnas por nombre, validaciones, conciliación contra el Excel, un registro `entidad → lector` sin condicionales dispersos, una previsualización que **no persiste nada** (el navegador se queda con el archivo y lo reenvía al aprobar), una sola columna `origen_json` en `corrida`, y una única función de dominio que calcula el resumen por capítulo para la API, la web y el Excel. No toca el matcher, no toca el motor de precios y no mete IA en ninguna parte de la lectura.

**Tech Stack:** Python 3.11+ · openpyxl · FastAPI · SQLite + PostgreSQL (psycopg) · pytest · React 18 + TypeScript + Vite · vitest + Testing Library

**Especificación:** `docs/superpowers/specs/2026-09-11-ruta-idu-formulario-1-design.md`

**Rama:** `ruta-idu-formulario-1` (ya creada; el diseño está en el commit `630a637`)

---

## Antes de empezar

```bash
cd /c/Users/luis.fajardo/Downloads/intento_plan
git branch --show-current     # debe decir: ruta-idu-formulario-1
python -m pytest tests/ -q    # debe estar verde ANTES de tocar nada
```

Para los tests de regresión contra el archivo real (opcionales, se saltan si falta):

```bash
export APU_IDU_F1_XLSX="/c/Users/luis.fajardo/Downloads/Formulario 1 Formulario de Presupuesto Oficial (version 1).xlsx"
```

**Reglas que no se negocian** (vienen de `CLAUDE.md`):

- La IA nunca recibe dinero. Todo campo monetario nuevo entra a `privacy._FORBIDDEN_KEYS`.
- Español en nombres de dominio, comentarios y mensajes de usuario.
- Toda la persistencia pasa por `apu_tool/datos/`. Nada de SQL crudo fuera de ahí.
- No sacar una corrida de `estado='armando'` con un `set_estado` pelado.
- `python -m pytest tests/ -q` verde al cerrar cada tarea. Commit por tarea.

---

## Estructura de archivos

| Archivo | Responsabilidad | Estado |
|---|---|---|
| `apu_tool/dominio/presupuesto.py` | Parser IDU: detección, clasificación, normalización, conciliación | Modificar (134 → ~390 líneas) |
| `apu_tool/dominio/entrada.py` | Registro `entidad → lector`. Único punto de despacho | **Crear** (~60 líneas) |
| `apu_tool/nucleo/models.py` | `EntidadOrigen`, 5 campos de `LicitacionItem`, `CorridaMeta.origen` | Modificar |
| `apu_tool/dominio/privacy.py` | Claves monetarias nuevas + capítulo hacia la IA | Modificar |
| `apu_tool/dominio/report_categorizado.py` | `resumen_por_capitulo()`: fuente única del cálculo por capítulo | Modificar |
| `apu_tool/dominio/report.py` | Hoja `RESUMEN POR CAPÍTULO` + columnas sin AIU | Modificar |
| `db/corridas.sql` · `apu_tool/datos/corridas_db.py` | `origen_json` en SQLite | Modificar |
| `db/pg/corridas.sql` · `apu_tool/datos/pg/corridas_pg.py` | `origen_json` en Postgres | Modificar |
| `apu_tool/datos/repositorio.py` | `set_origen` / `get_origen` en el `Protocol` | Modificar |
| `apu_tool/servicio/corridas.py` | `previsualizar()`, `origen` al crear, `capitulos` en la vista | Modificar |
| `apu_tool/servicio/rutas.py` | `POST /corridas/previsualizar`, `entidad` + `confirmada` | Modificar |
| `web/src/components/corrida/PreviaIdu.tsx` | Panel de previsualización y confirmación | **Crear** (~210 líneas) |
| `web/src/pages/CorridasInicio.tsx` | Selector de entidad + flujo de previa | Modificar |
| `web/src/components/corrida/TablaItems.tsx` | Columna `Capítulo` | Modificar |
| `web/src/pages/Corrida.tsx` | Panel `Resumen por capítulo` | Modificar |

---

# Fase 1 — Núcleo del parser (funciones puras)

## Task 1: Normalización de encabezados

**Files:**
- Modify: `apu_tool/dominio/presupuesto.py`
- Test: `tests/test_presupuesto_idu.py` (crear)

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_presupuesto_idu.py`:

```python
"""Parser del Formulario 1 de Presupuesto Oficial del IDU."""
from apu_tool.dominio.presupuesto import norm_encabezado


def test_norm_encabezado_quita_tildes_y_mayusculas():
    assert norm_encabezado("DESCRIPCION") == "descripcion"
    assert norm_encabezado("DESCRIPCIÓN") == "descripcion"
    assert norm_encabezado("ÍTEM DE PAGO") == "item de pago"
    assert norm_encabezado("ITEM DE PAGO") == "item de pago"


def test_norm_encabezado_colapsa_espacios_y_saltos():
    assert norm_encabezado("VALOR TOTAL                 ") == "valor total"
    assert norm_encabezado("VALOR UNITARIO SIN AIU\nCORREGIDO") == \
        "valor unitario sin aiu corregido"
    assert norm_encabezado("  CANTIDAD  ") == "cantidad"


def test_norm_encabezado_unifica_las_variantes_de_numero():
    # Nº (ordinal masculino), N° (grado), No. y No son el mismo encabezado.
    assert norm_encabezado("Nº") == "no"
    assert norm_encabezado("N°") == "no"
    assert norm_encabezado("No.") == "no"
    assert norm_encabezado("No") == "no"


def test_norm_encabezado_quita_puntos_y_parentesis():
    assert norm_encabezado("UND.") == "und"
    assert norm_encabezado("VALOR UNITARIO BASICO (SIN A.I.U)") == \
        "valor unitario basico sin aiu"
    assert norm_encabezado("VALOR UNITARIO (INCLUYE A.I.U)") == \
        "valor unitario incluye aiu"


def test_norm_encabezado_tolera_none_y_numeros():
    assert norm_encabezado(None) == ""
    assert norm_encabezado(3007) == "3007"
```

- [ ] **Step 2: Correr el test para ver que falla**

Run: `python -m pytest tests/test_presupuesto_idu.py -q`
Expected: FAIL con `ImportError: cannot import name 'norm_encabezado'`

- [ ] **Step 3: Implementar**

En `apu_tool/dominio/presupuesto.py`, agregar `import re` arriba y este bloque después de `_norm`:

```python
# Caracteres que se van del encabezado antes de comparar. Los ordinales (º, °, ª) se
# traducen a letra en vez de borrarse: así `Nº`, `N°` y `No.` colapsan al mismo "no",
# que es lo que permite mapear la columna por nombre y no por letra de Excel.
_FUERA_ENCABEZADO = str.maketrans(
    {"º": "o", "°": "o", "ª": "a", ".": "", "(": "", ")": "", ",": "", ":": "", ";": ""})


def norm_encabezado(s) -> str:
    """Encabezado comparable: sin tildes, minúsculas, sin puntuación, espacios colapsados.

    Es la pieza que hace que el parser NO dependa de las letras de columna. El archivo
    del IDU trae `ITEM`/`ÍTEM`, `Nº`/`N°`, `UND.`, `A.I.U` entre paréntesis y saltos de
    línea dentro del texto del encabezado; todo eso colapsa acá.
    """
    t = "".join(c for c in unicodedata.normalize("NFD", str(s if s is not None else ""))
                if unicodedata.category(c) != "Mn")
    t = t.lower().translate(_FUERA_ENCABEZADO)
    return re.sub(r"\s+", " ", t).strip()
```

- [ ] **Step 4: Correr el test para ver que pasa**

Run: `python -m pytest tests/test_presupuesto_idu.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add apu_tool/dominio/presupuesto.py tests/test_presupuesto_idu.py
git commit -m "feat(idu): normalizacion de encabezados del Formulario 1"
```

---

## Task 2: Normalización del ítem de pago

Esta es la tarea que resuelve los 100 ceros significativos que el `float` de Excel perdió
(`2.010` llega como `2.01`). El formato de celda (`'0.000'`) los recupera.

**Files:**
- Modify: `apu_tool/dominio/presupuesto.py`
- Test: `tests/test_presupuesto_idu.py`

- [ ] **Step 1: Escribir el test que falla**

Agregar al final de `tests/test_presupuesto_idu.py`:

```python
from apu_tool.dominio.presupuesto import (
    capitulo_de, es_item_entero, item_pago_texto, normalizar_item_pago,
)


def test_item_pago_texto_recupera_el_cero_perdido_por_el_float():
    # Excel guarda 2.010 como el float 2.01; el formato de celda dice cuántos
    # decimales tenía. Sin esto, el ítem de pago del pliego no se puede cruzar.
    assert item_pago_texto(2.01, "0.000") == "2.010"
    assert item_pago_texto(3.1, "0.000") == "3.100"
    assert item_pago_texto(2.001, "0.000") == "2.001"


def test_item_pago_texto_capitulo_es_entero():
    assert item_pago_texto(2, "0") == "2"
    assert item_pago_texto(14.0, "0") == "14"


def test_item_pago_texto_pasa_el_texto_tal_cual():
    assert item_pago_texto("1,001-N", "General") == "1,001-N"
    assert item_pago_texto("  2.014 N  ", "General") == "2.014 N"
    assert item_pago_texto(None, "0.000") == ""


def test_item_pago_texto_sin_formato_util_no_inventa_decimales():
    assert item_pago_texto(2.001, "General") == "2.001"
    assert item_pago_texto(7.0, "General") == "7"


def test_normalizar_item_pago_unifica_separadores_y_sufijo_de_turno():
    assert normalizar_item_pago("2.001") == "2.001"
    assert normalizar_item_pago("2,001") == "2.001"
    assert normalizar_item_pago("2.001 N") == "2.001 N"
    assert normalizar_item_pago("2.001-N") == "2.001 N"
    assert normalizar_item_pago("2,001-N") == "2.001 N"
    assert normalizar_item_pago('"2.001"') == "2.001"


def test_normalizar_item_pago_no_pierde_ceros():
    # La normalización es TEXTO: nunca pasa por float, así que el cero sobrevive.
    assert normalizar_item_pago("2.010") == "2.010"
    assert normalizar_item_pago("3.100") == "3.100"


def test_capitulo_de_saca_el_prefijo_entero():
    assert capitulo_de("2.014") == "2"
    assert capitulo_de("2.014 N") == "2"
    assert capitulo_de("2,014-N") == "2"
    assert capitulo_de("14.057-N") == "14"
    assert capitulo_de("2") == "2"
    assert capitulo_de("") == ""
    assert capitulo_de("SUBTOTAL") == ""


def test_es_item_entero_distingue_capitulo_de_actividad():
    assert es_item_entero("2") is True
    assert es_item_entero("14") is True
    assert es_item_entero("2.001") is False
    assert es_item_entero("2.001 N") is False
    assert es_item_entero("") is False
```

- [ ] **Step 2: Correr el test para ver que falla**

Run: `python -m pytest tests/test_presupuesto_idu.py -q`
Expected: FAIL con `ImportError: cannot import name 'capitulo_de'`

- [ ] **Step 3: Implementar**

En `apu_tool/dominio/presupuesto.py`, después de `norm_encabezado`:

```python
def _decimales_del_formato(formato: str) -> int:
    """Cuántos decimales declara un formato numérico de Excel: '0.000' -> 3, '0' -> 0."""
    f = str(formato or "")
    if "." not in f:
        return 0
    return sum(1 for c in f.split(".", 1)[1] if c in "0#")


def item_pago_texto(valor, formato: str = "") -> str:
    """El ítem de pago como TEXTO, recuperando los ceros que el float de Excel perdió.

    Excel guarda `2.010` como el float `2.01`: openpyxl entrega el número, no lo que se
    ve en pantalla. El formato de la celda (`'0.000'`) dice cuántos decimales tenía, así
    que el cero es recuperable y no hay que adivinarlo. En el archivo de referencia son
    100 de 1939 filas.

    Nunca se vuelve a convertir a float después de esto: el ítem de pago es texto.
    """
    if valor is None:
        return ""
    if isinstance(valor, bool):          # bool es int en Python; no es un ítem de pago
        return ""
    if isinstance(valor, float):
        if valor != valor:               # NaN
            return ""
        decimales = _decimales_del_formato(formato)
        if decimales:
            return f"{valor:.{decimales}f}"
        return str(int(valor)) if valor.is_integer() else f"{valor:g}"
    if isinstance(valor, int):
        return str(valor)
    return str(valor).strip()


def normalizar_item_pago(s) -> str:
    """Forma canónica del ítem de pago: coma decimal a punto, sufijo de turno separado.

    `2,001-N`, `2.001-N` y `2.001 N` son el MISMO ítem. Trabaja solo con texto, así que
    `2.010` conserva su cero (ver `item_pago_texto`).
    """
    t = str(s if s is not None else "").strip().strip('"').strip("'").strip()
    t = t.replace(",", ".")
    return re.sub(r"[\s\-_]+", " ", t).strip().upper()


def capitulo_de(s) -> str:
    """El capítulo al que pertenece un ítem de pago: '2.014 N' -> '2'. '' si no hay.

    Es el prefijo ENTERO hasta el primer separador. No se usa una división de punto
    flotante (`item/prefijo == 1`): con `2.010` el float ya perdió el cero antes de
    llegar acá, y la división arrastraría ese error a la estructura.
    """
    m = re.match(r"(\d+)", normalizar_item_pago(s))
    return str(int(m.group(1))) if m else ""


def es_item_entero(s) -> bool:
    """El ítem de pago representa SOLO el entero del capítulo, sin parte subordinada."""
    return normalizar_item_pago(s).isdigit()
```

- [ ] **Step 4: Correr el test para ver que pasa**

Run: `python -m pytest tests/test_presupuesto_idu.py -q`
Expected: PASS (13 passed)

- [ ] **Step 5: Commit**

```bash
git add apu_tool/dominio/presupuesto.py tests/test_presupuesto_idu.py
git commit -m "feat(idu): normalizacion del item de pago que recupera los ceros del float"
```

---

## Task 3: Clasificación de filas

**Files:**
- Modify: `apu_tool/dominio/presupuesto.py`
- Test: `tests/test_presupuesto_idu.py`

- [ ] **Step 1: Escribir el test que falla**

Agregar al final de `tests/test_presupuesto_idu.py`:

```python
from apu_tool.dominio.presupuesto import (
    ACTIVIDAD, CAPITULO, ENCABEZADO, IGNORADA, SUBTITULO, SUBTOTAL, TURNO,
    clasificar_fila,
)


def _clasificar(codigo="", item_pago="", descripcion="", cantidad=None,
                es_encabezado=False):
    return clasificar_fila(codigo=codigo, item_pago=item_pago,
                           descripcion=descripcion, cantidad=cantidad,
                           es_encabezado=es_encabezado)


def test_clasificar_capitulo():
    # Fila 13 del archivo real: Nº vacío, ítem de pago entero, descripción.
    assert _clasificar(item_pago="1", descripcion="PRELIMINARES") == CAPITULO
    assert _clasificar(item_pago="10", descripcion="RED DE ALCANTARILLADO") == CAPITULO


def test_clasificar_actividad():
    # Fila 16: código IDU + cantidad > 0.
    assert _clasificar(codigo="3007", item_pago="1.001",
                       descripcion="REPLANTEO GENERAL", cantidad=74234) == ACTIVIDAD
    # Nocturna: el código trae el sufijo N.
    assert _clasificar(codigo="3007 N", item_pago="1.001 N",
                       descripcion="REPLANTEO GENERAL", cantidad=24745) == ACTIVIDAD


def test_clasificar_turno_subtitulo_y_subtotal():
    assert _clasificar(descripcion="TURNO DIURNO") == TURNO
    assert _clasificar(descripcion="TURNO NOCTURNO") == TURNO
    assert _clasificar(descripcion="LOCALIZACIÓN Y REPLANTEO") == SUBTITULO
    assert _clasificar(descripcion="PAVIMENTO RÍGIDO") == SUBTITULO
    assert _clasificar(codigo="Subtotal ") == SUBTOTAL
    assert _clasificar(codigo="Subtotal") == SUBTOTAL


def test_clasificar_encabezado_repetido():
    # Fila 2201: el segundo encabezado NO puede contar como actividad.
    assert _clasificar(codigo="Nº", item_pago="ÍTEM DE PAGO",
                       descripcion="DESCRIPCIÓN", es_encabezado=True) == ENCABEZADO


def test_clasificar_resumen_notas_y_vacias():
    # Filas 2204+: texto largo en la columna Nº, sin descripción y sin cantidad.
    assert _clasificar(codigo="VALOR PARA OBRAS SIN REDES (INCLUYE A.I.U)") == IGNORADA
    assert _clasificar(codigo="TOTAL OBRAS LICITACIÓN ( A+B+C+D)") == IGNORADA
    assert _clasificar() == IGNORADA


def test_clasificar_no_cuenta_actividad_sin_cantidad_positiva():
    assert _clasificar(codigo="3007", item_pago="1.001", descripcion="X",
                       cantidad=0) == IGNORADA
    assert _clasificar(codigo="3007", item_pago="1.001", descripcion="X",
                       cantidad=None) == IGNORADA
    assert _clasificar(codigo="3007", item_pago="1.001", descripcion="X",
                       cantidad="n/a") == IGNORADA


def test_clasificar_capitulo_gana_sobre_subtitulo():
    # Con ítem entero manda CAPITULO aunque también tenga descripción.
    assert _clasificar(item_pago="2", descripcion="PAVIMENTOS") == CAPITULO
    # Sin ítem entero, la misma forma es un subtítulo.
    assert _clasificar(item_pago="", descripcion="PAVIMENTOS") == SUBTITULO
```

- [ ] **Step 2: Correr el test para ver que falla**

Run: `python -m pytest tests/test_presupuesto_idu.py -q`
Expected: FAIL con `ImportError: cannot import name 'ACTIVIDAD'`

- [ ] **Step 3: Implementar**

En `apu_tool/dominio/presupuesto.py`, agregar `from apu_tool.nucleo.texto import normalizar`
a los imports y este bloque después de `es_item_entero`:

```python
# Tipos de fila del Formulario 1. Vocabulario cerrado: lo consume `leer_formulario_idu`
# y los tests. Solo ACTIVIDAD produce un LicitacionItem; solo CAPITULO y TURNO mueven el
# estado del recorrido; SUBTOTAL se guarda para conciliar; el resto no existe aguas abajo.
ACTIVIDAD = "ACTIVIDAD"
CAPITULO = "CAPITULO"
TURNO = "TURNO"
SUBTITULO = "SUBTITULO"
SUBTOTAL = "SUBTOTAL"
ENCABEZADO = "ENCABEZADO"
IGNORADA = "IGNORADA"


def _cantidad_valida(v) -> bool:
    """La cantidad es un número positivo. `not (x > 0)` cierra el NaN de un solo golpe."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    return v > 0


def clasificar_fila(*, codigo: str, item_pago: str, descripcion: str,
                    cantidad, es_encabezado: bool = False) -> str:
    """Qué es esta fila del Formulario 1. Determinístico, sin IA y sin heurísticas.

    El ORDEN importa y es parte del contrato: la primera regla que aplica gana.
      1. encabezado repetido      -> ENCABEZADO   (la fila 2201 del archivo real)
      2. todo vacío               -> IGNORADA
      3. col Nº empieza "subtotal"-> SUBTOTAL
      4. Nº vacío + ítem entero   -> CAPITULO
      5. Nº vacío + "TURNO…"      -> TURNO
      6. Nº vacío + descripción   -> SUBTITULO
      7. cantidad > 0 + Nº        -> ACTIVIDAD
      8. resto                    -> IGNORADA    (resumen, notas, firmas, valores globales)
    """
    if es_encabezado:
        return ENCABEZADO
    cod = str(codigo or "").strip()
    desc = str(descripcion or "").strip()
    if not cod and not desc and not str(item_pago or "").strip() \
            and not _cantidad_valida(cantidad):
        return IGNORADA
    if cod and normalizar(cod).startswith("SUBTOTAL"):
        return SUBTOTAL
    if not cod and desc:
        if es_item_entero(item_pago):
            return CAPITULO
        if normalizar(desc).startswith("TURNO"):
            return TURNO
        return SUBTITULO
    if cod and _cantidad_valida(cantidad):
        return ACTIVIDAD
    return IGNORADA
```

- [ ] **Step 4: Correr el test para ver que pasa**

Run: `python -m pytest tests/test_presupuesto_idu.py -q`
Expected: PASS (20 passed)

- [ ] **Step 5: Correr la suite completa**

Run: `python -m pytest tests/ -q`
Expected: PASS — ningún test previo se rompe (solo se agregaron funciones).

- [ ] **Step 6: Commit**

```bash
git add apu_tool/dominio/presupuesto.py tests/test_presupuesto_idu.py
git commit -m "feat(idu): clasificacion deterministica de filas del Formulario 1"
```

---

## Task 4: Detección de hoja y de la fila de encabezado

**Files:**
- Modify: `apu_tool/dominio/presupuesto.py`
- Test: `tests/test_presupuesto_idu.py`

- [ ] **Step 1: Escribir el test que falla**

Agregar al final de `tests/test_presupuesto_idu.py`:

```python
import openpyxl
import pytest

from apu_tool.dominio.presupuesto import (
    COLUMNAS_OBLIGATORIAS, elegir_hoja, encontrar_encabezado,
)


class _LibroFalso:
    """Stand-in de un Workbook: `elegir_hoja` solo necesita `sheetnames`."""
    def __init__(self, nombres):
        self.sheetnames = list(nombres)


def test_elegir_hoja_encuentra_propuesta_economica():
    wb = _LibroFalso(["PROPUESTA ECONÓMICA", "INDICAR CÓDIGO DEL ITEM DE PAGO"])
    hoja, ambiguas = elegir_hoja(wb, None)
    assert hoja == "PROPUESTA ECONÓMICA"
    assert ambiguas == []


def test_elegir_hoja_avisa_cuando_hay_varias_candidatas():
    # El archivo real trae dos hojas idénticas: se usa la primera y se avisa.
    wb = _LibroFalso(["PROPUESTA ECONÓMICA", "PROPUESTA ECONÓMICA (2)", "OTRA"])
    hoja, ambiguas = elegir_hoja(wb, None)
    assert hoja == "PROPUESTA ECONÓMICA"
    assert ambiguas == ["PROPUESTA ECONÓMICA (2)"]


def test_elegir_hoja_acepta_las_variantes_conocidas():
    assert elegir_hoja(_LibroFalso(["FOR 1-PPTO OFICIAL"]), None)[0] == "FOR 1-PPTO OFICIAL"
    assert elegir_hoja(_LibroFalso(["Presupuesto Oficial"]), None)[0] == "Presupuesto Oficial"


def test_elegir_hoja_respeta_la_hoja_explicita():
    wb = _LibroFalso(["PROPUESTA ECONÓMICA", "HOJA RARA"])
    assert elegir_hoja(wb, "HOJA RARA")[0] == "HOJA RARA"


def test_elegir_hoja_sin_candidata_devuelve_none():
    hoja, ambiguas = elegir_hoja(_LibroFalso(["Hoja1", "Datos"]), None)
    assert hoja is None
    assert ambiguas == []


def test_elegir_hoja_explicita_inexistente_devuelve_none():
    assert elegir_hoja(_LibroFalso(["PROPUESTA ECONÓMICA"]), "NO EXISTE")[0] is None


_ENCABEZADO_REAL = [
    None, None, "Nº", "ITEM DE PAGO", "ESPECIFICACIONES ", None, "DESCRIPCION",
    "UND.", "CANTIDAD", "VALOR UNITARIO BASICO (SIN A.I.U)",
    "VALOR UNITARIO (INCLUYE A.I.U)", "VALOR TOTAL                    ",
    None, None, "VALOR UNITARIO SIN AIU OFERTADO",
]


def test_encontrar_encabezado_mapea_las_columnas_por_nombre():
    filas = [[None] * 15, [None] * 15, _ENCABEZADO_REAL, [None] * 15]
    idx, mapeo, faltan = encontrar_encabezado(filas)
    assert idx == 2                       # 0-based; es la fila 3 del Excel
    assert faltan == []
    assert mapeo["codigo"] == 2
    assert mapeo["item_pago"] == 3
    assert mapeo["descripcion"] == 6
    assert mapeo["unidad"] == 7
    assert mapeo["cantidad"] == 8
    assert mapeo["unitario_sin_aiu"] == 9
    assert mapeo["unitario_con_aiu"] == 10
    assert mapeo["total_excel"] == 11


def test_encontrar_encabezado_ignora_las_columnas_de_oferta():
    # `VALOR UNITARIO SIN AIU OFERTADO` no debe robarle el mapeo a la col J.
    filas = [_ENCABEZADO_REAL]
    _idx, mapeo, _faltan = encontrar_encabezado(filas)
    assert mapeo["unitario_sin_aiu"] == 9
    assert 14 not in mapeo.values()


def test_encontrar_encabezado_reporta_las_columnas_que_faltan():
    fila = [None, None, "Nº", "ITEM DE PAGO", None, None, "DESCRIPCION", None, None]
    idx, _mapeo, faltan = encontrar_encabezado([fila])
    assert idx == 0
    assert "cantidad" in faltan
    assert "unitario_con_aiu" in faltan


def test_encontrar_encabezado_sin_encabezado_devuelve_menos_uno():
    idx, mapeo, faltan = encontrar_encabezado([[None] * 8, ["a", "b", "c"]])
    assert idx == -1
    assert mapeo == {}
    assert faltan == sorted(COLUMNAS_OBLIGATORIAS)
```

- [ ] **Step 2: Correr el test para ver que falla**

Run: `python -m pytest tests/test_presupuesto_idu.py -q`
Expected: FAIL con `ImportError: cannot import name 'elegir_hoja'`

- [ ] **Step 3: Implementar**

En `apu_tool/dominio/presupuesto.py`, después de `clasificar_fila`:

```python
# Encabezado normalizado -> campo lógico. Se compara por IGUALDAD sobre el nombre
# normalizado, no por "contiene": `VALOR UNITARIO SIN AIU OFERTADO` y `VALOR UNITARIO
# BASICO SIN AIU` comparten casi todas las palabras, y un match por subcadena leería la
# oferta del proponente como si fuera el presupuesto oficial.
_ENCABEZADOS: dict[str, tuple[str, ...]] = {
    "codigo":           ("no", "no de apu", "codigo"),
    "item_pago":        ("item de pago",),
    "descripcion":      ("descripcion",),
    "unidad":           ("und", "unidad"),
    "cantidad":         ("cantidad",),
    "unitario_sin_aiu": ("valor unitario basico sin aiu",),
    "unitario_con_aiu": ("valor unitario incluye aiu",),
    "total_excel":      ("valor total",),
}

# Sin una de estas no se puede leer el archivo: es error bloqueante, no advertencia.
# `total_excel` NO está: solo sirve para conciliar, y su ausencia no impide importar.
COLUMNAS_OBLIGATORIAS = ("codigo", "item_pago", "descripcion", "unidad",
                         "cantidad", "unitario_sin_aiu", "unitario_con_aiu")

# Fragmentos que identifican la hoja del presupuesto, en orden de preferencia.
_HOJAS_CANDIDATAS = ("propuesta economica", "ppto oficial", "presupuesto oficial")

# Cuántas filas se miran buscando el encabezado. En el archivo real está en la 10;
# 40 deja margen de sobra para un membrete más largo sin recorrer el libro entero.
MAX_FILAS_ENCABEZADO = 40


def elegir_hoja(wb, hoja: Optional[str]) -> tuple[Optional[str], list[str]]:
    """(hoja elegida, otras candidatas). `None` si no hay ninguna compatible.

    Una `hoja` explícita gana sobre la detección, pero solo si existe: pedir una hoja
    que no está es un error, no una razón para adivinar otra.

    Cuando hay varias candidatas se toma la primera y las demás se devuelven para
    ADVERTIR cuál se usó. El archivo de referencia trae `PROPUESTA ECONÓMICA` y
    `PROPUESTA ECONÓMICA (2)`, idénticas valor a valor; elegir en silencio estaría bien
    hasta el día en que no sean idénticas.
    """
    if hoja:
        return (hoja if hoja in wb.sheetnames else None), []
    candidatas = [n for n in wb.sheetnames
                  if any(f in norm_encabezado(n) for f in _HOJAS_CANDIDATAS)]
    if not candidatas:
        return None, []
    return candidatas[0], candidatas[1:]


def _es_fila_encabezado(fila: list, mapeo: dict[str, int]) -> bool:
    """La fila repite el encabezado ya mapeado (≥ 2 columnas coinciden).

    Dos y no una: `DESCRIPCION` suelta aparece como texto de alguna celda, pero que
    coincidan dos de las columnas mapeadas a la vez solo pasa en un encabezado real.
    """
    aciertos = sum(1 for campo, idx in mapeo.items()
                   if norm_encabezado(_get(fila, idx)) in _ENCABEZADOS[campo])
    return aciertos >= 2


def encontrar_encabezado(filas: list[list]) -> tuple[int, dict[str, int], list[str]]:
    """(índice 0-based de la fila de encabezado, mapeo campo->columna, obligatorias que faltan).

    Devuelve `-1` y un mapeo vacío si no encontró encabezado en las primeras
    `MAX_FILAS_ENCABEZADO` filas. Nunca levanta: el llamador decide si eso es un error
    bloqueante (lo es) y con qué mensaje.
    """
    for i, fila in enumerate(filas[:MAX_FILAS_ENCABEZADO]):
        mapeo: dict[str, int] = {}
        for idx, celda in enumerate(fila):
            nombre = norm_encabezado(celda)
            if not nombre:
                continue
            for campo, variantes in _ENCABEZADOS.items():
                if campo not in mapeo and nombre in variantes:
                    mapeo[campo] = idx
                    break
        # Una fila es el encabezado si trae la descripción y algo más: así una fila de
        # datos con un "UND" suelto no se confunde con el encabezado.
        if "descripcion" in mapeo and len(mapeo) >= 3:
            faltan = sorted(c for c in COLUMNAS_OBLIGATORIAS if c not in mapeo)
            return i, mapeo, faltan
    return -1, {}, sorted(COLUMNAS_OBLIGATORIAS)
```

Agregar `from typing import Optional` a los imports si no está.

- [ ] **Step 4: Correr el test para ver que pasa**

Run: `python -m pytest tests/test_presupuesto_idu.py -q`
Expected: PASS (30 passed)

- [ ] **Step 5: Commit**

```bash
git add apu_tool/dominio/presupuesto.py tests/test_presupuesto_idu.py
git commit -m "feat(idu): deteccion de hoja y mapeo de columnas por nombre"
```

---

# Fase 2 — Lectura completa y conciliación

## Task 5: Fixture del Formulario 1 en miniatura

Un Excel de ~30 filas que reproduce **todos** los casos del archivo real. Es el que corre siempre en CI; el archivo de 4,5 MB no se versiona.

**Files:**
- Create: `tests/fixtures_idu.py`
- Test: `tests/test_presupuesto_idu.py`

- [ ] **Step 1: Escribir el fixture**

Crear `tests/fixtures_idu.py`:

```python
"""Formulario 1 del IDU en miniatura, con todos los casos del archivo real.

Reproduce: membrete, encabezado en una fila que no es la 1, dos capítulos, turno diurno
y nocturno, subtítulos, filas Subtotal, un encabezado repetido a mitad, filas de resumen
global, un ítem de pago con cero significativo (guardado como float con formato 0.000,
igual que Excel) y otro con coma y sufijo -N.

Los valores están elegidos para que round(cantidad * con_aiu) dé exacto, igual que en el
archivo real (1939 de 1939 filas).
"""
import openpyxl

# Estructura del archivo real (columnas 0-based):
# 2=Nº  3=ITEM DE PAGO  6=DESCRIPCION  7=UND.  8=CANTIDAD
# 9=VALOR UNITARIO BASICO (SIN A.I.U)  10=VALOR UNITARIO (INCLUYE A.I.U)  11=VALOR TOTAL
COL_CODIGO, COL_ITEM, COL_DESC, COL_UND, COL_CANT = 2, 3, 6, 7, 8
COL_SIN_AIU, COL_CON_AIU, COL_TOTAL = 9, 10, 11

ENCABEZADO = {
    COL_CODIGO: "Nº", COL_ITEM: "ITEM DE PAGO", 4: "ESPECIFICACIONES ",
    COL_DESC: "DESCRIPCION", COL_UND: "UND.", COL_CANT: "CANTIDAD",
    COL_SIN_AIU: "VALOR UNITARIO BASICO (SIN A.I.U)",
    COL_CON_AIU: "VALOR UNITARIO (INCLUYE A.I.U)",
    COL_TOTAL: "VALOR TOTAL                    ",
    14: "VALOR UNITARIO SIN AIU OFERTADO",
}

# (código, ítem de pago, formato del ítem, descripción, und, cantidad, sin AIU, con AIU)
ACTIVIDADES_CAP_1 = [
    (3007, 1.001, "0.000", "REPLANTEO GENERAL", "M2", 100, 1056, 1351),
    ("3007 N", "1,001-N", "General", "REPLANTEO GENERAL", "M2", 40, 1179, 1508),
]
ACTIVIDADES_CAP_2 = [
    (3710, 2.001, "0.000", "EXCAVACIÓN MECÁNICA", "M3", 30, 5963, 7628),
    # El cero significativo: Excel guarda 2.010 como el float 2.01 con formato 0.000.
    (3866, 2.01, "0.000", "RIEGO DE LIGA", "M2", 50, 3815, 4880),
    ("4200 N", "2,011-N", "General", "MEZCLA ASFÁLTICA MD20", "M3", 7, 1188814, 1520731),
]


def total_esperado(cant, con_aiu) -> int:
    return round(cant * con_aiu)


def escribir_formulario(path, *, hoja="PROPUESTA ECONÓMICA", con_hoja_gemela=False,
                        sin_columna_cantidad=False):
    """Escribe el Formulario 1 en miniatura y devuelve la ruta.

    `con_hoja_gemela` agrega una segunda hoja candidata (el caso real de las dos
    PROPUESTA ECONÓMICA). `sin_columna_cantidad` borra un encabezado obligatorio para
    probar el error bloqueante.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = hoja
    _volcar(ws, sin_columna_cantidad=sin_columna_cantidad)
    if con_hoja_gemela:
        _volcar(wb.create_sheet(f"{hoja} (2)"), sin_columna_cantidad=sin_columna_cantidad)
    wb.create_sheet("INDICAR CÓDIGO DEL ITEM DE PAGO")
    wb.save(path)
    return path


def _volcar(ws, *, sin_columna_cantidad=False):
    ancho = 16

    def fila(cols=None, formatos=None):
        ws.append([(cols or {}).get(i) for i in range(ancho)])
        for idx, fmt in (formatos or {}).items():
            ws.cell(row=ws.max_row, column=idx + 1).number_format = fmt

    fila()                                            # 1: vacía
    fila({5: "FORMULARIO 1"})                         # 2: membrete
    fila({5: "PRESUPUESTO OFICIAL ESTIMADO"})         # 3: membrete
    fila()                                            # 4
    enc = dict(ENCABEZADO)
    if sin_columna_cantidad:
        enc.pop(COL_CANT)
    fila(enc)                                         # 5: ENCABEZADO
    fila({4: "GENERAL", 5: "PARTICULAR"})             # 6: subencabezado, se ignora
    _capitulo(fila, 1, "PRELIMINARES", ACTIVIDADES_CAP_1, "LOCALIZACIÓN Y REPLANTEO")
    _capitulo(fila, 2, "PAVIMENTOS", ACTIVIDADES_CAP_2, "PAVIMENTO FLEXIBLE")
    fila()
    fila(dict(ENCABEZADO))                            # encabezado REPETIDO a mitad
    fila({4: "GENERAL", 5: "PARTICULAR"})
    fila()
    fila({COL_CODIGO: "VALOR PARA OBRAS SIN REDES (INCLUYE A.I.U)", COL_TOTAL: 999999})
    fila({COL_CODIGO: "TOTAL OBRAS LICITACIÓN ( A+B+C+D)", COL_TOTAL: 999999})
    fila()
    fila({0: "Total general"})                        # cola del archivo real


def _capitulo(fila, numero, nombre, actividades, subtitulo):
    fila({COL_ITEM: numero, COL_DESC: nombre}, {COL_ITEM: "0"})
    subtotal = 0
    for i, (cod, item, fmt, desc, und, cant, sin_aiu, con_aiu) in enumerate(actividades):
        if i == 0:
            fila({COL_DESC: "TURNO DIURNO"})
            fila({COL_DESC: subtitulo})
        elif i == 1:
            fila({COL_DESC: "TURNO NOCTURNO"})
            fila({COL_DESC: subtitulo})
        total = total_esperado(cant, con_aiu)
        subtotal += total
        fila({COL_CODIGO: cod, COL_ITEM: item, COL_DESC: desc, COL_UND: und,
              COL_CANT: cant, COL_SIN_AIU: sin_aiu, COL_CON_AIU: con_aiu,
              COL_TOTAL: total},
             {COL_ITEM: fmt})
    fila({COL_CODIGO: "Subtotal ", COL_TOTAL: subtotal})
```

- [ ] **Step 2: Escribir el test que verifica el fixture**

Agregar a `tests/test_presupuesto_idu.py`:

```python
from tests.fixtures_idu import ACTIVIDADES_CAP_1, ACTIVIDADES_CAP_2, escribir_formulario


def test_fixture_conserva_el_formato_del_item_de_pago(tmp_path):
    # Si el fixture no reprodujera el float CON formato, el test del cero significativo
    # estaría probando algo que el archivo real no hace.
    p = escribir_formulario(tmp_path / "f1.xlsx")
    wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
    ws = wb["PROPUESTA ECONÓMICA"]
    formatos = {c.value: c.number_format
                for fila in ws.iter_rows(min_col=4, max_col=4) for c in fila
                if isinstance(c.value, float)}
    wb.close()
    assert formatos[2.01] == "0.000"
```

- [ ] **Step 3: Correr el test**

Run: `python -m pytest tests/test_presupuesto_idu.py -q`
Expected: PASS (31 passed)

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures_idu.py tests/test_presupuesto_idu.py
git commit -m "test(idu): fixture del Formulario 1 en miniatura"
```

---

## Task 6: Campos nuevos de `LicitacionItem`

Va **antes** del lector porque el lector los produce. Es la tarea 3 del plan original de
fases; se adelanta acá para que la Task 7 pueda correr en verde.

**Files:**
- Modify: `apu_tool/nucleo/models.py:140-150`
- Test: `tests/test_presupuesto.py`

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_presupuesto.py`:

```python
from apu_tool.nucleo.models import AssembledApu, MatchStatus


def test_licitacion_item_campos_de_capitulo_son_opcionales():
    # Una corrida vieja se rehidrata sin estos campos: tienen que tener default.
    plano = LicitacionItem(item="1", descripcion="X", unidad="M2", cantidad=1.0,
                           precio_contractual=100.0, shift="DIURNO")
    assert plano.capitulo_codigo == ""
    assert plano.capitulo_nombre == ""
    assert plano.item_pago_original == ""
    assert plano.fila_origen == 0
    assert plano.precio_contractual_sin_aiu == 0.0


def test_contractual_total_sin_aiu_usa_el_redondeo_del_repo():
    item = LicitacionItem(item="2.001", descripcion="X", unidad="M3", cantidad=30.0,
                          precio_contractual=7628.0, shift="DIURNO",
                          precio_contractual_sin_aiu=5963.0)
    ens = AssembledApu(item=item, apu_codigo="A", apu_nombre="A", unidad="M3",
                       shift="DIURNO", componentes=[], costo_unitario=0.0,
                       status=MatchStatus.NEW, confianza=0.0)
    assert ens.contractual_total == 228840        # 30 * 7628, con AIU
    assert ens.contractual_total_sin_aiu == 178890  # 30 * 5963, sin AIU
```

- [ ] **Step 2: Correr el test para ver que falla**

Run: `python -m pytest tests/test_presupuesto.py -q`
Expected: FAIL con `TypeError: __init__() got an unexpected keyword argument 'precio_contractual_sin_aiu'`

- [ ] **Step 3: Implementar**

En `apu_tool/nucleo/models.py`, dentro de `LicitacionItem`, después de `codigo_sugerido`:

```python
    # --- capítulo del presupuesto (ruta IDU) ---------------------------------
    # Todos con default: es lo que hace que una corrida encolada ANTES de este deploy
    # se rehidrate sin explotar (`plan_de` hace LicitacionItem(**d) sobre plan_json).
    # `categoria` se conserva y se DERIVA de estos dos en el lector, para que
    # report_categorizado.agrupar_por_capitulo y sus tests sigan funcionando igual.
    capitulo_codigo: str = ""          # "2" — la referencia estable, no el nombre
    capitulo_nombre: str = ""          # "PAVIMENTOS"
    item_pago_original: str = ""       # "2,001-N" tal cual venía, para auditoría
    fila_origen: int = 0               # fila del Excel de la que salió, 1-based
    # Valor unitario SIN AIU. Es DINERO: está en privacy._FORBIDDEN_KEYS y NO viaja en
    # licitacion_item_to_dict. `precio_contractual` sigue siendo el que manda (con AIU).
    precio_contractual_sin_aiu: float = 0.0
```

Y dentro de `AssembledApu`, junto a `contractual_total`:

```python
    @property
    def contractual_total_sin_aiu(self) -> int:
        """El contractual del ítem sin AIU. Misma regla de redondeo que su gemelo."""
        return mul_redondeado(self.item.precio_contractual_sin_aiu, self.item.cantidad)
```

- [ ] **Step 4: Correr el test**

Run: `python -m pytest tests/test_presupuesto.py -q`
Expected: PASS

- [ ] **Step 5: Correr la suite completa**

Run: `python -m pytest tests/ -q`
Expected: PASS. Los campos tienen default, así que ningún constructor existente se rompe.

- [ ] **Step 6: Commit**

```bash
git add apu_tool/nucleo/models.py tests/test_presupuesto.py
git commit -m "feat(idu): capitulo y contractual sin AIU en LicitacionItem"
```

---

## Task 7: `leer_formulario_idu` — el lector completo

**Files:**
- Modify: `apu_tool/dominio/presupuesto.py`
- Test: `tests/test_presupuesto_idu.py`

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_presupuesto_idu.py`:

```python
from apu_tool.dominio.presupuesto import leer_formulario_idu


def test_lee_hoja_encabezado_y_estructura(tmp_path):
    lec = leer_formulario_idu(escribir_formulario(tmp_path / "f1.xlsx"))
    assert lec.errores == []
    assert lec.hoja == "PROPUESTA ECONÓMICA"
    assert lec.fila_encabezado == 5               # 1-based, como lo ve el usuario
    assert lec.parser_version == "idu-f1/1"
    assert [c.codigo for c in lec.capitulos] == ["1", "2"]
    assert [c.nombre for c in lec.capitulos] == ["PRELIMINARES", "PAVIMENTOS"]
    assert [c.orden for c in lec.capitulos] == [1, 2]
    assert len(lec.items) == len(ACTIVIDADES_CAP_1) + len(ACTIVIDADES_CAP_2)


def test_no_cuenta_turnos_subtitulos_subtotales_ni_encabezados(tmp_path):
    lec = leer_formulario_idu(escribir_formulario(tmp_path / "f1.xlsx"))
    descripciones = {i.descripcion for i in lec.items}
    for basura in ("TURNO DIURNO", "TURNO NOCTURNO", "PRELIMINARES", "PAVIMENTOS",
                   "LOCALIZACIÓN Y REPLANTEO", "PAVIMENTO FLEXIBLE", "DESCRIPCION",
                   "VALOR PARA OBRAS SIN REDES (INCLUYE A.I.U)"):
        assert basura not in descripciones
    assert lec.filas_ignoradas > 0
    assert any(a.tipo == "encabezado_repetido" for a in lec.advertencias)


def test_cada_actividad_hereda_capitulo_y_turno(tmp_path):
    lec = leer_formulario_idu(escribir_formulario(tmp_path / "f1.xlsx"))
    por_item = {i.item_pago_original: i for i in lec.items}
    diurna = por_item["1.001"]
    assert diurna.capitulo_codigo == "1"
    assert diurna.capitulo_nombre == "PRELIMINARES"
    assert diurna.categoria == "1 · PRELIMINARES"     # derivado, para report_categorizado
    assert diurna.shift == "DIURNO"
    assert diurna.codigo_sugerido == "3007"
    nocturna = por_item["1,001-N"]
    assert nocturna.shift == "NOCTURNO"
    assert nocturna.codigo_sugerido == "3007 N"
    assert nocturna.capitulo_codigo == "1"


def test_preserva_el_item_original_y_recupera_el_cero(tmp_path):
    lec = leer_formulario_idu(escribir_formulario(tmp_path / "f1.xlsx"))
    originales = [i.item_pago_original for i in lec.items]
    assert "2.010" in originales          # el float 2.01 con formato 0.000
    assert "1,001-N" in originales        # el texto, tal cual venía
    assert "2,011-N" in originales


def test_las_dos_columnas_de_precio(tmp_path):
    lec = leer_formulario_idu(escribir_formulario(tmp_path / "f1.xlsx"))
    replanteo = next(i for i in lec.items if i.item_pago_original == "1.001")
    assert replanteo.cantidad == 100
    assert replanteo.precio_contractual == 1351             # col K, CON AIU
    assert replanteo.precio_contractual_sin_aiu == 1056      # col J, SIN AIU
    assert replanteo.fila_origen > 0


def test_hoja_gemela_se_avisa_y_no_duplica_actividades(tmp_path):
    lec = leer_formulario_idu(
        escribir_formulario(tmp_path / "f1.xlsx", con_hoja_gemela=True))
    assert lec.hoja == "PROPUESTA ECONÓMICA"
    assert len(lec.items) == 5
    assert any(a.tipo == "hoja_ambigua" for a in lec.advertencias)


def test_sin_hoja_compatible_es_error_bloqueante(tmp_path):
    lec = leer_formulario_idu(escribir_formulario(tmp_path / "f1.xlsx", hoja="DATOS"))
    assert lec.items == []
    assert any("sin_hoja" in e for e in lec.errores)


def test_falta_columna_obligatoria_es_error_bloqueante(tmp_path):
    lec = leer_formulario_idu(
        escribir_formulario(tmp_path / "f1.xlsx", sin_columna_cantidad=True))
    assert any("falta_columna" in e and "cantidad" in e for e in lec.errores)
    assert lec.items == []


def test_archivo_que_no_es_excel_es_error_bloqueante(tmp_path):
    malo = tmp_path / "no-es.xlsx"
    malo.write_bytes(b"esto no es un zip")
    lec = leer_formulario_idu(malo)
    assert any("archivo_invalido" in e for e in lec.errores)
    assert lec.items == []


def test_read_presupuesto_sigue_funcionando(tmp_path):
    # El envoltorio viejo (CLI y GUI) no cambia de firma ni de comportamiento.
    from apu_tool.dominio.presupuesto import read_presupuesto
    items = read_presupuesto(escribir_formulario(tmp_path / "f1.xlsx"),
                             hoja="PROPUESTA ECONÓMICA")
    assert len(items) == 5
    assert items[0].categoria == "1 · PRELIMINARES"
```

- [ ] **Step 2: Correr el test para ver que falla**

Run: `python -m pytest tests/test_presupuesto_idu.py -q`
Expected: FAIL con `ImportError: cannot import name 'leer_formulario_idu'`

- [ ] **Step 3: Implementar los tipos de retorno**

En `apu_tool/dominio/presupuesto.py`, agregar a los imports:

```python
import zipfile
from dataclasses import dataclass, field

from openpyxl.utils.exceptions import InvalidFileException

from apu_tool.nucleo.redondeo import mul_redondeado
from apu_tool.nucleo.texto import normalizar
```

Y después de `encontrar_encabezado`:

```python
PARSER_VERSION = "idu-f1/1"


@dataclass(frozen=True)
class Capitulo:
    """Un capítulo del presupuesto. `codigo` es la referencia estable, no el nombre."""
    codigo: str          # "2"
    nombre: str          # "PAVIMENTOS"
    orden: int           # posición de aparición, 1-based
    fila_origen: int     # fila del Excel, 1-based

    def to_dict(self) -> dict:
        return {"codigo": self.codigo, "nombre": self.nombre,
                "orden": self.orden, "fila_origen": self.fila_origen}


@dataclass(frozen=True)
class Advertencia:
    """Algo que el usuario tiene que mirar, pero que no impide importar."""
    tipo: str            # de TIPOS_ADVERTENCIA
    fila: int            # 0 = no aplica a una fila puntual
    detalle: str

    def to_dict(self) -> dict:
        return {"tipo": self.tipo, "fila": self.fila, "detalle": self.detalle}


TIPOS_ADVERTENCIA = (
    "hoja_ambigua", "actividad_sin_capitulo", "capitulo_sin_actividades",
    "capitulo_ambiguo", "total_fila_no_concilia", "subtotal_no_concilia",
    "codigo_apu_vacio", "unidad_vacia", "encabezado_repetido",
    "item_pago_formato_inusual", "formula_sin_valor", "fila_relevante_ignorada",
    "oferta_diligenciada",
)


@dataclass(frozen=True)
class LecturaPresupuesto:
    """El resultado de leer un presupuesto. NUNCA levanta: los problemas viajan adentro.

    `errores` no vacío = no se puede crear la corrida. `advertencias` = se puede, pero el
    usuario tiene que confirmar explícitamente. Esa distinción es la que sostiene la
    pantalla de previsualización, así que vive en el dominio y no en el servicio: el
    mismo resultado alimenta la previa (que los MUESTRA) y la creación (que los rechaza).
    """
    items: list = field(default_factory=list)
    capitulos: list = field(default_factory=list)
    hoja: str = ""
    fila_encabezado: int = 0
    filas_ignoradas: int = 0
    errores: list = field(default_factory=list)
    advertencias: list = field(default_factory=list)
    conciliacion: dict = field(default_factory=dict)
    parser_version: str = PARSER_VERSION
```

- [ ] **Step 4: Implementar el recorrido con estado**

En el mismo archivo, después de los tipos:

```python
def _a_entero(v) -> int:
    f = _to_float(v)
    return int(f) if f == f else 0          # `f == f` descarta NaN


class _Recorrido:
    """Estado del recorrido de arriba abajo: capítulo y turno vigentes.

    Es una clase y no un bucle suelto porque el recorrido lleva SEIS estados a la vez
    (capítulo, turno, items, capítulos, subtotales, advertencias), y pasarlos como
    variables sueltas es exactamente cómo se cuela un capítulo desactualizado en una fila.
    """

    def __init__(self, mapeo: dict[str, int], default_shift: str,
                 avisos: list) -> None:
        self.mapeo = mapeo
        self.shift = default_shift
        self.avisos = avisos
        self.items: list[LicitacionItem] = []
        self.capitulos: list[Capitulo] = []
        self.subtotales: list[int] = []
        self.ignoradas = 0
        self._cap: Optional[Capitulo] = None
        self._con_actividades: set[str] = set()
        self._vistos: set[tuple] = set()
        self._duplicados: list[str] = []

    def procesar(self, fila: list, n: int) -> None:
        m = self.mapeo
        codigo = _code(_val(fila, m.get("codigo")))
        item_pago = item_pago_texto(_val(fila, m.get("item_pago")),
                                    _fmt(fila, m.get("item_pago")))
        desc = str(_val(fila, m.get("descripcion")) or "").strip()
        cantidad = _val(fila, m.get("cantidad"))
        tipo = clasificar_fila(
            codigo=codigo, item_pago=item_pago, descripcion=desc, cantidad=cantidad,
            es_encabezado=_es_fila_encabezado([c[0] for c in fila], m))
        if tipo == CAPITULO:
            self._abrir_capitulo(item_pago, desc, n)
        elif tipo == TURNO:
            self.shift = (config.SHIFT_NOCTURNO if "NOC" in normalizar(desc)
                          else config.SHIFT_DIURNO)
        elif tipo == ACTIVIDAD:
            self._agregar_actividad(fila, codigo, item_pago, desc, cantidad, n)
        elif tipo == SUBTOTAL:
            self.subtotales.append(_a_entero(_val(fila, m.get("total_excel"))))
        else:
            self.ignoradas += 1
            if tipo == ENCABEZADO:
                self.avisos.append(Advertencia(
                    "encabezado_repetido", n, "Fila de encabezado repetida; se ignoró."))

    def cerrar(self) -> None:
        """Avisa del último capítulo si se quedó sin actividades."""
        self._avisar_capitulo_vacio()

    # ------------------------------------------------------------------ interno
    def _avisar_capitulo_vacio(self) -> None:
        c = self._cap
        if c is not None and c.codigo not in self._con_actividades:
            self.avisos.append(Advertencia(
                "capitulo_sin_actividades", c.fila_origen,
                f"El capítulo {c.codigo} «{c.nombre}» no trae actividades."))

    def _abrir_capitulo(self, item_pago: str, desc: str, n: int) -> None:
        self._avisar_capitulo_vacio()
        self._cap = Capitulo(codigo=capitulo_de(item_pago), nombre=desc,
                             orden=len(self.capitulos) + 1, fila_origen=n)
        self.capitulos.append(self._cap)

    def _agregar_actividad(self, fila, codigo, item_pago, desc, cantidad, n) -> None:
        m = self.mapeo
        cap = self._cap
        if cap is None:
            self.avisos.append(Advertencia(
                "actividad_sin_capitulo", n,
                f"«{desc[:60]}» aparece antes de cualquier capítulo."))
        else:
            prefijo = capitulo_de(item_pago)
            if prefijo and prefijo != cap.codigo:
                # No se decide en silencio: manda la POSICIÓN y queda el rastro, que es
                # lo que la previsualización muestra y el usuario tiene que confirmar.
                self.avisos.append(Advertencia(
                    "capitulo_ambiguo", n,
                    f"El ítem {item_pago} dice capítulo {prefijo} pero está dentro del "
                    f"{cap.codigo} «{cap.nombre}». Se usó la posición."))
            self._con_actividades.add(cap.codigo)
        unidad = str(_val(fila, m.get("unidad")) or "").strip()
        if not unidad:
            self.avisos.append(Advertencia("unidad_vacia", n,
                                           f"«{desc[:60]}» no trae unidad."))
        if not codigo:
            self.avisos.append(Advertencia("codigo_apu_vacio", n,
                                           f"«{desc[:60]}» no trae código de APU."))
        clave = (normalizar_item_pago(item_pago), normalizar(desc), self.shift)
        if clave in self._vistos:
            self._duplicados.append(item_pago)
        self._vistos.add(clave)
        con_aiu = _to_float(_val(fila, m.get("unitario_con_aiu")))
        sin_aiu = _to_float(_val(fila, m.get("unitario_sin_aiu")))
        total_excel = _a_entero(_val(fila, m.get("total_excel")))
        recalculado = mul_redondeado(con_aiu, float(cantidad))
        if total_excel and recalculado != total_excel:
            self.avisos.append(Advertencia(
                "total_fila_no_concilia", n,
                f"El Excel dice {total_excel:,} y el recálculo da {recalculado:,}."))
        self.items.append(LicitacionItem(
            item=item_pago or str(len(self.items) + 1),
            descripcion=desc,
            unidad=unidad,
            cantidad=float(cantidad),
            precio_contractual=con_aiu,
            precio_contractual_sin_aiu=sin_aiu,
            shift=self.shift,
            categoria=(f"{cap.codigo} · {cap.nombre}" if cap else ""),
            capitulo_codigo=(cap.codigo if cap else ""),
            capitulo_nombre=(cap.nombre if cap else ""),
            item_pago_original=item_pago,
            fila_origen=n,
            codigo_sugerido=codigo,
        ))

    # ------------------------------------------------------------------ salidas
    def _contractual(self, items) -> int:
        return sum(mul_redondeado(i.precio_contractual, i.cantidad) for i in items)

    def errores(self) -> list[str]:
        errs: list[str] = []
        if not self.items:
            errs.append("sin_actividades: no se detectó ninguna actividad válida.")
            return errs
        if self._duplicados:
            errs.append("item_duplicado: hay ítems de pago repetidos con la misma "
                        f"descripción y turno: {', '.join(self._duplicados[:10])}.")
        sin_precio = [i.item for i in self.items if not (i.precio_contractual > 0)]
        if sin_precio:
            errs.append("sin_contractual: estas actividades no traen valor unitario con "
                        f"AIU legible: {', '.join(sin_precio[:10])}.")
        total = self._contractual(self.items)
        por_capitulo = sum(
            self._contractual([i for i in self.items if i.capitulo_codigo == c.codigo])
            for c in self.capitulos)
        huerfanas = self._contractual([i for i in self.items if not i.capitulo_codigo])
        if por_capitulo + huerfanas != total:
            errs.append(f"total_no_concilia: la suma por capítulos "
                        f"({por_capitulo + huerfanas:,}) no coincide con la de las "
                        f"actividades ({total:,}).")
        return errs

    def conciliacion(self) -> dict:
        con = self._contractual(self.items)
        sin = sum(mul_redondeado(i.precio_contractual_sin_aiu, i.cantidad)
                  for i in self.items)
        suma_sub = sum(self.subtotales)
        if self.subtotales and suma_sub != con:
            self.avisos.append(Advertencia(
                "subtotal_no_concilia", 0,
                f"Los subtotales del Excel suman {suma_sub:,} y las actividades {con:,}."))
        return {"contractual_con_aiu": con, "contractual_sin_aiu": sin,
                "subtotales_excel": suma_sub,
                "diferencia": (suma_sub - con) if self.subtotales else 0,
                "subtotales_ok": (not self.subtotales) or suma_sub == con}
```

- [ ] **Step 5: Implementar la función pública**

Al final de `apu_tool/dominio/presupuesto.py`:

```python
def _celdas_con_formato(path: Path, hoja: str) -> list[list[tuple]]:
    """Filas de (valor, formato). El formato hace falta SOLO para el ítem de pago, pero
    leerlo por celda cuesta menos que abrir el libro dos veces."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        return [[(c.value, getattr(c, "number_format", "")) for c in fila]
                for fila in wb[hoja].iter_rows()]
    finally:
        wb.close()


def _val(fila: list, idx: Optional[int]):
    """Valor de una celda en una fila de (valor, formato). None si la columna no existe."""
    if idx is None or idx >= len(fila):
        return None
    return fila[idx][0]


def _fmt(fila: list, idx: Optional[int]) -> str:
    if idx is None or idx >= len(fila):
        return ""
    return fila[idx][1] or ""


def leer_formulario_idu(path: Path | str, hoja: Optional[str] = None,
                        default_shift: str = config.SHIFT_DIURNO) -> LecturaPresupuesto:
    """Lee el Formulario 1 de Presupuesto Oficial del IDU. Determinístico, sin IA.

    No levanta nunca por un problema de contenido: todo vuelve en `errores` y
    `advertencias`. Es deliberado — el mismo resultado alimenta la previsualización (que
    los muestra y deshabilita el botón) y la creación de la corrida (que responde 400).
    """
    path = Path(path)
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            elegida, gemelas = elegir_hoja(wb, hoja)
            nombres = list(wb.sheetnames)
        finally:
            wb.close()
    except (zipfile.BadZipFile, InvalidFileException, OSError) as exc:
        return LecturaPresupuesto(errores=[
            "archivo_invalido: el archivo no es un Excel válido o está dañado "
            f"({exc})."])
    if elegida is None:
        return LecturaPresupuesto(errores=[
            "sin_hoja: no se encontró una hoja de presupuesto compatible. "
            f"Hojas del archivo: {', '.join(nombres)}."])

    filas = _celdas_con_formato(path, elegida)
    idx_enc, mapeo, faltan = encontrar_encabezado([[c[0] for c in f] for f in filas])
    if idx_enc < 0:
        return LecturaPresupuesto(hoja=elegida, errores=[
            "sin_encabezado: no se encontró la fila de encabezado en las primeras "
            f"{MAX_FILAS_ENCABEZADO} filas de «{elegida}»."])
    if faltan:
        return LecturaPresupuesto(hoja=elegida, fila_encabezado=idx_enc + 1, errores=[
            "falta_columna: el archivo no trae la(s) columna(s) "
            f"{', '.join(faltan)} en la hoja «{elegida}»."])

    avisos: list[Advertencia] = []
    if gemelas:
        avisos.append(Advertencia(
            "hoja_ambigua", 0,
            f"Se usó la hoja «{elegida}». Otras candidatas: {', '.join(gemelas)}."))

    ctx = _Recorrido(mapeo, default_shift, avisos)
    for n, fila in enumerate(filas[idx_enc + 1:], start=idx_enc + 2):
        ctx.procesar(fila, n)
    ctx.cerrar()

    return LecturaPresupuesto(
        items=ctx.items, capitulos=ctx.capitulos, hoja=elegida,
        fila_encabezado=idx_enc + 1, filas_ignoradas=ctx.ignoradas,
        errores=ctx.errores(), advertencias=avisos, conciliacion=ctx.conciliacion())
```

- [ ] **Step 6: Reescribir `read_presupuesto` como envoltorio**

Reemplazar el cuerpo de `read_presupuesto` (deja la firma igual) por:

```python
def read_presupuesto(path: Path | str, hoja: str = "",
                     default_shift: str = config.SHIFT_DIURNO) -> list[LicitacionItem]:
    """Los ítems del presupuesto. Envoltorio de `leer_formulario_idu` para CLI y GUI.

    Se conserva el nombre y el orden de los parámetros a propósito: lo llaman
    `pipeline.build_desde_presupuesto`, `interfaz/cli.py` y `tests/test_presupuesto.py`.
    Levanta ValueError con los errores bloqueantes, que es lo que esos llamadores ya
    saben manejar; la web NO pasa por acá (usa `leer_formulario_idu` directo, porque
    necesita MOSTRAR los errores, no tragarlos).

    El default de `hoja` cambia de `HOJA_DEFECTO` a `""` = detección automática. Antes
    era un nombre fijo, y `elegir_hoja` respeta la hoja explícita **solo si existe**: con
    el default viejo, un archivo que no tuviera exactamente esa pestaña fallaría con
    `sin_hoja` en vez de detectar la suya. `HOJA_DEFECTO` sigue existiendo como constante
    (la CLI la pasa con `--hoja`) y `_HOJAS_CANDIDATAS` ya la cubre por el fragmento
    `ppto oficial`, así que un archivo con `FOR 1-PPTO OFICIAL` se detecta igual.
    """
    lectura = leer_formulario_idu(path, hoja=hoja or None,
                                  default_shift=default_shift)
    if lectura.errores:
        raise ValueError(" ".join(lectura.errores))
    return lectura.items
```

`HOJA_DEFECTO = "FOR 1-PPTO OFICIAL"` **se queda** en el módulo: la usa
`interfaz/cli.py` como valor por defecto de `--hoja` y `pipeline.build_desde_presupuesto`.
No la borres.

- [ ] **Step 7: Avisar si las columnas ofertadas vienen diligenciadas**

Primero el test, en `tests/test_presupuesto_idu.py`:

```python
def test_avisa_si_la_oferta_viene_diligenciada(tmp_path):
    # En el archivo de referencia las columnas O–S están en cero (la oferta no está
    # diligenciada). Si algún día llegan con valor, el parser NO las lee — pero avisa,
    # en vez de callarse y dejar creer que las tuvo en cuenta.
    p = escribir_formulario(tmp_path / "f1.xlsx")
    wb = openpyxl.load_workbook(p)
    ws = wb["PROPUESTA ECONÓMICA"]
    ws.cell(row=1, column=15).value = "VALOR UNITARIO SIN AIU OFERTADO"
    for fila in (9, 10):                       # dos actividades del capítulo 1
        ws.cell(row=fila, column=15).value = 1200
    wb.save(p)
    lec = leer_formulario_idu(p)
    avisos = [a for a in lec.advertencias if a.tipo == "oferta_diligenciada"]
    assert len(avisos) == 1
    assert "2" in avisos[0].detalle           # cuántas filas traen oferta
    # Y NO cambia el contractual: se sigue leyendo la columna oficial con AIU.
    assert next(i for i in lec.items if i.item_pago_original == "1.001") \
        .precio_contractual == 1351
```

> Si las filas 9 y 10 de tu fixture no son actividades del capítulo 1, ajustá los números
> de fila: lo que fija el test es que se cuenten las filas con oferta, no cuáles son.

Implementar en `apu_tool/dominio/presupuesto.py`:

```python
# Encabezados de las columnas de oferta y corrección del proponente. NO se leen: en el
# presupuesto oficial vienen en cero, y no hay un caso real medido que diga qué hacer
# con ellas. Se detectan para AVISAR, que es distinto de ignorarlas en silencio.
_ENCABEZADOS_OFERTA = (
    "valor unitario sin aiu ofertado",
    "valor unitario sin aiu corregido",
    "valor unitario con aiu corregido",
    "valor unitario con aiu corregido x cantidad",
)


def _columnas_de_oferta(fila_encabezado: list) -> list[int]:
    return [i for i, celda in enumerate(fila_encabezado)
            if norm_encabezado(celda) in _ENCABEZADOS_OFERTA]
```

En `leer_formulario_idu`, después de armar `avisos` y antes del bucle del recorrido:

```python
    cols_oferta = _columnas_de_oferta([c[0] for c in filas[idx_enc]])
    con_oferta = sum(
        1 for f in filas[idx_enc + 1:]
        if any(_to_float(_val(f, i)) for i in cols_oferta))
    if con_oferta:
        avisos.append(Advertencia(
            "oferta_diligenciada", 0,
            f"{con_oferta} fila(s) traen valores en las columnas de oferta o corrección. "
            f"Esta versión NO las lee: el contractual sale del valor unitario oficial "
            f"con AIU."))
```

- [ ] **Step 8: Correr los tests**

Run: `python -m pytest tests/test_presupuesto_idu.py tests/test_presupuesto.py -q`
Expected: PASS (42 passed)

- [ ] **Step 9: Correr la suite completa**

Run: `python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add apu_tool/dominio/presupuesto.py tests/test_presupuesto_idu.py tests/test_presupuesto.py
git commit -m "feat(idu): leer_formulario_idu con capitulos, advertencias y conciliacion"
```

---

## Task 8: Regresión contra el archivo real

**Files:**
- Create: `tests/test_presupuesto_idu_regresion.py`

- [ ] **Step 1: Escribir el test**

Crear `tests/test_presupuesto_idu_regresion.py`:

```python
"""Regresión del parser IDU contra el Formulario 1 real.

El archivo pesa 4,5 MB y NO se versiona: se salta si `APU_IDU_F1_XLSX` no apunta a él.
Mismo trato que el Excel histórico. Los números son los medidos el 2026-09-10 y están
en la especificación (docs/superpowers/specs/2026-09-11-ruta-idu-formulario-1-design.md).
"""
import os
from pathlib import Path

import pytest

from apu_tool.dominio.presupuesto import leer_formulario_idu

RUTA = os.environ.get("APU_IDU_F1_XLSX", "")
pytestmark = pytest.mark.skipif(
    not RUTA or not Path(RUTA).exists(),
    reason="define APU_IDU_F1_XLSX con la ruta del Formulario 1 real")

CONTRACTUAL_CON_AIU = 158_456_072_140
CONTRACTUAL_SIN_AIU = 123_871_215_068


@pytest.fixture(scope="module")
def lectura():
    return leer_formulario_idu(RUTA)


def test_sin_errores_bloqueantes(lectura):
    assert lectura.errores == []


def test_hoja_y_encabezado(lectura):
    assert lectura.hoja == "PROPUESTA ECONÓMICA"
    assert lectura.fila_encabezado == 10


def test_catorce_capitulos_numerados_del_1_al_14(lectura):
    assert len(lectura.capitulos) == 14
    assert [c.codigo for c in lectura.capitulos] == [str(n) for n in range(1, 15)]
    assert lectura.capitulos[0].nombre == "PRELIMINARES"
    assert lectura.capitulos[1].nombre == "PAVIMENTOS"
    assert lectura.capitulos[9].nombre == "RED DE ALCANTARILLADO"


def test_mil_novecientas_treinta_y_nueve_actividades(lectura):
    assert len(lectura.items) == 1939


def test_ninguna_actividad_sin_capitulo(lectura):
    assert [i.item for i in lectura.items if not i.capitulo_codigo] == []


def test_la_fila_2201_no_es_actividad(lectura):
    # Segundo encabezado del archivo: Nº / ÍTEM DE PAGO / DESCRIPCIÓN.
    assert 2201 not in {i.fila_origen for i in lectura.items}
    assert any(a.tipo == "encabezado_repetido" and a.fila == 2201
               for a in lectura.advertencias)


def test_turno_nocturno_detectado(lectura):
    nocturnas = [i for i in lectura.items if i.shift == "NOCTURNO"]
    assert len(nocturnas) == 872


def test_prefijo_y_posicion_coinciden_en_todas(lectura):
    assert [a for a in lectura.advertencias if a.tipo == "capitulo_ambiguo"] == []


def test_conciliacion_exacta_contra_el_excel(lectura):
    c = lectura.conciliacion
    assert c["contractual_con_aiu"] == CONTRACTUAL_CON_AIU
    assert c["contractual_sin_aiu"] == CONTRACTUAL_SIN_AIU
    assert c["subtotales_excel"] == CONTRACTUAL_CON_AIU
    assert c["diferencia"] == 0
    assert c["subtotales_ok"] is True


def test_ninguna_fila_desconcilia_contra_su_valor_total(lectura):
    assert [a for a in lectura.advertencias if a.tipo == "total_fila_no_concilia"] == []


def test_ceros_significativos_recuperados(lectura):
    originales = {i.item_pago_original for i in lectura.items}
    assert "2.010" in originales      # el float 2.01 con formato 0.000
    assert "3.100" in originales


def test_hoja_gemela_avisada(lectura):
    # El archivo real trae PROPUESTA ECONÓMICA y PROPUESTA ECONÓMICA (2), idénticas.
    assert any(a.tipo == "hoja_ambigua" for a in lectura.advertencias)
```

- [ ] **Step 2: Correr el test con el archivo real**

Run:
```bash
APU_IDU_F1_XLSX="/c/Users/luis.fajardo/Downloads/Formulario 1 Formulario de Presupuesto Oficial (version 1).xlsx" \
  python -m pytest tests/test_presupuesto_idu_regresion.py -q
```
Expected: PASS (12 passed)

Si alguno falla, el parser está mal — **no ajustes el número esperado**. Los valores
vienen de la medición registrada en la especificación.

- [ ] **Step 3: Correr el test sin el archivo**

Run: `python -m pytest tests/test_presupuesto_idu_regresion.py -q`
Expected: `12 skipped` (así se comporta en CI)

- [ ] **Step 4: Commit**

```bash
git add tests/test_presupuesto_idu_regresion.py
git commit -m "test(idu): regresion 14 capitulos / 1939 actividades contra el archivo real"
```

---

# Fase 3 — Entidad de origen y privacidad

## Task 9: El enum `EntidadOrigen` y el registro de lectores

**Files:**
- Modify: `apu_tool/nucleo/models.py`
- Create: `apu_tool/dominio/entrada.py`
- Test: `tests/test_entrada_entidad.py` (crear)

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_entrada_entidad.py`:

```python
"""Registro entidad -> lector. Un diccionario, no una jerarquía de clases."""
import pytest

from apu_tool.dominio import entrada
from apu_tool.nucleo.models import EntidadOrigen
from tests.fixtures_idu import escribir_formulario


def test_el_enum_tiene_las_seis_entidades():
    assert {e.value for e in EntidadOrigen} == {
        "IDU", "METRO_BOGOTA", "INVIAS", "OTRA_PUBLICA", "PRIVADA", "NO_IDENTIFICADA"}


def test_el_enum_serializa_como_texto():
    # str, Enum como MatchStatus: sobrevive a asdict() y a json.dumps().
    import json
    assert json.dumps({"e": EntidadOrigen.IDU}) == '{"e": "IDU"}'


def test_parse_entidad_tolera_minusculas_y_espacios():
    assert entrada.parse_entidad("idu") is EntidadOrigen.IDU
    assert entrada.parse_entidad("  IDU  ") is EntidadOrigen.IDU
    assert entrada.parse_entidad("METRO_BOGOTA") is EntidadOrigen.METRO_BOGOTA


def test_parse_entidad_rechaza_lo_desconocido():
    # Valor estable, no texto libre: una entidad inventada es un error del llamador.
    with pytest.raises(ValueError):
        entrada.parse_entidad("ALCALDIA DE CHIA")
    with pytest.raises(ValueError):
        entrada.parse_entidad("")


def test_todas_las_entidades_tienen_lector():
    # Si mañana se agrega una entidad al enum y se olvida el lector, esto falla acá y
    # no en producción con un KeyError.
    assert set(entrada.LECTORES) == set(EntidadOrigen)


def test_solo_idu_exige_confirmacion_hoy():
    assert entrada.requiere_confirmacion(EntidadOrigen.IDU) is True
    for otra in EntidadOrigen:
        if otra is not EntidadOrigen.IDU:
            assert entrada.requiere_confirmacion(otra) is False


def test_idu_lee_el_formulario_1_con_capitulos(tmp_path):
    lec = entrada.leer(EntidadOrigen.IDU, escribir_formulario(tmp_path / "f1.xlsx"))
    assert len(lec.capitulos) == 2
    assert len(lec.items) == 5
    assert lec.errores == []


def test_las_demas_entidades_usan_el_importador_generico(tmp_path):
    # Una lista plana normal: sin capítulos, sin conciliación, y NO se rompe.
    import openpyxl
    p = tmp_path / "plana.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["ITEM", "DESCRIPCION", "UNIDAD", "CANTIDAD", "PRECIO", "TURNO"])
    ws.append(["1", "EXCAVACION MANUAL", "M3", 10, 45000, "DIURNO"])
    wb.save(p)
    for e in (EntidadOrigen.METRO_BOGOTA, EntidadOrigen.INVIAS,
              EntidadOrigen.OTRA_PUBLICA, EntidadOrigen.PRIVADA,
              EntidadOrigen.NO_IDENTIFICADA):
        lec = entrada.leer(e, p)
        assert lec.errores == [], e
        assert len(lec.items) == 1
        assert lec.capitulos == []
        assert lec.items[0].capitulo_codigo == ""


def test_el_generico_traduce_el_fallo_de_lectura_a_error(tmp_path):
    malo = tmp_path / "no-es.xlsx"
    malo.write_bytes(b"no soy un zip")
    lec = entrada.leer(EntidadOrigen.PRIVADA, malo)
    assert lec.items == []
    assert lec.errores != []
```

- [ ] **Step 2: Correr el test para ver que falla**

Run: `python -m pytest tests/test_entrada_entidad.py -q`
Expected: FAIL con `ImportError: cannot import name 'EntidadOrigen'`

- [ ] **Step 3: Agregar el enum**

En `apu_tool/nucleo/models.py`, junto a `MatchStatus`:

```python
class EntidadOrigen(str, Enum):
    """De dónde salió el presupuesto de una corrida.

    Valor ESTABLE, no texto libre: se guarda en `corrida.origen_json` y decide qué
    lector se usa (`dominio/entrada.py`). `str, Enum` como MatchStatus, para que
    sobreviva a `asdict()` y a `json.dumps()` sin conversión.

    Hoy solo IDU tiene lector especializado. Las demás usan el importador genérico a
    propósito: no se inventan reglas para formatos que nadie midió.
    """
    IDU = "IDU"
    METRO_BOGOTA = "METRO_BOGOTA"
    INVIAS = "INVIAS"
    OTRA_PUBLICA = "OTRA_PUBLICA"
    PRIVADA = "PRIVADA"
    NO_IDENTIFICADA = "NO_IDENTIFICADA"
```

- [ ] **Step 4: Crear `apu_tool/dominio/entrada.py`**

```python
"""Qué lector le toca a cada entidad. El ÚNICO punto de despacho.

Un diccionario y no una jerarquía de clases: hay una sola implementación especializada
(IDU), y un Protocol con una implementación es andamiaje. Agregar INVIAS mañana es una
entrada más en `LECTORES` y una función — sin tocar ningún `if` de `rutas.py`.

Todos los lectores devuelven `LecturaPresupuesto`, así que el servicio y el frontend
tienen un solo tipo de retorno y una sola forma de mostrar errores y advertencias.
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Callable

from openpyxl.utils.exceptions import InvalidFileException

from apu_tool import config
from apu_tool.dominio.licitacion import read_licitacion
from apu_tool.dominio.presupuesto import LecturaPresupuesto, leer_formulario_idu
from apu_tool.nucleo.models import EntidadOrigen

Lector = Callable[..., LecturaPresupuesto]


def parse_entidad(valor) -> EntidadOrigen:
    """Texto -> EntidadOrigen. Levanta ValueError si no es una entidad conocida.

    Tolera minúsculas y espacios (viene de un <select> del navegador), pero NO inventa:
    una entidad desconocida es un error del llamador, no un `NO_IDENTIFICADA` silencioso.
    Si fuera silencioso, un typo en el formulario mandaría un Formulario 1 del IDU por
    el importador genérico y el usuario vería una corrida sin capítulos sin saber por qué.
    """
    texto = str(valor or "").strip().upper()
    try:
        return EntidadOrigen(texto)
    except ValueError as exc:
        validas = ", ".join(e.value for e in EntidadOrigen)
        raise ValueError(
            f"Entidad desconocida: «{valor}». Válidas: {validas}.") from exc


def leer_generico(path: Path | str, default_shift: str = config.SHIFT_DIURNO,
                  **_kw) -> LecturaPresupuesto:
    """El importador de siempre (`read_licitacion`), envuelto en LecturaPresupuesto.

    Sin capítulos, sin conciliación y sin advertencias: no hay reglas medidas para estos
    formatos, y no se inventan. `require_turno=True` es el comportamiento que la web ya
    tenía; no cambia.
    """
    try:
        items = read_licitacion(path, default_shift=default_shift, require_turno=True)
    except ValueError as exc:
        return LecturaPresupuesto(errores=[str(exc)])
    except (zipfile.BadZipFile, InvalidFileException, OSError) as exc:
        return LecturaPresupuesto(errores=[
            f"archivo_invalido: el archivo no es un Excel válido o está dañado ({exc})."])
    if not items:
        return LecturaPresupuesto(errores=["sin_actividades: la lista no tiene ítems "
                                           "legibles."])
    return LecturaPresupuesto(items=items)


LECTORES: dict[EntidadOrigen, Lector] = {
    EntidadOrigen.IDU:             leer_formulario_idu,
    EntidadOrigen.METRO_BOGOTA:    leer_generico,
    EntidadOrigen.INVIAS:          leer_generico,
    EntidadOrigen.OTRA_PUBLICA:    leer_generico,
    EntidadOrigen.PRIVADA:         leer_generico,
    EntidadOrigen.NO_IDENTIFICADA: leer_generico,
}

# Entidades cuya estructura hay que confirmar antes de crear la corrida. Solo las que
# tienen lector especializado: en el genérico no hay estructura que revisar.
_CON_CONFIRMACION = frozenset({EntidadOrigen.IDU})


def requiere_confirmacion(entidad: EntidadOrigen) -> bool:
    return entidad in _CON_CONFIRMACION


def formato_de(entidad: EntidadOrigen) -> str:
    """Etiqueta del formato leído; va a `origen_json.formato`."""
    return "idu_formulario_1" if entidad is EntidadOrigen.IDU else "generico"


def leer(entidad: EntidadOrigen, path: Path | str,
         default_shift: str = config.SHIFT_DIURNO, **kw) -> LecturaPresupuesto:
    """Lee el archivo con el lector de esa entidad."""
    return LECTORES[entidad](path, default_shift=default_shift, **kw)
```

- [ ] **Step 5: Correr el test**

Run: `python -m pytest tests/test_entrada_entidad.py -q`
Expected: PASS (9 passed)

- [ ] **Step 6: Commit**

```bash
git add apu_tool/nucleo/models.py apu_tool/dominio/entrada.py tests/test_entrada_entidad.py
git commit -m "feat(idu): EntidadOrigen y registro entidad->lector"
```

---

## Task 10: Frontera de privacidad

**Files:**
- Modify: `apu_tool/dominio/privacy.py:22-27` y `privacy.licitacion_item_to_dict`
- Test: `tests/test_privacy.py`

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_privacy.py`:

```python
import pytest

from apu_tool.dominio.privacy import (
    PrivacyViolation, assert_no_money, licitacion_item_to_dict,
)
from apu_tool.nucleo.models import LicitacionItem


@pytest.mark.parametrize("clave", [
    "precio_contractual_sin_aiu", "contractual_total_sin_aiu", "origen_json",
    "conciliacion", "total_excel", "subtotales_excel", "unitario_sin_aiu",
    "unitario_con_aiu", "contractual_con_aiu",
])
def test_los_campos_monetarios_de_la_ruta_idu_disparan_la_violacion(clave):
    with pytest.raises(PrivacyViolation):
        assert_no_money({"actividad": {clave: 1351}})


def test_el_capitulo_si_puede_llegar_a_la_ia():
    # Texto, no dinero: saber que la actividad es de RED DE ACUEDUCTO es estructura.
    item = LicitacionItem(
        item="11.005", descripcion="TUBERÍA PVC", unidad="ML", cantidad=120.0,
        precio_contractual=95463.0, shift="DIURNO",
        precio_contractual_sin_aiu=74627.0,
        capitulo_codigo="11", capitulo_nombre="RED DE ACUEDUCTO",
        item_pago_original="11.005", fila_origen=1420, codigo_sugerido="3903")
    d = licitacion_item_to_dict(item)
    assert d["capitulo_codigo"] == "11"
    assert d["capitulo_nombre"] == "RED DE ACUEDUCTO"
    assert_no_money(d)      # no levanta


def test_ningun_precio_del_item_cruza_la_frontera():
    item = LicitacionItem(
        item="11.005", descripcion="TUBERÍA PVC", unidad="ML", cantidad=120.0,
        precio_contractual=95463.0, shift="DIURNO",
        precio_contractual_sin_aiu=74627.0)
    d = licitacion_item_to_dict(item)
    assert "precio_contractual" not in d
    assert "precio_contractual_sin_aiu" not in d
    # Y tampoco por valor: ninguno de los dos montos aparece en el payload.
    assert 95463.0 not in d.values()
    assert 74627.0 not in d.values()


def test_el_origen_de_la_corrida_nunca_viaja_entero():
    # origen_json lleva la conciliación (dinero) adentro: misma razón que plan_json.
    with pytest.raises(PrivacyViolation):
        assert_no_money({"corrida": {"origen_json": {"entidad": "IDU"}}})
```

- [ ] **Step 2: Correr el test para ver que falla**

Run: `python -m pytest tests/test_privacy.py -q`
Expected: FAIL — `assert_no_money` no levanta para `precio_contractual_sin_aiu`, y
`licitacion_item_to_dict` no trae `capitulo_codigo`.

- [ ] **Step 3: Implementar**

En `apu_tool/dominio/privacy.py`, reemplazar `_FORBIDDEN_KEYS` por:

```python
_FORBIDDEN_KEYS = {
    "precio", "precio_unitario", "precio_contractual", "precio_unitario_hist",
    "costo", "costo_unitario", "costo_total", "valor", "valor_unitario",
    "valor_total", "margen", "price", "cost", "amount", "total",
    "fuente_precio", "costo_manual", "plan_json",
    # --- ruta IDU (Formulario 1) ------------------------------------------------
    # Las dos bases del contractual y sus multiplicaciones.
    "precio_contractual_sin_aiu", "contractual_total_sin_aiu",
    "contractual_con_aiu", "contractual_sin_aiu",
    "unitario_sin_aiu", "unitario_con_aiu",
    # Lo que el Excel del IDU trae y el parser concilia.
    "total_excel", "subtotales_excel", "conciliacion",
    # `origen_json` va por la MISMA razón que `plan_json`: lleva la conciliación
    # —o sea dinero— adentro, así que el objeto entero no puede cruzar la frontera.
    "origen_json",
}
```

Y en `licitacion_item_to_dict`, agregar las dos claves de texto:

```python
def licitacion_item_to_dict(item: LicitacionItem) -> dict[str, Any]:
    """Versión SIN dinero de un ítem de licitación.

    Se arma clave por clave a propósito: un campo nuevo del dataclass NO se cuela solo
    por existir. Por eso `precio_contractual` y `precio_contractual_sin_aiu` no están.
    El capítulo sí viaja: es texto y es estructura — saber que una actividad pertenece a
    RED DE ACUEDUCTO ayuda a componerla, y no dice nada de lo que cuesta.
    """
    return {
        "item": item.item,
        "descripcion": item.descripcion,
        "unidad": item.unidad,
        "cantidad": round(item.cantidad, 6),
        "shift": item.shift,
        "capitulo_codigo": item.capitulo_codigo,
        "capitulo_nombre": item.capitulo_nombre,
    }
```

- [ ] **Step 4: Correr el test**

Run: `python -m pytest tests/test_privacy.py -q`
Expected: PASS

- [ ] **Step 5: Correr los tests de privacidad de servicio y composición**

Run: `python -m pytest tests/test_servicio_privacidad.py tests/test_composicion_privacidad.py tests/test_revision_privacidad.py -q`
Expected: PASS. Si alguno falla porque ahora llegan dos claves más al payload de
composición, **el test tiene razón en mirar**: revisá que sean `capitulo_codigo` y
`capitulo_nombre` y actualizá la lista esperada del test, no la denylist.

- [ ] **Step 6: Correr la suite completa**

Run: `python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add apu_tool/dominio/privacy.py tests/test_privacy.py
git commit -m "feat(idu): frontera de privacidad para los campos del Formulario 1"
```

---

# Fase 4 — Persistencia (`origen_json`)

## Task 11: `origen_json` en SQLite

**Files:**
- Modify: `db/corridas.sql`
- Modify: `apu_tool/datos/corridas_db.py`
- Modify: `apu_tool/nucleo/models.py` (`CorridaMeta.origen`)
- Test: `tests/test_corridas_origen.py` (crear)

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_corridas_origen.py`:

```python
"""El origen de importación de una corrida (entidad, hoja, parser, conciliación)."""
import json

from apu_tool.datos.corridas_db import CorridasDB
from apu_tool.nucleo.models import CorridaMeta

ORIGEN = {
    "entidad": "IDU", "formato": "idu_formulario_1",
    "hoja": "PROPUESTA ECONÓMICA", "fila_encabezado": 10,
    "parser_version": "idu-f1/1", "estructura_confirmada": True,
    "capitulos": 14, "actividades": 1939,
    "conciliacion": {"contractual_con_aiu": 158456072140, "diferencia": 0},
}


def _db(tmp_path) -> CorridasDB:
    db = CorridasDB(tmp_path / "corridas.db")
    db.init_schema()
    return db


def _crear(db) -> int:
    return db.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-09-11T09:00:00", archivo="f1.xlsx",
        turno_def="DIURNO", use_ai=False, estado="armando", cuadro_path=None))


def test_origen_se_guarda_y_se_relee(tmp_path):
    db = _db(tmp_path)
    cid = _crear(db)
    db.set_origen(cid, json.dumps(ORIGEN, ensure_ascii=False))
    assert json.loads(db.get_origen(cid)) == ORIGEN


def test_origen_llega_en_la_meta(tmp_path):
    db = _db(tmp_path)
    cid = _crear(db)
    db.set_origen(cid, json.dumps(ORIGEN, ensure_ascii=False))
    meta = db.get_corrida(cid)
    assert meta.origen["entidad"] == "IDU"
    assert meta.origen["capitulos"] == 14


def test_corrida_vieja_sin_origen_abre_igual(tmp_path):
    # Es el caso de TODA corrida anterior a esta feature: la columna llega en NULL.
    db = _db(tmp_path)
    cid = _crear(db)
    assert db.get_origen(cid) is None
    assert db.get_corrida(cid).origen is None
    assert db.listar_corridas()[0].origen is None


def test_migracion_idempotente(tmp_path):
    # init_schema corre en cada arranque: dos veces no puede romper nada.
    db = _db(tmp_path)
    cid = _crear(db)
    db.set_origen(cid, json.dumps(ORIGEN, ensure_ascii=False))
    db.init_schema()
    db.init_schema()
    assert json.loads(db.get_origen(cid)) == ORIGEN


def test_origen_de_una_corrida_inexistente_es_none(tmp_path):
    assert _db(tmp_path).get_origen(9999) is None
```

- [ ] **Step 2: Correr el test para ver que falla**

Run: `python -m pytest tests/test_corridas_origen.py -q`
Expected: FAIL con `AttributeError: 'CorridasDB' object has no attribute 'set_origen'`

- [ ] **Step 3: Agregar la columna al esquema**

En `db/corridas.sql`, dentro de `CREATE TABLE IF NOT EXISTS corrida`, después de `plan_json`:

```sql
  -- De dónde salió el presupuesto: entidad, formato, hoja, versión del parser, quién
  -- confirmó la estructura y la conciliación contra el Excel. NULL en toda corrida
  -- anterior a la ruta IDU: eso es "sin clasificación por capítulo", no un error.
  -- OJO: lleva la conciliación —o sea DINERO— adentro, así que esta columna nunca
  -- puede viajar en un payload hacia la IA. Está en privacy._FORBIDDEN_KEYS.
  origen_json   TEXT,
```

- [ ] **Step 4: Agregar la migración y los métodos**

En `apu_tool/datos/corridas_db.py::init_schema`, junto a las demás guardas de `corrida`:

```python
            if "origen_json" not in cols:
                conn.execute("ALTER TABLE corrida ADD COLUMN origen_json TEXT")
```

Agregar `origen_json` a `_COLS_META` (al final de la cadena):

```python
    _COLS_META = ("id, creada_en, archivo, turno_def, use_ai, estado, cuadro_path, "
                  "duracion_ms, modo, carpeta_id, nombre, lista_precios_id, "
                  "intentos, ultimo_error, armando_por, armando_desde, origen_json")
```

> Va en `_COLS_META` y `plan_json` no: el origen pesa menos de 1 KB, mientras que el plan
> son ~400 KB que esta lectura descartaría en cada poll de la pantalla.

En `_row_to_meta`, agregar el campo:

```python
            origen=_json_o_none(r["origen_json"] if "origen_json" in r.keys() else None),
```

Y el ayudante, arriba de la clase:

```python
def _json_o_none(crudo):
    """Texto JSON -> dict. None si está vacío o si no parsea (una corrida vieja con
    basura en la columna no puede tumbar el listado entero)."""
    if not crudo:
        return None
    try:
        return json.loads(crudo)
    except (ValueError, TypeError):
        return None
```

Y los dos métodos, junto a `set_plan` / `get_plan`:

```python
    def set_origen(self, corrida_id: int, origen_json: str, conn=None) -> None:
        """Guarda el origen de importación. Se escribe UNA vez, al crear la corrida."""
        sql = "UPDATE corrida SET origen_json=? WHERE id=?"
        if conn is not None:
            conn.execute(sql, (origen_json, int(corrida_id)))
            return
        with self.connect() as c:
            c.execute(sql, (origen_json, int(corrida_id)))

    def get_origen(self, corrida_id: int) -> Optional[str]:
        with self.connect() as conn:
            r = conn.execute("SELECT origen_json FROM corrida WHERE id=?",
                             (int(corrida_id),)).fetchone()
        return r["origen_json"] if r else None
```

- [ ] **Step 5: Agregar el campo a `CorridaMeta`**

En `apu_tool/nucleo/models.py`, dentro de `CorridaMeta`, al final:

```python
    # De dónde salió el presupuesto (entidad, hoja, parser, conciliación). None en toda
    # corrida anterior a la ruta IDU: se muestra como "sin clasificación por capítulo".
    # Es DINERO por dentro (la conciliación): nunca va a un payload de la IA.
    origen: Optional[dict] = None
```

- [ ] **Step 6: Correr el test**

Run: `python -m pytest tests/test_corridas_origen.py -q`
Expected: PASS (5 passed)

- [ ] **Step 7: Commit**

```bash
git add db/corridas.sql apu_tool/datos/corridas_db.py apu_tool/nucleo/models.py tests/test_corridas_origen.py
git commit -m "feat(idu): columna origen_json en SQLite"
```

---

## Task 12: `origen_json` en PostgreSQL y en el `Protocol`

**Files:**
- Modify: `db/pg/corridas.sql`
- Modify: `apu_tool/datos/pg/corridas_pg.py`
- Modify: `apu_tool/datos/repositorio.py`
- Test: `tests/test_repositorios_contrato.py`, `tests/test_pg_esquema.py`

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_repositorios_contrato.py`:

```python
def test_el_contrato_de_corridas_incluye_el_origen():
    from apu_tool.datos.repositorio import RepositorioCorridas
    assert hasattr(RepositorioCorridas, "set_origen")
    assert hasattr(RepositorioCorridas, "get_origen")
```

Agregar a `tests/test_pg_esquema.py`:

```python
def test_el_esquema_pg_trae_origen_json():
    from pathlib import Path
    sql = Path("db/pg/corridas.sql").read_text(encoding="utf-8")
    assert "origen_json" in sql
    # La migración idempotente para bases que ya existen.
    assert "ADD COLUMN IF NOT EXISTS origen_json TEXT" in sql
```

- [ ] **Step 2: Correr los tests para ver que fallan**

Run: `python -m pytest tests/test_repositorios_contrato.py tests/test_pg_esquema.py tests/test_paridad_backends.py -q`
Expected: FAIL — el contrato no tiene `set_origen` y `test_paridad_backends` detecta que
SQLite tiene métodos que Postgres no.

- [ ] **Step 3: Implementar en Postgres**

En `db/pg/corridas.sql`, dentro de `CREATE TABLE IF NOT EXISTS corridas.corrida`, después
de `plan_json`:

```sql
    -- De dónde salió el presupuesto: entidad, formato, hoja, versión del parser, quién
    -- confirmó la estructura y la conciliación contra el Excel. NULL en toda corrida
    -- anterior a la ruta IDU. Lleva DINERO adentro (la conciliación): nunca viaja hacia
    -- la IA; está en privacy._FORBIDDEN_KEYS.
    origen_json   TEXT,
```

Y en el bloque de migraciones idempotentes del mismo archivo:

```sql
ALTER TABLE corridas.corrida ADD COLUMN IF NOT EXISTS origen_json TEXT;
```

En `apu_tool/datos/pg/corridas_pg.py`, agregar `origen_json` al final de `_COLS_META`, el
campo en `_row_to_meta`:

```python
            origen=_json_o_none(r.get("origen_json")),
```

el mismo ayudante `_json_o_none` (copiado tal cual del backend SQLite — son dos módulos
espejo, no comparten código a propósito), y los dos métodos junto a `set_plan`/`get_plan`:

```python
    def set_origen(self, corrida_id: int, origen_json: str, conn=None) -> None:
        """Guarda el origen de importación. Se escribe UNA vez, al crear la corrida."""
        sql = "UPDATE corridas.corrida SET origen_json=%s WHERE id=%s"
        if conn is not None:
            conn.execute(sql, (origen_json, int(corrida_id)))
            return
        with self.cx.connection() as c:
            c.execute(sql, (origen_json, int(corrida_id)))

    def get_origen(self, corrida_id: int) -> Optional[str]:
        with self.cx.connection() as conn:
            r = conn.execute("SELECT origen_json FROM corridas.corrida WHERE id=%s",
                             (int(corrida_id),)).fetchone()
        return r["origen_json"] if r else None
```

- [ ] **Step 4: Agregarlo al `Protocol`**

En `apu_tool/datos/repositorio.py`, dentro de `RepositorioCorridas`, junto a `set_plan`:

```python
    def set_origen(self, corrida_id: int, origen_json: str, conn=None) -> None:
        """De dónde salió el presupuesto (entidad, hoja, parser, conciliación).

        Se escribe UNA vez, justo después de crear la corrida, por la misma razón que
        `set_plan`: no ensucia el INSERT de los dos backends.
        """
        ...

    def get_origen(self, corrida_id: int) -> Optional[str]:
        """El JSON crudo del origen, o None si la corrida es anterior a la ruta IDU."""
        ...
```

- [ ] **Step 5: Correr los tests**

Run: `python -m pytest tests/test_repositorios_contrato.py tests/test_pg_esquema.py tests/test_paridad_backends.py tests/test_corridas_contrato.py -q`
Expected: PASS. `test_paridad_backends` compara nombres y firmas de los métodos públicos
de los dos backends: si una firma quedó distinta, falla acá.

- [ ] **Step 6: Correr contra Postgres real (opcional pero recomendado)**

Run: `TEST_DATABASE_URL=postgresql://... python -m pytest tests/test_pg_esquema.py tests/test_migracion_pg.py -q`
Expected: PASS. Sin `TEST_DATABASE_URL` esos tests se saltan.

⚠️ **Nunca apuntes `TEST_DATABASE_URL` a producción**: esos tests hacen `DROP SCHEMA`.

- [ ] **Step 7: Correr la suite completa**

Run: `python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add db/pg/corridas.sql apu_tool/datos/pg/corridas_pg.py apu_tool/datos/repositorio.py tests/test_repositorios_contrato.py tests/test_pg_esquema.py
git commit -m "feat(idu): origen_json en Postgres y en el contrato de corridas"
```

---

# Fase 5 — Resumen por capítulo y capa de servicio

## Task 13: `resumen_por_capitulo` — la fuente única del cálculo

Va antes del servicio porque el servicio la consume. Es **la única** función que suma
dinero por capítulo: la usan la API, la web y las dos hojas de Excel.

**Files:**
- Modify: `apu_tool/dominio/report_categorizado.py`
- Test: `tests/test_resumen_capitulo.py` (crear)

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_resumen_capitulo.py`:

```python
"""Resumen por capítulo: una sola función suma dinero, y la usan API, web y Excel."""
from apu_tool.dominio.report_categorizado import resumen_por_capitulo
from apu_tool.nucleo.models import (
    AssembledApu, CostedComponent, LicitacionItem, MatchStatus,
)


def _item(cap_cod, cap_nom, cant, con_aiu, sin_aiu, item="1.001"):
    return LicitacionItem(
        item=item, descripcion=f"ACT {item}", unidad="M2", cantidad=cant,
        precio_contractual=con_aiu, precio_contractual_sin_aiu=sin_aiu,
        shift="DIURNO", categoria=f"{cap_cod} · {cap_nom}",
        capitulo_codigo=cap_cod, capitulo_nombre=cap_nom, item_pago_original=item)


def _ens(item, costo_unitario, apu_codigo="A1", costo_manual=False):
    comps = []
    if costo_unitario > 0 and not costo_manual:
        comps = [CostedComponent(
            insumo_codigo="I1", insumo_nombre="CEMENTO", unidad="KG", rendimiento=1.0,
            precio_unitario=costo_unitario, fuente_precio="COSTO INTERNO",
            costo=costo_unitario)]
    return AssembledApu(
        item=item, apu_codigo=apu_codigo, apu_nombre="APU", unidad=item.unidad,
        shift="DIURNO", componentes=comps, costo_unitario=costo_unitario,
        status=MatchStatus.AUTO, confianza=1.0)


def test_agrupa_por_capitulo_en_orden_de_aparicion():
    apus = [_ens(_item("2", "PAVIMENTOS", 10, 100, 80), 60),
            _ens(_item("1", "PRELIMINARES", 5, 200, 160), 120),
            _ens(_item("2", "PAVIMENTOS", 3, 100, 80), 60)]
    res = resumen_por_capitulo(apus)
    assert [r["codigo"] for r in res] == ["2", "1"]
    assert [r["nombre"] for r in res] == ["PAVIMENTOS", "PRELIMINARES"]
    assert [r["orden"] for r in res] == [1, 2]
    assert [r["actividades"] for r in res] == [2, 1]


def test_suma_las_dos_bases_del_contractual_y_el_costo():
    apus = [_ens(_item("1", "PRELIMINARES", 10, 1351, 1056), 900),
            _ens(_item("1", "PRELIMINARES", 4, 1508, 1179), 1000)]
    r = resumen_por_capitulo(apus)[0]
    assert r["contractual"] == 10 * 1351 + 4 * 1508            # con AIU
    assert r["contractual_sin_aiu"] == 10 * 1056 + 4 * 1179    # sin AIU
    assert r["costo"] == 10 * 900 + 4 * 1000
    assert r["diferencia"] == r["contractual"] - r["costo"]
    assert abs(r["margen_pct"] - r["diferencia"] / r["contractual"]) < 1e-9


def test_sin_apu_cuenta_y_marca_el_capitulo_incompleto():
    completa = _ens(_item("1", "PRELIMINARES", 10, 100, 80), 60)
    huerfana = _ens(_item("1", "PRELIMINARES", 5, 100, 80, item="1.002"), 0.0,
                    apu_codigo=None)
    r = resumen_por_capitulo([completa, huerfana])[0]
    assert r["actividades"] == 2
    assert r["con_apu"] == 1
    assert r["sin_apu"] == 1
    assert r["completo"] is False


def test_capitulo_entero_costeado_queda_completo():
    apus = [_ens(_item("1", "PRELIMINARES", 10, 100, 80), 60),
            _ens(_item("1", "PRELIMINARES", 5, 100, 80, item="1.002"), 40)]
    r = resumen_por_capitulo(apus)[0]
    assert r["sin_apu"] == 0
    assert r["completo"] is True
    assert r["cobertura"] == 1.0
    assert r["cobertura_valor"] == 1.0


def test_cobertura_por_conteo_y_por_valor_no_son_lo_mismo():
    # Justificación de la métrica ponderada: 3 de 4 actividades costeadas (75 % por
    # conteo) pero la que falta vale el 90 % del capítulo.
    chicas = [_ens(_item("2", "PAVIMENTOS", 1, 100, 80, item=f"2.00{i}"), 60)
              for i in range(1, 4)]
    grande = _ens(_item("2", "PAVIMENTOS", 1, 2700, 2100, item="2.004"), 0.0,
                  apu_codigo=None)
    r = resumen_por_capitulo(chicas + [grande])[0]
    assert r["cobertura"] == 0.75
    assert r["cobertura_valor"] == 300 / 3000
    assert r["completo"] is False


def test_costo_puesto_a_mano_cuenta_como_costeado():
    # Misma regla que seqs_sin_apu: sin APU pero con costo declarado positivo SÍ cuenta.
    a_mano = _ens(_item("1", "PRELIMINARES", 10, 100, 80), 100.0, apu_codigo=None,
                  costo_manual=True)
    r = resumen_por_capitulo([a_mano])[0]
    assert r["sin_apu"] == 0
    assert r["costo"] == 1000


def test_items_sin_capitulo_caen_en_un_grupo_con_nombre():
    plano = LicitacionItem(item="1", descripcion="X", unidad="M2", cantidad=1.0,
                           precio_contractual=100.0, shift="DIURNO")
    r = resumen_por_capitulo([_ens(plano, 60)])[0]
    assert r["codigo"] == ""
    assert r["nombre"] == "(sin capítulo)"


def test_lista_vacia_no_revienta():
    assert resumen_por_capitulo([]) == []


def test_contractual_en_cero_no_divide_por_cero():
    gratis = _ens(_item("1", "PRELIMINARES", 10, 0, 0), 0.0, apu_codigo=None)
    r = resumen_por_capitulo([gratis])[0]
    assert r["margen_pct"] == 0.0
    assert r["cobertura_valor"] == 0.0
```

- [ ] **Step 2: Correr el test para ver que falla**

Run: `python -m pytest tests/test_resumen_capitulo.py -q`
Expected: FAIL con `ImportError: cannot import name 'resumen_por_capitulo'`

- [ ] **Step 3: Implementar**

En `apu_tool/dominio/report_categorizado.py`, después de `agrupar_por_capitulo`:

```python
SIN_CAPITULO = "(sin capítulo)"


def _costeada(a: AssembledApu) -> bool:
    """La actividad tiene costo válido. MISMA regla que `corridas.seqs_sin_apu`:
    con APU, o con un costo declarado a mano POSITIVO. Si las dos reglas divergen, el
    resumen diría que un capítulo está completo mientras el candado del cuadro lo frena."""
    return bool(a.apu_codigo) or a.costo_unitario > 0


def resumen_por_capitulo(apus: list[AssembledApu]) -> list[dict]:
    """Contractual, costo y cobertura por capítulo. LA fuente única de este cálculo.

    La consumen la API (`vista_corrida["capitulos"]`), la web (que solo pinta) y las dos
    hojas de Excel. Es deliberado: tener la misma suma en tres lados es cómo se llega a
    tres números distintos en la misma pantalla.

    Redondeo: suma `contractual_total` y `costo_total`, que YA pasaron por
    `mul_redondeado`. No redondea dos veces ni vuelve a multiplicar.

    Las actividades sin APU no se esconden: cuentan en `sin_apu`, bajan la cobertura y
    dejan el capítulo en `completo: false`, que es lo que la web usa para mostrar el
    margen como parcial en vez de como cifra definitiva.
    """
    grupos: dict[str, list[AssembledApu]] = {}
    nombres: dict[str, str] = {}
    for a in apus:
        cod = a.item.capitulo_codigo
        nombres.setdefault(cod, a.item.capitulo_nombre or SIN_CAPITULO if cod
                           else SIN_CAPITULO)
        grupos.setdefault(cod, []).append(a)

    salida: list[dict] = []
    for orden, (cod, filas) in enumerate(grupos.items(), start=1):
        contractual = sum(a.contractual_total for a in filas)
        costeadas = [a for a in filas if _costeada(a)]
        salida.append({
            "codigo": cod,
            "nombre": nombres[cod],
            "orden": orden,
            "actividades": len(filas),
            "con_apu": len(costeadas),
            "sin_apu": len(filas) - len(costeadas),
            "contractual": contractual,
            "contractual_sin_aiu": sum(a.contractual_total_sin_aiu for a in filas),
            "costo": sum(a.costo_total for a in filas),
            "diferencia": contractual - sum(a.costo_total for a in filas),
            "margen_pct": ((contractual - sum(a.costo_total for a in filas)) / contractual
                           if contractual else 0.0),
            "cobertura": (len(costeadas) / len(filas)) if filas else 0.0,
            # Ponderada por valor: un capítulo puede estar casi entero por conteo y a
            # media máquina por plata, si lo que falta son las actividades caras.
            # Medido en el archivo real: en PAVIMENTOS, 2 de 42 actividades son el 32 %
            # del capítulo; en RED DE GAS, 2 de 8 son el 57 %.
            "cobertura_valor": (sum(a.contractual_total for a in costeadas) / contractual
                                if contractual else 0.0),
            "completo": (len(costeadas) == len(filas)
                         and not any(alertas_costeo(a) for a in filas)),
        })
    return salida
```

- [ ] **Step 4: Correr el test**

Run: `python -m pytest tests/test_resumen_capitulo.py -q`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add apu_tool/dominio/report_categorizado.py tests/test_resumen_capitulo.py
git commit -m "feat(idu): resumen_por_capitulo como fuente unica del calculo"
```

---

## Task 14: Servicio — previsualizar y guardar el origen

**Files:**
- Modify: `apu_tool/servicio/corridas.py`
- Test: `tests/test_servicio_previsualizacion.py` (crear)

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_servicio_previsualizacion.py`:

```python
"""Previsualización: lee y valida SIN escribir nada en la base."""
import json

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import EntidadOrigen
from apu_tool.servicio import corridas as svc
from tests.fixtures_idu import escribir_formulario


def _almacen(tmp_path) -> Almacen:
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def test_previsualizar_no_escribe_nada(tmp_path):
    alm = _almacen(tmp_path)
    p = escribir_formulario(tmp_path / "f1.xlsx")
    antes = len(alm.corridas.listar_corridas())
    svc.previsualizar(EntidadOrigen.IDU, p.read_bytes(), "f1.xlsx")
    assert len(alm.corridas.listar_corridas()) == antes == 0


def test_previsualizar_devuelve_capitulos_totales_y_conciliacion(tmp_path):
    p = escribir_formulario(tmp_path / "f1.xlsx")
    prev = svc.previsualizar(EntidadOrigen.IDU, p.read_bytes(), "f1.xlsx")
    assert prev["entidad"] == "IDU"
    assert prev["formato"] == "idu_formulario_1"
    assert prev["hoja"] == "PROPUESTA ECONÓMICA"
    assert prev["fila_encabezado"] == 5
    assert prev["actividades"] == 5
    assert [c["codigo"] for c in prev["capitulos"]] == ["1", "2"]
    assert prev["capitulos"][0]["actividades"] == 2
    assert prev["capitulos"][0]["contractual"] > 0
    assert prev["capitulos"][0]["contractual_sin_aiu"] > 0
    assert prev["totales"]["contractual"] == sum(
        c["contractual"] for c in prev["capitulos"])
    assert prev["conciliacion"]["subtotales_ok"] is True
    assert prev["errores"] == []
    assert prev["puede_aprobar"] is True


def test_previsualizar_con_error_no_deja_aprobar(tmp_path):
    p = escribir_formulario(tmp_path / "f1.xlsx", sin_columna_cantidad=True)
    prev = svc.previsualizar(EntidadOrigen.IDU, p.read_bytes(), "f1.xlsx")
    assert prev["errores"] != []
    assert prev["puede_aprobar"] is False
    assert prev["capitulos"] == []


def test_previsualizar_con_advertencias_deja_aprobar_pero_las_muestra(tmp_path):
    p = escribir_formulario(tmp_path / "f1.xlsx", con_hoja_gemela=True)
    prev = svc.previsualizar(EntidadOrigen.IDU, p.read_bytes(), "f1.xlsx")
    assert prev["puede_aprobar"] is True
    assert any(a["tipo"] == "hoja_ambigua" for a in prev["advertencias"])


def test_previsualizar_limita_las_filas_senaladas(tmp_path):
    p = escribir_formulario(tmp_path / "f1.xlsx")
    prev = svc.previsualizar(EntidadOrigen.IDU, p.read_bytes(), "f1.xlsx")
    assert len(prev["filas_senaladas"]) <= svc.MAX_FILAS_SENALADAS


def test_previsualizar_no_devuelve_las_actividades_una_por_una(tmp_path):
    # La previa valida la ESTRUCTURA; la tabla de la corrida muestra las actividades.
    p = escribir_formulario(tmp_path / "f1.xlsx")
    prev = svc.previsualizar(EntidadOrigen.IDU, p.read_bytes(), "f1.xlsx")
    assert "items" not in prev


def test_crear_corrida_guarda_el_origen(tmp_path):
    alm = _almacen(tmp_path)
    p = escribir_formulario(tmp_path / "f1.xlsx")
    lectura = svc.leer_para_corrida(EntidadOrigen.IDU, p.read_bytes(), "f1.xlsx")
    cid = svc.crear_corrida_encolada(
        alm, "f1.xlsx", lectura.items, "DIURNO", False,
        origen=svc.origen_de(EntidadOrigen.IDU, lectura, "f1.xlsx", "yo@test.co"))
    origen = json.loads(alm.corridas.get_origen(cid))
    assert origen["entidad"] == "IDU"
    assert origen["formato"] == "idu_formulario_1"
    assert origen["hoja"] == "PROPUESTA ECONÓMICA"
    assert origen["parser_version"] == "idu-f1/1"
    assert origen["estructura_confirmada"] is True
    assert origen["confirmada_por"] == "yo@test.co"
    assert origen["capitulos"] == 2
    assert origen["actividades"] == 5
    assert origen["conciliacion"]["contractual_con_aiu"] > 0


def test_crear_corrida_sin_origen_sigue_funcionando(tmp_path):
    # El camino de la CLI/GUI y el de las entidades sin lector especializado.
    alm = _almacen(tmp_path)
    from apu_tool.nucleo.models import LicitacionItem
    items = [LicitacionItem(item="1", descripcion="X", unidad="M2", cantidad=1.0,
                            precio_contractual=100.0, shift="DIURNO")]
    cid = svc.crear_corrida_encolada(alm, "plana.xlsx", items, "DIURNO", False)
    assert alm.corridas.get_origen(cid) is None
    assert alm.corridas.get_corrida(cid).origen is None
```

- [ ] **Step 2: Correr el test para ver que falla**

Run: `python -m pytest tests/test_servicio_previsualizacion.py -q`
Expected: FAIL con `AttributeError: module 'apu_tool.servicio.corridas' has no attribute 'previsualizar'`

- [ ] **Step 3: Implementar**

En `apu_tool/servicio/corridas.py`, agregar los imports:

```python
import os
import tempfile

from apu_tool.dominio import entrada
from apu_tool.dominio.presupuesto import LecturaPresupuesto
from apu_tool.dominio.report_categorizado import resumen_por_capitulo
from apu_tool.nucleo.models import EntidadOrigen
from apu_tool.nucleo.redondeo import mul_redondeado
```

Y este bloque, después de `nombre_desde_archivo`:

```python
# Cuántas filas con problema viajan en la previsualización. La previa valida la
# ESTRUCTURA (14 capítulos, 1939 actividades, conciliación), no reemplaza a la tabla de
# la corrida: mandar 1939 filas para que el usuario mire 3 es pagar medio mega por nada.
MAX_FILAS_SENALADAS = 50


def leer_para_corrida(entidad: EntidadOrigen, contenido: bytes,
                      nombre_archivo: str) -> LecturaPresupuesto:
    """Bytes subidos -> LecturaPresupuesto, con el lector de esa entidad.

    El archivo se escribe a un temporal porque openpyxl necesita una ruta; se borra
    siempre. El archivo subido NO se persiste (igual que en el camino de hoy): lo que
    sobrevive es `plan_json`, que es de donde se reanuda el armado.
    """
    sufijo = Path(nombre_archivo or "presupuesto.xlsx").suffix or ".xlsx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=sufijo) as tmp:
        tmp.write(contenido)
        ruta = tmp.name
    try:
        return entrada.leer(entidad, ruta)
    finally:
        os.unlink(ruta)


def previsualizar(entidad: EntidadOrigen, contenido: bytes,
                  nombre_archivo: str) -> dict:
    """Qué se detectó en el archivo, SIN escribir una sola fila.

    Es el paso que el usuario aprueba. No hay borrador ni estado temporal en la base: el
    navegador se queda con el archivo y lo reenvía al aprobar, y el parser es
    determinístico, así que la segunda lectura da lo mismo. Cancelar no deja nada que
    limpiar porque nunca hubo nada.
    """
    lectura = leer_para_corrida(entidad, contenido, nombre_archivo)
    capitulos = _capitulos_de_lectura(lectura)
    return {
        "entidad": entidad.value,
        "formato": entrada.formato_de(entidad),
        "archivo": nombre_archivo,
        "hoja": lectura.hoja,
        "fila_encabezado": lectura.fila_encabezado,
        "parser_version": lectura.parser_version,
        "capitulos": capitulos,
        "actividades": len(lectura.items),
        "filas_ignoradas": lectura.filas_ignoradas,
        "totales": {
            "contractual": sum(c["contractual"] for c in capitulos),
            "contractual_sin_aiu": sum(c["contractual_sin_aiu"] for c in capitulos),
        },
        "conciliacion": lectura.conciliacion,
        "errores": list(lectura.errores),
        "advertencias": [a.to_dict() for a in lectura.advertencias],
        "filas_senaladas": [a.to_dict() for a in lectura.advertencias
                            if a.fila][:MAX_FILAS_SENALADAS],
        # El servidor decide si se puede aprobar; el botón del navegador solo obedece.
        # `POST /corridas` lo vuelve a evaluar al crear: el cliente puede mentir.
        "puede_aprobar": not lectura.errores and bool(lectura.items),
        "requiere_confirmacion": entrada.requiere_confirmacion(entidad),
    }


def _capitulos_de_lectura(lectura: LecturaPresupuesto) -> list[dict]:
    """Capítulos con sus totales contractuales, para la previsualización.

    Acá todavía NO hay costo (nada está armado), así que no se puede usar
    `resumen_por_capitulo`, que trabaja sobre `AssembledApu`. Lo que sí se comparte es la
    regla de redondeo: `mul_redondeado`, la misma que usará el armado.
    """
    por_codigo: dict[str, dict] = {}
    for cap in lectura.capitulos:
        por_codigo[cap.codigo] = {**cap.to_dict(), "actividades": 0,
                                  "contractual": 0, "contractual_sin_aiu": 0}
    for it in lectura.items:
        fila = por_codigo.get(it.capitulo_codigo)
        if fila is None:
            fila = por_codigo.setdefault(it.capitulo_codigo, {
                "codigo": it.capitulo_codigo, "nombre": it.capitulo_nombre or
                "(sin capítulo)", "orden": len(por_codigo) + 1, "fila_origen": 0,
                "actividades": 0, "contractual": 0, "contractual_sin_aiu": 0})
        fila["actividades"] += 1
        fila["contractual"] += mul_redondeado(it.precio_contractual, it.cantidad)
        fila["contractual_sin_aiu"] += mul_redondeado(
            it.precio_contractual_sin_aiu, it.cantidad)
    return list(por_codigo.values())


def origen_de(entidad: EntidadOrigen, lectura: LecturaPresupuesto,
              nombre_archivo: str, confirmada_por: Optional[str]) -> dict:
    """El registro de importación que se guarda en `corrida.origen_json`.

    Una sola columna y no ocho, como `plan_json`: la migración es una línea por backend.
    Lleva la conciliación adentro, o sea DINERO, y por eso `origen_json` está en
    `privacy._FORBIDDEN_KEYS` — este objeto nunca cruza hacia la IA.
    """
    return {
        "entidad": entidad.value,
        "formato": entrada.formato_de(entidad),
        "archivo": nombre_archivo,
        "hoja": lectura.hoja,
        "fila_encabezado": lectura.fila_encabezado,
        "parser_version": lectura.parser_version,
        "importada_en": datetime.now().isoformat(timespec="seconds"),
        "confirmada_por": confirmada_por or "",
        "estructura_confirmada": True,
        "capitulos": len(lectura.capitulos),
        "actividades": len(lectura.items),
        "filas_ignoradas": lectura.filas_ignoradas,
        "advertencias": _contar_advertencias(lectura),
        "conciliacion": dict(lectura.conciliacion),
    }


def _contar_advertencias(lectura: LecturaPresupuesto) -> dict:
    """{tipo: cuántas}. El detalle de cada una no se persiste: la previa ya lo mostró y
    el usuario ya lo confirmó; lo que importa después es que quede el rastro de que las
    hubo y de cuántas."""
    conteo: dict[str, int] = {}
    for a in lectura.advertencias:
        conteo[a.tipo] = conteo.get(a.tipo, 0) + 1
    return conteo
```

- [ ] **Step 4: Guardar el origen al crear la corrida**

En `crear_corrida_encolada`, agregar el parámetro y la escritura:

```python
def crear_corrida_encolada(alm: Almacen, archivo: str, items: list[LicitacionItem],
                           turno_def: str, use_ai: Optional[bool],
                           carpeta_id: Optional[int] = None,
                           nombre: Optional[str] = None,
                           lista_precios_id: Optional[int] = None,
                           origen: Optional[dict] = None) -> int:
```

y justo después del `alm.corridas.set_plan(...)` que ya está:

```python
    if origen is not None:
        # Igual que el plan: una escritura aparte en vez de ensuciar el INSERT de los
        # dos backends. Va DESPUÉS del plan a propósito — si esto falla, la corrida
        # queda armable; al revés quedaría con sello de origen y sin qué armar.
        alm.corridas.set_origen(corrida_id, json.dumps(origen, ensure_ascii=False))
```

- [ ] **Step 5: Correr el test**

Run: `python -m pytest tests/test_servicio_previsualizacion.py -q`
Expected: PASS (8 passed)

- [ ] **Step 6: Commit**

```bash
git add apu_tool/servicio/corridas.py tests/test_servicio_previsualizacion.py
git commit -m "feat(idu): previsualizacion sin persistencia y origen de la corrida"
```

---

## Task 15: La vista de la corrida con capítulos

**Files:**
- Modify: `apu_tool/servicio/corridas.py` (`_vista_item`, `vista_corrida`)
- Test: `tests/test_servicio_corridas_capitulos.py` (crear)

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_servicio_corridas_capitulos.py`:

```python
"""La vista de una corrida IDU trae capítulos; la de una plana, no."""
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import EntidadOrigen, LicitacionItem
from apu_tool.servicio import corridas as svc
from tests.fixtures_idu import escribir_formulario


def _almacen(tmp_path) -> Almacen:
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def _corrida_idu(tmp_path, alm) -> int:
    p = escribir_formulario(tmp_path / "f1.xlsx")
    lec = svc.leer_para_corrida(EntidadOrigen.IDU, p.read_bytes(), "f1.xlsx")
    return svc.construir_corrida(
        alm, "f1.xlsx", lec.items, "DIURNO", False,
        origen=svc.origen_de(EntidadOrigen.IDU, lec, "f1.xlsx", "yo@test.co"))


def test_la_vista_trae_el_resumen_por_capitulo(tmp_path):
    alm = _almacen(tmp_path)
    vista = svc.vista_corrida(alm, _corrida_idu(tmp_path, alm))
    assert [c["codigo"] for c in vista["capitulos"]] == ["1", "2"]
    assert vista["capitulos"][0]["actividades"] == 2
    assert vista["capitulos"][0]["contractual"] > 0
    assert vista["capitulos"][0]["costo"] == 0        # biblioteca vacía: nada costeado
    assert vista["capitulos"][0]["sin_apu"] == 2
    assert vista["capitulos"][0]["completo"] is False


def test_la_vista_trae_el_origen(tmp_path):
    alm = _almacen(tmp_path)
    vista = svc.vista_corrida(alm, _corrida_idu(tmp_path, alm))
    assert vista["origen"]["entidad"] == "IDU"
    assert vista["origen"]["hoja"] == "PROPUESTA ECONÓMICA"


def test_cada_item_trae_su_capitulo_y_las_dos_bases(tmp_path):
    alm = _almacen(tmp_path)
    vista = svc.vista_corrida(alm, _corrida_idu(tmp_path, alm))
    fila = vista["items"][0]
    assert fila["capitulo_codigo"] == "1"
    assert fila["capitulo_nombre"] == "PRELIMINARES"
    assert fila["item_pago_original"] == "1.001"
    assert fila["precio_contractual"] == 1351
    assert fila["precio_contractual_sin_aiu"] == 1056
    assert fila["contractual_total"] == 100 * 1351
    assert fila["contractual_total_sin_aiu"] == 100 * 1056


def test_una_corrida_plana_no_trae_capitulos_ni_origen(tmp_path):
    alm = _almacen(tmp_path)
    items = [LicitacionItem(item="1", descripcion="X", unidad="M2", cantidad=1.0,
                            precio_contractual=100.0, shift="DIURNO")]
    cid = svc.construir_corrida(alm, "plana.xlsx", items, "DIURNO", False)
    vista = svc.vista_corrida(alm, cid)
    assert vista["capitulos"] == []
    assert vista["origen"] is None
    assert vista["items"][0]["capitulo_codigo"] == ""


def test_los_capitulos_conservan_orden_y_asociacion_al_releer(tmp_path):
    alm = _almacen(tmp_path)
    cid = _corrida_idu(tmp_path, alm)
    primera = svc.vista_corrida(alm, cid)["capitulos"]
    # Otra instancia del almacén: se lee de disco, no de memoria.
    alm2 = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                   corridas_path=tmp_path / "c.db")
    segunda = svc.vista_corrida(alm2, cid)["capitulos"]
    assert primera == segunda
    assert [c["orden"] for c in segunda] == [1, 2]
```

- [ ] **Step 2: Correr el test para ver que falla**

Run: `python -m pytest tests/test_servicio_corridas_capitulos.py -q`
Expected: FAIL con `TypeError: construir_corrida() got an unexpected keyword argument 'origen'`

- [ ] **Step 3: Implementar**

En `apu_tool/servicio/corridas.py`:

`construir_corrida` pasa el origen:

```python
def construir_corrida(alm: Almacen, archivo: str, items: list[LicitacionItem],
                      turno_def: str, use_ai: Optional[bool],
                      carpeta_id: Optional[int] = None,
                      nombre: Optional[str] = None,
                      lista_precios_id: Optional[int] = None,
                      origen: Optional[dict] = None) -> int:
    corrida_id = crear_corrida_encolada(alm, archivo, items, turno_def, use_ai,
                                        carpeta_id, nombre, lista_precios_id, origen)
```

`_vista_item` gana cinco claves (dentro del `return`, junto a `precio_contractual`):

```python
        # --- ruta IDU: capítulo y la segunda base del contractual ----------------
        # Vacíos en una corrida plana; el frontend esconde la columna cuando lo están.
        "capitulo_codigo": ens.item.capitulo_codigo,
        "capitulo_nombre": ens.item.capitulo_nombre,
        "item_pago_original": ens.item.item_pago_original,
        "precio_contractual_sin_aiu": ens.item.precio_contractual_sin_aiu,
        "contractual_total_sin_aiu": ens.contractual_total_sin_aiu,
```

`vista_corrida` gana dos claves (en su `return`):

```python
        # Resumen por capítulo, calculado por la ÚNICA función que lo hace
        # (dominio/report_categorizado.resumen_por_capitulo). El frontend solo pinta:
        # no suma dinero. `[]` cuando la corrida no tiene capítulos.
        "capitulos": (resumen_por_capitulo(ensambles)
                      if any(e.item.capitulo_codigo for e in ensambles) else []),
        # De dónde salió el presupuesto. None en corridas anteriores a la ruta IDU:
        # la pantalla lo muestra como "sin clasificación por capítulo".
        "origen": meta.origen,
```

- [ ] **Step 4: Correr el test**

Run: `python -m pytest tests/test_servicio_corridas_capitulos.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Correr la suite completa**

Run: `python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apu_tool/servicio/corridas.py tests/test_servicio_corridas_capitulos.py
git commit -m "feat(idu): capitulos y origen en la vista de la corrida"
```

---

## Task 16: Endpoints

**Files:**
- Modify: `apu_tool/servicio/rutas.py:146-215`
- Test: `tests/test_api_idu.py` (crear)

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_api_idu.py`:

```python
"""Los endpoints de la ruta IDU: previsualizar y crear con confirmación."""
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.servicio.app import create_app
from tests.conftest import cliente
from tests.fixtures_idu import escribir_formulario


@pytest.fixture
def app_y_alm(tmp_path, monkeypatch):
    monkeypatch.setenv("APU_RATELIMIT_ENABLED", "false")
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    # Biblioteca mínima para que `_asegurar_biblioteca` no rebote.
    from apu_tool.nucleo.models import Apu
    alm.apus.insert_apus([Apu(codigo="3007", nombre="REPLANTEO GENERAL",
                              unidad="M2", shift="DIURNO")])
    app = create_app()
    app.state.almacen = alm
    return app, alm


def _carpeta(alm) -> int:
    from apu_tool.servicio import carpetas as carpetas_svc
    return carpetas_svc.carpeta_sin_clasificar_id(alm)


def _subida(tmp_path, **kw):
    p = escribir_formulario(tmp_path / "f1.xlsx", **kw)
    return {"archivo": ("f1.xlsx", p.read_bytes(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}


def test_previsualizar_devuelve_la_estructura(app_y_alm, tmp_path):
    app, _alm = app_y_alm
    c = cliente(app, "consulta")
    r = c.post("/api/corridas/previsualizar", data={"entidad": "IDU"},
               files=_subida(tmp_path))
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["actividades"] == 5
    assert len(cuerpo["capitulos"]) == 2
    assert cuerpo["puede_aprobar"] is True


def test_previsualizar_no_crea_ninguna_corrida(app_y_alm, tmp_path):
    app, alm = app_y_alm
    c = cliente(app, "consulta")
    c.post("/api/corridas/previsualizar", data={"entidad": "IDU"}, files=_subida(tmp_path))
    assert alm.corridas.listar_corridas() == []


def test_previsualizar_rechaza_una_entidad_inventada(app_y_alm, tmp_path):
    app, _alm = app_y_alm
    c = cliente(app, "consulta")
    r = c.post("/api/corridas/previsualizar", data={"entidad": "ALCALDIA DE CHIA"},
               files=_subida(tmp_path))
    assert r.status_code == 400
    assert "Entidad desconocida" in r.json()["detail"]


def test_crear_idu_sin_confirmar_es_400(app_y_alm, tmp_path):
    app, alm = app_y_alm
    c = cliente(app, "consulta")
    r = c.post("/api/corridas",
               data={"entidad": "IDU", "carpeta_id": _carpeta(alm), "turno": "DIURNO"},
               files=_subida(tmp_path))
    assert r.status_code == 400
    assert "confirm" in r.json()["detail"].lower()
    assert alm.corridas.listar_corridas() == []


def test_crear_idu_confirmada_encola_y_sella_el_origen(app_y_alm, tmp_path):
    app, alm = app_y_alm
    c = cliente(app, "consulta")
    r = c.post("/api/corridas",
               data={"entidad": "IDU", "confirmada": "true",
                     "carpeta_id": _carpeta(alm), "turno": "DIURNO"},
               files=_subida(tmp_path))
    assert r.status_code == 200
    cid = r.json()["id"]
    assert r.json()["estado"] == "armando"
    import json
    assert json.loads(alm.corridas.get_origen(cid))["entidad"] == "IDU"


def test_crear_idu_con_error_bloqueante_es_400_aunque_diga_confirmada(app_y_alm, tmp_path):
    # El cliente puede mentir con `confirmada=true`: el servidor relee y revalida.
    app, alm = app_y_alm
    c = cliente(app, "consulta")
    r = c.post("/api/corridas",
               data={"entidad": "IDU", "confirmada": "true",
                     "carpeta_id": _carpeta(alm), "turno": "DIURNO"},
               files=_subida(tmp_path, sin_columna_cantidad=True))
    assert r.status_code == 400
    assert "falta_columna" in r.json()["detail"]
    assert alm.corridas.listar_corridas() == []


def test_el_doble_clic_no_crea_dos_corridas(app_y_alm, tmp_path):
    app, alm = app_y_alm
    c = cliente(app, "consulta")
    datos = {"entidad": "IDU", "confirmada": "true",
             "carpeta_id": _carpeta(alm), "turno": "DIURNO"}
    primera = c.post("/api/corridas", data=datos, files=_subida(tmp_path))
    segunda = c.post("/api/corridas", data=datos, files=_subida(tmp_path))
    assert primera.status_code == 200
    assert segunda.status_code == 409
    assert segunda.json()["detail"]["corrida_id"] == primera.json()["id"]
    assert len(alm.corridas.listar_corridas()) == 1


def test_sin_entidad_el_endpoint_se_comporta_como_siempre(app_y_alm, tmp_path):
    # Compatibilidad: el formulario viejo no manda `entidad` y sigue funcionando.
    import openpyxl
    app, alm = app_y_alm
    p = tmp_path / "plana.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["ITEM", "DESCRIPCION", "UNIDAD", "CANTIDAD", "PRECIO", "TURNO"])
    ws.append(["1", "REPLANTEO GENERAL", "M2", 10, 1000, "DIURNO"])
    wb.save(p)
    r = c = cliente(app, "consulta").post(
        "/api/corridas", data={"carpeta_id": _carpeta(alm), "turno": "DIURNO"},
        files={"archivo": ("plana.xlsx", p.read_bytes(),
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200
    assert alm.corridas.get_origen(r.json()["id"]) is None
```

- [ ] **Step 2: Correr el test para ver que falla**

Run: `python -m pytest tests/test_api_idu.py -q`
Expected: FAIL — 404 en `/api/corridas/previsualizar`.

- [ ] **Step 3: Implementar**

En `apu_tool/servicio/rutas.py`, agregar los imports:

```python
from apu_tool.dominio import entrada
```

Reemplazar `_items_del_upload` por una versión que use el registro (misma responsabilidad,
un parámetro más):

```python
def _leer_upload(entidad, nombre: str, contenido: bytes, turno: str):
    """Bytes de un archivo subido -> LecturaPresupuesto, con el lector de la entidad.

    A diferencia de la versión anterior, NO levanta HTTPException por un problema de
    contenido: la lectura devuelve `errores` y cada endpoint decide qué hacer con ellos
    (la previa los muestra, la creación responde 400). La única traducción que queda es
    la de una entidad inválida, que sí es un error de la petición.
    """
    return svc.leer_para_corrida(entidad, contenido, nombre)


def _entidad_o_400(valor):
    try:
        return entrada.parse_entidad(valor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

Agregar el endpoint de previsualización, justo antes de `@router.post("/corridas")`:

```python
@router.post("/corridas/previsualizar")
async def previsualizar_corrida(entidad: str = Form(...),
                                archivo: UploadFile = File(...),
                                _: object = Depends(requiere_rol("consulta"))):
    """Qué se detectó en el archivo. NO escribe nada: no hay borrador que limpiar.

    El navegador se queda con el archivo y lo reenvía al aprobar; el parser es
    determinístico, así que la segunda lectura da la misma estructura. Si diera otra,
    `POST /corridas` responde 400, que es la respuesta correcta.
    """
    ent = _entidad_o_400(entidad)
    return svc.previsualizar(ent, await archivo.read(), archivo.filename or "archivo.xlsx")
```

Y reescribir `crear_corrida`:

```python
@router.post("/corridas")
async def crear_corrida(turno: str = Form(config.SHIFT_DIURNO),
                        use_ai: Optional[bool] = Form(None),
                        carpeta_id: int = Form(...),
                        nombre: Optional[str] = Form(None),
                        lista_id: Optional[int] = Form(None),
                        entidad: str = Form("NO_IDENTIFICADA"),
                        confirmada: bool = Form(False),
                        archivo: UploadFile = File(...),
                        alm: Almacen = Depends(get_almacen),
                        actor: object = Depends(requiere_rol("consulta"))):
    if alm.carpetas.get(carpeta_id) is None:
        raise HTTPException(status_code=400, detail="La carpeta indicada no existe.")
    _validar_lista(alm, lista_id)
    _asegurar_biblioteca(alm)
    ent = _entidad_o_400(entidad)
    if entrada.requiere_confirmacion(ent) and not confirmada:
        # La estructura tiene que pasar por la pantalla de previsualización. Sin esto,
        # un POST directo saltaría la única revisión humana de 14 capítulos y 1939 filas.
        raise HTTPException(
            status_code=400,
            detail="La estructura detectada debe confirmarse antes de crear la corrida. "
                   "Previsualiza el archivo y aprueba el resumen.")
    nombre_archivo = archivo.filename or "licitacion"
    lectura = _leer_upload(ent, nombre_archivo, await archivo.read(), turno)
    if lectura.errores:
        # El servidor RELEE y revalida: `confirmada=true` es lo que dice el cliente, no
        # una prueba. Un archivo distinto al que se previsualizó rebota acá.
        raise HTTPException(status_code=400, detail=" ".join(lectura.errores))
    origen = (svc.origen_de(ent, lectura, nombre_archivo, getattr(actor, "email", ""))
              if entrada.requiere_confirmacion(ent) else None)
    return _encolar(alm, nombre_archivo, lectura.items, turno, use_ai,
                    carpeta_id=carpeta_id, nombre=nombre, lista_precios_id=lista_id,
                    origen=origen)
```

Y `_encolar` pasa el origen a través de `**kw` (ya lo hace: `svc.crear_corrida_encolada(...)`
recibe `**kw`; verificá que `origen` viaje).

Ajustar `crear_sample` para que siga compilando: usa `read_licitacion` directo, que no
cambió; no toques nada ahí.

- [ ] **Step 4: Correr el test**

Run: `python -m pytest tests/test_api_idu.py -q`
Expected: PASS (8 passed)

- [ ] **Step 5: Correr los tests de API existentes**

Run: `python -m pytest tests/test_api_corridas.py tests/test_api_autorizacion.py tests/test_endurecimiento_excel.py tests/test_endurecimiento_subida.py -q`
Expected: PASS. Si alguno esperaba el `HTTPException` de `_items_del_upload`, ahora el
mismo mensaje sale del 400 de `crear_corrida`: ajustá el test al camino nuevo, no la ruta.

- [ ] **Step 6: Correr la suite completa**

Run: `python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add apu_tool/servicio/rutas.py tests/test_api_idu.py
git commit -m "feat(idu): endpoints de previsualizacion y creacion confirmada"
```

---

# Fase 6 — Reporte

## Task 17: Hoja `RESUMEN POR CAPÍTULO` en el cuadro de la web

**Files:**
- Modify: `apu_tool/dominio/report.py`
- Modify: `apu_tool/dominio/report_categorizado.py` (`_build_resumen_capitulo` deja de calcular)
- Test: `tests/test_report_capitulos.py` (crear)

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_report_capitulos.py`:

```python
"""El cuadro gana una hoja por capítulo — y SOLO cuando hay capítulos."""
import openpyxl

from apu_tool.dominio.report import write_report
from apu_tool.dominio.report_categorizado import write_report_categorizado
from apu_tool.nucleo.models import (
    AssembledApu, CostedComponent, LicitacionItem, MatchStatus,
)

HOJA = "RESUMEN POR CAPÍTULO"


def _item(cap_cod="", cap_nom="", cant=10.0, con_aiu=1351.0, sin_aiu=1056.0,
          item="1.001"):
    return LicitacionItem(
        item=item, descripcion=f"ACT {item}", unidad="M2", cantidad=cant,
        precio_contractual=con_aiu, precio_contractual_sin_aiu=sin_aiu,
        shift="DIURNO", categoria=(f"{cap_cod} · {cap_nom}" if cap_cod else ""),
        capitulo_codigo=cap_cod, capitulo_nombre=cap_nom, item_pago_original=item)


def _ens(item, costo=900.0, apu_codigo="A1"):
    comps = [CostedComponent(insumo_codigo="I1", insumo_nombre="CEMENTO", unidad="KG",
                             rendimiento=1.0, precio_unitario=costo,
                             fuente_precio="COSTO INTERNO", costo=costo)] if costo else []
    return AssembledApu(item=item, apu_codigo=apu_codigo, apu_nombre="APU",
                        unidad="M2", shift="DIURNO", componentes=comps,
                        costo_unitario=costo, status=MatchStatus.AUTO, confianza=1.0)


def _hojas(path) -> list[str]:
    wb = openpyxl.load_workbook(path)
    nombres = wb.sheetnames
    wb.close()
    return nombres


def test_una_corrida_plana_produce_el_cuadro_de_siempre(tmp_path):
    out = tmp_path / "plano.xlsx"
    write_report([_ens(_item())], out)
    assert _hojas(out) == ["RESUMEN", "DESGLOSE", "ALERTAS", "INFO"]


def test_una_corrida_con_capitulos_gana_la_hoja(tmp_path):
    out = tmp_path / "cap.xlsx"
    write_report([_ens(_item("1", "PRELIMINARES")),
                  _ens(_item("2", "PAVIMENTOS", item="2.001"))], out)
    assert HOJA in _hojas(out)


def test_la_hoja_trae_las_columnas_pedidas(tmp_path):
    out = tmp_path / "cap.xlsx"
    write_report([_ens(_item("1", "PRELIMINARES")),
                  _ens(_item("1", "PRELIMINARES", item="1.002"), costo=0.0,
                       apu_codigo=None)], out)
    wb = openpyxl.load_workbook(out)
    ws = wb[HOJA]
    encabezados = [c.value for c in ws[1]]
    for esperado in ("Capítulo", "Nombre", "Actividades", "Con APU", "Sin APU",
                     "Contractual", "Contractual sin AIU", "Costo interno",
                     "Diferencia", "Margen %", "Cobertura", "Estado"):
        assert esperado in encabezados
    fila = [c.value for c in ws[2]]
    assert fila[encabezados.index("Capítulo")] == "1"
    assert fila[encabezados.index("Actividades")] == 2
    assert fila[encabezados.index("Sin APU")] == 1
    assert fila[encabezados.index("Estado")] == "Incompleto"
    wb.close()


def test_el_gran_total_de_la_hoja_cuadra_con_los_items(tmp_path):
    out = tmp_path / "cap.xlsx"
    apus = [_ens(_item("1", "PRELIMINARES")),
            _ens(_item("2", "PAVIMENTOS", cant=4.0, item="2.001"))]
    write_report(apus, out)
    wb = openpyxl.load_workbook(out)
    ws = wb[HOJA]
    total_hoja = ws.cell(row=ws.max_row, column=6).value      # columna Contractual
    wb.close()
    assert total_hoja == sum(a.contractual_total for a in apus)


def test_el_cuadro_categorizado_usa_la_misma_funcion(tmp_path):
    # Si los dos escritores calcularan por su cuenta, este test sería el que avisa.
    from apu_tool.dominio.report_categorizado import resumen_por_capitulo
    apus = [_ens(_item("1", "PRELIMINARES")),
            _ens(_item("2", "PAVIMENTOS", cant=4.0, item="2.001"))]
    esperado = resumen_por_capitulo(apus)
    out = tmp_path / "categorizado.xlsx"
    write_report_categorizado(apus, out)
    wb = openpyxl.load_workbook(out)
    ws = wb["RESUMEN POR CAPÍTULO"]
    encabezados = [c.value for c in ws[1]]
    col_contractual = encabezados.index("Contractual") + 1
    leidos = [ws.cell(row=r, column=col_contractual).value
              for r in range(2, 2 + len(esperado))]
    wb.close()
    assert leidos == [c["contractual"] for c in esperado]
```

- [ ] **Step 2: Correr el test para ver que falla**

Run: `python -m pytest tests/test_report_capitulos.py -q`
Expected: FAIL — `write_report` no escribe la hoja.

- [ ] **Step 3: Implementar la hoja compartida**

En `apu_tool/dominio/report_categorizado.py`, reemplazar `_build_resumen_capitulo` por una
versión que **consume** `resumen_por_capitulo` en vez de calcular:

```python
HOJA_CAPITULOS = "RESUMEN POR CAPÍTULO"

_COLUMNAS_CAPITULO = ["Capítulo", "Nombre", "Actividades", "Con APU", "Sin APU",
                      "Contractual", "Contractual sin AIU", "Costo interno",
                      "Diferencia", "Margen %", "Cobertura", "Cobertura $", "Estado"]


def escribir_hoja_capitulos(ws, apus: list[AssembledApu]) -> None:
    """La hoja RESUMEN POR CAPÍTULO. La escriben los DOS cuadros (report.py y este).

    No calcula: consume `resumen_por_capitulo`, la única función que suma por capítulo.
    Antes esta hoja tenía su propia suma; tenerla acá y en la API era el camino directo
    a dos números distintos para la misma corrida.
    """
    ws.append(_COLUMNAS_CAPITULO)
    _style_header(ws, 1, len(_COLUMNAS_CAPITULO))
    ws.freeze_panes = "A2"

    filas = resumen_por_capitulo(apus)
    for c in filas:
        ws.append([c["codigo"], c["nombre"], c["actividades"], c["con_apu"],
                   c["sin_apu"], c["contractual"], c["contractual_sin_aiu"],
                   c["costo"], c["diferencia"], c["margen_pct"], c["cobertura"],
                   c["cobertura_valor"],
                   "Completo" if c["completo"] else "Incompleto"])
        r = ws.max_row
        for col in (6, 7, 8, 9):
            ws.cell(row=r, column=col).number_format = _MONEY
        for col in (10, 11, 12):
            ws.cell(row=r, column=col).number_format = _PCT
        if not c["completo"]:
            # El capítulo tiene actividades sin costear: el margen NO es definitivo y
            # la fila se pinta para que no se lea como si lo fuera.
            for col in range(1, len(_COLUMNAS_CAPITULO) + 1):
                ws.cell(row=r, column=col).fill = _WARN_FILL

    contractual = sum(c["contractual"] for c in filas)
    costo = sum(c["costo"] for c in filas)
    ws.append(["", "GRAN TOTAL", sum(c["actividades"] for c in filas),
               sum(c["con_apu"] for c in filas), sum(c["sin_apu"] for c in filas),
               contractual, sum(c["contractual_sin_aiu"] for c in filas), costo,
               contractual - costo,
               ((contractual - costo) / contractual) if contractual else 0.0,
               "", "", "Completo" if all(c["completo"] for c in filas) else "Incompleto"])
    r = ws.max_row
    for col in (6, 7, 8, 9):
        celda = ws.cell(row=r, column=col)
        celda.number_format = _MONEY
        celda.font = Font(bold=True)
    ws.cell(row=r, column=10).number_format = _PCT
    for col in range(1, len(_COLUMNAS_CAPITULO) + 1):
        ws.cell(row=r, column=col).fill = _TOTAL_FILL
    ws.cell(row=r, column=2).font = Font(bold=True)
    _autosize(ws, {1: 10, 2: 42, 3: 12, 4: 10, 5: 10, 6: 18, 7: 18, 8: 16,
                   9: 16, 10: 10, 11: 11, 12: 12, 13: 12})


def hay_capitulos(apus: list[AssembledApu]) -> bool:
    """Al menos una actividad trae capítulo. Es la condición para escribir la hoja."""
    return any(a.item.capitulo_codigo for a in apus)
```

Y en `write_report_categorizado`, cambiar la primera hoja:

```python
    escribir_hoja_capitulos(wb.active, apus)
    wb.active.title = HOJA_CAPITULOS
```

- [ ] **Step 4: Agregar la hoja a `write_report`**

En `apu_tool/dominio/report.py`, dentro de `write_report`, después de crear ALERTAS y
antes de INFO:

```python
    # Solo si la corrida trae capítulos (ruta IDU). Una corrida plana produce el mismo
    # cuadro de siempre, hoja por hoja: no se le agrega una pestaña vacía.
    from apu_tool.dominio.report_categorizado import (
        HOJA_CAPITULOS, escribir_hoja_capitulos, hay_capitulos)
    if hay_capitulos(apus):
        escribir_hoja_capitulos(wb.create_sheet(HOJA_CAPITULOS), apus)
```

> El import va **adentro** de la función a propósito: `report_categorizado` importa de
> `report` (los estilos), y a nivel de módulo sería un ciclo.

- [ ] **Step 5: Correr el test**

Run: `python -m pytest tests/test_report_capitulos.py -q`
Expected: PASS (5 passed)

- [ ] **Step 6: Correr los tests de reporte existentes**

Run: `python -m pytest tests/test_report_categorizado.py tests/test_report_categorizado_alertas.py tests/test_report_alertas_costeo.py tests/test_report_lista.py -q`
Expected: PASS

- [ ] **Step 7: Correr la suite completa**

Run: `python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add apu_tool/dominio/report.py apu_tool/dominio/report_categorizado.py tests/test_report_capitulos.py
git commit -m "feat(idu): hoja RESUMEN POR CAPITULO en el cuadro, con calculo unico"
```

---

## Task 18: Columnas sin AIU en las hojas de detalle

**Files:**
- Modify: `apu_tool/dominio/report.py` (`_build_resumen`)
- Modify: `apu_tool/dominio/report_categorizado.py` (`_build_detalle`)
- Test: `tests/test_report_capitulos.py`

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_report_capitulos.py`:

```python
def test_la_hoja_resumen_trae_las_dos_bases(tmp_path):
    out = tmp_path / "cap.xlsx"
    write_report([_ens(_item("1", "PRELIMINARES"))], out)
    wb = openpyxl.load_workbook(out)
    ws = wb["RESUMEN"]
    encabezados = [c.value for c in ws[1]]
    assert "P. Contractual sin AIU" in encabezados
    assert "Total Contractual sin AIU" in encabezados
    fila = [c.value for c in ws[2]]
    assert fila[encabezados.index("P. Contractual sin AIU")] == 1056
    assert fila[encabezados.index("Total Contractual sin AIU")] == 10 * 1056
    wb.close()


def test_el_detalle_categorizado_trae_las_dos_bases(tmp_path):
    out = tmp_path / "categorizado.xlsx"
    write_report_categorizado([_ens(_item("1", "PRELIMINARES"))], out)
    wb = openpyxl.load_workbook(out)
    encabezados = [c.value for c in wb["DETALLE"][1]]
    assert "P. Contractual sin AIU" in encabezados
    assert "Total Contractual sin AIU" in encabezados
    wb.close()
```

- [ ] **Step 2: Correr el test para ver que falla**

Run: `python -m pytest tests/test_report_capitulos.py -q`
Expected: FAIL — las columnas no existen.

- [ ] **Step 3: Implementar en `report.py::_build_resumen`**

Las dos columnas nuevas quedan en las posiciones **6** y **11** (1-based), y eso corre
todos los índices posteriores. Reemplazá el encabezado y el cuerpo del bucle por esto,
completo — no lo edites a mano columna por columna, que es donde se rompe esta hoja:

```python
def _build_resumen(ws, apus: list[AssembledApu]) -> None:
    headers = ["Ítem", "Descripción", "Und", "Cantidad",
               "P. Contractual", "P. Contractual sin AIU",
               "Costo Unit.", "Margen Unit.", "Margen %",
               "Total Contractual", "Total Contractual sin AIU",
               "Total Costo", "Margen Total",
               "Estado", "Confianza", "APU base"]
    ws.append(headers)
    _style_header(ws, 1, len(headers))
    ws.freeze_panes = "A2"

    for a in apus:
        ws.append([
            a.item.item, a.item.descripcion, a.unidad, a.item.cantidad,
            a.item.precio_contractual, a.item.precio_contractual_sin_aiu,
            a.costo_unitario, a.margen_unitario, a.margen_pct,
            a.contractual_total, a.contractual_total_sin_aiu,
            a.costo_total, a.margen_total,
            _STATUS_LABEL.get(a.status, a.status), round(a.confianza, 2),
            a.apu_codigo or "",
        ])
        r = ws.max_row
        ws.cell(row=r, column=4).number_format = _REND
        for col in (5, 6, 7, 8, 10, 11, 12, 13):
            ws.cell(row=r, column=col).number_format = _MONEY
        ws.cell(row=r, column=9).number_format = _PCT
        # Resaltado por prioridad: alerta de costeo > margen negativo > revisar.
        if alertas_costeo(a):
            fill = _ALERT_FILL
        elif a.margen_total < 0:
            fill = _BAD_FILL
        elif a.status in (MatchStatus.REVIEW, MatchStatus.NEW):
            fill = _WARN_FILL
        else:
            fill = None
        if fill is not None:
            for col in range(1, len(headers) + 1):
                ws.cell(row=r, column=col).fill = fill
        for col in range(1, len(headers) + 1):
            ws.cell(row=r, column=col).border = _BORDER
```

La fila de totales que viene después del bucle escribe posicionalmente: corré sus
posiciones dos lugares a la derecha y agregá `sum(a.contractual_total_sin_aiu for a in
apus)` en la columna 11. Lo mismo con el dict de `_autosize` de esa función: agregá
`6: 18` y `11: 20` y desplazá las claves siguientes.

- [ ] **Step 4: Implementar en `report_categorizado.py::_build_detalle`**

Mismo cambio, mismas posiciones. Reemplazá el encabezado y el `ws.append` de cada ítem:

```python
def _build_detalle(ws, grupos: dict[str, list[AssembledApu]]) -> None:
    headers = ["Ítem", "Descripción", "Und", "Cantidad",
               "P. Contractual", "P. Contractual sin AIU",
               "Costo Unit.", "Margen Unit.", "Margen %",
               "Total Contractual", "Total Contractual sin AIU",
               "Total Costo", "Margen Total", "Estado"]
```

y dentro del bucle de ítems:

```python
            ws.append([
                a.item.item, a.item.descripcion, a.unidad, a.item.cantidad,
                a.item.precio_contractual, a.item.precio_contractual_sin_aiu,
                a.costo_unitario, a.margen_unitario, a.margen_pct,
                a.contractual_total, a.contractual_total_sin_aiu,
                a.costo_total, a.margen_total,
                _STATUS_LABEL.get(a.status, a.status),
            ])
            r = ws.max_row
            ws.cell(row=r, column=4).number_format = _REND
            for col in (5, 6, 7, 8, 10, 11, 12, 13):
                ws.cell(row=r, column=col).number_format = _MONEY
            ws.cell(row=r, column=9).number_format = _PCT
```

y el subtotal por capítulo, que también escribe posicionalmente:

```python
        sc = sum(a.contractual_total for a in apus)
        sc_sin = sum(a.contractual_total_sin_aiu for a in apus)
        sk = sum(a.costo_total for a in apus)
        ws.append(["", f"Subtotal {cap}", "", "", "", "", "", "", "",
                   sc, sc_sin, sk, sc - sk, ""])
        r = ws.max_row
        for col in (10, 11, 12, 13):
            celda = ws.cell(row=r, column=col)
            celda.number_format = _MONEY
            celda.font = Font(bold=True)
        ws.cell(row=r, column=2).font = Font(bold=True)
```

Y el `_autosize` final de `_build_detalle`:

```python
    _autosize(ws, {1: 9, 2: 46, 3: 6, 4: 12, 5: 16, 6: 18, 7: 14, 8: 14, 9: 10,
                   10: 18, 11: 20, 12: 16, 13: 16, 14: 12})
```

- [ ] **Step 5: Correr los tests**

Run: `python -m pytest tests/test_report_capitulos.py tests/test_report_categorizado.py tests/test_report_alertas_costeo.py -q`
Expected: PASS

- [ ] **Step 6: Correr la suite completa**

Run: `python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add apu_tool/dominio/report.py apu_tool/dominio/report_categorizado.py tests/test_report_capitulos.py
git commit -m "feat(idu): columnas de contractual sin AIU en las hojas de detalle"
```

---

# Fase 7 — Frontend

## Task 19: Tipos y cliente de API

**Files:**
- Modify: `web/src/lib/tipos.ts`
- Modify: `web/src/api/corridas.ts`
- Test: `web/src/api/corridas.previa.test.ts` (crear)

- [ ] **Step 1: Escribir el test que falla**

Crear `web/src/api/corridas.previa.test.ts`:

```ts
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { previsualizarCorrida } from "@/api/corridas";

vi.mock("@/lib/supabase", () => ({
  supabase: { auth: { getSession: async () => ({ data: { session: null } }) } },
}));

describe("previsualizarCorrida", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ entidad: "IDU", capitulos: [], actividades: 0, errores: [],
                       advertencias: [], puede_aprobar: false }),
      { status: 200, headers: { "Content-Type": "application/json" } })));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("pega a /api/corridas/previsualizar con el archivo y la entidad", async () => {
    const form = new FormData();
    form.append("entidad", "IDU");
    form.append("archivo", new File(["x"], "f1.xlsx"));
    const previa = await previsualizarCorrida(form);
    expect(previa.entidad).toBe("IDU");
    const [url, init] = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/api/corridas/previsualizar");
    expect((init as RequestInit).method).toBe("POST");
    expect((init as RequestInit).body).toBeInstanceOf(FormData);
  });
});
```

- [ ] **Step 2: Correr el test para ver que falla**

Run: `cd web && npx vitest run src/api/corridas.previa.test.ts`
Expected: FAIL — `previsualizarCorrida` no existe.

- [ ] **Step 3: Agregar los tipos**

En `web/src/lib/tipos.ts`:

```ts
/** De dónde salió el presupuesto. Espejo de `EntidadOrigen` del backend: valor estable,
 *  no texto libre. Solo IDU tiene lector especializado hoy. */
export const ENTIDADES = [
  { valor: "IDU", etiqueta: "IDU" },
  { valor: "METRO_BOGOTA", etiqueta: "Metro de Bogotá" },
  { valor: "INVIAS", etiqueta: "INVÍAS" },
  { valor: "OTRA_PUBLICA", etiqueta: "Otra entidad pública" },
  { valor: "PRIVADA", etiqueta: "Cliente privado" },
  { valor: "NO_IDENTIFICADA", etiqueta: "No identificada" },
] as const;

export type Entidad = (typeof ENTIDADES)[number]["valor"];

export interface AdvertenciaPresupuesto {
  tipo: string;
  /** Fila del Excel, 1-based. 0 = no aplica a una fila puntual. */
  fila: number;
  detalle: string;
}

export interface CapituloPrevia {
  codigo: string;
  nombre: string;
  orden: number;
  fila_origen: number;
  actividades: number;
  contractual: number;
  contractual_sin_aiu: number;
}

export interface PreviaPresupuesto {
  entidad: Entidad;
  formato: string;
  archivo: string;
  hoja: string;
  fila_encabezado: number;
  parser_version: string;
  capitulos: CapituloPrevia[];
  actividades: number;
  filas_ignoradas: number;
  totales: { contractual: number; contractual_sin_aiu: number };
  conciliacion: {
    contractual_con_aiu?: number;
    contractual_sin_aiu?: number;
    subtotales_excel?: number;
    diferencia?: number;
    subtotales_ok?: boolean;
  };
  errores: string[];
  advertencias: AdvertenciaPresupuesto[];
  filas_senaladas: AdvertenciaPresupuesto[];
  /** Lo decide el SERVIDOR. El botón solo obedece; `POST /corridas` lo revalida. */
  puede_aprobar: boolean;
  requiere_confirmacion: boolean;
}

/** Una fila del resumen por capítulo de una corrida ya armada. Lo calcula el backend
 *  (`dominio/report_categorizado.resumen_por_capitulo`): acá NO se suma dinero. */
export interface CapituloCorrida {
  codigo: string;
  nombre: string;
  orden: number;
  actividades: number;
  con_apu: number;
  sin_apu: number;
  contractual: number;
  contractual_sin_aiu: number;
  costo: number;
  diferencia: number;
  margen_pct: number;
  cobertura: number;
  cobertura_valor: number;
  completo: boolean;
}
```

Y agregar los campos a las interfaces existentes:

```ts
// en ItemCuadro:
  capitulo_codigo: string;
  capitulo_nombre: string;
  item_pago_original: string;
  precio_contractual_sin_aiu: number;
  contractual_total_sin_aiu: number;

// en CorridaDetalle:
  capitulos: CapituloCorrida[];
  origen: { entidad?: string; hoja?: string; parser_version?: string } | null;
```

- [ ] **Step 4: Agregar la llamada**

En `web/src/api/corridas.ts`:

```ts
/** Qué se detectó en el archivo, SIN crear nada. El navegador se queda con el archivo
 *  y lo reenvía al aprobar: no hay borrador en el servidor que expirar o limpiar. */
export function previsualizarCorrida(form: FormData): Promise<PreviaPresupuesto> {
  return apiPost<PreviaPresupuesto>("/corridas/previsualizar", form);
}
```

(y agregar `PreviaPresupuesto` al `import type`).

- [ ] **Step 5: Correr el test**

Run: `cd web && npx vitest run src/api/corridas.previa.test.ts`
Expected: PASS

- [ ] **Step 6: Compilar**

Run: `cd web && npm run build`
Expected: build OK. **`npm run build` (que es `tsc -b`) y NO `tsc --noEmit`**: el
`--noEmit` no revisa los proyectos referenciados y ya dejó pasar un build roto a master.

- [ ] **Step 7: Commit**

```bash
git add web/src/lib/tipos.ts web/src/api/corridas.ts web/src/api/corridas.previa.test.ts
git commit -m "feat(idu): tipos y cliente de la previsualizacion"
```

---

## Task 20: El panel de previsualización

**Files:**
- Create: `web/src/components/corrida/PreviaIdu.tsx`
- Test: `web/src/components/corrida/PreviaIdu.test.tsx` (crear)

- [ ] **Step 1: Escribir el test que falla**

Crear `web/src/components/corrida/PreviaIdu.test.tsx`:

```tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import PreviaIdu from "@/components/corrida/PreviaIdu";
import type { PreviaPresupuesto } from "@/lib/tipos";

const BASE: PreviaPresupuesto = {
  entidad: "IDU", formato: "idu_formulario_1", archivo: "f1.xlsx",
  hoja: "PROPUESTA ECONÓMICA", fila_encabezado: 10, parser_version: "idu-f1/1",
  capitulos: [
    { codigo: "1", nombre: "PRELIMINARES", orden: 1, fila_origen: 13,
      actividades: 2, contractual: 137605594, contractual_sin_aiu: 107565459 },
    { codigo: "2", nombre: "PAVIMENTOS", orden: 2, fila_origen: 21,
      actividades: 52, contractual: 8284911000, contractual_sin_aiu: 6477000000 },
  ],
  actividades: 1939, filas_ignoradas: 804,
  totales: { contractual: 158456072140, contractual_sin_aiu: 123871215068 },
  conciliacion: { subtotales_ok: true, diferencia: 0 },
  errores: [], advertencias: [], filas_senaladas: [],
  puede_aprobar: true, requiere_confirmacion: true,
};

const props = (previa: PreviaPresupuesto) => ({
  previa, cargando: false, onAprobar: vi.fn(), onCancelar: vi.fn(),
  onCambiarArchivo: vi.fn(),
});

describe("PreviaIdu", () => {
  it("dice cuántos capítulos y actividades se detectaron", () => {
    render(<PreviaIdu {...props(BASE)} />);
    expect(screen.getByText(/2 capítulos y 1.939 actividades/)).toBeTruthy();
  });

  it("muestra la hoja usada y la fila de encabezado", () => {
    render(<PreviaIdu {...props(BASE)} />);
    expect(screen.getByText(/PROPUESTA ECONÓMICA/)).toBeTruthy();
    expect(screen.getByText(/fila 10/)).toBeTruthy();
  });

  it("lista los capítulos con su contractual en formato colombiano", () => {
    render(<PreviaIdu {...props(BASE)} />);
    expect(screen.getByText("PRELIMINARES")).toBeTruthy();
    expect(screen.getByText("$137.605.594")).toBeTruthy();
    expect(screen.getByText("$107.565.459")).toBeTruthy();
  });

  it("aprueba sin fricción cuando no hay ni errores ni advertencias", () => {
    const p = props(BASE);
    render(<PreviaIdu {...p} />);
    const boton = screen.getByRole("button", { name: /aprobar y crear corrida/i });
    expect((boton as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(boton);
    expect(p.onAprobar).toHaveBeenCalledTimes(1);
  });

  it("bloquea la aprobación y muestra los errores", () => {
    const conError = { ...BASE, puede_aprobar: false, capitulos: [], actividades: 0,
      errores: ["falta_columna: el archivo no trae la columna cantidad."] };
    const p = props(conError);
    render(<PreviaIdu {...p} />);
    const boton = screen.getByRole("button", { name: /aprobar y crear corrida/i });
    expect((boton as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByRole("alert").textContent).toContain("falta_columna");
    fireEvent.click(boton);
    expect(p.onAprobar).not.toHaveBeenCalled();
  });

  it("con advertencias exige una confirmación explícita antes de aprobar", () => {
    const conAviso = { ...BASE, advertencias: [
      { tipo: "hoja_ambigua", fila: 0, detalle: "Se usó la hoja «PROPUESTA ECONÓMICA»." }] };
    const p = props(conAviso);
    render(<PreviaIdu {...p} />);
    const boton = screen.getByRole("button", { name: /aprobar y crear corrida/i });
    expect((boton as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByLabelText(/entiendo las 1 advertencias/i));
    expect((boton as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(boton);
    expect(p.onAprobar).toHaveBeenCalledTimes(1);
  });

  it("muestra el detalle de cada advertencia con su fila", () => {
    const conAviso = { ...BASE, advertencias: [
      { tipo: "capitulo_ambiguo", fila: 412,
        detalle: "El ítem 3.001 dice capítulo 3 pero está dentro del 2." }] };
    render(<PreviaIdu {...props(conAviso)} />);
    expect(screen.getByText(/fila 412/)).toBeTruthy();
    expect(screen.getByText(/dice capítulo 3/)).toBeTruthy();
  });

  it("avisa cuando la conciliación contra el Excel no cuadra", () => {
    const desfasada = { ...BASE,
      conciliacion: { subtotales_ok: false, diferencia: -1200 } };
    render(<PreviaIdu {...props(desfasada)} />);
    expect(screen.getByText(/no cuadra/i)).toBeTruthy();
  });

  it("cancelar y volver a elegir archivo avisan al padre", () => {
    const p = props(BASE);
    render(<PreviaIdu {...p} />);
    fireEvent.click(screen.getByRole("button", { name: /cancelar/i }));
    expect(p.onCancelar).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: /volver a seleccionar/i }));
    expect(p.onCambiarArchivo).toHaveBeenCalledTimes(1);
  });

  it("mientras crea la corrida no deja apretar dos veces", () => {
    const p = { ...props(BASE), cargando: true };
    render(<PreviaIdu {...p} />);
    expect((screen.getByRole("button", { name: /creando/i }) as HTMLButtonElement)
      .disabled).toBe(true);
  });
});
```

- [ ] **Step 2: Correr el test para ver que falla**

Run: `cd web && npx vitest run src/components/corrida/PreviaIdu.test.tsx`
Expected: FAIL — el módulo no existe.

- [ ] **Step 3: Implementar**

Crear `web/src/components/corrida/PreviaIdu.tsx`:

```tsx
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { cop } from "@/lib/moneda";
import type { PreviaPresupuesto } from "@/lib/tipos";

interface Props {
  previa: PreviaPresupuesto;
  cargando: boolean;
  onAprobar: () => void;
  onCancelar: () => void;
  onCambiarArchivo: () => void;
}

/** Lo que se detectó en el archivo, antes de crear nada.
 *
 *  No hay corrida todavía y no hay borrador en el servidor: el archivo sigue en el
 *  <input> del formulario y se reenvía al aprobar. Por eso "Cancelar" no tiene que
 *  limpiar nada — nunca hubo nada que limpiar. */
export default function PreviaIdu({ previa, cargando, onAprobar, onCancelar,
                                    onCambiarArchivo }: Props) {
  const [avisosEntendidos, setAvisosEntendidos] = useState(false);
  const nAvisos = previa.advertencias.length;
  // Una previa nueva (otro archivo) vuelve a exigir la confirmación de advertencias.
  useEffect(() => setAvisosEntendidos(false), [previa]);

  const bloqueado = !previa.puede_aprobar || (nAvisos > 0 && !avisosEntendidos) || cargando;
  const conciliacionOk = previa.conciliacion?.subtotales_ok !== false;

  return (
    <section className="mt-5 border-t pt-4" aria-labelledby="previa-titulo">
      <h3 id="previa-titulo" className="text-[13px] font-semibold">
        Estructura detectada
      </h3>

      <p className="mt-1 text-[11px] text-muted-foreground">
        Hoja «{previa.hoja}» · encabezado en la fila {previa.fila_encabezado} · parser{" "}
        {previa.parser_version}
      </p>
      <p className="mt-1 text-xs">
        Se detectaron {previa.capitulos.length.toLocaleString("es-CO")} capítulos y{" "}
        {previa.actividades.toLocaleString("es-CO")} actividades. Filas ignoradas:{" "}
        {previa.filas_ignoradas.toLocaleString("es-CO")}.
      </p>
      <p className="mt-1 text-xs">
        Contractual (con AIU) {cop(previa.totales.contractual)} · sin AIU{" "}
        {cop(previa.totales.contractual_sin_aiu)}
      </p>
      <p className={"mt-1 text-[11px] " + (conciliacionOk ? "text-muted-foreground"
                                                          : "text-revisar")}>
        {conciliacionOk
          ? "Conciliación contra el Excel: cuadra."
          : `Conciliación contra el Excel: no cuadra (diferencia ${
              cop(previa.conciliacion.diferencia ?? 0)}).`}
      </p>

      {previa.errores.length > 0 && (
        <div role="alert" className="mt-3 rounded-md border border-destructive/40 p-2">
          <p className="text-xs font-medium text-destructive">
            No se puede importar este archivo:
          </p>
          <ul className="mt-1 list-disc pl-4 text-[11px]">
            {previa.errores.map((e) => <li key={e}>{e}</li>)}
          </ul>
        </div>
      )}

      {nAvisos > 0 && (
        <div className="mt-3 rounded-md border border-revisar/40 p-2">
          <p className="text-xs font-medium">
            {nAvisos} advertencia{nAvisos === 1 ? "" : "s"}
          </p>
          <ul className="mt-1 max-h-40 list-disc overflow-y-auto pl-4 text-[11px]">
            {previa.advertencias.map((a, i) => (
              <li key={`${a.tipo}-${a.fila}-${i}`}>
                <span className="font-medium">{a.tipo}</span>
                {a.fila > 0 && <> (fila {a.fila})</>}: {a.detalle}
              </li>
            ))}
          </ul>
          <label className="mt-2 flex items-center gap-1.5 text-[11px]">
            <input
              type="checkbox"
              checked={avisosEntendidos}
              onChange={(e) => setAvisosEntendidos(e.target.checked)}
            />
            Entiendo las {nAvisos} advertencias y quiero continuar
          </label>
        </div>
      )}

      {previa.capitulos.length > 0 && (
        <div className="mt-3 max-h-72 overflow-auto">
          <table className="w-full border-collapse text-[11px]">
            <caption className="sr-only">
              Capítulos detectados con su total contractual
            </caption>
            <thead className="sticky top-0 bg-card">
              <tr>
                <th scope="col" className="p-1 text-left">Capítulo</th>
                <th scope="col" className="p-1 text-left">Nombre</th>
                <th scope="col" className="p-1 text-right">Actividades</th>
                <th scope="col" className="p-1 text-right">Contractual (c/AIU)</th>
                <th scope="col" className="p-1 text-right">Contractual (s/AIU)</th>
              </tr>
            </thead>
            <tbody>
              {previa.capitulos.map((c) => (
                <tr key={c.codigo || c.nombre} className="border-t">
                  <td className="p-1">{c.codigo}</td>
                  <td className="p-1">{c.nombre}</td>
                  <td className="p-1 text-right">
                    {c.actividades.toLocaleString("es-CO")}
                  </td>
                  <td className="p-1 text-right tabular-nums">{cop(c.contractual)}</td>
                  <td className="p-1 text-right tabular-nums">
                    {cop(c.contractual_sin_aiu)}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t font-medium">
                <td className="p-1" colSpan={2}>TOTAL</td>
                <td className="p-1 text-right">
                  {previa.actividades.toLocaleString("es-CO")}
                </td>
                <td className="p-1 text-right tabular-nums">
                  {cop(previa.totales.contractual)}
                </td>
                <td className="p-1 text-right tabular-nums">
                  {cop(previa.totales.contractual_sin_aiu)}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        {/* Deshabilitado SOLO cuando hay una razón visible en pantalla (errores listados
            o advertencias sin confirmar). Un botón muerto sin explicación deja al
            usuario sin salida: pasó en el smoke test de producción del 2026-08-03. */}
        <Button type="button" disabled={bloqueado} onClick={onAprobar}>
          {cargando ? "Creando…" : "Aprobar y crear corrida"}
        </Button>
        <Button type="button" variant="outline" disabled={cargando}
                onClick={onCambiarArchivo}>
          Volver a seleccionar archivo
        </Button>
        <Button type="button" variant="outline" disabled={cargando} onClick={onCancelar}>
          Cancelar
        </Button>
      </div>
    </section>
  );
}
```

- [ ] **Step 4: Correr el test**

Run: `cd web && npx vitest run src/components/corrida/PreviaIdu.test.tsx`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
git add web/src/components/corrida/PreviaIdu.tsx web/src/components/corrida/PreviaIdu.test.tsx
git commit -m "feat(idu): panel de previsualizacion y confirmacion"
```

---

## Task 21: Selector de entidad en el formulario

**Files:**
- Modify: `web/src/pages/CorridasInicio.tsx`
- Test: `web/src/pages/CorridasInicio.idu.test.tsx` (crear)

- [ ] **Step 1: Escribir el test que falla**

Crear `web/src/pages/CorridasInicio.idu.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import CorridasInicio from "@/pages/CorridasInicio";

const previsualizar = vi.fn();
const crear = vi.fn();

vi.mock("@/api/corridas", () => ({
  previsualizarCorrida: (...a: unknown[]) => previsualizar(...a),
  crearCorrida: (...a: unknown[]) => crear(...a),
  crearSample: vi.fn(),
  corridaEnCurso: () => null,
}));
vi.mock("@/api/carpetas", () => ({
  listarCarpetas: async () => [{ id: 1, nombre: "Obras", hijas: [] }],
  crearCarpeta: vi.fn(),
}));
vi.mock("@/api/listas", () => ({ listarListas: async () => [{ id: 1, nombre: "Principal" }] }));
vi.mock("react-router-dom", async (orig) => ({
  ...(await orig<typeof import("react-router-dom")>()),
  useNavigate: () => vi.fn(),
}));

const PREVIA = {
  entidad: "IDU", formato: "idu_formulario_1", archivo: "f1.xlsx",
  hoja: "PROPUESTA ECONÓMICA", fila_encabezado: 10, parser_version: "idu-f1/1",
  capitulos: [{ codigo: "1", nombre: "PRELIMINARES", orden: 1, fila_origen: 13,
                actividades: 2, contractual: 100, contractual_sin_aiu: 80 }],
  actividades: 2, filas_ignoradas: 5,
  totales: { contractual: 100, contractual_sin_aiu: 80 },
  conciliacion: { subtotales_ok: true, diferencia: 0 },
  errores: [], advertencias: [], filas_senaladas: [],
  puede_aprobar: true, requiere_confirmacion: true,
};

function pintar() {
  return render(<MemoryRouter><CorridasInicio /></MemoryRouter>);
}

function elegirArchivo() {
  const input = screen.getByLabelText(/archivo/i) as HTMLInputElement;
  fireEvent.change(input, { target: { files: [new File(["x"], "f1.xlsx")] } });
}

describe("CorridasInicio · entidad", () => {
  beforeEach(() => {
    previsualizar.mockReset().mockResolvedValue(PREVIA);
    crear.mockReset().mockResolvedValue({ id: 7, total: 2, estado: "armando" });
  });

  it("ofrece las seis entidades y arranca en No identificada", async () => {
    pintar();
    const sel = await screen.findByLabelText(/entidad o fuente/i) as HTMLSelectElement;
    expect(sel.value).toBe("NO_IDENTIFICADA");
    const opciones = screen.getAllByRole("option").map((o) => (o as HTMLOptionElement).value);
    for (const v of ["IDU", "METRO_BOGOTA", "INVIAS", "OTRA_PUBLICA", "PRIVADA",
                     "NO_IDENTIFICADA"]) {
      expect(opciones).toContain(v);
    }
  });

  it("con IDU el botón dice Previsualizar y NO crea la corrida", async () => {
    pintar();
    fireEvent.change(await screen.findByLabelText(/entidad o fuente/i),
                     { target: { value: "IDU" } });
    fireEvent.change(await screen.findByLabelText(/^carpeta/i), { target: { value: "1" } });
    elegirArchivo();
    fireEvent.click(screen.getByRole("button", { name: /previsualizar/i }));
    await waitFor(() => expect(previsualizar).toHaveBeenCalledTimes(1));
    expect(crear).not.toHaveBeenCalled();
    expect(await screen.findByText(/Estructura detectada/)).toBeTruthy();
  });

  it("aprobar reenvía el archivo con confirmada=true", async () => {
    pintar();
    fireEvent.change(await screen.findByLabelText(/entidad o fuente/i),
                     { target: { value: "IDU" } });
    fireEvent.change(await screen.findByLabelText(/^carpeta/i), { target: { value: "1" } });
    elegirArchivo();
    fireEvent.click(screen.getByRole("button", { name: /previsualizar/i }));
    fireEvent.click(await screen.findByRole("button", { name: /aprobar y crear/i }));
    await waitFor(() => expect(crear).toHaveBeenCalledTimes(1));
    const form = crear.mock.calls[0][0] as FormData;
    expect(form.get("entidad")).toBe("IDU");
    expect(form.get("confirmada")).toBe("true");
    expect(form.get("carpeta_id")).toBe("1");
    expect(form.get("archivo")).toBeInstanceOf(File);
  });

  it("cancelar cierra la previa sin crear nada", async () => {
    pintar();
    fireEvent.change(await screen.findByLabelText(/entidad o fuente/i),
                     { target: { value: "IDU" } });
    fireEvent.change(await screen.findByLabelText(/^carpeta/i), { target: { value: "1" } });
    elegirArchivo();
    fireEvent.click(screen.getByRole("button", { name: /previsualizar/i }));
    fireEvent.click(await screen.findByRole("button", { name: /cancelar/i }));
    await waitFor(() =>
      expect(screen.queryByText(/Estructura detectada/)).toBeNull());
    expect(crear).not.toHaveBeenCalled();
  });

  it("con otra entidad el flujo de siempre no se toca", async () => {
    pintar();
    fireEvent.change(await screen.findByLabelText(/entidad o fuente/i),
                     { target: { value: "INVIAS" } });
    fireEvent.change(await screen.findByLabelText(/^carpeta/i), { target: { value: "1" } });
    elegirArchivo();
    fireEvent.click(screen.getByRole("button", { name: /^armar$/i }));
    await waitFor(() => expect(crear).toHaveBeenCalledTimes(1));
    expect(previsualizar).not.toHaveBeenCalled();
    expect((crear.mock.calls[0][0] as FormData).get("entidad")).toBe("INVIAS");
  });
});
```

- [ ] **Step 2: Correr el test para ver que falla**

Run: `cd web && npx vitest run src/pages/CorridasInicio.idu.test.tsx`
Expected: FAIL — no existe el selector.

- [ ] **Step 3: Implementar**

En `web/src/pages/CorridasInicio.tsx`:

1. Importar lo nuevo:

```tsx
import { previsualizarCorrida } from "@/api/corridas";
import PreviaIdu from "@/components/corrida/PreviaIdu";
import { ENTIDADES, type Entidad, type PreviaPresupuesto } from "@/lib/tipos";
```

2. Agregar el estado:

```tsx
  // La entidad decide qué lector usa el backend y si hay que confirmar la estructura.
  const [entidad, setEntidad] = useState<Entidad>("NO_IDENTIFICADA");
  // La previa vive acá, no en el servidor: el archivo sigue en el <input> y se reenvía
  // al aprobar. Sin borrador que expirar, sin corrida a medio crear si cierran la pestaña.
  const [previa, setPrevia] = useState<PreviaPresupuesto | null>(null);
```

3. Reemplazar `handleArmar` por:

```tsx
  /** El formulario, como FormData. Uno solo para previsualizar y para crear: si fueran
   *  dos, el archivo que se aprueba podría no ser el que se previsualizó. */
  function armarForm(archivo: File, confirmada: boolean): FormData {
    const form = new FormData();
    form.append("archivo", archivo);
    form.append("carpeta_id", String(carpetaDestino));
    form.append("nombre", nombre.trim());
    form.append("entidad", entidad);
    if (confirmada) form.append("confirmada", "true");
    if (listaId !== LISTA_PRINCIPAL_ID) form.append("lista_id", String(listaId));
    return form;
  }

  function archivoElegido(): File | null {
    const f = fileRef.current?.files?.[0];
    if (!f) {
      toast.error("Selecciona un archivo .xlsx o .csv");
      return null;
    }
    if (carpetaDestino == null) {
      toast.error("Elige una carpeta");
      return null;
    }
    return f;
  }

  const requiereConfirmacion = entidad === "IDU";

  async function handleEnviar(e: React.FormEvent) {
    e.preventDefault();
    const archivo = archivoElegido();
    if (!archivo) return;
    if (!requiereConfirmacion) {
      await encolar(() => crearCorrida(armarForm(archivo, false)),
                    "Error al crear la corrida");
      return;
    }
    // Ruta IDU: primero se muestra lo que se detectó. No se crea nada todavía.
    if (enVuelo.current) return;
    enVuelo.current = true;
    setCargando(true);
    try {
      setPrevia(await previsualizarCorrida(armarForm(archivo, false)));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "No se pudo leer el archivo");
    } finally {
      enVuelo.current = false;
      setCargando(false);
    }
  }

  async function handleAprobar() {
    const archivo = archivoElegido();
    if (!archivo) return;
    await encolar(() => crearCorrida(armarForm(archivo, true)),
                  "Error al crear la corrida");
  }
```

4. Cambiar el `onSubmit` del `<form>` a `handleEnviar` y el texto del botón:

```tsx
          <Button type="submit" disabled={cargando}>
            {cargando ? "Leyendo…" : requiereConfirmacion ? "Previsualizar" : "Armar"}
          </Button>
```

5. Agregar el selector **antes** del campo de archivo:

```tsx
        <div className={CLASE_CAMPO}>
          <label className={CLASE_ETIQUETA} htmlFor="entidad">
            Entidad o fuente del presupuesto
          </label>
          <select
            id="entidad"
            value={entidad}
            onChange={(e) => { setEntidad(e.target.value as Entidad); setPrevia(null); }}
            disabled={cargando}
            className={CLASE_SELECT}
          >
            {ENTIDADES.map((e) => (
              <option key={e.valor} value={e.valor}>{e.etiqueta}</option>
            ))}
          </select>
          {requiereConfirmacion && (
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              Se lee el Formulario 1 de Presupuesto Oficial y se confirma la estructura
              antes de armar.
            </p>
          )}
        </div>
```

6. Renderizar la previa **después** del `</form>`:

```tsx
      {previa && (
        <PreviaIdu
          previa={previa}
          cargando={cargando}
          onAprobar={handleAprobar}
          onCancelar={() => setPrevia(null)}
          onCambiarArchivo={() => { setPrevia(null); fileRef.current?.click(); }}
        />
      )}
```

7. En `handleArchivoChange`, limpiar la previa al cambiar de archivo:

```tsx
  function handleArchivoChange(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    setPrevia(null);            // otra estructura: la previa vieja ya no describe nada
    if (f && !nombreTocado) setNombre(stripExt(f.name));
  }
```

- [ ] **Step 4: Correr los tests de la pantalla**

Run: `cd web && npx vitest run src/pages/CorridasInicio.idu.test.tsx src/pages/CorridasInicio.test.tsx src/pages/CorridasInicio.toast.test.tsx`
Expected: PASS. Los 7 tests viejos de la pantalla tienen que seguir verdes: con la entidad
por defecto (`NO_IDENTIFICADA`) el botón sigue diciendo "Armar" y el flujo no cambia.

- [ ] **Step 5: Compilar**

Run: `cd web && npm run build`
Expected: build OK

- [ ] **Step 6: Commit**

```bash
git add web/src/pages/CorridasInicio.tsx web/src/pages/CorridasInicio.idu.test.tsx
git commit -m "feat(idu): selector de entidad y flujo de previsualizacion"
```

---

## Task 22: Capítulo en la tabla y resumen por capítulo en la corrida

**Files:**
- Modify: `web/src/components/corrida/TablaItems.tsx`
- Modify: `web/src/pages/Corrida.tsx`
- Test: `web/src/pages/Corrida.capitulos.test.tsx` (crear)

- [ ] **Step 1: Escribir el test que falla**

Crear `web/src/pages/Corrida.capitulos.test.tsx`:

```tsx
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import ResumenCapitulos from "@/components/corrida/ResumenCapitulos";
import type { CapituloCorrida } from "@/lib/tipos";

const CAPS: CapituloCorrida[] = [
  { codigo: "1", nombre: "PRELIMINARES", orden: 1, actividades: 2, con_apu: 2,
    sin_apu: 0, contractual: 137605594, contractual_sin_aiu: 107565459,
    costo: 100000000, diferencia: 37605594, margen_pct: 0.2733,
    cobertura: 1, cobertura_valor: 1, completo: true },
  { codigo: "2", nombre: "PAVIMENTOS", orden: 2, actividades: 52, con_apu: 50,
    sin_apu: 2, contractual: 8284911000, contractual_sin_aiu: 6477000000,
    costo: 6000000000, diferencia: 2284911000, margen_pct: 0.2758,
    cobertura: 50 / 52, cobertura_valor: 0.4, completo: false },
];

describe("ResumenCapitulos", () => {
  it("muestra una fila por capítulo con contractual y costo", () => {
    render(<ResumenCapitulos capitulos={CAPS} />);
    expect(screen.getByText("PRELIMINARES")).toBeTruthy();
    expect(screen.getByText("PAVIMENTOS")).toBeTruthy();
    expect(screen.getByText("$137.605.594")).toBeTruthy();
    expect(screen.getByText("$100.000.000")).toBeTruthy();
  });

  it("cuenta las actividades sin APU en vez de esconderlas", () => {
    render(<ResumenCapitulos capitulos={CAPS} />);
    const filaPavimentos = screen.getByText("PAVIMENTOS").closest("tr")!;
    expect(filaPavimentos.textContent).toContain("2");   // sin_apu
  });

  it("marca el margen como parcial cuando el capítulo está incompleto", () => {
    render(<ResumenCapitulos capitulos={CAPS} />);
    const filaPavimentos = screen.getByText("PAVIMENTOS").closest("tr")!;
    expect(filaPavimentos.textContent).toMatch(/parcial|incompleto/i);
    const filaPreliminares = screen.getByText("PRELIMINARES").closest("tr")!;
    expect(filaPreliminares.textContent).toMatch(/completo/i);
  });

  it("muestra la cobertura por conteo y por valor", () => {
    render(<ResumenCapitulos capitulos={CAPS} />);
    const fila = screen.getByText("PAVIMENTOS").closest("tr")!;
    expect(fila.textContent).toContain("96.2%");   // 50/52 por conteo
    expect(fila.textContent).toContain("40.0%");   // por valor
  });

  it("no se dibuja cuando la corrida no tiene capítulos", () => {
    const { container } = render(<ResumenCapitulos capitulos={[]} />);
    expect(container.firstChild).toBeNull();
  });
});
```

- [ ] **Step 2: Correr el test para ver que falla**

Run: `cd web && npx vitest run src/pages/Corrida.capitulos.test.tsx`
Expected: FAIL — el componente no existe.

- [ ] **Step 3: Crear `web/src/components/corrida/ResumenCapitulos.tsx`**

```tsx
import { cop, pct } from "@/lib/moneda";
import type { CapituloCorrida } from "@/lib/tipos";

/** Contractual, costo y cobertura por capítulo, después del armado.
 *
 *  NO calcula nada: el backend manda las filas ya sumadas
 *  (`dominio/report_categorizado.resumen_por_capitulo`), que es la misma función que
 *  escribe la hoja de Excel. Sumar acá sería el segundo lugar donde el mismo número
 *  puede salir distinto. */
export default function ResumenCapitulos({ capitulos }: { capitulos: CapituloCorrida[] }) {
  if (!capitulos.length) return null;
  const total = (f: (c: CapituloCorrida) => number) =>
    capitulos.reduce((a, c) => a + f(c), 0);
  const contractual = total((c) => c.contractual);
  const costo = total((c) => c.costo);

  return (
    <details open className="mb-3 rounded-md border">
      <summary className="cursor-pointer px-2 py-1.5 text-xs font-medium">
        Resumen por capítulo ({capitulos.length})
      </summary>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-[11px]">
          <caption className="sr-only">
            Contractual y costo interno por capítulo de la corrida
          </caption>
          <thead>
            <tr className="border-t">
              <th scope="col" className="p-1 text-left">Capítulo</th>
              <th scope="col" className="p-1 text-left">Nombre</th>
              <th scope="col" className="p-1 text-right">Actividades</th>
              <th scope="col" className="p-1 text-right">Con APU</th>
              <th scope="col" className="p-1 text-right">Sin APU</th>
              <th scope="col" className="p-1 text-right">Contractual</th>
              <th scope="col" className="p-1 text-right">Costo interno</th>
              <th scope="col" className="p-1 text-right">Diferencia</th>
              <th scope="col" className="p-1 text-right">Margen</th>
              <th scope="col" className="p-1 text-right">Cobertura</th>
              <th scope="col" className="p-1 text-right">Cobertura $</th>
              <th scope="col" className="p-1 text-left">Estado</th>
            </tr>
          </thead>
          <tbody>
            {capitulos.map((c) => (
              <tr key={c.codigo || c.nombre} className="border-t">
                <td className="p-1">{c.codigo}</td>
                <td className="p-1">{c.nombre}</td>
                <td className="p-1 text-right">{c.actividades.toLocaleString("es-CO")}</td>
                <td className="p-1 text-right">{c.con_apu.toLocaleString("es-CO")}</td>
                <td className={"p-1 text-right " + (c.sin_apu ? "text-revisar" : "")}>
                  {c.sin_apu.toLocaleString("es-CO")}
                </td>
                <td className="p-1 text-right tabular-nums">{cop(c.contractual)}</td>
                <td className="p-1 text-right tabular-nums">{cop(c.costo)}</td>
                <td className="p-1 text-right tabular-nums">{cop(c.diferencia)}</td>
                {/* Con actividades sin costear el margen NO es definitivo: se dice, en
                    vez de mostrar un porcentaje que parece final y no lo es. */}
                <td className="p-1 text-right tabular-nums">
                  {pct(c.margen_pct)}{!c.completo && " parcial"}
                </td>
                <td className="p-1 text-right">{pct(c.cobertura)}</td>
                <td className="p-1 text-right">{pct(c.cobertura_valor)}</td>
                <td className="p-1">{c.completo ? "Completo" : "Incompleto"}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t font-medium">
              <td className="p-1" colSpan={2}>TOTAL</td>
              <td className="p-1 text-right">
                {total((c) => c.actividades).toLocaleString("es-CO")}
              </td>
              <td className="p-1 text-right">
                {total((c) => c.con_apu).toLocaleString("es-CO")}
              </td>
              <td className="p-1 text-right">
                {total((c) => c.sin_apu).toLocaleString("es-CO")}
              </td>
              <td className="p-1 text-right tabular-nums">{cop(contractual)}</td>
              <td className="p-1 text-right tabular-nums">{cop(costo)}</td>
              <td className="p-1 text-right tabular-nums">{cop(contractual - costo)}</td>
              <td className="p-1 text-right tabular-nums">
                {pct(contractual ? (contractual - costo) / contractual : 0)}
              </td>
              <td className="p-1" colSpan={3} />
            </tr>
          </tfoot>
        </table>
      </div>
    </details>
  );
}
```

- [ ] **Step 4: Montarlo en `Corrida.tsx`**

Importar y renderizar encima de `<TablaItems …>`:

```tsx
import ResumenCapitulos from "@/components/corrida/ResumenCapitulos";
// …
      <ResumenCapitulos capitulos={corrida.capitulos ?? []} />
```

- [ ] **Step 5: Columna `Capítulo` filtrable**

La tabla ya tiene filtro y orden por columna (`lib/corridaTabla.ts` +
`components/corrida/CabeceraFiltros.tsx`). La columna nueva **reusa esa maquinaria**: es
un filtro de texto más, como `descripcion` o `item`. Son cinco puntos de paso, todos en
`web/src/lib/corridaTabla.ts` salvo el último.

Primero el test, en `web/src/lib/corridaTabla.capitulo.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { FILTROS_VACIOS, filtrar, ordenar } from "@/lib/corridaTabla";
import type { ItemCuadro } from "@/lib/tipos";

const fila = (seq: number, cod: string, nom: string) => ({
  seq, item: `${cod}.00${seq}`, descripcion: `ACT ${seq}`, unidad: "M2", cantidad: 1,
  apu_codigo: "A1", apu_nombre: "APU", status: "auto", confianza: 1,
  precio_contractual: 100, costo_unitario: 60, margen_unitario: 40, margen_pct: 0.4,
  contractual_total: 100, costo_total: 60, margen_total: 40, costo_manual: false,
  alertas_costeo: [], revision: null,
  capitulo_codigo: cod, capitulo_nombre: nom, item_pago_original: `${cod}.00${seq}`,
  precio_contractual_sin_aiu: 80, contractual_total_sin_aiu: 80,
}) as unknown as ItemCuadro;

const ITEMS = [fila(1, "2", "PAVIMENTOS"), fila(2, "1", "PRELIMINARES"),
               fila(3, "2", "PAVIMENTOS")];

describe("filtro y orden por capítulo", () => {
  it("filtra por código", () => {
    const r = filtrar(ITEMS, { ...FILTROS_VACIOS, capitulo: "2" }, false);
    expect(r.map((i) => i.seq)).toEqual([1, 3]);
  });

  it("filtra por nombre, no solo por código", () => {
    const r = filtrar(ITEMS, { ...FILTROS_VACIOS, capitulo: "prelim" }, false);
    expect(r.map((i) => i.seq)).toEqual([2]);
  });

  it("sin filtro no descarta nada", () => {
    expect(filtrar(ITEMS, FILTROS_VACIOS, false)).toHaveLength(3);
  });

  it("ordena por capítulo", () => {
    const r = ordenar(ITEMS, { clave: "capitulo", dir: "asc" });
    expect(r.map((i) => i.capitulo_codigo)).toEqual(["1", "2", "2"]);
  });
});
```

Implementar:

1. `ClaveColumna` gana `| "capitulo"`.
2. `FiltrosColumna` gana `capitulo: string;`.
3. `FILTROS_VACIOS` gana `capitulo: "",`.
4. `CLAVES_TEXTO` gana `"capitulo"`.
5. En `filtrar`, junto a las demás líneas de texto:

```ts
    // Código y nombre en el mismo texto: buscar "2" o "PAVIMENTOS" encuentra lo mismo.
    if (!contiene(`${it.capitulo_codigo} ${it.capitulo_nombre}`, f.capitulo)) return false;
```

6. En `valorTexto`, un caso más:

```ts
    case "capitulo": return `${it.capitulo_codigo} ${it.capitulo_nombre}`;
```

7. En `CabeceraFiltros.tsx`, una celda de cabecera igual a la de `item` (input de texto
   ligado a `filtros.capitulo`), y en `TablaItems.tsx` la celda del cuerpo, las dos
   **condicionadas** a que haya capítulos:

```tsx
  // Corrida plana: ni columna ni filtro. La tabla queda exactamente como estaba, que es
  // lo que mantiene verdes los 927 renglones de TablaItems.test.tsx.
  const hayCapitulos = items.some((i) => i.capitulo_codigo);
```

```tsx
  {hayCapitulos && (
    <TableCell className="text-[11px]">
      {item.capitulo_codigo && `${item.capitulo_codigo} · ${item.capitulo_nombre}`}
    </TableCell>
  )}
```

8. Ajustar el `colSpan` de la fila vacía: hoy es "1 chevron + 12 columnas de datos"
   (`TablaItems.tsx:356`); con capítulos son 13.

- [ ] **Step 6: Correr los tests del frontend**

Run: `cd web && npx vitest run`
Expected: PASS — incluidos los 927 renglones de `TablaItems.test.tsx`, que no deben
cambiar: sus fixtures no traen capítulo, así que la columna no aparece.

- [ ] **Step 7: Compilar**

Run: `cd web && npm run build`
Expected: build OK

- [ ] **Step 8: Commit**

```bash
git add web/src/components/corrida/ResumenCapitulos.tsx web/src/pages/Corrida.capitulos.test.tsx web/src/pages/Corrida.tsx web/src/components/corrida/TablaItems.tsx web/src/components/corrida/CabeceraFiltros.tsx web/src/lib/corridaTabla.ts web/src/lib/corridaTabla.capitulo.test.ts
git commit -m "feat(idu): columna de capitulo y resumen por capitulo en la corrida"
```

---

## Task 23: Documentación y cierre

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/ARQUITECTURA.md`

- [ ] **Step 1: Actualizar `CLAUDE.md`**

En la tabla de `apu_tool/dominio/`, agregar la fila:

```
| `entrada.py`             | registro entidad → lector de presupuesto (único despacho) |
```

y cambiar la de `presupuesto.py`:

```
| `presupuesto.py`         | lectura del Formulario 1 del IDU: capítulos, validación y conciliación |
```

En **Datos**, agregar la sección:

```markdown
- **Entidad de origen y capítulos.** Una corrida guarda de dónde salió su presupuesto en
  `corrida.origen_json` (una sola columna, como `plan_json`): entidad, formato, hoja,
  versión del parser, quién confirmó la estructura y la conciliación contra el Excel.
  `NULL` en toda corrida anterior a esta feature — eso es "sin clasificación por
  capítulo", no un error, y no se inventan capítulos retroactivamente. **Lleva dinero
  adentro** (la conciliación), así que `origen_json` está en `_FORBIDDEN_KEYS`, igual que
  `plan_json`. El capítulo de cada actividad NO tiene tabla: viaja dentro de `item_json`
  y `plan_json` (`LicitacionItem.capitulo_codigo` / `capitulo_nombre`), que es donde ya
  viajaba `categoria`. El precio contractual de la ruta IDU es el **valor unitario CON
  AIU** (col K del Formulario 1), que concilia exacto con el `VALOR TOTAL` y los
  subtotales del Excel; el valor sin AIU viaja aparte en `precio_contractual_sin_aiu` y
  se muestra en columna propia. Ojo: el costo interno no lleva AIU, así que la diferencia
  contra el contractual incluye el A.I.U.
```

En **No hacer**, agregar:

```markdown
- No calcules el resumen por capítulo en dos lados. `dominio/report_categorizado.py::
  resumen_por_capitulo` es la ÚNICA función que suma por capítulo: la consumen la API
  (`vista_corrida["capitulos"]`), la web (que solo pinta) y las dos hojas de Excel. El
  frontend no suma dinero.
- No crees una corrida de la ruta IDU sin `confirmada=true`, y no confíes en ese flag: el
  endpoint **relee y revalida** el archivo, porque el cliente puede mentir.
- No le inventes reglas de formato a Metro, INVÍAS ni a las demás entidades. Están en el
  registro de `dominio/entrada.py` apuntando al importador genérico **a propósito**.
```

- [ ] **Step 2: Actualizar `docs/ARQUITECTURA.md`**

Agregar `entrada.py` al mapa de módulos y el flujo nuevo:

```
entidad IDU ──► previsualizar (no persiste) ──► usuario aprueba ──► crea la corrida
                      └─ capítulos, conciliación, errores y advertencias
```

- [ ] **Step 3: Correr TODO**

```bash
python -m pytest tests/ -q
cd web && npm run build && npx vitest run
```
Expected: todo verde.

- [ ] **Step 4: Correr la regresión contra el archivo real**

```bash
APU_IDU_F1_XLSX="/c/Users/luis.fajardo/Downloads/Formulario 1 Formulario de Presupuesto Oficial (version 1).xlsx" \
  python -m pytest tests/test_presupuesto_idu_regresion.py -q
```
Expected: 12 passed — 14 capítulos, 1939 actividades, conciliación en $0.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md docs/ARQUITECTURA.md
git commit -m "docs: ruta IDU, entidad de origen y resumen por capitulo"
```

---

## Verificación final (antes de pedir el merge)

- [ ] `python -m pytest tests/ -q` — verde
- [ ] `cd web && npm run build` — verde (es `tsc -b`, no `tsc --noEmit`)
- [ ] `cd web && npx vitest run` — verde
- [ ] Regresión contra el archivo real — 14 capítulos, 1.939 actividades, diferencia $0
- [ ] **En el navegador** (`python run_web.py`, con `SUPABASE_URL` y `APU_ADMIN_EMAILS`):
  - [ ] Elegir IDU, subir el Formulario 1, ver el resumen de 14 capítulos
  - [ ] Cancelar y comprobar que no quedó ninguna corrida
  - [ ] Aprobar, ver el armado en curso y el resumen por capítulo al terminar
  - [ ] Descargar el cuadro y verificar la hoja `RESUMEN POR CAPÍTULO`
  - [ ] Subir una licitación plana con otra entidad: la pantalla queda como antes
- [ ] Los tests de Postgres, si hay una base desechable a mano (**nunca producción**:
      hacen `DROP SCHEMA`)

El push a master necesita aprobación explícita del usuario: master auto-despliega.
