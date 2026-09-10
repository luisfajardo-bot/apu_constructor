"""Rendimientos observados: la evidencia determinística de la biblioteca.

Sin esto el validador no tiene contra qué comparar y la confianza no tiene señal.
"""
import pytest

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.dominio.compose import rendimientos_observados
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo


@pytest.fixture()
def alm(tmp_path):
    a = Almacen(tmp_path / "precios.db", tmp_path / "apus.db",
                tmp_path / "corridas.db")
    a.reset()
    a.precios.insert_insumos([
        Insumo("4279", "CUADRILLA", "HR", "MO", 40000, "PRECIO IDU"),
        Insumo("6092", "HERRAMIENTA MENOR", "GLB", "EQ", 2000, "PRECIO IDU"),
    ])
    a.apus.insert_apus([
        Apu("A1", "UNO", "M3", "DIURNO"), Apu("A2", "DOS", "M3", "DIURNO"),
        Apu("A3", "TRES", "M3", "DIURNO"),
    ])
    a.apus.insert_components([
        ApuComponent("A1", "DIURNO", "4279", "CUADRILLA", "HR", 0.40, 0),
        ApuComponent("A2", "DIURNO", "4279", "CUADRILLA", "HR", 0.62, 0),
        ApuComponent("A3", "DIURNO", "4279", "CUADRILLA", "HR", 1.10, 0),
        ApuComponent("A1", "DIURNO", "6092", "HERRAMIENTA MENOR", "GLB", 1.0, 0),
    ])
    return a


def test_devuelve_n_minimo_mediana_y_maximo(alm):
    obs = rendimientos_observados(alm, ["4279"])
    r = obs["4279"]
    assert r.n == 3
    assert r.minimo == 0.40
    assert r.mediana == 0.62
    assert r.maximo == 1.10
    assert r.unidad == "HR"


def test_un_insumo_sin_uso_no_aparece(alm):
    assert "9999" not in rendimientos_observados(alm, ["9999"])


def test_ignora_rendimientos_no_positivos(alm):
    """Un 0 en la biblioteca es un dato roto, no un antecedente."""
    alm.apus.insert_apus([Apu("A4", "CUATRO", "M3", "DIURNO")])
    alm.apus.insert_components([
        ApuComponent("A4", "DIURNO", "6092", "HERRAMIENTA MENOR", "GLB", 0.0, 0)])
    assert rendimientos_observados(alm, ["6092"])["6092"].n == 1


def test_mediana_con_n_par(alm):
    alm.apus.insert_apus([Apu("A5", "CINCO", "M3", "DIURNO")])
    alm.apus.insert_components([
        ApuComponent("A5", "DIURNO", "4279", "CUADRILLA", "HR", 0.80, 0)])
    # 0.40, 0.62, 0.80, 1.10 -> (0.62+0.80)/2
    assert rendimientos_observados(alm, ["4279"])["4279"].mediana == pytest.approx(0.71)


def test_sin_codigos_no_consulta_nada(alm):
    assert rendimientos_observados(alm, []) == {}


def test_umbral_minimo_de_antecedentes_existe():
    assert config.COMPOSICION_MIN_ANTECEDENTES == 3
    assert config.COMPOSICION_LIMITE_RENDIMIENTO > 0


def test_a_la_ia_no_le_llega_dinero_en_esto(alm):
    """El tipo no tiene campos monetarios y el guardián lo confirma."""
    from apu_tool.dominio import privacy
    obs = rendimientos_observados(alm, ["4279"])
    privacy.assert_no_money([r.to_dict() for r in obs.values()])


def test_la_unidad_mayoritaria_manda_y_las_otras_no_entran_al_rango(alm):
    """Caso real: el insumo 4288 N aparece en HR (0,033) y en JR (hasta 2,6).
    Un rango que mezcla las dos no describe nada."""
    alm.apus.insert_apus([Apu("A6", "SEIS", "M3", "DIURNO"),
                          Apu("A7", "SIETE", "M3", "DIURNO")])
    alm.apus.insert_components([
        ApuComponent("A6", "DIURNO", "4279", "CUADRILLA", "JR", 2.60, 0),
        ApuComponent("A7", "DIURNO", "4279", "CUADRILLA", "JR", 2.40, 0),
    ])
    r = rendimientos_observados(alm, ["4279"])["4279"]
    assert r.unidad == "HR"          # 3 filas en HR contra 2 en JR
    assert r.n == 3
    assert r.maximo == 1.10          # el 2,60 de JR NO entra
    assert r.descartados_otra_unidad == 2


def test_el_empate_de_unidades_se_resuelve_igual_siempre(alm):
    """Sin desempate, cuál gana depende del orden de la base, que difiere entre
    SQLite y Postgres."""
    alm.apus.insert_apus([Apu("A8", "OCHO", "M3", "DIURNO")])
    alm.apus.insert_components([
        ApuComponent("A8", "DIURNO", "6092", "HERRAMIENTA MENOR", "ZZZ", 5.0, 0)])
    # 6092 tiene 1 fila en GLB y 1 en ZZZ: empate, gana el primero alfabético.
    assert rendimientos_observados(alm, ["6092"])["6092"].unidad == "GLB"


def test_un_insumo_con_todas_sus_filas_en_cero_no_aparece(alm):
    """Rama distinta de 'no se usa en ningún APU': acá SÍ está en la biblioteca,
    pero no tiene un solo antecedente utilizable."""
    alm.apus.insert_apus([Apu("A9", "NUEVE", "M3", "DIURNO")])
    alm.apus.insert_components([
        ApuComponent("A9", "DIURNO", "7777", "INSUMO ROTO", "UN", 0.0, 0)])
    assert "7777" not in rendimientos_observados(alm, ["7777"])
