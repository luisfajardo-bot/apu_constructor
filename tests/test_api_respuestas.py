# tests/test_api_respuestas.py
from fastapi.testclient import TestClient

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Insumo, Perfil
from apu_tool.servicio.app import create_app
from apu_tool.servicio.auth import usuario_actual

INS = {"entidad": "insumo", "codigo": "4520", "nombre": "DUCTO PVC"}
OTRO = {"entidad": "insumo", "codigo": "4521", "nombre": "CODO PVC"}
ANA = Perfil(user_id="u-ana", email="ana@obra.co", rol="editor", estado="activo", nombre="Ana")
BETO = Perfil(user_id="u-beto", email="beto@obra.co", rol="editor", estado="activo", nombre="Beto")
ADMIN = Perfil(user_id="u-adm", email="adm@obra.co", rol="admin", estado="activo", nombre="Adm")


def _app(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([Insumo("4520", "DUCTO PVC", "ML", "D", 1.0, "COSTO INTERNO"),
                                Insumo("4521", "CODO PVC", "UN", "D", 1.0, "COSTO INTERNO")])
    for p in (ANA, BETO, ADMIN):
        alm.perfiles.upsert(p)
    return create_app(almacen=alm), alm


def _como(app, p):
    app.dependency_overrides[usuario_actual] = lambda: p
    return TestClient(app)


def test_responder_y_listar_el_hilo(tmp_path):
    app, _ = _app(tmp_path)
    raiz = _como(app, ANA).post("/api/notas", json={**INS, "texto": "raíz"}).json()
    assert raiz["responde_a"] is None and raiz["borrada"] is False
    r = _como(app, BETO).post("/api/notas", json={**INS, "texto": "de acuerdo", "responde_a": raiz["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["responde_a"] == raiz["id"]
    lista = _como(app, ANA).get("/api/notas", params=INS).json()
    assert [(n["texto"], n["responde_a"]) for n in lista] == [("raíz", None), ("de acuerdo", raiz["id"])]


def test_responder_a_una_respuesta_cuelga_de_la_raiz(tmp_path):
    app, _ = _app(tmp_path)
    ana = _como(app, ANA)
    raiz = ana.post("/api/notas", json={**INS, "texto": "raíz"}).json()["id"]
    r1 = ana.post("/api/notas", json={**INS, "texto": "r1", "responde_a": raiz}).json()["id"]
    r2 = ana.post("/api/notas", json={**INS, "texto": "r2", "responde_a": r1}).json()
    assert r2["responde_a"] == raiz


def test_padre_de_otro_dueno_o_inexistente_es_400(tmp_path):
    app, _ = _app(tmp_path)
    ana = _como(app, ANA)
    raiz = ana.post("/api/notas", json={**INS, "texto": "raíz"}).json()["id"]
    assert ana.post("/api/notas", json={**OTRO, "texto": "x", "responde_a": raiz}).status_code == 400
    assert ana.post("/api/notas", json={**INS, "texto": "x", "responde_a": 99999}).status_code == 400
    ana.delete(f"/api/notas/{raiz}")
    r = ana.post("/api/notas", json={**INS, "texto": "x", "responde_a": raiz})
    assert r.status_code == 400 and "ya no existe" in r.json()["detail"]


def test_raiz_borrada_con_respuestas_queda_como_marcador(tmp_path):
    app, _ = _app(tmp_path)
    # _como reemplaza el usuario de la app entera: se llama justo antes de cada request
    raiz = _como(app, ANA).post("/api/notas", json={**INS, "texto": "secreto", "menciones": ["u-beto"]}).json()["id"]
    resp = _como(app, BETO).post("/api/notas", json={**INS, "texto": "respuesta", "responde_a": raiz}).json()["id"]
    _como(app, ANA).delete(f"/api/notas/{raiz}")
    lista = _como(app, ADMIN).get("/api/notas", params=INS).json()
    marcador = lista[0]
    assert marcador["id"] == raiz and marcador["borrada"] is True
    assert marcador["texto"] == "" and marcador["menciones"] == []
    assert marcador["puede_editar"] is False and marcador["puede_borrar"] is False
    assert lista[1]["id"] == resp
    # sin respuestas vivas, la raíz borrada desaparece
    _como(app, BETO).delete(f"/api/notas/{resp}")
    assert _como(app, ANA).get("/api/notas", params=INS).json() == []


def test_respuesta_con_mencion_y_auditoria(tmp_path):
    app, alm = _app(tmp_path)
    raiz = _como(app, ANA).post("/api/notas", json={**INS, "texto": "raíz"}).json()["id"]
    _como(app, BETO).post("/api/notas", json={**INS, "texto": "@Ana mira", "responde_a": raiz,
                                              "menciones": ["u-ana"]})
    assert alm.notas.contar_sin_leer("u-ana") == 1
    items, _ = alm.auditoria.listar(entidad_tipo="nota")
    assert items[0]["despues"]["responde_a"] == raiz


def test_responder_no_avisa_solo_al_autor_de_la_raiz(tmp_path):
    app, alm = _app(tmp_path)
    raiz = _como(app, ANA).post("/api/notas", json={**INS, "texto": "raíz"}).json()["id"]
    _como(app, BETO).post("/api/notas", json={**INS, "texto": "ok", "responde_a": raiz})
    assert alm.notas.contar_sin_leer("u-ana") == 0


def test_consulta_no_responde(tmp_path):
    app, _ = _app(tmp_path)
    raiz = _como(app, ANA).post("/api/notas", json={**INS, "texto": "raíz"}).json()["id"]
    lector = Perfil(user_id="u-l", email="l@obra.co", rol="consulta", estado="activo", nombre="L")
    r = _como(app, lector).post("/api/notas", json={**INS, "texto": "x", "responde_a": raiz})
    assert r.status_code == 403


def test_el_marcador_no_se_edita_ni_se_borra(tmp_path):
    app, _ = _app(tmp_path)
    raiz = _como(app, ANA).post("/api/notas", json={**INS, "texto": "raíz"}).json()["id"]
    _como(app, BETO).post("/api/notas", json={**INS, "texto": "r", "responde_a": raiz})
    _como(app, ANA).delete(f"/api/notas/{raiz}")
    assert _como(app, ANA).patch(f"/api/notas/{raiz}", json={"texto": "revivo"}).status_code == 404
    assert _como(app, ADMIN).delete(f"/api/notas/{raiz}").status_code == 404


def test_no_se_responde_bajo_una_raiz_borrada_ni_via_una_respuesta(tmp_path):
    """La pantalla no ofrece «Responder» en una raíz borrada; la API tampoco lo deja
    colar respondiendo a una de sus respuestas vivas."""
    app, _ = _app(tmp_path)
    raiz = _como(app, ANA).post("/api/notas", json={**INS, "texto": "raíz"}).json()["id"]
    resp = _como(app, BETO).post("/api/notas", json={**INS, "texto": "r", "responde_a": raiz}).json()["id"]
    _como(app, ANA).delete(f"/api/notas/{raiz}")
    r = _como(app, BETO).post("/api/notas", json={**INS, "texto": "x", "responde_a": resp})
    assert r.status_code == 400 and "ya no existe" in r.json()["detail"]
