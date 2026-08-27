"""API de distancias del proyecto y clasificación de la biblioteca."""
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo
from apu_tool.servicio.app import create_app
from tests.conftest import cliente


def _cli(tmp_path, rol="admin"):
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
    return cliente(create_app(almacen=alm), rol=rol), alm


def test_get_parametros_vacios(tmp_path):
    cli, alm = _cli(tmp_path)
    cid = alm.carpetas.crear("Metro")
    r = cli.get(f"/api/carpetas/{cid}/transporte")
    assert r.status_code == 200
    body = r.json()
    assert body["parametros"]["km_botadero"] is None
    assert body["impacto"] == [] and body["sin_clasificar"] == 0


def test_put_y_get_parametros(tmp_path):
    cli, alm = _cli(tmp_path)
    cid = alm.carpetas.crear("Metro")
    r = cli.put(f"/api/carpetas/{cid}/transporte", json={
        "km_botadero": 34, "km_mezclas": 28, "km_granulares": 32,
        "peaje_aplica": True, "peaje_valor": 12400})
    assert r.status_code == 200, r.text
    p = cli.get(f"/api/carpetas/{cid}/transporte").json()["parametros"]
    assert p["km_granulares"] == 32 and p["peaje_valor"] == 12400


def test_peaje_sin_valor_es_400(tmp_path):
    cli, alm = _cli(tmp_path)
    cid = alm.carpetas.crear("Metro")
    r = cli.put(f"/api/carpetas/{cid}/transporte",
                json={"peaje_aplica": True, "peaje_valor": 0})
    assert r.status_code == 400 and "$0" in r.text


def test_km_negativo_o_cero_es_400(tmp_path):
    """Un km en 0 dejaría el acarreo en rendimiento 0 y el ítem en $0."""
    cli, alm = _cli(tmp_path)
    cid = alm.carpetas.crear("Metro")
    assert cli.put(f"/api/carpetas/{cid}/transporte",
                   json={"km_botadero": -1}).status_code == 400
    assert cli.put(f"/api/carpetas/{cid}/transporte",
                   json={"km_botadero": 0}).status_code == 400
    # vacío sí se acepta: es "esta distancia no aplica".
    assert cli.put(f"/api/carpetas/{cid}/transporte",
                   json={"km_botadero": None}).status_code == 200


def test_subcarpeta_no_puede_tener_parametros(tmp_path):
    cli, alm = _cli(tmp_path)
    raiz = alm.carpetas.crear("Metro")
    sub = alm.carpetas.crear("Lote 2", parent_id=raiz)
    r = cli.put(f"/api/carpetas/{sub}/transporte", json={"km_botadero": 34})
    assert r.status_code == 400 and "nivel" in r.text.lower()


def test_consulta_no_puede_escribir(tmp_path):
    cli, alm = _cli(tmp_path, rol="consulta")
    cid = alm.carpetas.crear("Metro")
    assert cli.get(f"/api/carpetas/{cid}/transporte").status_code == 200
    assert cli.put(f"/api/carpetas/{cid}/transporte",
                   json={"km_botadero": 34}).status_code == 403


def test_candidatos_y_clasificacion(tmp_path):
    cli, _ = _cli(tmp_path)
    filas = cli.get("/api/transporte/componentes").json()["items"]
    assert len(filas) == 1
    f = filas[0]
    assert f["insumo_codigo"] == "7462" and f["categoria_sugerida"] == "granulares"
    assert f["km_base"] == 25.0 and round(f["volumen"], 4) == 1.05
    assert f["categoria"] is None                       # sin clasificar todavía
    r = cli.put("/api/transporte/componentes", json={"filas": [{
        "apu_codigo": "4390", "shift": "DIURNO", "insumo_codigo": "7462",
        "insumo_nombre": "TRANSPORTE DE PETREOS", "categoria": "granulares",
        "volumen": 1.05, "km_base": 25.0}]})
    assert r.status_code == 200 and r.json()["aplicados"] == 1
    f = cli.get("/api/transporte/componentes").json()["items"][0]
    assert f["categoria"] == "granulares"


def test_categoria_invalida_es_400(tmp_path):
    cli, _ = _cli(tmp_path)
    r = cli.put("/api/transporte/componentes", json={"filas": [{
        "apu_codigo": "4390", "shift": "DIURNO", "insumo_codigo": "7462",
        "insumo_nombre": "TRANSPORTE DE PETREOS", "categoria": "cemento",
        "volumen": 1.05}]})
    assert r.status_code == 400


def test_impacto_muestra_el_rendimiento_nuevo(tmp_path):
    from apu_tool.nucleo.models import LicitacionItem
    from apu_tool.servicio import corridas as svc
    cli, alm = _cli(tmp_path)
    cid = alm.carpetas.crear("Metro")
    corrida = svc.construir_corrida(
        alm, "lic.xlsx",
        [LicitacionItem(item="1", descripcion="RELLENO", unidad="M3", cantidad=1,
                        precio_contractual=100.0, shift="DIURNO")],
        "DIURNO", False, carpeta_id=cid)
    # OJO: el seq de una corrida es 0-based (el plan original decía 1, que era un
    # no-op silencioso contra un seq inexistente).
    svc.confirmar_item(alm, corrida, 0, "4390", "DIURNO")
    cli.put("/api/transporte/componentes", json={"filas": [{
        "apu_codigo": "4390", "shift": "DIURNO", "insumo_codigo": "7462",
        "insumo_nombre": "TRANSPORTE DE PETREOS", "categoria": "granulares",
        "volumen": 1.05, "km_base": 25.0}]})
    cli.put(f"/api/carpetas/{cid}/transporte", json={"km_granulares": 32})
    imp = cli.get(f"/api/carpetas/{cid}/transporte").json()["impacto"]
    fila = [f for f in imp if f["insumo_codigo"] == "7462"][0]
    assert fila["rendimiento_actual"] == 26.25
    assert fila["rendimiento_nuevo"] == 33.6
    assert fila["origen"] == "distancia"


def test_impacto_incluye_el_peaje_quitado(tmp_path):
    """Si el peaje era el ÚNICO componente de acarreo/peaje del APU, la composición
    efectiva queda vacía — y aun así la fila tiene que seguir en la tabla de
    impacto, con quitado=true y origen="distancia" (no "biblioteca": el proyecto
    SÍ desvió esta fila, al excluirla)."""
    from apu_tool.nucleo.models import LicitacionItem
    from apu_tool.servicio import corridas as svc
    cli, alm = _cli(tmp_path)
    alm.apus.insert_apus([Apu(codigo="5000", nombre="TRANSPORTE PEAJE", unidad="GLB",
                              shift="DIURNO", grupo="TRANSPORTES")])
    alm.apus.insert_components([
        ApuComponent(apu_codigo="5000", shift="DIURNO", insumo_codigo="INT3",
                     insumo_nombre="PEAJE", unidad="GLB", rendimiento=1.0,
                     precio_unitario_hist=8000.0)])
    cid = alm.carpetas.crear("Metro")
    corrida = svc.construir_corrida(
        alm, "lic.xlsx",
        [LicitacionItem(item="1", descripcion="PEAJE", unidad="GLB", cantidad=1,
                        precio_contractual=8000.0, shift="DIURNO")],
        "DIURNO", False, carpeta_id=cid)
    svc.confirmar_item(alm, corrida, 0, "5000", "DIURNO")
    r = cli.put(f"/api/carpetas/{cid}/transporte", json={"peaje_aplica": False})
    assert r.status_code == 200, r.text
    imp = cli.get(f"/api/carpetas/{cid}/transporte").json()["impacto"]
    filas = [f for f in imp if f["apu_codigo"] == "5000"]
    assert len(filas) == 1, imp
    assert filas[0]["quitado"] is True
    assert filas[0]["origen"] == "distancia"
