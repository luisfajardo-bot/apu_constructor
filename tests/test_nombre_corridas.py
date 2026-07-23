from apu_tool.servicio.corridas import nombre_desde_archivo


def test_nombre_desde_archivo_quita_extension():
    assert nombre_desde_archivo("Licitacion Calle 13.xlsx") == "Licitacion Calle 13"


def test_nombre_desde_archivo_csv_y_espacios():
    assert nombre_desde_archivo("  Obra Lote SL5.csv  ") == "Obra Lote SL5"


def test_nombre_desde_archivo_sin_extension():
    assert nombre_desde_archivo("presupuesto") == "presupuesto"


def test_nombre_desde_archivo_puntos_intermedios():
    assert nombre_desde_archivo("v1.2.final.xlsx") == "v1.2.final"


def test_nombre_desde_archivo_vacio():
    assert nombre_desde_archivo("") == ""
