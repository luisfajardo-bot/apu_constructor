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


# --------------------------------------------------- piso de $1 vs. alerta de $0
def test_componente_huerfano_creado_por_web_alerta_por_cruce_no_por_cero(tmp_path):
    """Con el piso de $1 (Task 1), un componente huérfano deja de reportar el
    genérico 'en $0' -que tapaba el motivo real- y reporta el motivo accionable
    del cruce ('sin insumo en catálogo'). Sigue alertando, solo cambia el motivo."""
    from apu_tool.datos.almacen import Almacen
    from apu_tool.dominio.alertas import alertas_costeo
    from apu_tool.dominio.pricing import PricingEngine
    from apu_tool.servicio import autoria

    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    # "999" no existe en el catálogo -> cruce huérfano al costear.
    autoria.crear_apu(alm, {"codigo": "H1", "turno": "DIURNO", "nombre": "HUERFANO",
        "unidad": "UN", "grupo": "G",
        "componentes": [{"insumo_codigo": "999", "rendimiento": 1.0,
                         "insumo_nombre": "NO EXISTE", "unidad": "UN"}]})
    comps = alm.apus.get_components("H1", "DIURNO")
    assert comps[0].precio_unitario_hist == 1.0            # el piso quedó guardado

    costed, total = PricingEngine(alm).cost_apu("H1", "DIURNO")
    assert costed[0].calidad_cruce == "huerfano"            # confirma el escenario
    item = LicitacionItem(item="1", descripcion="HUERFANO", unidad="UN", cantidad=1.0,
                          precio_contractual=1.0, shift="DIURNO")
    ens = AssembledApu(item=item, apu_codigo="H1", apu_nombre="HUERFANO", unidad="UN",
                       shift="DIURNO", componentes=costed, costo_unitario=total,
                       status=MatchStatus.AUTO, confianza=1.0)

    motivos = alertas_costeo(ens)
    assert motivos, "el componente huérfano debe seguir alertando"
    assert any("sin insumo en catálogo" in m for m in motivos)
    assert not any("en $0" in m for m in motivos)
