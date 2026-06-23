import pytest
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Insumo, LicitacionItem
from apu_tool.dominio.assemble import Assembler
from apu_tool.dominio.ai_assist import ComposeResult


class _Advisor:
    """Advisor falso: no elige histórico, y compone con un código conocido."""
    def choose_apu(self, item, candidatos, depriced):
        class D:  # decisión vacía -> fuerza la rama generativa
            apu_codigo = None; confianza = 0.0; justificacion = ""; fuente = "test"
        return D()
    def compose_apu(self, item, insumos, ejemplos):
        class C:
            componentes = [type("X", (), {"insumo_codigo": "4279", "rendimiento": 2.0})()]
            justificacion = "ok"; confianza = 0.9
        return C()


@pytest.fixture()
def alm(tmp_path):
    a = Almacen(tmp_path / "p.db", tmp_path / "a.db")
    a.reset()
    a.precios.insert_insumos([Insumo("4279", "CUADRILLA", "HR", "MO", 40000, "PRECIO IDU")])
    return a


def test_generado_usa_candidato_del_codigo(alm):
    asm = Assembler(alm, advisor=_Advisor())
    item = LicitacionItem(item="1", descripcion="ACTIVIDAD NUEVA", unidad="M2",
                          cantidad=1, precio_contractual=0, shift="DIURNO")
    res = asm._try_generate(item)
    assert res is not None
    assert res.componentes[0].insumo_nombre == "CUADRILLA"
    assert res.componentes[0].precio_unitario == 40000
