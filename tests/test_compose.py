"""Recuperación de insumos candidatos: qué entra a la lista blanca y qué no.

Lo que se hace con esa lista — pedirle una composición al modelo, validarla y
puntuarla — se prueba en `test_composicion_motor.py`. El armado NO llega acá (ver
test_assemble.py::test_armado_nunca_llama_a_la_ia).
"""
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.dominio.compose import InsumoRetriever
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo


@pytest.fixture()
def alm(tmp_path):
    a = Almacen(tmp_path / "precios.db", tmp_path / "apus.db")
    a.reset()
    a.precios.insert_insumos([
        Insumo("4279", "CUADRILLA OFICIAL MAS AYUDANTES", "HR", "MO", 40000, "PRECIO IDU"),
        Insumo("6092", "HERRAMIENTA MENOR", "GLB", "EQ", 2000, "PRECIO IDU"),
        Insumo("322", "CONCRETO 3000 PSI", "M3", "MAT", 500000, "PRECIO IDU"),
    ])
    a.apus.insert_apus([Apu("3010", "DEMOLICION PAVIMENTO", "M3", "DIURNO")])
    a.apus.insert_components([
        ApuComponent("3010", "DIURNO", "4279", "CUADRILLA", "HR", 0.5, 40000),
        ApuComponent("3010", "DIURNO", "6092", "HERRAMIENTA MENOR", "GLB", 1.0, 2000),
    ])
    return a


def test_retriever_returns_candidates(alm):
    r = InsumoRetriever(alm)
    insumos, ejemplos = r.retrieve("CONCRETO para jardinera", "DIURNO")
    codigos = {i.codigo for i in insumos}
    assert "322" in codigos          # por nombre (CONCRETO)


def test_un_subapu_de_un_apu_de_referencia_no_entra_como_candidato(alm):
    """La IA no propone sub-APUs en esta fase: un código de APU en la lista blanca
    la invita a proponer algo que el validador después rechaza."""
    alm.apus.insert_apus([Apu("SUB", "SUB-APU DE PRUEBA", "M3", "DIURNO")])
    alm.apus.insert_components([
        ApuComponent("3010", "DIURNO", "SUB", "SUB-APU DE PRUEBA", "M3", 1.0, 0,
                     tipo="apu", ref_shift="DIURNO")])
    insumos, _ = InsumoRetriever(alm).retrieve("DEMOLICION PAVIMENTO", "DIURNO")
    assert "SUB" not in {i.codigo for i in insumos}
