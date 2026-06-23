"""El armado por código directo (presupuesto) no pasa por el match difuso."""
import pytest

from apu_tool.dominio.ai_assist import ApuAdvisor
from apu_tool.dominio.assemble import Assembler
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo, LicitacionItem, MatchStatus


@pytest.fixture()
def alm(tmp_path):
    a = Almacen(tmp_path / "precios.db", tmp_path / "apus.db")
    a.reset()
    a.precios.insert_insumos([Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU")])
    a.apus.insert_apus([Apu("3009", "EXCAVACION MANUAL PARA RED", "M3", "DIURNO")])
    a.apus.insert_components([ApuComponent("3009", "DIURNO", "100", "CEMENTO", "KG", 3.0, 900)])
    return a


def test_arma_por_codigo_directo(alm):
    asm = Assembler(alm, advisor=ApuAdvisor(enabled=False))
    # Descripción deliberadamente NO parecida: si funcionara por nombre, fallaría.
    item = LicitacionItem(item="7.101", descripcion="texto irrelevante zzz",
                          unidad="M3", cantidad=10.0, precio_contractual=50000.0,
                          shift="DIURNO", categoria="7 · REDES", codigo_sugerido="3009")
    res = asm.assemble_item(item)
    assert res.apu_codigo == "3009"
    assert res.status == MatchStatus.AUTO
    assert res.confianza == 1.0
    assert res.costo_unitario == pytest.approx(3000)   # 3 * 1000


def test_codigo_inexistente_cae_al_flujo_normal(alm):
    asm = Assembler(alm, advisor=ApuAdvisor(enabled=False))
    item = LicitacionItem(item="9.999", descripcion="actividad sin match alguno",
                          unidad="UN", cantidad=1.0, precio_contractual=10.0,
                          shift="DIURNO", categoria="9 · X", codigo_sugerido="NO_EXISTE")
    res = asm.assemble_item(item)
    # No se armó por código directo: el path directo produce exactamente AUTO + confianza 1.0.
    # El fallback difuso puede devolver el único APU del fixture pero con status != AUTO.
    assert not (res.status == MatchStatus.AUTO and res.confianza == 1.0)
