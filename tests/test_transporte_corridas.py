"""Las corridas costean con los parámetros de SU proyecto (carpeta raíz)."""
from apu_tool.datos.almacen import Almacen
from apu_tool.dominio import transporte
from apu_tool.nucleo.models import (
    Apu, ApuComponent, ClaseTransporte, Insumo, LicitacionItem, ParametrosProyecto)
from apu_tool.servicio import corridas as svc


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo(codigo="7462", nombre="TRANSPORTE DE PETREOS", unidad="M3-KM",
               grupo="TRANSPORTES", precio=1000.0, fuente_precio="COSTO INTERNO")])
    alm.apus.insert_apus([Apu(codigo="4390", nombre="RELLENO", unidad="M3",
                              shift="DIURNO", grupo="VIAS")])
    alm.apus.insert_components([
        ApuComponent(apu_codigo="4390", shift="DIURNO", insumo_codigo="7462",
                     insumo_nombre="TRANSPORTE DE PETREOS", unidad="M3-KM",
                     rendimiento=26.25, precio_unitario_hist=1000.0)])
    alm.apus.set_clasificacion_transporte([ClaseTransporte(
        apu_codigo="4390", shift="DIURNO", insumo_codigo="7462",
        insumo_nombre="TRANSPORTE DE PETREOS", categoria="granulares",
        volumen=1.05, km_base=25.0)])
    return alm


def _corrida(alm, carpeta_id):
    items = [LicitacionItem(item="1", descripcion="RELLENO", unidad="M3", cantidad=10,
                            precio_contractual=100000.0, shift="DIURNO")]
    cid = svc.construir_corrida(alm, "lic.xlsx", items, "DIURNO", False,
                                carpeta_id=carpeta_id)
    svc.confirmar_item(alm, cid, 0, "4390", "DIURNO")
    return cid


def test_cada_proyecto_costea_con_su_distancia(tmp_path):
    alm = _alm(tmp_path)
    metro = alm.carpetas.crear("Metro")
    calle13 = alm.carpetas.crear("Calle 13")
    alm.carpetas.set_parametros(ParametrosProyecto(carpeta_id=metro, km_granulares=32))
    alm.carpetas.set_parametros(ParametrosProyecto(carpeta_id=calle13, km_granulares=25))
    c_metro, c_c13 = _corrida(alm, metro), _corrida(alm, calle13)
    v_metro = svc.vista_corrida(alm, c_metro)["items"][0]
    v_c13 = svc.vista_corrida(alm, c_c13)["items"][0]
    assert v_metro["costo_unitario"] == 33600      # 1.05 * 32 * 1000
    assert v_c13["costo_unitario"] == 26250       # 1.05 * 25 * 1000
    # y la biblioteca no cambió
    comps = alm.apus.get_components("4390", "DIURNO")
    assert comps[0].rendimiento == 26.25


def test_subcarpeta_hereda_del_proyecto(tmp_path):
    alm = _alm(tmp_path)
    metro = alm.carpetas.crear("Metro")
    lote = alm.carpetas.crear("Lote 2", parent_id=metro)
    alm.carpetas.set_parametros(ParametrosProyecto(carpeta_id=metro, km_granulares=32))
    cid = _corrida(alm, lote)
    assert svc.vista_corrida(alm, cid)["items"][0]["costo_unitario"] == 33600


def test_congelada_conserva_su_foto(tmp_path):
    alm = _alm(tmp_path)
    metro = alm.carpetas.crear("Metro")
    alm.carpetas.set_parametros(ParametrosProyecto(carpeta_id=metro, km_granulares=32))
    cid = _corrida(alm, metro)
    svc.congelar(alm, cid)
    alm.carpetas.set_parametros(ParametrosProyecto(carpeta_id=metro, km_granulares=50))
    assert svc.vista_corrida(alm, cid)["items"][0]["costo_unitario"] == 33600


def test_sin_parametros_costea_como_siempre(tmp_path):
    alm = _alm(tmp_path)
    cid = _corrida(alm, alm.carpetas.crear("Sin distancias"))
    assert svc.vista_corrida(alm, cid)["items"][0]["costo_unitario"] == 26250


def test_cargar_contexto_sube_a_la_raiz(tmp_path):
    alm = _alm(tmp_path)
    metro = alm.carpetas.crear("Metro")
    lote = alm.carpetas.crear("Lote 2", parent_id=metro)
    alm.carpetas.set_parametros(ParametrosProyecto(carpeta_id=metro, km_botadero=34))
    ctx = transporte.cargar_contexto(alm, lote)
    assert ctx.params.km_botadero == 34
    assert transporte.cargar_contexto(alm, None).vacio is True


def test_detalle_item_y_cuadro_usan_el_contexto(tmp_path):
    alm = _alm(tmp_path)
    metro = alm.carpetas.crear("Metro")
    alm.carpetas.set_parametros(ParametrosProyecto(carpeta_id=metro, km_granulares=32))
    cid = _corrida(alm, metro)
    det = svc.detalle_item(alm, cid, 0)
    assert det["composicion"][0]["rendimiento"] == 33.6
    assert svc.generar_cuadro(alm, cid) is not None


def test_el_armado_en_vivo_costea_con_las_distancias_del_proyecto(tmp_path):
    """Los eventos del armado tienen que traer el mismo costo que la vista: si no,
    el numero salta cuando termina de armar."""
    alm = _alm(tmp_path)
    metro = alm.carpetas.crear("Metro")
    alm.carpetas.set_parametros(ParametrosProyecto(carpeta_id=metro, km_granulares=32))
    items = [LicitacionItem(item="1", descripcion="RELLENO", unidad="M3", cantidad=10,
                            precio_contractual=100000.0, shift="DIURNO")]
    filas = []
    for evento, payload in svc.construir_corrida_stream(
            alm, "lic.xlsx", items, "DIURNO", False, carpeta_id=metro):
        if evento == "progress":
            filas.append(payload["fila"])
    costeadas = [f for f in filas if f.get("costo_unitario")]
    assert costeadas, filas
    assert all(f["costo_unitario"] == 33600 for f in costeadas)


def test_listar_corridas_resuelve_el_contexto_una_vez_por_proyecto(tmp_path, monkeypatch):
    """El contexto se resuelve por PROYECTO, no por corrida: contra Postgres cada
    resolucion son varios round-trips."""
    alm = _alm(tmp_path)
    metro = alm.carpetas.crear("Metro")
    alm.carpetas.set_parametros(ParametrosProyecto(carpeta_id=metro, km_granulares=32))
    _corrida(alm, metro)
    _corrida(alm, metro)
    _corrida(alm, metro)
    llamadas = []
    real = transporte.cargar_contexto
    def espia(almacen, carpeta_id):
        llamadas.append(carpeta_id)
        return real(almacen, carpeta_id)
    monkeypatch.setattr(svc.transporte, "cargar_contexto", espia)
    svc.listar_corridas(alm)
    assert llamadas.count(metro) == 1, llamadas


def test_la_corrida_alerta_el_componente_sin_clasificar(tmp_path):
    alm = _alm(tmp_path)
    # Se borra la clasificación para simular un APU nuevo sin clasificar.
    with alm.apus.connect() as conn:
        conn.execute("DELETE FROM componente_transporte")
    metro = alm.carpetas.crear("Metro")
    alm.carpetas.set_parametros(ParametrosProyecto(carpeta_id=metro, km_granulares=32))
    cid = _corrida(alm, metro)
    alertas = svc.vista_corrida(alm, cid)["items"][0]["alertas_costeo"]
    assert any("distancia del proyecto no aplicada" in a for a in alertas)
