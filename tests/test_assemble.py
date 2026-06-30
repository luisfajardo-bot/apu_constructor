"""Prueba el orquestador completo con IA deshabilitada (fallback determinístico)."""
import pytest

from apu_tool.dominio.ai_assist import ApuAdvisor
from apu_tool.dominio.assemble import Assembler
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import (
    Apu,
    ApuComponent,
    Insumo,
    LicitacionItem,
    MatchStatus,
)


@pytest.fixture()
def assembler(tmp_path):
    a = Almacen(tmp_path / "precios.db", tmp_path / "apus.db")
    a.reset()
    a.precios.insert_insumos([Insumo("4279", "CUADRILLA", "HR", "MO", 40000, "PRECIO IDU")])
    a.apus.insert_apus([Apu("3009", "EXCAVACION MANUAL PARA REDES", "M3", "DIURNO")])
    a.apus.insert_components([ApuComponent("3009", "DIURNO", "4279", "CUADRILLA", "HR", 1.5, 30000)])
    return Assembler(a, advisor=ApuAdvisor(enabled=False))


def test_auto_match_and_cost(assembler):
    item = LicitacionItem("1", "EXCAVACION MANUAL PARA REDES", "M3", 10, 80000, "DIURNO")
    a = assembler.assemble_item(item)
    assert a.status == MatchStatus.AUTO
    assert a.apu_codigo == "3009"
    assert a.costo_unitario == pytest.approx(60000)   # 1.5 * 40000
    assert a.costo_total == pytest.approx(600000)
    assert a.margen_unitario == pytest.approx(20000)


def test_new_activity_marked(assembler):
    item = LicitacionItem("2", "MONTAJE DE TURBINA EOLICA", "UN", 1, 1000, "DIURNO")
    a = assembler.assemble_item(item)
    assert a.status in (MatchStatus.NEW, MatchStatus.REVIEW)


def test_reassemble_with_choice(assembler):
    item = LicitacionItem("3", "algo raro", "M3", 4, 100000, "DIURNO")
    a = assembler.reassemble_with_choice(item, "3009", "DIURNO")
    assert a.status == MatchStatus.CONFIRMED
    assert a.costo_unitario == pytest.approx(60000)


def test_assemble_item_acepta_match_precomputado(assembler):
    # A.1: pasar el MatchResult ya calculado produce el MISMO AssembledApu que
    # calcularlo adentro (permite eliminar el doble match del stream).
    item = LicitacionItem("1", "EXCAVACION MANUAL PARA REDES", "M3", 10, 80000, "DIURNO")
    base = assembler.assemble_item(item)
    pre = assembler.matcher.match(item)
    assert assembler.assemble_item(item, pre) == base


def test_totals_consistency(assembler):
    item = LicitacionItem("1", "EXCAVACION MANUAL PARA REDES", "M3", 3, 80000, "DIURNO")
    a = assembler.assemble_item(item)
    assert a.contractual_total == pytest.approx(240000)
    assert a.margen_total == pytest.approx(a.contractual_total - a.costo_total)
