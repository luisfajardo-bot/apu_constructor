"""Una fila sin APU bloquea congelar y descargar el cuadro.

Regla de negocio: una corrida con filas sin APU no describe un presupuesto — le
faltan líneas. Mejor trabar la puerta que emitir un cuadro incompleto que alguien
va a mandar creyendo que está entero.
"""
import pytest

from apu_tool import config
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
    # El mensaje dice cuántas líneas faltan, pero NO el seq interno (0-based, no es
    # lo que la columna "Ítem" de la interfaz muestra): la interfaz ya tiene `seqs`
    # en la respuesta para resaltar las filas exactas.
    assert str(exc.value) == (
        "1 línea(s) sin APU asignado. "
        "Asígnalas antes de congelar o descargar el cuadro.")
    # No dejó la corrida a medio congelar.
    assert alm.corridas.get_corrida(cid).modo == "activa"


def test_cuadro_falla_con_filas_sin_apu(alm):
    cid = _corrida_con_fila_sin_apu(alm)
    with pytest.raises(svc.FilasSinApu):
        svc.generar_cuadro(alm, cid)
    # No quedó nada a medio hacer: ni se congeló ni se marcó como finalizada.
    meta = alm.corridas.get_corrida(cid)
    assert meta.estado == "en_revision"
    assert meta.cuadro_path is None


def test_cuadro_congelado_legacy_tambien_falla(alm):
    """Congelada ANTES del candado: `generar_cuadro` se salta `congelar`, así que
    necesita su propio chequeo o el cuadro incompleto sale igual."""
    cid = _corrida_con_fila_sin_apu(alm)
    alm.corridas.set_modo(cid, "congelada")
    # Una corrida congelada de verdad antes del candado tiene snapshot en TODAS las
    # filas (congelar iteraba sobre todos los _rows), incluida la que no tiene APU.
    alm.corridas.set_snapshot(cid, 0, {"composicion": [], "costo_unitario": 0.0})
    alm.corridas.set_snapshot(cid, 1, {"composicion": [], "costo_unitario": 0.0})
    with pytest.raises(svc.FilasSinApu):
        svc.generar_cuadro(alm, cid)


def test_activar_nunca_se_bloquea(alm):
    """La salida del callejón: una congelada con filas sin APU se puede activar."""
    cid = _corrida_con_fila_sin_apu(alm)
    alm.corridas.set_modo(cid, "congelada")
    assert svc.activar(alm, cid)["modo"] == "activa"


def test_con_todas_asignadas_pasa(alm, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "salidas")
    cid = _corrida_con_fila_sin_apu(alm)
    svc.confirmar_items(alm, cid, [1], "100", "DIURNO")
    assert svc.congelar(alm, cid) is not None
    assert svc.generar_cuadro(alm, cid) is not None


def test_corrida_vacia_no_bloquea(alm, tmp_path, monkeypatch):
    """Cero ítems pasa el guard y emite un cuadro vacío (comportamiento previo,
    correcto): es justo el caso que un refactor convierte en 409 por accidente."""
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "salidas")
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-08-31T10:00:00", archivo="vacia.xlsx",
        turno_def="DIURNO", use_ai=None, estado="en_revision", cuadro_path=None,
        nombre="vacia"))
    assert svc.congelar(alm, cid) is not None
    assert svc.generar_cuadro(alm, cid) is not None


def test_endpoints_devuelven_409_con_los_seqs(alm):
    cli = cliente(create_app(almacen=alm), rol="admin")
    cid = _corrida_con_fila_sin_apu(alm)
    r = cli.post(f"/api/corridas/{cid}/congelar")
    assert r.status_code == 409
    assert r.json()["detail"]["seqs"] == [1]
    r = cli.get(f"/api/corridas/{cid}/cuadro")
    assert r.status_code == 409
    assert r.json()["detail"]["seqs"] == [1]


def test_costo_a_mano_abre_el_candado(alm):
    """La fila sin APU pero con costo declarado ya no bloquea: es el caso de uso
    entero (proyectos especiales que no se arman). El candado sigue existiendo para
    las filas que de verdad no tienen nada."""
    cid = _corrida_con_fila_sin_apu(alm)
    seq_malo = [r.seq for r in alm.corridas.get_items(cid) if not r.apu_codigo][0]
    contractual = {r.seq: r.item.precio_contractual
                   for r in alm.corridas.get_items(cid)}[seq_malo]
    alm.corridas.set_costo_manual(cid, {seq_malo: contractual})
    assert svc.seqs_sin_apu(alm.corridas.get_items(cid)) == []
    assert svc.congelar(alm, cid) is not None      # no levanta FilasSinApu


def test_fila_pelada_sigue_bloqueando(alm):
    """Sin APU y sin costo: el candado tiene que seguir trabado."""
    cid = _corrida_con_fila_sin_apu(alm)
    assert svc.seqs_sin_apu(alm.corridas.get_items(cid)) != []
    with pytest.raises(svc.FilasSinApu):
        svc.congelar(alm, cid)


def test_costo_a_mano_en_cero_no_abre_el_candado(alm):
    """El candado se defiende solo: un costo a mano de 0 no es un costo declarado.
    Si abriera, saldría al cuadro una fila en $0 sin APU, sin badge y sin alerta."""
    cid = _corrida_con_fila_sin_apu(alm)
    seq_malo = [r.seq for r in alm.corridas.get_items(cid) if not r.apu_codigo][0]
    alm.corridas.set_costo_manual(cid, {seq_malo: 0.0})
    assert svc.seqs_sin_apu(alm.corridas.get_items(cid)) == [seq_malo]
    with pytest.raises(svc.FilasSinApu):
        svc.congelar(alm, cid)


def test_el_cuadro_nombra_la_fila_con_costo_a_mano(alm):
    """Que salga en el cuadro no significa que salga callada: la hoja ALERTAS la nombra."""
    from apu_tool.dominio.alertas import filas_alertadas
    from apu_tool.dominio.pricing import PricingEngine
    cid = _corrida_con_fila_sin_apu(alm)
    seq_malo = [r.seq for r in alm.corridas.get_items(cid) if not r.apu_codigo][0]
    alm.corridas.set_costo_manual(cid, {seq_malo: 92106000.0})
    rows = alm.corridas.get_items(cid)
    meta = alm.corridas.get_corrida(cid)
    ensambles = svc._ensamblar_corrida(alm, meta, rows, PricingEngine(alm))
    motivos = {a.item.item: ac for a, ac in filas_alertadas(ensambles)}
    assert any("costo puesto a mano" in m
               for ms in motivos.values() for m in ms)


def test_congelada_sigue_marcando_el_costo_a_mano(alm):
    """El snapshot guarda `composicion: []` con el mismo costo, así que la firma que
    reconoce `alertas_costeo` sobrevive a congelar. Sin esto, el cuadro de una corrida
    congelada emitiría la fila sin decir que el costo lo puso una persona."""
    cid = _corrida_con_fila_sin_apu(alm)
    seq_malo = [r.seq for r in alm.corridas.get_items(cid) if not r.apu_codigo][0]
    alm.corridas.set_costo_manual(cid, {seq_malo: 92106000.0})
    svc.congelar(alm, cid)
    assert alm.corridas.get_corrida(cid).modo == "congelada"
    fila = {f["seq"]: f for f in svc.vista_corrida(alm, cid)["items"]}[seq_malo]
    assert fila["costo_unitario"] == 92106000.0
    assert fila["costo_manual"] is True
    assert any("costo puesto a mano" in m for m in fila["alertas_costeo"])
