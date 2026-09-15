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
