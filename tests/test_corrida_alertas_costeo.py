# tests/test_corrida_alertas_costeo.py
from apu_tool.servicio.corridas import _vista_item, _totales
from apu_tool.nucleo.models import AssembledApu, CostedComponent, LicitacionItem, MatchStatus


def _ensamble(costo, precio_comp):
    item = LicitacionItem(item="1", descripcion="Losa", unidad="m3", cantidad=1.0,
                          precio_contractual=100.0, shift="DIURNO")
    comp = CostedComponent(insumo_codigo="7", insumo_nombre="Cemento", unidad="kg",
                           rendimiento=1.0, precio_unitario=precio_comp, fuente_precio="X",
                           costo=costo, calidad_cruce="exacto")
    return AssembledApu(item=item, apu_codigo="A", apu_nombre="Losa", unidad="m3",
                        shift="DIURNO", componentes=[comp], costo_unitario=costo,
                        status=MatchStatus.AUTO, confianza=1.0)


class _Row:
    def __init__(self, status="auto"):
        self.status = status


def test_vista_item_expone_alertas_costeo():
    v = _vista_item(_ensamble(0.0, 0.0), seq=0, status="auto")
    assert v["alertas_costeo"] and "en $0" in v["alertas_costeo"][0]
    v_ok = _vista_item(_ensamble(10.0, 10.0), seq=0, status="auto")
    assert v_ok["alertas_costeo"] == []


def test_totales_cuenta_items_con_alerta():
    ens = [_ensamble(0.0, 0.0), _ensamble(10.0, 10.0)]
    tot = _totales(ens, [_Row(), _Row()])
    assert tot["n_alertas_costeo"] == 1
