from apu_tool.nucleo.redondeo import mul_redondeado


def test_medio_hacia_arriba():
    assert mul_redondeado(1.05, 1250) == 1313      # 1312.5 -> 1313
    assert mul_redondeado(1.0, 1312.4) == 1312     # 1312.4 -> 1312
    assert mul_redondeado(0.5, 1) == 1             # 0.5 -> 1


def test_producto_entero_exacto_sin_cambio():
    assert mul_redondeado(1.05, 350000) == 367500
    assert mul_redondeado(2.0, 350000) == 700000


def test_minimo_uno_si_positivo_redondea_a_cero():
    assert mul_redondeado(0.0003, 1000) == 1       # 0.3 -> 1 (nada en $0 por redondeo)
    assert mul_redondeado(0.4, 1) == 1             # 0.4 -> 1


def test_cero_genuino_queda_en_cero():
    assert mul_redondeado(2.0, 0) == 0             # precio 0
    assert mul_redondeado(0, 1000) == 0            # rendimiento 0


def test_devuelve_int():
    assert isinstance(mul_redondeado(1.05, 1250), int)
    assert isinstance(mul_redondeado(2.0, 0), int)


def test_pricing_redondea_costo_de_componente(tmp_path):
    from apu_tool.datos.almacen import Almacen
    from apu_tool.nucleo.models import Apu, ApuComponent, Insumo
    from apu_tool.dominio.pricing import PricingEngine
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([Insumo("100", "X", "KG", "MAT", 1000.0, "PRECIO IDU")])
    alm.apus.crear_apu(Apu("A1", "APU", "M2", "DIURNO"),
                       [ApuComponent("A1", "DIURNO", "100", "X", "KG", 1.0005, 1000.0)])
    costed, total = PricingEngine(alm).cost_apu("A1", "DIURNO")
    assert costed[0].costo == 1001            # 1.0005 * 1000 = 1000.5 -> 1001
    assert isinstance(costed[0].costo, int)
    assert total == 1001


def test_assembledapu_totales_redondeados():
    from apu_tool.nucleo.models import AssembledApu, LicitacionItem, MatchStatus
    item = LicitacionItem(item="1", descripcion="x", unidad="M2", cantidad=3.0,
                          precio_contractual=1000.5, shift="DIURNO")
    a = AssembledApu(item=item, apu_codigo="A1", apu_nombre="X", unidad="M2",
                     shift="DIURNO", componentes=[], costo_unitario=1312,
                     status=MatchStatus.AUTO, confianza=1.0)
    assert a.costo_total == 3936              # 1312 * 3 = 3936
    assert a.contractual_total == 3002        # 1000.5 * 3 = 3001.5 -> 3002
    assert isinstance(a.contractual_total, int)
