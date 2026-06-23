from apu_tool.nucleo.texto import normalizar


def test_normaliza_tildes_mayusculas_y_espacios():
    assert normalizar("  Camión  de   Volteo  ") == "CAMION DE VOLTEO"

def test_normaliza_puntuacion_a_espacio():
    assert normalizar('CODO 90° D=8" RDE-21.') == "CODO 90 D 8 RDE 21"

def test_normaliza_none_y_vacio():
    assert normalizar(None) == ""
    assert normalizar("") == ""
