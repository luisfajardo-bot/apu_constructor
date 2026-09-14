"""
Lectura del presupuesto oficial por capítulos (hoja FOR 1-PPTO OFICIAL).

El presupuesto está organizado jerárquicamente:
    Capítulo (con número)  ->  TURNO DIURNO/NOCTURNO  ->  subgrupo  ->  ítems.

Se recorre de arriba abajo llevando el estado (capítulo, turno) vigente; cada ítem
hereda ambos. El precio contractual es el valor unitario BÁSICO (sin AIU), columna [9].
A diferencia de la licitación plana, cada ítem trae su código IDU (columna [2]), que
permite armar el APU por código directo.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Optional

import openpyxl

from apu_tool import config
from apu_tool.nucleo.models import LicitacionItem
from apu_tool.nucleo.texto import normalizar

# Índices de columna (0-idx) en la hoja FOR 1-PPTO OFICIAL.
COL_CODIGO = 2
COL_ITEMPAGO = 3
COL_DESC = 6
COL_UND = 7
COL_CANT = 8
COL_PRECIO = 9   # valor unitario BÁSICO (sin AIU)

HOJA_DEFECTO = "FOR 1-PPTO OFICIAL"


def _norm(s) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", str(s or ""))
                if unicodedata.category(c) != "Mn")
    return s.strip().lower()


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
    # openpyxl entrega las celdas numéricas como float (3007.0, no 3007) y el punto
    # decimal se lo comería `_FUERA_ENCABEZADO` junto con el de `UND.`: 3007.0 saldría
    # como "30070". Mismo guard que ya usa `_code` unas líneas más abajo.
    if isinstance(s, float) and not isinstance(s, bool) and s.is_integer():
        s = int(s)
    t = "".join(c for c in unicodedata.normalize("NFD", str(s if s is not None else ""))
                if unicodedata.category(c) != "Mn")
    t = t.lower().translate(_FUERA_ENCABEZADO)
    return re.sub(r"\s+", " ", t).strip()


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
        # `str(valor)` y NO `f"{valor:g}"`: `:g` corta a 6 cifras significativas, así
        # que 123456.789 saldría "123457" — perder un dígito es exactamente lo que esta
        # función existe para evitar. `str` de un float da la representación más corta
        # que vuelve al mismo número, sin tope ni notación científica en este rango.
        return str(int(valor)) if valor.is_integer() else str(valor)
    if isinstance(valor, int):
        return str(valor)
    return str(valor).strip()


def normalizar_item_pago(s) -> str:
    """Forma canónica del ítem de pago: coma decimal a punto, sufijo de turno separado.

    `2,001-N`, `2.001-N` y `2.001 N` son el MISMO ítem. Trabaja solo con texto, así que
    `2.010` conserva su cero (ver `item_pago_texto`).
    """
    # Un solo `strip` con el juego completo de caracteres: encadenar
    # `.strip('"').strip("'")` deja las comillas anidadas al revés ('"2.001"' con la
    # simple por fuera), y ahí `capitulo_de` no encontraría el dígito inicial y la fila
    # se saldría de su capítulo en silencio.
    t = str(s if s is not None else "").strip(" \t\n\r'\"")
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
    """(índice 0-based del encabezado, mapeo campo->columna, obligatorias que faltan).

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


def _code(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, int):
        return str(v)
    return str(v).strip()


def _es_codigo_item(v) -> bool:
    """Un código de ítem del presupuesto es numérico (3009) o alfanumérico corto."""
    c = _code(v)
    if not c:
        return False
    if c.isdigit():
        return True
    return len(c) <= 8 and any(ch.isalpha() for ch in c) and any(ch.isdigit() for ch in c)


def _es_numero_capitulo(v) -> bool:
    """Capítulo: la columna de ítem de pago trae un entero (7), no un 7.101."""
    if isinstance(v, int):
        return True
    if isinstance(v, float):
        return v.is_integer()
    s = str(v or "").strip()
    return s.isdigit()


def _get(row: list, idx: int):
    return row[idx] if idx < len(row) else None


def read_presupuesto(path: Path | str, hoja: str = HOJA_DEFECTO,
                     default_shift: str = config.SHIFT_DIURNO) -> list[LicitacionItem]:
    path = Path(path)
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        if hoja not in wb.sheetnames:
            raise ValueError(
                f"No se encontró la hoja '{hoja}'. Hojas: {wb.sheetnames}")
        ws = wb[hoja]
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
    finally:
        wb.close()

    capitulo = ""
    turno = default_shift
    items: list[LicitacionItem] = []

    for row in rows:
        codigo = _code(_get(row, COL_CODIGO))
        cantidad = _to_float(_get(row, COL_CANT))
        desc = str(_get(row, COL_DESC) or "").strip()

        # Ítem: tiene código válido y cantidad > 0.
        if cantidad > 0 and _es_codigo_item(_get(row, COL_CODIGO)):
            items.append(LicitacionItem(
                item=_code(_get(row, COL_ITEMPAGO)) or codigo,
                descripcion=desc,
                unidad=str(_get(row, COL_UND) or "").strip(),
                cantidad=cantidad,
                precio_contractual=_to_float(_get(row, COL_PRECIO)),
                shift=turno,
                categoria=capitulo,
                codigo_sugerido=codigo,
            ))
            continue

        # Encabezado: hay descripción y NO hay código de ítem.
        if desc and not codigo:
            n = _norm(desc)
            if "turno" in n:
                turno = (config.SHIFT_NOCTURNO if "noc" in n else config.SHIFT_DIURNO)
            elif _es_numero_capitulo(_get(row, COL_ITEMPAGO)):
                num = _code(_get(row, COL_ITEMPAGO))
                capitulo = f"{num} · {desc}" if num else desc
            # otros encabezados (subgrupos) no cambian capítulo ni turno.
    return items
