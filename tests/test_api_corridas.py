import openpyxl

from apu_tool.datos.almacen import Almacen
from apu_tool.dominio.licitacion import write_sample_licitacion
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo, LicitacionItem
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
    lic = _xlsx_lic(tmp_path)
    with open(lic, "rb") as f:
        r = cli.post("/api/corridas",
                     data={"turno": "DIURNO", "use_ai": "false"},
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
    mala = tmp_path / "mala.csv"
    mala.write_text("foo,bar\n1,2\n", encoding="utf-8")
    with open(mala, "rb") as f:
        r = cli.post("/api/corridas", data={"turno": "DIURNO"},
                     files={"archivo": ("mala.csv", f, "text/csv")})
    assert r.status_code == 400
    assert r.json()["detail"]


def test_corridas_stream_emite_started_progreso_done(tmp_path):
    cli, alm = _cli(tmp_path)
    lic = _xlsx_lic(tmp_path)
    with open(lic, "rb") as f:
        r = cli.post("/api/corridas/stream",
                     data={"turno": "DIURNO", "use_ai": "false"},
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
    mala = tmp_path / "mala.csv"
    mala.write_text("foo,bar\n1,2\n", encoding="utf-8")
    with open(mala, "rb") as f:
        r = cli.post("/api/corridas/stream", data={"turno": "DIURNO"},
                     files={"archivo": ("mala.csv", f, "text/csv")})
    assert r.status_code == 400


def test_listar_corridas_endpoint(tmp_path):
    cli, _ = _cli(tmp_path)
    lic = _xlsx_lic(tmp_path)
    with open(lic, "rb") as f:
        cli.post("/api/corridas", data={"turno": "DIURNO", "use_ai": "false"},
                 files={"archivo": ("lic.xlsx", f,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    r = cli.get("/api/corridas")
    assert r.status_code == 200
    body = r.json()
    assert len(body) >= 1 and "creada_en" in body[0] and "n_items" in body[0]


def test_eliminar_corrida_endpoint(tmp_path):
    cli, _ = _cli(tmp_path)
    lic = _xlsx_lic(tmp_path)
    with open(lic, "rb") as f:
        cid = cli.post("/api/corridas", data={"turno": "DIURNO", "use_ai": "false"},
                       files={"archivo": ("lic.xlsx", f, "application/octet-stream")}).json()["id"]
    assert cli.delete(f"/api/corridas/{cid}").status_code == 200
    assert cli.get(f"/api/corridas/{cid}").status_code == 404
    assert cli.delete(f"/api/corridas/{cid}").status_code == 404


def test_corridas_sin_turno_400(tmp_path):
    cli, _ = _cli(tmp_path)
    p = tmp_path / "noturno.xlsx"
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["ITEM", "DESCRIPCION", "UNIDAD", "CANTIDAD", "PRECIO"])
    ws.append(["1", "Concreto clase D", "M3", 10, 400000]); wb.save(p)
    with open(p, "rb") as f:
        r = cli.post("/api/corridas", data={"turno": "DIURNO"},
                     files={"archivo": ("noturno.xlsx", f, "application/octet-stream")})
    assert r.status_code == 400
