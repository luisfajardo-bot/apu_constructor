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
