"""API de ajustes puntuales del proyecto."""
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo
from apu_tool.servicio.app import create_app
from tests.conftest import cliente


def _cli(tmp_path, rol="admin"):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo(codigo="9001", nombre="GEOTEXTIL NT 2000", unidad="M2", grupo="GEO",
               precio=9000.0, fuente_precio="COSTO INTERNO"),
        Insumo(codigo="6722", nombre="SUBBASE GRANULAR B-400", unidad="M3",
               grupo="AGREGADOS", precio=80000.0, fuente_precio="COSTO INTERNO")])
    alm.apus.insert_apus([Apu(codigo="4390", nombre="RELLENO", unidad="M3",
                              shift="DIURNO", grupo="VIAS")])
    alm.apus.insert_components([
        ApuComponent(apu_codigo="4390", shift="DIURNO", insumo_codigo="6722",
                     insumo_nombre="SUBBASE GRANULAR B-400", unidad="M3",
                     rendimiento=1.0, precio_unitario_hist=80000.0)])
    return cliente(create_app(almacen=alm), rol=rol), alm


def _cuerpo(**kw):
    base = {"apu_codigo": "4390", "shift": "DIURNO", "accion": "agregar",
            "insumo_codigo": "9001", "insumo_nombre": "GEOTEXTIL NT 2000",
            "unidad": "M2", "rendimiento": 1.1, "nota": "lo exige la especificación"}
    base.update(kw)
    return base


def test_crear_listar_borrar(tmp_path):
    cli, alm = _cli(tmp_path)
    cid = alm.carpetas.crear("Metro")
    r = cli.post(f"/api/carpetas/{cid}/ajustes", json=_cuerpo())
    assert r.status_code == 200, r.text
    aid = r.json()["id"]
    lista = cli.get(f"/api/carpetas/{cid}/ajustes").json()
    assert len(lista) == 1 and lista[0]["insumo_codigo"] == "9001"
    assert cli.delete(f"/api/carpetas/{cid}/ajustes/{aid}").status_code == 200
    assert cli.get(f"/api/carpetas/{cid}/ajustes").json() == []


def test_accion_invalida_es_400(tmp_path):
    cli, alm = _cli(tmp_path)
    cid = alm.carpetas.crear("Metro")
    r = cli.post(f"/api/carpetas/{cid}/ajustes", json=_cuerpo(accion="inventada"))
    assert r.status_code == 400


def test_rendimiento_no_positivo_es_400(tmp_path):
    cli, alm = _cli(tmp_path)
    cid = alm.carpetas.crear("Metro")
    r = cli.post(f"/api/carpetas/{cid}/ajustes", json=_cuerpo(rendimiento=0))
    assert r.status_code == 400


def test_insumo_inexistente_es_400(tmp_path):
    cli, alm = _cli(tmp_path)
    cid = alm.carpetas.crear("Metro")
    r = cli.post(f"/api/carpetas/{cid}/ajustes",
                 json=_cuerpo(insumo_codigo="0000", insumo_nombre="NO EXISTE"))
    assert r.status_code == 400 and "catálogo" in r.text


def test_quitar_no_exige_rendimiento(tmp_path):
    cli, alm = _cli(tmp_path)
    cid = alm.carpetas.crear("Metro")
    r = cli.post(f"/api/carpetas/{cid}/ajustes", json=_cuerpo(
        accion="quitar", insumo_codigo="6722",
        insumo_nombre="SUBBASE GRANULAR B-400", rendimiento=None))
    assert r.status_code == 200


def test_consulta_no_puede_escribir(tmp_path):
    cli, alm = _cli(tmp_path, rol="consulta")
    cid = alm.carpetas.crear("Metro")
    assert cli.get(f"/api/carpetas/{cid}/ajustes").status_code == 200
    assert cli.post(f"/api/carpetas/{cid}/ajustes", json=_cuerpo()).status_code == 403


def test_el_ajuste_cambia_el_costo_de_la_corrida(tmp_path):
    from apu_tool.nucleo.models import LicitacionItem
    from apu_tool.servicio import corridas as svc
    cli, alm = _cli(tmp_path)
    cid = alm.carpetas.crear("Metro")
    corrida = svc.construir_corrida(
        alm, "lic.xlsx",
        [LicitacionItem(item="1", descripcion="RELLENO", unidad="M3", cantidad=1,
                        precio_contractual=200000.0, shift="DIURNO")],
        "DIURNO", False, carpeta_id=cid)
    svc.confirmar_item(alm, corrida, 0, "4390", "DIURNO")
    antes = svc.vista_corrida(alm, corrida)["items"][0]["costo_unitario"]
    cli.post(f"/api/carpetas/{cid}/ajustes", json=_cuerpo())
    despues = svc.vista_corrida(alm, corrida)["items"][0]["costo_unitario"]
    assert despues == antes + 9900          # 1.1 * 9000
    # el ajuste es del proyecto, no de la biblioteca: el APU sigue con un solo componente
    assert len(alm.apus.get_components("4390", "DIURNO")) == 1


def test_reemplazar_sin_insumo_nuevo_es_400(tmp_path):
    cli, alm = _cli(tmp_path)
    cid = alm.carpetas.crear("Metro")
    r = cli.post(f"/api/carpetas/{cid}/ajustes", json=_cuerpo(
        accion="reemplazar", insumo_codigo="6722",
        insumo_nombre="SUBBASE GRANULAR B-400", rendimiento=None))
    assert r.status_code == 400


def test_crear_dos_veces_actualiza_la_misma_fila(tmp_path):
    """`crear_ajuste` en la capa de datos es un UPSERT que conserva el id: la UI
    depende de que el mismo (apu, shift, accion, insumo) sea siempre la misma fila."""
    cli, alm = _cli(tmp_path)
    cid = alm.carpetas.crear("Metro")
    r1 = cli.post(f"/api/carpetas/{cid}/ajustes", json=_cuerpo(rendimiento=1.1))
    r2 = cli.post(f"/api/carpetas/{cid}/ajustes", json=_cuerpo(rendimiento=2.2))
    assert r1.json()["id"] == r2.json()["id"]
    lista = cli.get(f"/api/carpetas/{cid}/ajustes").json()
    assert len(lista) == 1 and lista[0]["rendimiento"] == 2.2


def test_borrar_con_id_de_otro_proyecto_es_404(tmp_path):
    cli, alm = _cli(tmp_path)
    cid1 = alm.carpetas.crear("Metro")
    cid2 = alm.carpetas.crear("Otro")
    aid = cli.post(f"/api/carpetas/{cid1}/ajustes", json=_cuerpo()).json()["id"]
    r = cli.delete(f"/api/carpetas/{cid2}/ajustes/{aid}")
    assert r.status_code == 404
    assert len(cli.get(f"/api/carpetas/{cid1}/ajustes").json()) == 1


def test_crear_audita(tmp_path):
    cli, alm = _cli(tmp_path)
    cid = alm.carpetas.crear("Metro")
    cli.post(f"/api/carpetas/{cid}/ajustes", json=_cuerpo())
    items, total = alm.auditoria.listar(accion="proyecto.ajuste.crear")
    assert total == 1 and items[0]["entidad_id"] == str(cid)


def test_borrar_audita(tmp_path):
    cli, alm = _cli(tmp_path)
    cid = alm.carpetas.crear("Metro")
    aid = cli.post(f"/api/carpetas/{cid}/ajustes", json=_cuerpo()).json()["id"]
    cli.delete(f"/api/carpetas/{cid}/ajustes/{aid}")
    items, total = alm.auditoria.listar(accion="proyecto.ajuste.borrar")
    assert total == 1
