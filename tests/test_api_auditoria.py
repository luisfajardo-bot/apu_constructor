from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Insumo
from apu_tool.servicio.app import create_app
from tests.conftest import cliente


def _app(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return create_app(almacen=alm), alm


def test_auditoria_solo_admin(tmp_path):
    app, _ = _app(tmp_path)
    assert cliente(app, rol="consulta").get("/api/auditoria").status_code == 403
    assert cliente(app, rol="editor").get("/api/auditoria").status_code == 403
    assert cliente(app, rol="admin").get("/api/auditoria").status_code == 200


def test_cambio_precio_via_api_deja_auditoria(tmp_path):
    app, alm = _app(tmp_path)
    iid = alm.precios.crear_insumo(Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU"))
    ed = cliente(app, rol="editor")
    r = ed.post("/api/insumos/cambios",
                json={"cambios": [{"insumo_id": iid, "precio": 1500, "fuente": "COSTO INTERNO"}]})
    assert r.status_code == 200, r.text
    adm = cliente(app, rol="admin")
    data = adm.get("/api/auditoria?accion=precio.editar").json()
    assert data["total"] == 1
    assert data["items"][0]["entidad_id"] == str(iid)
    assert data["items"][0]["user_id"] == "test-editor"     # actor = usuario_actual (conftest)


def test_auditoria_filtra_por_entidad_tipo(tmp_path):
    app, alm = _app(tmp_path)
    adm = cliente(app, rol="admin")
    # sin datos → total 0, estructura correcta
    data = adm.get("/api/auditoria?entidad_tipo=usuario").json()
    assert data == {"items": [], "total": 0, "limit": 100, "offset": 0}
