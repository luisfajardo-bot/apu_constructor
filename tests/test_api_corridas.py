from fastapi.testclient import TestClient

from apu_tool.datos.almacen import Almacen
from apu_tool.dominio.licitacion import write_sample_licitacion
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo, LicitacionItem
from apu_tool.servicio.app import create_app


def _cliente(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([Insumo("100", "Concreto 3000 PSI", "M3",
                                       "CONCRETOS", 350000.0, "COSTO INTERNO")])
    alm.apus.insert_apus([Apu("A1", "Concreto clase D", "M3", "DIURNO", "ESTR")])
    alm.apus.insert_components([ApuComponent("A1", "DIURNO", "100",
                               "Concreto 3000 PSI", "M3", 1.05, 350000.0)])
    return TestClient(create_app(almacen=alm)), alm


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
