from apu_tool.datos.almacen import Almacen
from apu_tool.servicio.app import create_app
from tests.conftest import cliente


def _cli(tmp_path, rol="admin"):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return cliente(create_app(almacen=alm), rol=rol), alm


def test_crud_carpetas_api(tmp_path):
    cli, _ = _cli(tmp_path)
    r = cli.post("/api/carpetas", json={"nombre": "Calle 13"})
    assert r.status_code == 200, r.text
    obra = r.json()
    r = cli.post("/api/carpetas", json={"nombre": "Lote 3", "parent_id": obra["id"]})
    assert r.status_code == 200
    arbol = cli.get("/api/carpetas").json()
    assert any(n["nombre"] == "Calle 13" and n["hijas"] for n in arbol)
    r = cli.patch(f"/api/carpetas/{obra['id']}", json={"nombre": "Calle 13 SL5"})
    assert r.status_code == 200 and r.json()["nombre"] == "Calle 13 SL5"


def test_borrar_carpeta_no_vacia_409(tmp_path):
    cli, _ = _cli(tmp_path)
    obra = cli.post("/api/carpetas", json={"nombre": "Obra"}).json()
    cli.post("/api/carpetas", json={"nombre": "Sub", "parent_id": obra["id"]})
    r = cli.delete(f"/api/carpetas/{obra['id']}")
    assert r.status_code == 409


def test_nombre_duplicado_409(tmp_path):
    cli, _ = _cli(tmp_path)
    cli.post("/api/carpetas", json={"nombre": "Obra"})
    r = cli.post("/api/carpetas", json={"nombre": "Obra"})
    assert r.status_code == 409


def test_consulta_puede_crear_pero_no_renombrar(tmp_path):
    cli, _ = _cli(tmp_path, rol="consulta")
    r = cli.post("/api/carpetas", json={"nombre": "X"})
    assert r.status_code == 200
    r = cli.patch(f"/api/carpetas/{r.json()['id']}", json={"nombre": "Y"})
    assert r.status_code == 403


from apu_tool.dominio.licitacion import write_sample_licitacion
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo, LicitacionItem


def _cli_seed(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([Insumo("100", "Concreto", "M3", "C", 350000.0, "COSTO INTERNO")])
    alm.apus.insert_apus([Apu("A1", "Concreto clase D", "M3", "DIURNO", "E")])
    alm.apus.insert_components([ApuComponent("A1", "DIURNO", "100", "Concreto", "M3", 1.05, 350000.0)])
    return cliente(create_app(almacen=alm), rol="admin"), alm


def test_crear_corrida_exige_carpeta(tmp_path):
    cli, alm = _cli_seed(tmp_path)
    obra = cli.post("/api/carpetas", json={"nombre": "Obra"}).json()
    lic = tmp_path / "lic.xlsx"
    write_sample_licitacion(lic, [LicitacionItem(
        item="1", descripcion="Concreto clase D", unidad="M3", cantidad=10.0,
        precio_contractual=400000.0, shift="DIURNO")])
    with open(lic, "rb") as f:
        r = cli.post("/api/corridas",
                     data={"turno": "DIURNO", "use_ai": "false", "carpeta_id": str(obra["id"])},
                     files={"archivo": ("lic.xlsx", f, "application/octet-stream")})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    assert alm.corridas.get_corrida(cid).carpeta_id == obra["id"]


def test_crear_corrida_carpeta_invalida_400(tmp_path):
    cli, _ = _cli_seed(tmp_path)
    lic = tmp_path / "lic.xlsx"
    write_sample_licitacion(lic, [LicitacionItem(
        item="1", descripcion="Concreto clase D", unidad="M3", cantidad=10.0,
        precio_contractual=400000.0, shift="DIURNO")])
    with open(lic, "rb") as f:
        r = cli.post("/api/corridas",
                     data={"turno": "DIURNO", "use_ai": "false", "carpeta_id": "9999"},
                     files={"archivo": ("lic.xlsx", f, "application/octet-stream")})
    assert r.status_code == 400


def test_sample_va_a_sin_clasificar(tmp_path):
    cli, alm = _cli_seed(tmp_path)
    r = cli.post("/api/sample")
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    sc = alm.corridas.get_corrida(cid).carpeta_id
    assert alm.carpetas.get(sc).nombre == "Sin clasificar"
