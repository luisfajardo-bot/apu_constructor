"""Parser del Formulario 1 de Presupuesto Oficial del IDU."""
from apu_tool.dominio.presupuesto import (
    capitulo_de, es_item_entero, item_pago_texto, norm_encabezado, normalizar_item_pago,
)


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
    # openpyxl entrega los enteros de una celda como float: 3007.0, no 3007. Sin el
    # guard, el punto decimal se pierde como puntuación y esto daría "30070".
    assert norm_encabezado(3007.0) == "3007"


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
    # Sin formato útil tampoco puede PERDER dígitos: un `:g` cortaría a 6 cifras
    # significativas y esto daría "123457".
    assert item_pago_texto(123456.789, "General") == "123456.789"


def test_item_pago_texto_descarta_booleanos_y_nan():
    # `bool` es `int` en Python: sin el guard, True se leería como el ítem "1" y la
    # fila entraría al capítulo 1. NaN es lo que deja una fórmula rota.
    assert item_pago_texto(True, "0.000") == ""
    assert item_pago_texto(False, "0.000") == ""
    assert item_pago_texto(float("nan"), "0.000") == ""


def test_normalizar_item_pago_unifica_separadores_y_sufijo_de_turno():
    assert normalizar_item_pago("2.001") == "2.001"
    assert normalizar_item_pago("2,001") == "2.001"
    assert normalizar_item_pago("2.001 N") == "2.001 N"
    assert normalizar_item_pago("2.001-N") == "2.001 N"
    assert normalizar_item_pago("2,001-N") == "2.001 N"
    assert normalizar_item_pago('"2.001"') == "2.001"
    assert normalizar_item_pago("'2.001'") == "2.001"
    # Comillas anidadas al revés: la simple por fuera, la doble por dentro.
    assert normalizar_item_pago("'\"2.001\"'") == "2.001"


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
    # Celda vacía de Excel: las tareas siguientes llaman esto sobre valores crudos.
    assert capitulo_de(None) == ""


def test_es_item_entero_distingue_capitulo_de_actividad():
    assert es_item_entero("2") is True
    assert es_item_entero("14") is True
    assert es_item_entero("2.001") is False
    assert es_item_entero("2.001 N") is False
    assert es_item_entero("") is False
    assert es_item_entero(None) is False
