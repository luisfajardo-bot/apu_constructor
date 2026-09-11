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

import openpyxl

from apu_tool import config
from apu_tool.nucleo.models import LicitacionItem

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
