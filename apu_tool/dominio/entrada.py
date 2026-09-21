"""Qué lector le toca a cada entidad. El ÚNICO punto de despacho.

Un diccionario y no una jerarquía de clases: hay una sola implementación especializada
(IDU), y un Protocol con una implementación es andamiaje. Agregar INVÍAS mañana es una
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
        return LecturaPresupuesto(errores=[
            "sin_actividades: la lista no tiene ítems legibles."])
    return LecturaPresupuesto(items=items)


LECTORES: dict[EntidadOrigen, Lector] = {
    EntidadOrigen.IDU:             leer_formulario_idu,
    # El resto usa el importador genérico A PROPÓSITO: no se inventan formatos para
    # entidades cuyos archivos nadie midió. Ver "Fuera de alcance" en la especificación.
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
