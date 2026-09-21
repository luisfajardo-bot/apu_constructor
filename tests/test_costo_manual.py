"""Una fila con costo puesto a mano cuesta eso, sin mirar el catálogo.

Proyectos especiales: la actividad vale lo que dice el contrato y armarle el APU
no paga. El costo lo declara una persona; el motor no lo recalcula.
"""
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import (
    Apu, ApuComponent, CorridaItemRow, CorridaMeta, Insumo, LicitacionItem,
)
from apu_tool.servicio import corridas as svc


@pytest.fixture()
def alm(tmp_path):
    a = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                corridas_path=tmp_path / "c.db")
    a.init_schema()
    a.precios.insert_insumos([Insumo("4279", "CUADRILLA", "HR", "MO", 40000.0, "PRECIO IDU")])
    a.apus.insert_apus([Apu("100", "EXCAVACION MANUAL", "M3", "DIURNO", "MOV")])
    a.apus.insert_components([
        ApuComponent("100", "DIURNO", "4279", "CUADRILLA", "HR", 1.0, 40000.0)])
    return a


def _corrida(alm, *, contractual: float, cantidad: float = 1.0,
             apu: str | None = None, estado: str = "en_revision") -> int:
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-09-07T10:00:00", archivo="x.xlsx", turno_def="DIURNO",
        use_ai=None, estado=estado, cuadro_path=None, nombre="x"))
    alm.corridas.agregar_item(cid, CorridaItemRow(
        seq=0,
        item=LicitacionItem(item="1", descripcion="PRUEBA DE CARGA 6 PUENTES",
                            unidad="GLB", cantidad=cantidad,
                            precio_contractual=contractual, shift="DIURNO"),
        status="new", apu_codigo=apu, apu_nombre=("EXCAVACION MANUAL" if apu else ""),
        unidad="GLB", shift="DIURNO", origen="historico", confianza=0.0,
        explicacion="", componentes=[], candidatos=[]))
    return cid


def test_costo_manual_manda_sobre_la_composicion(alm):
    """Aunque la fila tenga un APU con composición real, el costo a mano gana."""
    cid = _corrida(alm, contractual=92106000.0, apu="100")
    alm.corridas.set_costo_manual(cid, {0: 92106000.0})
    fila = svc.vista_corrida(alm, cid)["items"][0]
    assert fila["costo_unitario"] == 92106000.0    # no los $40.000 del APU 100
    assert fila["costo_manual"] is True


def test_margen_cero_exacto_en_el_total(alm):
    """El redondeo a la unidad no debe dejar un peso de resto en el total."""
    cid = _corrida(alm, contractual=92106000.0, cantidad=7.0)
    alm.corridas.set_costo_manual(cid, {0: 92106000.0})
    v = svc.vista_corrida(alm, cid)
    fila = v["items"][0]
    assert fila["costo_total"] == fila["contractual_total"]
    assert fila["margen_total"] == 0
    assert v["totales"]["margen"] == 0


def test_sin_costo_manual_la_vista_no_lo_marca(alm):
    cid = _corrida(alm, contractual=1000.0, apu="100")
    fila = svc.vista_corrida(alm, cid)["items"][0]
    assert fila["costo_manual"] is False
    assert fila["costo_unitario"] == 40000.0


def test_costo_a_mano_en_cero_no_se_marca_y_alerta_como_cero(alm):
    """Guarda que la firma de `costo_a_mano` sea `> 0` y no `>= 0` ni `is not None`:
    un costo puesto a mano en 0 no cuenta como costo a mano, así que sin badge y con
    la alerta genuina del $0."""
    cid = _corrida(alm, contractual=1000.0)
    alm.corridas.set_costo_manual(cid, {0: 0.0})
    fila = svc.vista_corrida(alm, cid)["items"][0]
    assert fila["costo_manual"] is False
    assert any("$0" in m for m in fila["alertas_costeo"])


def test_apu_sin_composicion_no_se_confunde_con_costo_a_mano(alm):
    """Falsificación directa de "sin componentes el motor no puede dar costo > 0":
    un APU vacío cuesta 0, así que la firma no se activa."""
    alm.apus.insert_apus([Apu("VACIO", "APU SIN COMPOSICION", "M3", "DIURNO", "MOV")])
    cid = _corrida(alm, contractual=1000.0, apu="VACIO")
    fila = svc.vista_corrida(alm, cid)["items"][0]
    assert fila["costo_unitario"] == 0.0
    assert fila["costo_manual"] is False


def test_detalle_item_marca_costo_manual_y_composicion_vacia(alm):
    cid = _corrida(alm, contractual=92106000.0, apu="100")
    alm.corridas.set_costo_manual(cid, {0: 92106000.0})
    detalle = svc.detalle_item(alm, cid, 0)
    assert detalle["costo_manual"] is True
    assert detalle["composicion"] == []


def test_detalle_item_sin_costo_manual(alm):
    cid = _corrida(alm, contractual=1000.0, apu="100")
    detalle = svc.detalle_item(alm, cid, 0)
    assert detalle["costo_manual"] is False
    assert detalle["composicion"] != []


def test_igualar_en_lote_copia_el_contractual_de_cada_fila(alm):
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-09-07T10:00:00", archivo="x.xlsx", turno_def="DIURNO",
        use_ai=None, estado="en_revision", cuadro_path=None, nombre="x"))
    for seq, precio in ((0, 92106000.0), (1, 10115000.0)):
        alm.corridas.agregar_item(cid, CorridaItemRow(
            seq=seq,
            item=LicitacionItem(item=str(seq), descripcion=f"ESPECIAL {seq}", unidad="GLB",
                                cantidad=1.0, precio_contractual=precio, shift="DIURNO"),
            status="new", apu_codigo=None, apu_nombre="", unidad="GLB", shift="DIURNO",
            origen="historico", confianza=0.0, explicacion="", componentes=[],
            candidatos=[]))
    v = svc.igualar_costo_al_contractual(alm, cid, [0, 1])
    assert v["igualadas"] == [0, 1]
    assert [f["costo_unitario"] for f in v["items"]] == [92106000.0, 10115000.0]
    assert all(f["status"] == "confirmed" for f in v["items"])


def test_contractual_en_cero_se_rechaza(alm):
    """Regla de negocio: nada en $0. Igualar a 0 es justo lo que la regla prohíbe."""
    cid = _corrida(alm, contractual=0.0)
    v = svc.igualar_costo_al_contractual(alm, cid, [0])
    assert v["rechazadas"] == [0]
    assert v["igualadas"] == []
    assert alm.corridas.get_items(cid)[0].costo_manual is None


def test_contractual_nan_se_rechaza(alm):
    """`nan <= 0` es False: sin el `not (x > 0)` el NaN se colaría al costo y
    envenenaría todos los totales."""
    cid = _corrida(alm, contractual=float("nan"))
    v = svc.igualar_costo_al_contractual(alm, cid, [0])
    assert v["rechazadas"] == [0]
    assert alm.corridas.get_items(cid)[0].costo_manual is None


def test_congelada_no_se_toca(alm):
    cid = _corrida(alm, contractual=1000.0)
    alm.corridas.set_modo(cid, "congelada")
    with pytest.raises(svc.CorridaCongelada):
        svc.igualar_costo_al_contractual(alm, cid, [0])


def test_corrida_inexistente_devuelve_none(alm):
    assert svc.igualar_costo_al_contractual(alm, 9999, [0]) is None


def test_finalizada_vuelve_a_revision(alm):
    """El cuadro emitido ya no dice la verdad."""
    cid = _corrida(alm, contractual=1000.0, estado="finalizada")
    svc.igualar_costo_al_contractual(alm, cid, [0])
    assert alm.corridas.get_corrida(cid).estado == "en_revision"


def test_seq_ajeno_se_saltea(alm):
    cid = _corrida(alm, contractual=1000.0)
    v = svc.igualar_costo_al_contractual(alm, cid, [0, 77])
    assert v["igualadas"] == [0]
