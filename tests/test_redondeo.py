from apu_tool.nucleo.redondeo import mul_redondeado


def test_medio_hacia_arriba():
    assert mul_redondeado(1.05, 1250) == 1313      # 1312.5 -> 1313
    assert mul_redondeado(1.0, 1312.4) == 1312     # 1312.4 -> 1312
    assert mul_redondeado(0.5, 1) == 1             # 0.5 -> 1


def test_producto_entero_exacto_sin_cambio():
    assert mul_redondeado(1.05, 350000) == 367500
    assert mul_redondeado(2.0, 350000) == 700000


def test_minimo_uno_si_positivo_redondea_a_cero():
    assert mul_redondeado(0.0003, 1000) == 1       # 0.3 -> 1 (nada en $0 por redondeo)
    assert mul_redondeado(0.4, 1) == 1             # 0.4 -> 1


def test_cero_genuino_queda_en_cero():
    assert mul_redondeado(2.0, 0) == 0             # precio 0
    assert mul_redondeado(0, 1000) == 0            # rendimiento 0


def test_devuelve_int():
    assert isinstance(mul_redondeado(1.05, 1250), int)
    assert isinstance(mul_redondeado(2.0, 0), int)
