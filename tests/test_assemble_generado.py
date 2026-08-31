import pytest
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Insumo, LicitacionItem
from apu_tool.dominio.assemble import Assembler


class _Advisor:
    """Advisor falso: compone con un código conocido. `generar_composicion` es lo
    único que usa al advisor ahora."""
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
    res = asm.generar_composicion(item)
    assert res is not None
    assert res.componentes[0].insumo_nombre == "CUADRILLA"
    assert res.componentes[0].precio_unitario == 40000
