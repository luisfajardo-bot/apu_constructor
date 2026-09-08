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
