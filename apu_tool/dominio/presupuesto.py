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
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import openpyxl
from openpyxl.utils.exceptions import InvalidFileException

from apu_tool import config
from apu_tool.nucleo.models import LicitacionItem
from apu_tool.nucleo.redondeo import mul_redondeado
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


# Encabezados de las columnas de oferta y corrección del proponente. NO se leen: en el
# presupuesto oficial vienen en cero, y no hay un caso real medido que diga qué hacer
# con ellas. Se detectan para AVISAR, que es distinto de ignorarlas en silencio.
_ENCABEZADOS_OFERTA = (
    "valor unitario sin aiu ofertado",
    "valor unitario sin aiu corregido",
    "valor unitario con aiu corregido",
    "valor unitario con aiu corregido x cantidad",
)


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

    OJO: el `precio_contractual` que devuelve ahora es el valor unitario CON AIU (la
    columna que concilia con el VALOR TOTAL del Excel), no el básico sin AIU que usaba
    la versión anterior. El básico viaja aparte, en `precio_contractual_sin_aiu`.
    """
    lectura = leer_formulario_idu(path, hoja=hoja or None,
                                  default_shift=default_shift)
    if lectura.errores:
        raise ValueError(" ".join(lectura.errores))
    return lectura.items


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


def _columnas_de_oferta(fila_encabezado: list) -> list[int]:
    """Las columnas del proponente (oferta y corrección). Se detectan para avisar."""
    return [i for i, celda in enumerate(fila_encabezado)
            if norm_encabezado(celda) in _ENCABEZADOS_OFERTA]


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

    cols_oferta = _columnas_de_oferta([c[0] for c in filas[idx_enc]])
    con_oferta = sum(1 for f in filas[idx_enc + 1:]
                     if any(_to_float(_val(f, i)) for i in cols_oferta))
    if con_oferta:
        avisos.append(Advertencia(
            "oferta_diligenciada", 0,
            f"{con_oferta} fila(s) traen valores en las columnas de oferta o corrección. "
            f"Esta versión NO las lee: el contractual sale del valor unitario oficial "
            f"con AIU."))

    ctx = _Recorrido(mapeo, default_shift, avisos)
    for n, fila in enumerate(filas[idx_enc + 1:], start=idx_enc + 2):
        ctx.procesar(fila, n)
    ctx.cerrar()

    return LecturaPresupuesto(
        items=ctx.items, capitulos=ctx.capitulos, hoja=elegida,
        fila_encabezado=idx_enc + 1, filas_ignoradas=ctx.ignoradas,
        errores=ctx.errores(), advertencias=avisos, conciliacion=ctx.conciliacion())
