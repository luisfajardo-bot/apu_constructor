import openpyxl
import pytest

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.dominio.licitacion import write_sample_licitacion
from apu_tool.nucleo.models import (
    Apu, ApuComponent, CorridaItemRow, CorridaMeta, Insumo, LicitacionItem)
from apu_tool.servicio import corridas as svc
from apu_tool.servicio.app import create_app
from tests.conftest import cliente


def _cli(tmp_path):  # alias usado por los tests de stream
    return _cliente(tmp_path)


def _cliente(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([Insumo("100", "Concreto 3000 PSI", "M3",
                                       "CONCRETOS", 350000.0, "COSTO INTERNO")])
    alm.apus.insert_apus([Apu("A1", "Concreto clase D", "M3", "DIURNO", "ESTR")])
    alm.apus.insert_components([ApuComponent("A1", "DIURNO", "100",
                               "Concreto 3000 PSI", "M3", 1.05, 350000.0)])
    return cliente(create_app(almacen=alm), rol="admin"), alm


def test_status(tmp_path):
    cli, _ = _cliente(tmp_path)
    r = cli.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["apus"] == 1 and body["insumos"] == 1 and "ia" in body
    assert isinstance(body["ia"], bool)


def _xlsx_lic(tmp_path):
    p = tmp_path / "lic.xlsx"
    write_sample_licitacion(p, [LicitacionItem(
        item="1", descripcion="Concreto clase D", unidad="M3", cantidad=10.0,
        precio_contractual=400000.0, shift="DIURNO")])
    return p


def test_flujo_corrida_completo(tmp_path):
    cli, _ = _cliente(tmp_path)
    obra = cli.post("/api/carpetas", json={"nombre": "Obra"}).json()
    lic = _xlsx_lic(tmp_path)
    with open(lic, "rb") as f:
        r = cli.post("/api/corridas",
                     data={"turno": "DIURNO", "use_ai": "false", "carpeta_id": str(obra["id"])},
                     files={"archivo": ("lic.xlsx", f,
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]

    v = cli.get(f"/api/corridas/{cid}")
    assert v.status_code == 200
    assert v.json()["totales"]["n_items"] == 1
    assert v.json()["items"][0]["costo_unitario"] == 367500.0

    det = cli.get(f"/api/corridas/{cid}/items/0")
    assert det.status_code == 200 and det.json()["apu_codigo"] == "A1"

    conf = cli.post(f"/api/corridas/{cid}/items/0/confirmar",
                    json={"apu_codigo": "A1"})
    assert conf.status_code == 200
    assert conf.json()["items"][0]["status"] == "confirmed"

    cuadro = cli.get(f"/api/corridas/{cid}/cuadro")
    assert cuadro.status_code == 200
    assert cuadro.headers["content-type"].startswith(
        "application/vnd.openxmlformats")


def test_corrida_inexistente_404(tmp_path):
    cli, _ = _cliente(tmp_path)
    assert cli.get("/api/corridas/999").status_code == 404


def test_archivo_ilegible_400(tmp_path):
    cli, _ = _cliente(tmp_path)
    obra = cli.post("/api/carpetas", json={"nombre": "Obra"}).json()
    mala = tmp_path / "mala.csv"
    mala.write_text("foo,bar\n1,2\n", encoding="utf-8")
    with open(mala, "rb") as f:
        r = cli.post("/api/corridas", data={"turno": "DIURNO", "carpeta_id": str(obra["id"])},
                     files={"archivo": ("mala.csv", f, "text/csv")})
    assert r.status_code == 400
    assert r.json()["detail"]


def test_corridas_stream_emite_started_progreso_done(tmp_path):
    cli, alm = _cli(tmp_path)
    obra = cli.post("/api/carpetas", json={"nombre": "Obra"}).json()
    lic = _xlsx_lic(tmp_path)
    with open(lic, "rb") as f:
        r = cli.post("/api/corridas/stream",
                     data={"turno": "DIURNO", "use_ai": "false", "carpeta_id": str(obra["id"])},
                     files={"archivo": ("lic.xlsx", f,
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    body = r.text
    assert "event: started" in body         # id de la corrida al inicio
    assert "event: progress" in body
    assert "event: done" in body
    # El progress trae la fila ya costeada (para la tabla en vivo).
    assert '"fila"' in body and '"costo_unitario"' in body
    # Persistencia incremental: la corrida quedó armada y consultable.
    assert len(alm.corridas.listar_corridas()) == 1


def test_sample_stream_ok(tmp_path):
    cli, _ = _cli(tmp_path)
    r = cli.post("/api/sample/stream")
    assert r.status_code == 200
    assert "event: done" in r.text


def test_corridas_stream_archivo_malo_400(tmp_path):
    cli, _ = _cli(tmp_path)
    obra = cli.post("/api/carpetas", json={"nombre": "Obra"}).json()
    mala = tmp_path / "mala.csv"
    mala.write_text("foo,bar\n1,2\n", encoding="utf-8")
    with open(mala, "rb") as f:
        r = cli.post("/api/corridas/stream",
                     data={"turno": "DIURNO", "carpeta_id": str(obra["id"])},
                     files={"archivo": ("mala.csv", f, "text/csv")})
    assert r.status_code == 400


def test_listar_corridas_endpoint(tmp_path):
    cli, _ = _cli(tmp_path)
    obra = cli.post("/api/carpetas", json={"nombre": "Obra"}).json()
    lic = _xlsx_lic(tmp_path)
    with open(lic, "rb") as f:
        cli.post("/api/corridas", data={"turno": "DIURNO", "use_ai": "false",
                                        "carpeta_id": str(obra["id"])},
                 files={"archivo": ("lic.xlsx", f,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    r = cli.get("/api/corridas")
    assert r.status_code == 200
    body = r.json()
    assert len(body) >= 1 and "creada_en" in body[0] and "n_items" in body[0]


def test_eliminar_corrida_endpoint(tmp_path):
    cli, _ = _cli(tmp_path)
    obra = cli.post("/api/carpetas", json={"nombre": "Obra"}).json()
    lic = _xlsx_lic(tmp_path)
    with open(lic, "rb") as f:
        cid = cli.post("/api/corridas",
                       data={"turno": "DIURNO", "use_ai": "false", "carpeta_id": str(obra["id"])},
                       files={"archivo": ("lic.xlsx", f, "application/octet-stream")}).json()["id"]
    assert cli.delete(f"/api/corridas/{cid}").status_code == 200
    assert cli.get(f"/api/corridas/{cid}").status_code == 404
    assert cli.delete(f"/api/corridas/{cid}").status_code == 404


def test_corridas_sin_turno_400(tmp_path):
    cli, _ = _cli(tmp_path)
    obra = cli.post("/api/carpetas", json={"nombre": "Obra"}).json()
    p = tmp_path / "noturno.xlsx"
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["ITEM", "DESCRIPCION", "UNIDAD", "CANTIDAD", "PRECIO"])
    ws.append(["1", "Concreto clase D", "M3", 10, 400000]); wb.save(p)
    with open(p, "rb") as f:
        r = cli.post("/api/corridas", data={"turno": "DIURNO", "carpeta_id": str(obra["id"])},
                     files={"archivo": ("noturno.xlsx", f, "application/octet-stream")})
    assert r.status_code == 400


def test_congelar_activar_y_confirmar_409(tmp_path):
    from apu_tool.datos.almacen import Almacen
    from apu_tool.nucleo.models import (Apu, ApuComponent, Insumo, CorridaMeta,
                                        CorridaItemRow, LicitacionItem)
    from apu_tool.servicio.app import create_app
    from tests.conftest import cliente

    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([Insumo("100", "CEMENTO", "KG", "MAT", 1000.0, "PRECIO IDU")])
    alm.apus.crear_apu(Apu("A1", "MURO", "M2", "DIURNO", "ESTR"),
                       [ApuComponent("A1", "DIURNO", "100", "CEMENTO", "KG", 2.0, 0.0)])
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="x", archivo="a.xlsx", turno_def="DIURNO",
        use_ai=False, estado="en_revision"))
    item = LicitacionItem(item="1", descripcion="muro", unidad="M2", cantidad=1.0,
                          precio_contractual=10000.0, shift="DIURNO")
    alm.corridas.guardar_items(cid, [CorridaItemRow(
        seq=0, item=item, status="auto", apu_codigo="A1", apu_nombre="MURO", unidad="M2",
        shift="DIURNO", origen="historico", confianza=1.0, explicacion="",
        componentes=[{"insumo_codigo": "100", "insumo_nombre": "CEMENTO", "unidad": "KG",
                      "rendimiento": 2.0}], candidatos=[])])
    cli = cliente(create_app(almacen=alm), rol="consulta")

    r = cli.post(f"/api/corridas/{cid}/congelar")
    assert r.status_code == 200 and r.json()["modo"] == "congelada"
    # confirmar en congelada → 409
    assert cli.post(f"/api/corridas/{cid}/items/0/confirmar",
                    json={"apu_codigo": "A1", "shift": "DIURNO"}).status_code == 409
    # activar → modo activa; ahora confirmar funciona
    assert cli.post(f"/api/corridas/{cid}/activar").json()["modo"] == "activa"
    assert cli.post(f"/api/corridas/{cid}/items/0/confirmar",
                    json={"apu_codigo": "A1", "shift": "DIURNO"}).status_code == 200


def test_crear_corrida_con_nombre(tmp_path):
    cli, alm = _cliente(tmp_path)
    obra = cli.post("/api/carpetas", json={"nombre": "Obra"}).json()
    lic = _xlsx_lic(tmp_path)
    with open(lic, "rb") as f:
        cid = cli.post("/api/corridas",
                       data={"turno": "DIURNO", "use_ai": "false",
                             "carpeta_id": str(obra["id"]), "nombre": "Presupuesto Norte"},
                       files={"archivo": ("lic.xlsx", f, "application/octet-stream")}).json()["id"]
    assert alm.corridas.get_corrida(cid).nombre == "Presupuesto Norte"
    assert cli.get(f"/api/corridas/{cid}").json()["nombre"] == "Presupuesto Norte"


def test_crear_corrida_sin_nombre_usa_archivo_sin_ext(tmp_path):
    cli, alm = _cliente(tmp_path)
    obra = cli.post("/api/carpetas", json={"nombre": "Obra"}).json()
    lic = _xlsx_lic(tmp_path)
    with open(lic, "rb") as f:
        cid = cli.post("/api/corridas",
                       data={"turno": "DIURNO", "use_ai": "false", "carpeta_id": str(obra["id"])},
                       files={"archivo": ("lic.xlsx", f, "application/octet-stream")}).json()["id"]
    assert alm.corridas.get_corrida(cid).nombre == "lic"


def test_renombrar_corrida_endpoint(tmp_path):
    cli, alm = _cliente(tmp_path)
    obra = cli.post("/api/carpetas", json={"nombre": "Obra"}).json()
    lic = _xlsx_lic(tmp_path)
    with open(lic, "rb") as f:
        cid = cli.post("/api/corridas",
                       data={"turno": "DIURNO", "use_ai": "false", "carpeta_id": str(obra["id"])},
                       files={"archivo": ("lic.xlsx", f, "application/octet-stream")}).json()["id"]
    r = cli.post(f"/api/corridas/{cid}/renombrar", json={"nombre": "Obra Renombrada"})
    assert r.status_code == 200 and r.json()["nombre"] == "Obra Renombrada"
    assert alm.corridas.get_corrida(cid).nombre == "Obra Renombrada"


def test_renombrar_corrida_vacio_400(tmp_path):
    cli, _ = _cliente(tmp_path)
    obra = cli.post("/api/carpetas", json={"nombre": "Obra"}).json()
    lic = _xlsx_lic(tmp_path)
    with open(lic, "rb") as f:
        cid = cli.post("/api/corridas",
                       data={"turno": "DIURNO", "use_ai": "false", "carpeta_id": str(obra["id"])},
                       files={"archivo": ("lic.xlsx", f, "application/octet-stream")}).json()["id"]
    assert cli.post(f"/api/corridas/{cid}/renombrar", json={"nombre": "   "}).status_code == 400


def test_renombrar_corrida_inexistente_404(tmp_path):
    cli, _ = _cliente(tmp_path)
    assert cli.post("/api/corridas/999/renombrar", json={"nombre": "X"}).status_code == 404


def test_renombrar_corrida_congelada_200(tmp_path):
    cli, alm = _cliente(tmp_path)
    obra = cli.post("/api/carpetas", json={"nombre": "Obra"}).json()
    lic = _xlsx_lic(tmp_path)
    with open(lic, "rb") as f:
        cid = cli.post("/api/corridas",
                       data={"turno": "DIURNO", "use_ai": "false", "carpeta_id": str(obra["id"])},
                       files={"archivo": ("lic.xlsx", f, "application/octet-stream")}).json()["id"]
    r = cli.post(f"/api/corridas/{cid}/congelar")
    assert r.status_code == 200 and r.json()["modo"] == "congelada"
    r2 = cli.post(f"/api/corridas/{cid}/renombrar", json={"nombre": "Congelada Renombrada"})
    assert r2.status_code == 200 and r2.json()["nombre"] == "Congelada Renombrada"


def test_renombrar_corrida_requiere_editor(tmp_path):
    from apu_tool.nucleo.models import CorridaMeta

    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="x", archivo="a.xlsx", turno_def="DIURNO",
        use_ai=False, estado="en_revision"))

    cli_consulta = cliente(create_app(almacen=alm), rol="consulta")
    r_consulta = cli_consulta.post(f"/api/corridas/{cid}/renombrar", json={"nombre": "Nuevo"})
    assert r_consulta.status_code == 403

    cli_editor = cliente(create_app(almacen=alm), rol="editor")
    r_editor = cli_editor.post(f"/api/corridas/{cid}/renombrar", json={"nombre": "Nuevo"})
    assert r_editor.status_code == 200 and r_editor.json()["nombre"] == "Nuevo"


def _corrida_api(cli, tmp_path):
    """Crea una corrida de 1 ítem por la API y devuelve su id."""
    obra = cli.post("/api/carpetas", json={"nombre": "Obra"}).json()
    lic = _xlsx_lic(tmp_path)
    with open(lic, "rb") as f:
        r = cli.post("/api/corridas",
                     data={"turno": "DIURNO", "use_ai": "false",
                           "carpeta_id": str(obra["id"])},
                     files={"archivo": ("lic.xlsx", f, _XLSX_MIME)})
    assert r.status_code == 200, r.text
    return r.json()["id"]


_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx_faltantes(tmp_path):
    """Excel con las líneas que faltaron: una nueva y una que ya está en la corrida."""
    p = tmp_path / "faltantes.xlsx"
    write_sample_licitacion(p, [
        LicitacionItem(item="9", descripcion="Sardinel A-10", unidad="ML",
                       cantidad=5.0, precio_contractual=40000.0, shift="DIURNO"),
        LicitacionItem(item="10", descripcion="Concreto clase D", unidad="M3",
                       cantidad=1.0, precio_contractual=400000.0, shift="NOCTURNO"),
    ])
    return p


def test_api_agregar_linea_a_mano(tmp_path):
    cli, _ = _cliente(tmp_path)
    cid = _corrida_api(cli, tmp_path)
    r = cli.post(f"/api/corridas/{cid}/items", json={"lineas": [
        {"descripcion": "Concreto clase D", "unidad": "M3", "cantidad": 3.0,
         "precio_contractual": 400000.0}]})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [f["seq"] for f in items] == [0, 1]
    assert items[1]["apu_codigo"] == "A1" and items[1]["cantidad"] == 3.0


def test_api_agregar_linea_sin_descripcion_es_400(tmp_path):
    cli, _ = _cliente(tmp_path)
    cid = _corrida_api(cli, tmp_path)
    r = cli.post(f"/api/corridas/{cid}/items", json={"lineas": [{"descripcion": "  "}]})
    assert r.status_code == 400


def test_api_agregar_linea_turno_invalido_es_400(tmp_path):
    cli, _ = _cliente(tmp_path)
    cid = _corrida_api(cli, tmp_path)
    r = cli.post(f"/api/corridas/{cid}/items", json={"lineas": [
        {"descripcion": "Concreto clase D", "shift": "TARDE"}]})
    assert r.status_code == 400
    assert "Turno" in r.json()["detail"]


def test_api_preview_y_importar_lineas(tmp_path):
    cli, _ = _cliente(tmp_path)
    cid = _corrida_api(cli, tmp_path)
    xls = _xlsx_faltantes(tmp_path)

    with open(xls, "rb") as f:
        prev = cli.post(f"/api/corridas/{cid}/items/preview",
                        files={"archivo": ("faltantes.xlsx", f, _XLSX_MIME)})
    assert prev.status_code == 200, prev.text
    cuerpo = prev.json()
    assert cuerpo["total"] == 2
    assert [n["descripcion"] for n in cuerpo["nuevas"]] == ["Sardinel A-10"]
    assert cuerpo["duplicadas"][0]["seq_existente"] == 0
    assert len(cli.get(f"/api/corridas/{cid}").json()["items"]) == 1   # el preview no escribió

    with open(xls, "rb") as f:
        r = cli.post(f"/api/corridas/{cid}/items/importar",
                     files={"archivo": ("faltantes.xlsx", f, _XLSX_MIME)})
    assert r.status_code == 200, r.text
    assert [f["seq"] for f in r.json()["items"]] == [0, 1, 2]


def test_api_importar_archivo_corrupto_es_400(tmp_path):
    cli, _ = _cliente(tmp_path)
    cid = _corrida_api(cli, tmp_path)
    r = cli.post(f"/api/corridas/{cid}/items/importar",
                 files={"archivo": ("malo.xlsx", b"no soy un excel", _XLSX_MIME)})
    assert r.status_code == 400


def test_api_agregar_en_corrida_congelada_es_409(tmp_path):
    cli, _ = _cliente(tmp_path)
    cid = _corrida_api(cli, tmp_path)
    assert cli.post(f"/api/corridas/{cid}/congelar").status_code == 200
    r = cli.post(f"/api/corridas/{cid}/items", json={"lineas": [
        {"descripcion": "Concreto clase D"}]})
    assert r.status_code == 409
    b = cli.post(f"/api/corridas/{cid}/items/borrar", json={"seqs": [0]})
    assert b.status_code == 409


def test_api_borrar_lineas(tmp_path):
    cli, _ = _cliente(tmp_path)
    cid = _corrida_api(cli, tmp_path)
    cli.post(f"/api/corridas/{cid}/items", json={"lineas": [
        {"descripcion": "Concreto clase D"}]})
    r = cli.post(f"/api/corridas/{cid}/items/borrar", json={"seqs": [0]})
    assert r.status_code == 200, r.text
    assert [f["seq"] for f in r.json()["items"]] == [1]        # sin renumerar


def test_api_corrida_inexistente_es_404(tmp_path):
    cli, _ = _cliente(tmp_path)
    assert cli.post("/api/corridas/999/items",
                    json={"lineas": [{"descripcion": "x"}]}).status_code == 404
    assert cli.post("/api/corridas/999/items/borrar",
                    json={"seqs": [0]}).status_code == 404


def test_api_agregar_pasado_del_tope_es_400(tmp_path):
    from apu_tool.servicio import corridas as svc
    cli, _ = _cliente(tmp_path)
    cid = _corrida_api(cli, tmp_path)
    lineas = [{"descripcion": "Concreto clase D"}
              for _ in range(svc.MAX_LINEAS_AGREGADAS + 1)]
    r = cli.post(f"/api/corridas/{cid}/items", json={"lineas": lineas})
    assert r.status_code == 400
    assert str(svc.MAX_LINEAS_AGREGADAS) in r.json()["detail"]
    assert len(cli.get(f"/api/corridas/{cid}").json()["items"]) == 1   # no escribió nada


def test_api_agregar_en_corrida_armando_es_400(tmp_path):
    cli, alm = _cliente(tmp_path)
    cid = _corrida_api(cli, tmp_path)
    alm.corridas.set_estado(cid, "armando")
    r = cli.post(f"/api/corridas/{cid}/items", json={"lineas": [
        {"descripcion": "Concreto clase D"}]})
    assert r.status_code == 400
    assert "armando" in r.json()["detail"]
    assert len(cli.get(f"/api/corridas/{cid}").json()["items"]) == 1


def test_api_agregar_linea_con_cantidad_negativa_es_422(tmp_path):
    cli, _ = _cliente(tmp_path)
    cid = _corrida_api(cli, tmp_path)
    r = cli.post(f"/api/corridas/{cid}/items", json={"lineas": [
        {"descripcion": "Concreto clase D", "cantidad": -5}]})
    assert r.status_code == 422        # pydantic rechaza antes del servicio
    assert len(cli.get(f"/api/corridas/{cid}").json()["items"]) == 1


def _cli_rol(tmp_path, rol: str):
    """Cliente con un rol dado + su Almacen. Para los tests de autorización."""
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return cliente(create_app(almacen=alm), rol=rol), alm


def _corrida_especial(alm, contractual: float = 92106000.0) -> int:
    """Una corrida con una fila SIN APU: el caso de los proyectos especiales."""
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-09-07T10:00:00", archivo="x.xlsx", turno_def="DIURNO",
        use_ai=None, estado="en_revision", cuadro_path=None, nombre="x"))
    alm.corridas.agregar_item(cid, CorridaItemRow(
        seq=0,
        item=LicitacionItem(item="1", descripcion="PRUEBA DE CARGA 6 PUENTES",
                            unidad="GLB", cantidad=1.0,
                            precio_contractual=contractual, shift="DIURNO"),
        status="new", apu_codigo=None, apu_nombre="", unidad="GLB", shift="DIURNO",
        origen="historico", confianza=0.0, explicacion="", componentes=[], candidatos=[]))
    return cid


def test_igualar_costo_endpoint(tmp_path):
    """Feliz: 200, la fila queda con el contractual como costo y marcada."""
    cli, alm = _cliente(tmp_path)
    cid = _corrida_especial(alm)
    r = cli.post(f"/api/corridas/{cid}/igualar-costo", json={"seqs": [0]})
    assert r.status_code == 200, r.text
    fila = r.json()["items"][0]
    assert fila["costo_unitario"] == fila["precio_contractual"] == 92106000.0
    assert fila["costo_manual"] is True
    assert r.json()["igualadas"] == [0]


def test_igualar_costo_404_si_no_existe(tmp_path):
    cli, _ = _cliente(tmp_path)
    r = cli.post("/api/corridas/9999/igualar-costo", json={"seqs": [0]})
    assert r.status_code == 404


def test_igualar_costo_409_si_congelada(tmp_path):
    cli, alm = _cliente(tmp_path)
    cid = _corrida_especial(alm)
    alm.corridas.set_modo(cid, "congelada")
    r = cli.post(f"/api/corridas/{cid}/igualar-costo", json={"seqs": [0]})
    assert r.status_code == 409


def test_igualar_costo_rol_consulta_prohibido(tmp_path):
    """Un endpoint que declara dinero no se le abre al rol de solo lectura."""
    cli, alm = _cli_rol(tmp_path, "consulta")
    cid = _corrida_especial(alm)
    r = cli.post(f"/api/corridas/{cid}/igualar-costo", json={"seqs": [0]})
    assert r.status_code == 403


def test_igualar_costo_rol_editor_permitido(tmp_path):
    cli, alm = _cli_rol(tmp_path, "editor")
    cid = _corrida_especial(alm)
    r = cli.post(f"/api/corridas/{cid}/igualar-costo", json={"seqs": [0]})
    assert r.status_code == 200, r.text


# --------------------------------------------------------------------------
# Armado partido en dos: crear-encolada + armar-pendientes (el worker entra por
# el medio, en el ítem donde quedó).
# --------------------------------------------------------------------------
def _item_plan(desc: str, **kw) -> LicitacionItem:
    base = dict(item="1", descripcion=desc, unidad="M3", cantidad=10.0,
                precio_contractual=400000.0, shift="DIURNO")
    base.update(kw)
    return LicitacionItem(**base)


def _carpeta(cli) -> int:
    return cli.post("/api/carpetas", json={"nombre": "Obra"}).json()["id"]


def test_armar_pendientes_arranca_donde_se_le_dice(tmp_path):
    """El worker reanuda por el medio: con desde_seq=2 no vuelve a armar 0 y 1."""
    cli, alm = _cliente(tmp_path)
    items = [_item_plan(f"ACTIVIDAD {i}") for i in range(4)]
    cid = svc.crear_corrida_encolada(alm, "x.xlsx", items, "DIURNO", None,
                                     carpeta_id=_carpeta(cli))
    eventos = list(svc.armar_pendientes(alm, cid, items, desde_seq=2))
    armados = [p["i"] for e, p in eventos if e == "progress"]
    assert armados == [3, 4]                       # 1-based: solo los seq 2 y 3
    assert [r.seq for r in alm.corridas.get_items(cid)] == [2, 3]


def test_crear_corrida_encolada_guarda_el_plan_y_no_arma(tmp_path):
    """Encolar es crear + guardar el plan. Ni una fila armada: eso es del worker."""
    cli, alm = _cliente(tmp_path)
    items = [_item_plan("Concreto clase D"), _item_plan("ACTIVIDAD 2")]
    cid = svc.crear_corrida_encolada(alm, "x.xlsx", items, "DIURNO", None,
                                     carpeta_id=_carpeta(cli))
    assert alm.corridas.get_corrida(cid).estado == "armando"
    assert alm.corridas.get_plan(cid)                      # el plan quedó guardado
    assert alm.corridas.get_items(cid) == []               # y NADA armado


def test_plan_de_devuelve_exactamente_lo_guardado(tmp_path):
    """Round-trip del plan. Si perdiera un campo, el armado reanudado costearía
    distinto que el original y en silencio."""
    cli, alm = _cliente(tmp_path)
    items = [_item_plan("Concreto clase D", item="7", unidad="M2", cantidad=3.5,
                        precio_contractual=123456.0, shift="NOCTURNO",
                        categoria="ESTRUCTURAS", codigo_sugerido="A1"),
             _item_plan("ACTIVIDAD 2")]
    cid = svc.crear_corrida_encolada(alm, "x.xlsx", items, "DIURNO", None,
                                     carpeta_id=_carpeta(cli))
    assert svc.plan_de(alm, cid) == items                  # dataclass: compara campo a campo


def test_plan_de_sin_plan_es_lista_vacia(tmp_path):
    _cli, alm = _cliente(tmp_path)
    cid = _corrida_especial(alm)                           # creada sin pasar por encolar
    assert svc.plan_de(alm, cid) == []


def test_un_item_que_revienta_no_tumba_el_armado(tmp_path, monkeypatch):
    """Un ítem venenoso cuesta una fila, no 1900: queda sin APU con el motivo a la
    vista y el armado sigue con los que faltan."""
    cli, alm = _cliente(tmp_path)
    items = [_item_plan(f"Concreto clase D {i}") for i in range(3)]
    cid = svc.crear_corrida_encolada(alm, "x.xlsx", items, "DIURNO", None,
                                     carpeta_id=_carpeta(cli))
    real = svc._armar_fila

    def _explota(assembler, item, seq):
        if seq == 1:
            raise RuntimeError("insumo maldito")
        return real(assembler, item, seq)

    monkeypatch.setattr(svc, "_armar_fila", _explota)
    eventos = list(svc.armar_pendientes(alm, cid, items))
    assert [p["i"] for e, p in eventos if e == "progress"] == [1, 2, 3]

    filas = {r.seq: r for r in alm.corridas.get_items(cid)}
    assert set(filas) == {0, 1, 2}
    assert filas[0].apu_codigo == "A1" and filas[2].apu_codigo == "A1"   # los sanos, armados
    envenenada = filas[1]
    assert envenenada.apu_codigo is None
    assert "insumo maldito" in envenenada.explicacion
    assert svc.seqs_sin_apu(filas.values()) == [1]         # cae sola en el candado


def test_construir_corrida_arma_todo_y_finaliza(tmp_path):
    """REGRESION del camino sincrónico (CLI/GUI): crea, arma todo en el acto y
    termina en 'en_revision' con la duración guardada."""
    cli, alm = _cliente(tmp_path)
    items = [_item_plan("Concreto clase D"), _item_plan("Concreto clase D", item="2")]
    cid = svc.construir_corrida(alm, "lic.xlsx", items, "DIURNO", False,
                                carpeta_id=_carpeta(cli))
    meta = alm.corridas.get_corrida(cid)
    assert meta.estado == "en_revision"
    assert isinstance(meta.duracion_ms, int) and meta.duracion_ms >= 0
    assert [r.seq for r in alm.corridas.get_items(cid)] == [0, 1]
    assert svc.vista_corrida(alm, cid)["totales"]["n_items"] == 2


def _armado_que_falla(monkeypatch, falla) -> list[int]:
    """Parchea `_armar_fila` para que reviente en los seq donde `falla(seq)` sea
    cierto. Devuelve la lista (viva) de los seq que se intentaron armar."""
    real = svc._armar_fila
    intentados: list[int] = []

    def _quizas_explota(assembler, item, seq):
        intentados.append(seq)
        if falla(seq):
            raise RuntimeError(f"la base no responde ({seq})")
        return real(assembler, item, seq)

    monkeypatch.setattr(svc, "_armar_fila", _quizas_explota)
    return intentados


def test_fallos_alternados_no_cortan_el_armado(tmp_path, monkeypatch):
    """El contador es de fallos SEGUIDOS: un ítem que arma bien lo reinicia. Sin
    esto, una licitación con muchos ítems raros salpicados se cortaría sola."""
    cli, alm = _cliente(tmp_path)
    n = config.MAX_FALLOS_SEGUIDOS_ARMADO * 4          # muchos más fallos que el tope
    items = [_item_plan("Concreto clase D", item=str(i)) for i in range(n)]
    cid = svc.crear_corrida_encolada(alm, "x.xlsx", items, "DIURNO", None,
                                     carpeta_id=_carpeta(cli))
    _armado_que_falla(monkeypatch, lambda seq: seq % 2 == 0)   # uno sí, uno no
    eventos = list(svc.armar_pendientes(alm, cid, items))      # NO levanta
    assert len(eventos) == n
    assert len(alm.corridas.get_items(cid)) == n
    assert len(svc.seqs_sin_apu(alm.corridas.get_items(cid))) == n // 2


def test_fallos_seguidos_cortan_y_la_excepcion_sube(tmp_path, monkeypatch):
    """N seguidos ya no es un ítem malo, es el entorno: se corta ANTES de escribir
    otra fila envenenada y la excepción sube, para que el worker deje la corrida en
    la cola y la reintente cuando la base vuelva."""
    cli, alm = _cliente(tmp_path)
    tope = config.MAX_FALLOS_SEGUIDOS_ARMADO
    items = [_item_plan("Concreto clase D", item=str(i)) for i in range(tope * 3)]
    cid = svc.crear_corrida_encolada(alm, "x.xlsx", items, "DIURNO", None,
                                     carpeta_id=_carpeta(cli))
    intentados = _armado_que_falla(monkeypatch, lambda seq: seq >= 1)   # el 0 arma bien
    with pytest.raises(RuntimeError, match="seguidos"):
        list(svc.armar_pendientes(alm, cid, items))
    # El fallo nº `tope` corta sin persistir: quedan el ítem sano y `tope - 1` filas
    # envenenadas, no las 15 del plan.
    assert [r.seq for r in alm.corridas.get_items(cid)] == list(range(tope))
    assert intentados == list(range(tope + 1))          # y no se intentó ni uno más


def test_borrar_lineas_mientras_arma_da_error(tmp_path):
    """El worker reanuda en `max_seq + 1`. Borrar las ÚLTIMAS líneas hace RETROCEDER
    ese máximo, y si la instancia muere ahí, al reanudar se re-arma justo lo borrado.

    Hoy no se podía llegar a este caso porque durante el armado no se ven las filas;
    el armado como trabajo del servidor las hace visibles y operables, así que la
    puerta la abre este diseño y hay que cerrarla."""
    cli, alm = _cliente(tmp_path)
    items = [_item_plan("ACTIVIDAD A"), _item_plan("ACTIVIDAD B")]
    cid = svc.crear_corrida_encolada(alm, "x.xlsx", items, "DIURNO", None,
                                     carpeta_id=_carpeta(cli))
    for _ in svc.armar_pendientes(alm, cid, items):
        pass
    # crear_corrida_encolada NO finaliza: sigue en 'armando', que es la cola.
    with pytest.raises(ValueError, match="se está armando"):
        svc.borrar_items(alm, cid, [1])
    assert len(alm.corridas.get_items(cid)) == 2          # no borró nada

    alm.corridas.finalizar_armado(cid, "en_revision")
    svc.borrar_items(alm, cid, [1])                        # ya terminada: sí deja
    assert len(alm.corridas.get_items(cid)) == 1


def test_el_endpoint_de_borrar_traduce_el_armando_a_400(tmp_path):
    """El test de arriba prueba el servicio; este prueba la RUTA. Sin el
    `except ValueError` de `rutas.py`, la guarda sigue funcionando pero el usuario
    recibe un 500 opaco en vez del motivo — y la suite quedaría verde igual."""
    cli, alm = _cliente(tmp_path)
    items = [_item_plan("ACTIVIDAD A"), _item_plan("ACTIVIDAD B")]
    cid = svc.crear_corrida_encolada(alm, "x.xlsx", items, "DIURNO", None,
                                     carpeta_id=_carpeta(cli))
    for _ in svc.armar_pendientes(alm, cid, items):
        pass
    r = cli.post(f"/api/corridas/{cid}/items/borrar", json={"seqs": [1]})
    assert r.status_code == 400, r.text
    assert "armando" in r.json()["detail"]
