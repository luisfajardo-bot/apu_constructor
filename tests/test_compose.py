"""Composición generativa a pedido: se simula la IA (no se llama a la API real).

El armado NO la usa (ver test_assemble.py::test_armado_nunca_llama_a_la_ia); llega
acá solo por `Assembler.generar_composicion`, que dispara el usuario.
"""
import pytest

from apu_tool.dominio.ai_assist import (
    ApuAdvisor,
    ComposedComponent,
    ComposeResult,
    IANoDisponible,
)
from apu_tool.dominio.compose import CandidateInsumo
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
    """Simula la IA y devuelve una composición fija."""
    def __init__(self, composicion):
        self.enabled = True
        self._client = object()  # no se usa
        self.model = "fake"
        self._composicion = composicion

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


def test_un_subapu_de_un_apu_de_referencia_no_entra_como_candidato(alm):
    """La IA no propone sub-APUs en esta fase: un código de APU en la lista blanca
    la invita a proponer algo que el validador después rechaza."""
    alm.apus.insert_apus([Apu("SUB", "SUB-APU DE PRUEBA", "M3", "DIURNO")])
    alm.apus.insert_components([
        ApuComponent("3010", "DIURNO", "SUB", "SUB-APU DE PRUEBA", "M3", 1.0, 0,
                     tipo="apu", ref_shift="DIURNO")])
    insumos, _ = InsumoRetriever(alm).retrieve("DEMOLICION PAVIMENTO", "DIURNO")
    assert "SUB" not in {i.codigo for i in insumos}


def test_generative_composition_is_costed(alm):
    comp = ComposeResult(
        componentes=[ComposedComponent("4279", 2.0), ComposedComponent("322", 0.1)],
        justificacion="cuadrilla + concreto", confianza=0.7)
    assembler = Assembler(alm, advisor=FakeAdvisor(comp))
    item = LicitacionItem("1", "JARDINERA PREFABRICADA EN CONCRETO", "M2", 10,
                          120000, "DIURNO")
    a = assembler.generar_composicion(item)
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
    a = assembler.generar_composicion(item)
    assert len(a.componentes) == 1           # se descarta el código inválido
    assert a.componentes[0].insumo_codigo == "4279"


def test_no_ai_keeps_manual(alm):
    # El armado nunca genera: una actividad sin match queda manual, con o sin IA.
    assembler = Assembler(alm, advisor=ApuAdvisor(enabled=False))
    item = LicitacionItem("1", "ACTIVIDAD TOTALMENTE INEXISTENTE XYZ", "UN", 1, 1, "DIURNO")
    a = assembler.assemble_item(item)
    assert a.status in (MatchStatus.NEW, MatchStatus.REVIEW)
    if a.status == MatchStatus.NEW:
        assert a.origen == "manual"
    assert a.origen != "generado"


def test_una_fuga_de_dinero_al_componer_no_se_disfraza_de_None(alm, monkeypatch):
    """El `except Exception: return None` de `compose_apu` NO puede tragarse el
    guardián del invariante #1: el usuario leería "la IA no pudo componer esta
    actividad" y nadie se enteraría. Gemelo del arreglo de `revision.py::barrer_lote`.
    """
    from apu_tool.dominio import ai_assist, privacy

    llamadas = []

    class _Cliente:
        @property
        def messages(self):
            return self

        def create(self, **kw):
            llamadas.append(kw)
            return None

    monkeypatch.setattr(ai_assist, "candidate_insumo_to_dict",
                        lambda i: {"codigo": i.codigo, "precio_unitario": 40000})
    advisor = ApuAdvisor(enabled=False)
    advisor.enabled, advisor._client = True, _Cliente()
    item = LicitacionItem("1", "ALGO NUEVO", "M2", 1, 1000, "DIURNO")
    insumos, ejemplos = InsumoRetriever(alm).retrieve(item.descripcion, "DIURNO")
    assert insumos                      # si no hay insumos, `compose_apu` sale antes

    with pytest.raises(privacy.PrivacyViolation):
        advisor.compose_apu(item, insumos, ejemplos)
    assert llamadas == []               # y revienta ANTES de tocar la red


class _ErrorSDK(Exception):
    """Como en test_revision_motor: solo importa `status_code` (el SDK es opcional)."""
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class _ClienteQueFalla:
    def __init__(self, status_code):
        self.status_code = status_code

    @property
    def messages(self):
        return self

    def create(self, **kw):
        raise _ErrorSDK(self.status_code)


def _advisor_que_falla(status_code):
    a = ApuAdvisor(enabled=False)      # no construye anthropic.Anthropic()
    a.enabled = True
    a._client = _ClienteQueFalla(status_code)
    return a


_ITEM = LicitacionItem(item="1", descripcion="JARDINERA EN CONCRETO", unidad="M3",
                       cantidad=1, precio_contractual=0, shift="DIURNO")
_INSUMOS = [CandidateInsumo("322", "CONCRETO 3000 PSI", "M3")]


@pytest.mark.parametrize("codigo", [401, 403])
def test_credencial_invalida_al_componer_no_se_lee_como_actividad_imposible(codigo):
    """Con la llave rota, `compose_apu` devolvía None y el diálogo decía "la IA no pudo
    componer esta actividad": mandaba a armar a mano en vez de a revisar el servidor."""
    with pytest.raises(IANoDisponible, match="ANTHROPIC_API_KEY"):
        _advisor_que_falla(codigo).compose_apu(_ITEM, _INSUMOS, [])


@pytest.mark.parametrize("codigo", [429, 500])
def test_un_fallo_pasajero_al_componer_sigue_devolviendo_none(codigo):
    """Guarda: un 429 o un 500 se sigue tragando (el usuario reintenta el botón)."""
    assert _advisor_que_falla(codigo).compose_apu(_ITEM, _INSUMOS, []) is None
