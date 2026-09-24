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


def test_quitar_costo_manual_devuelve_la_fila_al_costeo(alm):
    """Con APU, la fila vuelve a costear desde su composición ($40.000 del APU 100)."""
    cid = _corrida(alm, contractual=92106000.0, apu="100")
    alm.corridas.set_costo_manual(cid, {0: 92106000.0})
    v = svc.quitar_costo_manual(alm, cid, [0])
    assert v["quitadas"] == [0]
    fila = v["items"][0]
    assert fila["costo_manual"] is False
    assert fila["costo_unitario"] == 40000.0
    # El status NO se degrada: `set_costo_manual` la dejó `confirmed` y así queda.
    assert fila["status"] == "confirmed"


def test_quitar_costo_manual_sin_apu_vuelve_a_trabar_el_cuadro(alm):
    """El candado tiene que volver a cerrarse: la fila está otra vez en $0 sin APU."""
    cid = _corrida(alm, contractual=1000.0)
    svc.igualar_costo_al_contractual(alm, cid, [0])
    assert svc.seqs_sin_apu(alm.corridas.get_items(cid)) == []
    svc.quitar_costo_manual(alm, cid, [0])
    filas = alm.corridas.get_items(cid)
    assert filas[0].status == "new"
    assert svc.seqs_sin_apu(filas) == [0]


def test_quitar_costo_manual_sin_costo_a_mano_es_no_op(alm):
    """Pedir el borrado de una fila que no lo tiene no es un error."""
    cid = _corrida(alm, contractual=1000.0, apu="100")
    v = svc.quitar_costo_manual(alm, cid, [0])
    assert v["quitadas"] == []
    assert v["items"][0]["costo_unitario"] == 40000.0


def test_quitar_costo_manual_congelada_no_se_toca(alm):
    cid = _corrida(alm, contractual=1000.0)
    alm.corridas.set_costo_manual(cid, {0: 1000.0})
    alm.corridas.set_modo(cid, "congelada")
    with pytest.raises(svc.CorridaCongelada):
        svc.quitar_costo_manual(alm, cid, [0])


def test_quitar_costo_manual_corrida_inexistente_devuelve_none(alm):
    assert svc.quitar_costo_manual(alm, 9999, [0]) is None


def test_quitar_costo_manual_finalizada_vuelve_a_revision(alm):
    """El cuadro emitido ya no dice la verdad."""
    cid = _corrida(alm, contractual=1000.0, estado="finalizada")
    alm.corridas.set_costo_manual(cid, {0: 1000.0})
    svc.quitar_costo_manual(alm, cid, [0])
    assert alm.corridas.get_corrida(cid).estado == "en_revision"


def _corrida_varias(alm, precios, *, cantidad: float = 1.0) -> int:
    """Una corrida con una fila por precio, todas SIN APU (o sea, todas en $0)."""
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-09-21T10:00:00", archivo="x.xlsx", turno_def="DIURNO",
        use_ai=None, estado="en_revision", cuadro_path=None, nombre="x"))
    for seq, precio in enumerate(precios):
        alm.corridas.agregar_item(cid, CorridaItemRow(
            seq=seq,
            item=LicitacionItem(item=str(seq), descripcion=f"ACTIVIDAD {seq}",
                                unidad="GLB", cantidad=cantidad,
                                precio_contractual=precio, shift="DIURNO"),
            status="new", apu_codigo=None, apu_nombre="", unidad="GLB", shift="DIURNO",
            origen="historico", confianza=0.0, explicacion="", componentes=[],
            candidatos=[]))
    return cid


def test_umbral_iguala_lo_de_abajo_y_deja_lo_de_arriba(alm):
    """El techo es inclusivo: «iguales o menores al límite», como lo pidió el usuario."""
    cid = _corrida_varias(alm, [100_000_000.0, 500_000_000.0, 900_000_000.0])
    v = svc.igualar_por_umbral(alm, cid, 500_000_000.0, [0, 1, 2])
    assert v["igualadas"] == [0, 1]
    assert v["salteadas"] == [2]
    assert [f["costo_unitario"] for f in v["items"]] == [
        100_000_000.0, 500_000_000.0, 0.0]


def test_umbral_mide_el_total_y_no_el_unitario(alm):
    """Unitario chico por cantidad grande es una actividad cara: no se iguala."""
    cid = _corrida_varias(alm, [1_000_000.0], cantidad=1000.0)   # total = $1.000M
    v = svc.igualar_por_umbral(alm, cid, 500_000_000.0, [0])
    assert v["igualadas"] == []
    assert v["salteadas"] == [0]


def test_umbral_saltea_la_fila_que_dejo_de_estar_en_cero(alm):
    """La carrera de la pestaña vieja: entre la previa y el aplicar le asignaron un
    APU. Sin el recálculo en el servidor, el costo real se pisaría con el contractual
    y encima la fila quedaría `confirmed`, fuera del alcance de volver a buscar."""
    cid = _corrida_varias(alm, [1000.0])
    alm.corridas.actualizar_eleccion(
        cid, 0, status="confirmed", apu_codigo="100", apu_nombre="EXCAVACION MANUAL",
        unidad="M3", shift="DIURNO", origen="historico", confianza=1.0, explicacion="",
        componentes=[{"insumo_codigo": "4279", "insumo_nombre": "CUADRILLA",
                      "unidad": "HR", "rendimiento": 1.0}])
    v = svc.igualar_por_umbral(alm, cid, 500_000_000.0, [0])
    assert v["igualadas"] == []
    assert v["salteadas"] == [0]
    assert v["items"][0]["costo_unitario"] == 40000.0      # el del APU, intacto


def test_umbral_no_toca_la_que_ya_tiene_costo_a_mano(alm):
    cid = _corrida_varias(alm, [1000.0])
    alm.corridas.set_costo_manual(cid, {0: 777.0})
    v = svc.igualar_por_umbral(alm, cid, 500_000_000.0, [0])
    assert v["salteadas"] == [0]
    assert v["items"][0]["costo_unitario"] == 777.0


def test_umbral_saltea_la_fila_sin_precio_contractual(alm):
    """Está en $0 pero el contrato tampoco la paga: igualarla sería el $0 que la
    regla de negocio prohíbe, así que ni se propone."""
    cid = _corrida_varias(alm, [0.0])
    v = svc.igualar_por_umbral(alm, cid, 500_000_000.0, [0])
    assert v["salteadas"] == [0]
    assert v["igualadas"] == []


def test_umbral_solo_mira_lo_que_el_cliente_marco(alm):
    """Destildar una fila en la previa la deja afuera, y ni siquiera se saltea:
    nunca se pidió."""
    cid = _corrida_varias(alm, [100.0, 200.0])
    v = svc.igualar_por_umbral(alm, cid, 500_000_000.0, [1])
    assert v["igualadas"] == [1]
    assert v["salteadas"] == []
    assert v["items"][0]["costo_unitario"] == 0.0


def test_umbral_no_positivo_es_error(alm):
    """Un umbral de $0 no iguala nada y uno negativo es un dedo resbalado. El NaN va
    con `not (x > 0)`: `nan <= 0` es False y dejaría pasar cualquier fila."""
    cid = _corrida_varias(alm, [1000.0])
    for malo in (0.0, -5.0, float("nan")):
        with pytest.raises(ValueError):
            svc.igualar_por_umbral(alm, cid, malo, [0])


def test_umbral_congelada_no_se_toca(alm):
    cid = _corrida_varias(alm, [1000.0])
    alm.corridas.set_modo(cid, "congelada")
    with pytest.raises(svc.CorridaCongelada):
        svc.igualar_por_umbral(alm, cid, 500_000_000.0, [0])


def test_umbral_corrida_inexistente_devuelve_none(alm):
    assert svc.igualar_por_umbral(alm, 9999, 500_000_000.0, [0]) is None


def test_igualar_con_el_plan_a_medias_se_rechaza(alm):
    """Las filas que faltan armar NO existen: igualar ahí decide sobre una vista
    parcial. Mismo candado que agregar/borrar líneas y que volver a buscar APU."""
    cid = _corrida(alm, contractual=1000.0, estado="armando")
    with pytest.raises(ValueError, match="armar"):
        svc.igualar_costo_al_contractual(alm, cid, [0])


def test_igualar_con_el_plan_detenido_se_rechaza(alm):
    """`armado_detenido` cuenta igual: el armador puede reanudar en cualquier
    momento y el espacio de `seq` sigue siendo suyo."""
    cid = _corrida(alm, contractual=1000.0, estado="armado_detenido")
    with pytest.raises(ValueError):
        svc.igualar_costo_al_contractual(alm, cid, [0])


def test_umbral_con_el_plan_a_medias_se_rechaza(alm):
    """`igualar_por_umbral` costea la corrida entera antes de delegar: el candado
    tiene que frenar ANTES de ese trabajo, no solo en el camino compartido."""
    cid = _corrida_varias(alm, [1000.0])
    alm.corridas.set_estado(cid, "armando")
    with pytest.raises(ValueError, match="armar"):
        svc.igualar_por_umbral(alm, cid, 500_000_000.0, [0])


def test_umbral_con_el_plan_detenido_se_rechaza(alm):
    cid = _corrida_varias(alm, [1000.0])
    alm.corridas.set_estado(cid, "armado_detenido")
    with pytest.raises(ValueError):
        svc.igualar_por_umbral(alm, cid, 500_000_000.0, [0])


def test_quitar_costo_manual_con_el_plan_a_medias_se_rechaza(alm):
    cid = _corrida(alm, contractual=1000.0, estado="armando")
    with pytest.raises(ValueError, match="armar"):
        svc.quitar_costo_manual(alm, cid, [0])


def test_quitar_costo_manual_con_el_plan_detenido_se_rechaza(alm):
    cid = _corrida(alm, contractual=1000.0, estado="armado_detenido")
    with pytest.raises(ValueError):
        svc.quitar_costo_manual(alm, cid, [0])


def test_las_tres_siguen_funcionando_con_el_plan_completo(alm):
    """Regresión: el candado nuevo no debe trabar el camino normal (sin plan a
    medias) de ninguna de las tres funciones."""
    cid = _corrida_varias(alm, [100_000_000.0, 1000.0, 1000.0])
    assert svc.igualar_por_umbral(alm, cid, 500_000_000.0, [0])["igualadas"] == [0]
    assert svc.igualar_costo_al_contractual(alm, cid, [1])["igualadas"] == [1]
    assert svc.quitar_costo_manual(alm, cid, [1])["quitadas"] == [1]


def test_umbral_iguala_la_fila_con_apu_pero_en_cero(alm):
    """El SEGUNDO caso que cubre la regla: la fila tiene APU, pero su composición no
    cuesta nada (insumos sin precio), así que está en $0 y traba el cuadro igual que
    una sin APU. `_candidata_umbral` mira el costo, no el `apu_codigo`."""
    alm.apus.insert_apus([Apu("VACIO", "APU SIN COMPOSICION", "M3", "DIURNO", "MOV")])
    cid = _corrida(alm, contractual=1000.0, apu="VACIO")
    assert svc.vista_corrida(alm, cid)["items"][0]["costo_unitario"] == 0.0  # el punto de partida
    v = svc.igualar_por_umbral(alm, cid, 500_000_000.0, [0])
    assert v["igualadas"] == [0]
    assert v["salteadas"] == []
    fila = v["items"][0]
    assert fila["costo_unitario"] == 1000.0
    assert fila["costo_manual"] is True
