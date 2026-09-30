# tests/test_api_menciones.py
from fastapi.testclient import TestClient

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Insumo, Perfil
from apu_tool.servicio import presencia
from apu_tool.servicio.app import create_app
from apu_tool.servicio.auth import usuario_actual

INS = {"entidad": "insumo", "codigo": "4520", "nombre": "DUCTO PVC"}
ANA = Perfil(user_id="u-ana", email="ana@obra.co", rol="editor", estado="activo", nombre="Ana")
BETO = Perfil(user_id="u-beto", email="beto@obra.co", rol="consulta", estado="activo", nombre="")
CARO = Perfil(user_id="u-caro", email="caro@obra.co", rol="editor", estado="inactivo", nombre="Caro")


def _app(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([Insumo("4520", "DUCTO PVC", "ML", "D", 1.0, "COSTO INTERNO")])
    for p in (ANA, BETO, CARO):
        alm.perfiles.upsert(p)
    return create_app(almacen=alm), alm


def _como(app, p):
    app.dependency_overrides[usuario_actual] = lambda: p
    return TestClient(app)


def setup_function():
    presencia._vistos.clear()


def test_crear_con_menciones_valida_y_avisa(tmp_path):
    app, _ = _app(tmp_path)
    ana = _como(app, ANA)
    # se descartan: ella misma, un inactivo, uno que no existe y el duplicado
    r = ana.post("/api/notas", json={**INS, "texto": "@beto revisa",
                                     "menciones": ["u-beto", "u-ana", "u-caro", "u-x", "u-beto"]})
    assert r.status_code == 200, r.text
    assert r.json()["menciones"] == [{"user_id": "u-beto", "nombre": "beto@obra.co"}]
    beto = _como(app, BETO)
    assert beto.get("/api/presencia").json()["menciones_sin_leer"] == 1
    bandeja = beto.get("/api/menciones").json()
    assert len(bandeja) == 1 and bandeja[0]["leida"] is False
    assert bandeja[0]["autor_email"] == "ana@obra.co" and bandeja[0]["texto"] == "@beto revisa"
    assert bandeja[0]["dueno"]["codigo"] == "4520"


def test_listar_notas_trae_las_menciones(tmp_path):
    app, _ = _app(tmp_path)
    ana = _como(app, ANA)
    ana.post("/api/notas", json={**INS, "texto": "sin menciones"})
    ana.post("/api/notas", json={**INS, "texto": "@beto", "menciones": ["u-beto"]})
    lista = ana.get("/api/notas", params=INS).json()
    assert [n["menciones"] for n in lista] == [[], [{"user_id": "u-beto", "nombre": "beto@obra.co"}]]


def test_editar_resincroniza_y_omitirlas_no_las_toca(tmp_path):
    app, alm = _app(tmp_path)
    ana = _como(app, ANA)
    nid = ana.post("/api/notas", json={**INS, "texto": "@beto", "menciones": ["u-beto"]}).json()["id"]
    beto = _como(app, BETO)
    beto.post(f"/api/menciones/{nid}/leida")
    ana = _como(app, ANA)
    # PATCH sin `menciones`: solo cambia el texto; beto sigue mencionado y leído
    r = ana.patch(f"/api/notas/{nid}", json={"texto": "@beto corregido"})
    assert r.json()["menciones"] == [{"user_id": "u-beto", "nombre": "beto@obra.co"}]
    assert alm.notas.contar_sin_leer("u-beto") == 0
    # PATCH con lista vacía: se van todas
    assert ana.patch(f"/api/notas/{nid}", json={"texto": "nadie", "menciones": []}).json()["menciones"] == []
    assert _como(app, BETO).get("/api/menciones").json() == []


def test_marcar_leida_y_todas(tmp_path):
    app, _ = _app(tmp_path)
    ana = _como(app, ANA)
    a = ana.post("/api/notas", json={**INS, "texto": "1", "menciones": ["u-beto"]}).json()["id"]
    ana.post("/api/notas", json={**INS, "texto": "2", "menciones": ["u-beto"]})
    beto = _como(app, BETO)
    assert beto.post(f"/api/menciones/{a}/leida").json() == {"leida": a}
    assert beto.get("/api/presencia").json()["menciones_sin_leer"] == 1
    assert beto.post("/api/menciones/leidas").json() == {"leidas": True}
    assert beto.get("/api/presencia").json()["menciones_sin_leer"] == 0
    assert all(m["leida"] for m in beto.get("/api/menciones").json())


def test_borrar_la_nota_saca_la_mencion(tmp_path):
    app, _ = _app(tmp_path)
    ana = _como(app, ANA)
    nid = ana.post("/api/notas", json={**INS, "texto": "x", "menciones": ["u-beto"]}).json()["id"]
    ana.delete(f"/api/notas/{nid}")
    beto = _como(app, BETO)
    assert beto.get("/api/presencia").json()["menciones_sin_leer"] == 0
    assert beto.get("/api/menciones").json() == []


def test_mencionables_solo_editor_y_sin_uno_mismo(tmp_path):
    app, _ = _app(tmp_path)
    assert _como(app, BETO).get("/api/usuarios/mencionables").status_code == 403
    r = _como(app, ANA).get("/api/usuarios/mencionables").json()
    assert r == [{"user_id": "u-beto", "nombre": "", "email": "beto@obra.co"}]   # sin Ana ni Caro (inactiva)


def test_presencia_no_se_cae_si_falla_el_conteo(tmp_path, monkeypatch):
    app, alm = _app(tmp_path)
    def boom(_uid):
        raise RuntimeError("base caída")
    monkeypatch.setattr(alm.notas, "contar_sin_leer", boom)
    r = _como(app, BETO).get("/api/presencia")
    assert r.status_code == 200 and r.json()["menciones_sin_leer"] is None
    assert r.json()["en_linea"][0]["email"] == "beto@obra.co"


def test_auditoria_de_crear_guarda_las_menciones(tmp_path):
    app, alm = _app(tmp_path)
    _como(app, ANA).post("/api/notas", json={**INS, "texto": "x", "menciones": ["u-beto"]})
    items, _ = alm.auditoria.listar(entidad_tipo="nota")
    assert items[0]["despues"]["menciones"] == ["u-beto"]
