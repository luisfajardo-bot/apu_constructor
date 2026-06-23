"""Composición generativa: se simula la IA (no se llama a la API real)."""
import pytest

from apu_tool.dominio.ai_assist import (
    AIDecision,
    ApuAdvisor,
    ComposedComponent,
    ComposeResult,
)
from apu_tool.dominio.assemble import Assembler
from apu_tool.dominio.compose import InsumoRetriever
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import (
    Apu,
    ApuComponent,
    Insumo,
    LicitacionItem,
    MatchStatus,
)


class FakeAdvisor(ApuAdvisor):
    """Simula la IA: fuerza el camino generativo y devuelve una composición fija."""
    def __init__(self, composicion):
        self.enabled = True
        self._client = object()  # no se usa
        self.model = "fake"
        self._composicion = composicion

    def choose_apu(self, item, candidatos, depriced):
        return AIDecision(None, 0.0, "sin base", "ia")  # fuerza generación

    def compose_apu(self, item, insumos, ejemplos):
        return self._composicion


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


def test_generative_composition_is_costed(alm):
    comp = ComposeResult(
        componentes=[ComposedComponent("4279", 2.0), ComposedComponent("322", 0.1)],
        justificacion="cuadrilla + concreto", confianza=0.7)
    assembler = Assembler(alm, advisor=FakeAdvisor(comp))
    item = LicitacionItem("1", "JARDINERA PREFABRICADA EN CONCRETO", "M2", 10,
                          120000, "DIURNO")
    a = assembler.assemble_item(item)
    assert a.origen == "generado"
    assert a.status == MatchStatus.REVIEW
    # 2.0*40000 + 0.1*500000 = 130000
    assert a.costo_unitario == pytest.approx(130000)
    assert len(a.componentes) == 2


def test_generative_drops_invalid_codes(alm):
    comp = ComposeResult(
        componentes=[ComposedComponent("4279", 1.0),
                     ComposedComponent("NOEXISTE", 5.0)],
        justificacion="x", confianza=0.5)
    assembler = Assembler(alm, advisor=FakeAdvisor(comp))
    item = LicitacionItem("1", "ALGO NUEVO", "M2", 1, 1000, "DIURNO")
    a = assembler.assemble_item(item)
    assert len(a.componentes) == 1           # se descarta el código inválido
    assert a.componentes[0].insumo_codigo == "4279"


def test_no_ai_keeps_manual(alm):
    # advisor real deshabilitado -> compose devuelve None -> manual
    assembler = Assembler(alm, advisor=ApuAdvisor(enabled=False))
    item = LicitacionItem("1", "ACTIVIDAD TOTALMENTE INEXISTENTE XYZ", "UN", 1, 1, "DIURNO")
    a = assembler.assemble_item(item)
    assert a.status in (MatchStatus.NEW, MatchStatus.REVIEW)
    if a.status == MatchStatus.NEW:
        assert a.origen == "manual"
