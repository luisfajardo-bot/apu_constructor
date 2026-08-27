"""El motor costea con las desviaciones del proyecto. Sin contexto, nada cambia."""
from apu_tool.datos.almacen import Almacen
from apu_tool.dominio.pricing import PricingEngine
from apu_tool.dominio.transporte import ContextoProyecto
from apu_tool.nucleo.models import (
    AjusteProyecto, Apu, ApuComponent, ClaseTransporte, Insumo, ParametrosProyecto)


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo(codigo="7462", nombre="TRANSPORTE DE PETREOS", unidad="M3-KM",
               grupo="TRANSPORTES", precio=1000.0, fuente_precio="COSTO INTERNO"),
        Insumo(codigo="7231", nombre="DERECHOS DE BOTADERO", unidad="M3",
               grupo="TRANSPORTES", precio=5000.0, fuente_precio="COSTO INTERNO"),
        Insumo(codigo="INT3", nombre="PEAJE", unidad="GLB", grupo="",
               precio=8000.0, fuente_precio="COSTO INTERNO"),
    ])
    alm.apus.insert_apus([
        Apu(codigo="4390", nombre="RELLENO", unidad="M3", shift="DIURNO", grupo="VIAS"),
        Apu(codigo="3017", nombre="TRANSPORTE Y DISPOSICION FINAL DE ESCOMBROS",
            unidad="M3", shift="DIURNO", grupo="TRANSPORTES"),
    ])
    alm.apus.insert_components([
        # el APU 4390 usa el sub-APU 3017 y transporte propio
        ApuComponent(apu_codigo="4390", shift="DIURNO", insumo_codigo="3017",
                     insumo_nombre="TRANSPORTE Y DISPOSICION FINAL DE ESCOMBROS",
                     unidad="M3", rendimiento=1.0, precio_unitario_hist=20000.0,
                     tipo="apu", ref_shift="DIURNO"),
        ApuComponent(apu_codigo="4390", shift="DIURNO", insumo_codigo="7462",
                     insumo_nombre="TRANSPORTE DE PETREOS", unidad="M3-KM",
                     rendimiento=26.25, precio_unitario_hist=1000.0),
        ApuComponent(apu_codigo="4390", shift="DIURNO", insumo_codigo="INT3",
                     insumo_nombre="PEAJE", unidad="GLB", rendimiento=1.0,
                     precio_unitario_hist=8000.0),
        # composición del sub-APU de botadero
        ApuComponent(apu_codigo="3017", shift="DIURNO", insumo_codigo="7231",
                     insumo_nombre="DERECHOS DE BOTADERO", unidad="M3",
                     rendimiento=1.3, precio_unitario_hist=5000.0),
        ApuComponent(apu_codigo="3017", shift="DIURNO", insumo_codigo="7462",
                     insumo_nombre="TRANSPORTE DE PETREOS", unidad="M3-KM",
                     rendimiento=20.0, precio_unitario_hist=1000.0),
    ])
    return alm


def _clas():
    def c(apu, cod, cat, vol):
        return ((apu, "DIURNO", cod), ClaseTransporte(
            apu_codigo=apu, shift="DIURNO", insumo_codigo=cod,
            insumo_nombre="TRANSPORTE DE PETREOS", categoria=cat, volumen=vol,
            km_base=25.0))
    return dict([c("4390", "7462", "granulares", 1.05),
                 c("3017", "7462", "botadero", 1.0)])


def test_sin_contexto_el_costeo_es_el_de_siempre(tmp_path):
    alm = _alm(tmp_path)
    base = PricingEngine(alm).cost_apu("4390", "DIURNO")
    conctx_vacio = PricingEngine(alm, contexto=ContextoProyecto(
        params=ParametrosProyecto(), clasificacion={})).cost_apu("4390", "DIURNO")
    assert [(c.insumo_codigo, c.rendimiento, c.costo) for c in base[0]] == \
           [(c.insumo_codigo, c.rendimiento, c.costo) for c in conctx_vacio[0]]
    assert base[1] == conctx_vacio[1]


def test_reescala_granulares_del_apu(tmp_path):
    alm = _alm(tmp_path)
    ctx = ContextoProyecto(params=ParametrosProyecto(km_granulares=32),
                           clasificacion=_clas())
    comps, _ = PricingEngine(alm, contexto=ctx).cost_apu("4390", "DIURNO")
    tte = [c for c in comps if c.insumo_codigo == "7462"][0]
    assert tte.rendimiento == 33.6           # 1.05 * 32
    assert tte.costo == 33600


def test_reescala_el_subapu_de_botadero(tmp_path):
    """La distancia del botadero vive dentro del sub-APU: reescalarlo alcanza a
    todos los APUs que lo usan, sin código extra."""
    alm = _alm(tmp_path)
    ctx = ContextoProyecto(params=ParametrosProyecto(km_botadero=34),
                           clasificacion=_clas())
    comps, _ = PricingEngine(alm, contexto=ctx).cost_apu("4390", "DIURNO")
    sub = [c for c in comps if c.insumo_codigo == "3017"][0]
    # sub-APU = derechos (1.3 * 5000) + transporte (1.0 * 34 * 1000)
    assert sub.precio_unitario == 6500 + 34000


def test_peaje_no_aplica_lo_saca_de_la_composicion(tmp_path):
    alm = _alm(tmp_path)
    ctx = ContextoProyecto(params=ParametrosProyecto(peaje_aplica=False),
                           clasificacion={})
    comps, _ = PricingEngine(alm, contexto=ctx).cost_apu("4390", "DIURNO")
    assert all(c.insumo_codigo != "INT3" for c in comps)
    assert all(c.costo > 0 for c in comps)   # y nada quedó en $0


def test_peaje_usa_el_valor_del_proyecto(tmp_path):
    alm = _alm(tmp_path)
    ctx = ContextoProyecto(
        params=ParametrosProyecto(peaje_aplica=True, peaje_valor=12400),
        clasificacion={})
    comps, _ = PricingEngine(alm, contexto=ctx).cost_apu("4390", "DIURNO")
    peaje = [c for c in comps if c.insumo_codigo == "INT3"][0]
    assert peaje.precio_unitario == 12400
    assert peaje.fuente_precio == "peaje del proyecto"
    assert peaje.costo == 12400


def test_pendientes_por_apu(tmp_path):
    alm = _alm(tmp_path)
    ctx = ContextoProyecto(params=ParametrosProyecto(km_granulares=32),
                           clasificacion={})
    motor = PricingEngine(alm, contexto=ctx)
    motor.cost_apu("4390", "DIURNO")
    assert motor.sin_distancia("4390", "DIURNO") == ("7462",)
    assert motor.sin_distancia("9999", "DIURNO") == ()


def test_ajuste_agrega_insumo_al_apu_del_proyecto(tmp_path):
    alm = _alm(tmp_path)
    ctx = ContextoProyecto(
        params=ParametrosProyecto(), clasificacion={},
        ajustes=(AjusteProyecto(apu_codigo="4390", shift="DIURNO", accion="quitar",
                                insumo_codigo="INT3", insumo_nombre="PEAJE"),))
    comps, _ = PricingEngine(alm, contexto=ctx).cost_apu("4390", "DIURNO")
    assert all(c.insumo_codigo != "INT3" for c in comps)


def test_precargar_no_cambia_el_resultado(tmp_path):
    alm = _alm(tmp_path)
    ctx = ContextoProyecto(params=ParametrosProyecto(km_granulares=32, km_botadero=34),
                           clasificacion=_clas())
    sin_precarga = PricingEngine(alm, contexto=ctx).cost_apu("4390", "DIURNO")
    motor = PricingEngine(alm, contexto=ctx)
    motor.precargar([("4390", "DIURNO")])
    con_precarga = motor.cost_apu("4390", "DIURNO")
    assert sin_precarga[1] == con_precarga[1]
