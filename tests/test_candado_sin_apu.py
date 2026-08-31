"""Una fila sin APU bloquea congelar y descargar el cuadro.

Regla de negocio: una corrida con filas sin APU no describe un presupuesto — le
faltan líneas. Mejor trabar la puerta que emitir un cuadro incompleto que alguien
va a mandar creyendo que está entero.
"""
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import (
    Apu, ApuComponent, CorridaItemRow, CorridaMeta, Insumo, LicitacionItem,
)
from apu_tool.servicio import corridas as svc
from apu_tool.servicio.app import create_app
from tests.conftest import cliente


def _almacen(tmp_path) -> Almacen:
    a = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                corridas_path=tmp_path / "c.db")
    a.init_schema()
    a.precios.insert_insumos([Insumo("4279", "CUADRILLA", "HR", "MO", 40000.0, "PRECIO IDU")])
    a.apus.insert_apus([Apu("100", "EXCAVACION MANUAL", "M3", "DIURNO", "MOV")])
    a.apus.insert_components([
        ApuComponent("100", "DIURNO", "4279", "CUADRILLA", "HR", 1.0, 40000.0)])
    return a


@pytest.fixture()
def alm(tmp_path):
    return _almacen(tmp_path)


def _corrida_con_fila_sin_apu(alm) -> int:
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-08-31T10:00:00", archivo="x.xlsx",
        turno_def="DIURNO", use_ai=None, estado="en_revision", cuadro_path=None,
        nombre="x"))
    item_ok = LicitacionItem(item="1", descripcion="EXCAVACION MANUAL", unidad="M3",
                             cantidad=1.0, precio_contractual=100.0, shift="DIURNO")
    item_malo = LicitacionItem(item="2", descripcion="ACTIVIDAD RARA", unidad="M2",
                               cantidad=1.0, precio_contractual=100.0, shift="DIURNO")
    alm.corridas.agregar_item(cid, CorridaItemRow(
        seq=0, item=item_ok, status="auto", apu_codigo="100", apu_nombre="EXCAVACION MANUAL",
        unidad="M3", shift="DIURNO", origen="historico", confianza=1.0, explicacion="",
        componentes=[], candidatos=[]))
    alm.corridas.agregar_item(cid, CorridaItemRow(
        seq=1, item=item_malo, status="new", apu_codigo=None, apu_nombre="(sin base)",
        unidad="M2", shift="DIURNO", origen="manual", confianza=0.0, explicacion="",
        componentes=[], candidatos=[]))
    return cid


def test_congelar_falla_con_filas_sin_apu(alm):
    cid = _corrida_con_fila_sin_apu(alm)
    with pytest.raises(svc.FilasSinApu) as exc:
        svc.congelar(alm, cid)
    assert exc.value.seqs == [1]
    # No dejó la corrida a medio congelar.
    assert alm.corridas.get_corrida(cid).modo == "activa"


def test_cuadro_falla_con_filas_sin_apu(alm):
    cid = _corrida_con_fila_sin_apu(alm)
    with pytest.raises(svc.FilasSinApu):
        svc.generar_cuadro(alm, cid)


def test_cuadro_congelado_legacy_tambien_falla(alm):
    """Congelada ANTES del candado: `generar_cuadro` se salta `congelar`, así que
    necesita su propio chequeo o el cuadro incompleto sale igual."""
    cid = _corrida_con_fila_sin_apu(alm)
    alm.corridas.set_modo(cid, "congelada")
    alm.corridas.set_snapshot(cid, 0, {"composicion": [], "costo_unitario": 0.0})
    with pytest.raises(svc.FilasSinApu):
        svc.generar_cuadro(alm, cid)


def test_activar_nunca_se_bloquea(alm):
    """La salida del callejón: una congelada con filas sin APU se puede activar."""
    cid = _corrida_con_fila_sin_apu(alm)
    alm.corridas.set_modo(cid, "congelada")
    assert svc.activar(alm, cid)["modo"] == "activa"


def test_con_todas_asignadas_pasa(alm):
    cid = _corrida_con_fila_sin_apu(alm)
    svc.confirmar_items(alm, cid, [1], "100", "DIURNO")
    assert svc.congelar(alm, cid) is not None
    assert svc.generar_cuadro(alm, cid) is not None


def test_endpoints_devuelven_409_con_los_seqs(tmp_path):
    alm = _almacen(tmp_path)
    cli = cliente(create_app(almacen=alm), rol="admin")
    cid = _corrida_con_fila_sin_apu(alm)
    r = cli.post(f"/api/corridas/{cid}/congelar")
    assert r.status_code == 409
    assert r.json()["detail"]["seqs"] == [1]
    r = cli.get(f"/api/corridas/{cid}/cuadro")
    assert r.status_code == 409
    assert r.json()["detail"]["seqs"] == [1]
