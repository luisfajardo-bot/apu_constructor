"""Una lista de precios inexistente (o id<=0) debe dar 400 en el borde HTTP, en
TODOS los endpoints que reciben una lista — no un costeo silencioso en $0
(PricingEngine no valida que la lista exista) ni un 500. `lista`/`lista_id`
ausente (None = Principal) sigue siendo válido en todos los casos."""
import openpyxl

from apu_tool.datos.almacen import Almacen
from apu_tool.dominio.licitacion import write_sample_licitacion
from apu_tool.nucleo.models import Insumo, LicitacionItem
from apu_tool.servicio.app import create_app
from tests.conftest import cliente

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _cli(tmp_path, rol="editor"):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo("100", "Concreto 3000 PSI", "M3", "CONCRETOS", 350000.0, "COSTO INTERNO")])
    return cliente(create_app(almacen=alm), rol=rol), alm


def _xlsx_insumos() -> bytes:
    import io
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["codigo", "nombre", "precio", "fuente"])
    ws.append(["100", "Concreto 3000 PSI", 390000, "ACTA NP"])
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def test_get_insumos_lista_inexistente_400(tmp_path):
    cli, _ = _cli(tmp_path, rol="consulta")
    r = cli.get("/api/insumos?lista=999")
    assert r.status_code == 400
    assert "no existe" in r.json()["detail"]


def test_get_insumos_lista_negativa_o_cero_400(tmp_path):
    cli, _ = _cli(tmp_path, rol="consulta")
    assert cli.get("/api/insumos?lista=0").status_code == 400
    assert cli.get("/api/insumos?lista=-1").status_code == 400


def test_get_insumos_sin_lista_ok(tmp_path):
    cli, _ = _cli(tmp_path, rol="consulta")
    assert cli.get("/api/insumos").status_code == 200


def test_get_insumos_sin_precio_combinado_con_fuente_da_400(tmp_path):
    """El ValueError de list_insumos (sin_precio excluyente con fuente/clasificacion)
    debe traducirse a 400, no escalar a 500."""
    cli, _ = _cli(tmp_path, rol="consulta")
    r = cli.get("/api/insumos?sin_precio=true&fuente=ACTA")
    assert r.status_code == 400


def test_get_insumos_fuentes_lista_inexistente_400(tmp_path):
    cli, _ = _cli(tmp_path, rol="consulta")
    assert cli.get("/api/insumos/fuentes?lista=999").status_code == 400


def test_get_insumo_detalle_lista_inexistente_400(tmp_path):
    cli, alm = _cli(tmp_path, rol="consulta")
    iid = alm.precios.get_candidatos("100")[0].id
    assert cli.get(f"/api/insumos/{iid}?lista=999").status_code == 400


def test_post_insumos_cambios_lista_inexistente_400(tmp_path):
    cli, alm = _cli(tmp_path)
    iid = alm.precios.get_candidatos("100")[0].id
    r = cli.post("/api/insumos/cambios", json={
        "cambios": [{"insumo_id": iid, "precio": 400000.0, "fuente": "ACTA"}],
        "lista_id": 999})
    assert r.status_code == 400


def test_post_insumos_crear_lista_inexistente_400(tmp_path):
    cli, _ = _cli(tmp_path)
    r = cli.post("/api/insumos/crear", json={
        "codigo": "300", "nombre": "GRAVA", "precio": 80000, "lista_id": 999})
    assert r.status_code == 400


def test_post_insumos_importar_preview_lista_inexistente_400(tmp_path):
    cli, _ = _cli(tmp_path)
    r = cli.post("/api/insumos/importar/preview",
                 data={"lista_id": "999"},
                 files={"archivo": ("l.xlsx", _xlsx_insumos(), _XLSX)})
    assert r.status_code == 400


def test_post_insumos_importar_lista_inexistente_400(tmp_path):
    cli, _ = _cli(tmp_path)
    r = cli.post("/api/insumos/importar",
                 data={"lista_id": "999"},
                 files={"archivo": ("l.xlsx", _xlsx_insumos(), _XLSX)})
    assert r.status_code == 400


def _xlsx_lic(tmp_path):
    p = tmp_path / "lic.xlsx"
    write_sample_licitacion(p, [LicitacionItem(
        item="1", descripcion="Concreto 3000 PSI", unidad="M3", cantidad=10.0,
        precio_contractual=400000.0, shift="DIURNO")])
    return p


def test_post_corridas_lista_inexistente_400(tmp_path):
    cli, _ = _cli(tmp_path, rol="consulta")
    obra = cli.post("/api/carpetas", json={"nombre": "Obra"}).json()
    lic = _xlsx_lic(tmp_path)
    with open(lic, "rb") as f:
        r = cli.post("/api/corridas",
                     data={"turno": "DIURNO", "use_ai": "false",
                           "carpeta_id": str(obra["id"]), "lista_id": "999"},
                     files={"archivo": ("lic.xlsx", f, _XLSX)})
    assert r.status_code == 400
    assert "no existe" in r.json()["detail"]


def test_post_corridas_stream_lista_inexistente_400(tmp_path):
    cli, _ = _cli(tmp_path, rol="consulta")
    obra = cli.post("/api/carpetas", json={"nombre": "Obra"}).json()
    lic = _xlsx_lic(tmp_path)
    with open(lic, "rb") as f:
        r = cli.post("/api/corridas/stream",
                     data={"turno": "DIURNO", "use_ai": "false",
                           "carpeta_id": str(obra["id"]), "lista_id": "999"},
                     files={"archivo": ("lic.xlsx", f, _XLSX)})
    assert r.status_code == 400


def test_post_corridas_sin_lista_ok(tmp_path):
    """lista_id ausente (None = Principal) no se rechaza."""
    cli, _ = _cli(tmp_path, rol="consulta")
    obra = cli.post("/api/carpetas", json={"nombre": "Obra"}).json()
    lic = _xlsx_lic(tmp_path)
    with open(lic, "rb") as f:
        r = cli.post("/api/corridas",
                     data={"turno": "DIURNO", "use_ai": "false", "carpeta_id": str(obra["id"])},
                     files={"archivo": ("lic.xlsx", f, _XLSX)})
    assert r.status_code == 200


def test_post_corridas_lista_valida_ok(tmp_path):
    cli, alm = _cli(tmp_path, rol="editor")
    lid = alm.precios.crear_lista("NP Calle 13")
    obra = cli.post("/api/carpetas", json={"nombre": "Obra"}).json()
    lic = _xlsx_lic(tmp_path)
    with open(lic, "rb") as f:
        r = cli.post("/api/corridas",
                     data={"turno": "DIURNO", "use_ai": "false",
                           "carpeta_id": str(obra["id"]), "lista_id": str(lid)},
                     files={"archivo": ("lic.xlsx", f, _XLSX)})
    assert r.status_code == 200
