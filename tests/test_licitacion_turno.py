# tests/test_licitacion_turno.py
import openpyxl
import pytest
from apu_tool.dominio.licitacion import read_licitacion


def _xlsx(tmp_path, headers, filas):
    p = tmp_path / "lic.xlsx"
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(headers)
    for f in filas:
        ws.append(f)
    wb.save(p)
    return p


def test_require_turno_sin_columna(tmp_path):
    p = _xlsx(tmp_path, ["ITEM", "DESCRIPCION", "UNIDAD", "CANTIDAD", "PRECIO"],
              [["1", "Concreto", "M3", 10, 400000]])
    with pytest.raises(ValueError):
        read_licitacion(p, require_turno=True)


def test_require_turno_por_fila_ok(tmp_path):
    p = _xlsx(tmp_path, ["ITEM", "DESCRIPCION", "UNIDAD", "CANTIDAD", "PRECIO", "TURNO"],
              [["1", "Concreto", "M3", 10, 400000, "DIURNO"],
               ["2", "Excavacion", "M3", 5, 200000, "NOCTURNO"]])
    items = read_licitacion(p, require_turno=True)
    assert [it.shift for it in items] == ["DIURNO", "NOCTURNO"]


def test_require_turno_fila_sin_valor(tmp_path):
    p = _xlsx(tmp_path, ["ITEM", "DESCRIPCION", "UNIDAD", "CANTIDAD", "PRECIO", "TURNO"],
              [["1", "Concreto", "M3", 10, 400000, "DIURNO"],
               ["2", "Excavacion", "M3", 5, 200000, ""]])
    with pytest.raises(ValueError):
        read_licitacion(p, require_turno=True)


def test_sin_require_turno_retrocompatible(tmp_path):
    p = _xlsx(tmp_path, ["ITEM", "DESCRIPCION", "UNIDAD", "CANTIDAD", "PRECIO"],
              [["1", "Concreto", "M3", 10, 400000]])
    items = read_licitacion(p, default_shift="DIURNO")
    assert items and items[0].shift == "DIURNO"
