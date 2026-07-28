# tests/test_api_listas.py
"""API de listas de precios: leer cualquiera, crear/renombrar solo editor, Principal intocable."""
import sqlite3

from apu_tool.datos.almacen import Almacen
from apu_tool.servicio.app import create_app
from tests.conftest import cliente


def _cli(tmp_path, rol="editor"):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return cliente(create_app(almacen=alm), rol=rol), alm


def test_listar_devuelve_principal(tmp_path):
    cli, _ = _cli(tmp_path, rol="consulta")
    r = cli.get("/api/listas-precios")
    assert r.status_code == 200
    assert [(l["id"], l["nombre"]) for l in r.json()] == [(1, "Principal")]


def test_crear_lista_como_editor(tmp_path):
    cli, _ = _cli(tmp_path)
    r = cli.post("/api/listas-precios", json={"nombre": "NP Calle 13"})
    assert r.status_code == 200
    assert r.json()["nombre"] == "NP Calle 13" and r.json()["id"] != 1


def test_crear_lista_duplicada_da_400(tmp_path):
    cli, _ = _cli(tmp_path)
    cli.post("/api/listas-precios", json={"nombre": "NP Calle 13"})
    assert cli.post("/api/listas-precios",
                    json={"nombre": "np calle 13"}).status_code == 400


def test_crear_lista_vacia_da_400(tmp_path):
    cli, _ = _cli(tmp_path)
    assert cli.post("/api/listas-precios", json={"nombre": "  "}).status_code == 400


def test_crear_lista_como_consulta_da_403(tmp_path):
    cli, _ = _cli(tmp_path, rol="consulta")
    assert cli.post("/api/listas-precios",
                    json={"nombre": "NP Calle 13"}).status_code == 403


def test_renombrar_lista(tmp_path):
    cli, _ = _cli(tmp_path)
    lid = cli.post("/api/listas-precios", json={"nombre": "NP A"}).json()["id"]
    r = cli.patch(f"/api/listas-precios/{lid}", json={"nombre": "NP A - Acta 2"})
    assert r.status_code == 200 and r.json()["nombre"] == "NP A - Acta 2"


def test_renombrar_principal_da_400(tmp_path):
    cli, _ = _cli(tmp_path)
    assert cli.patch("/api/listas-precios/1", json={"nombre": "Otra"}).status_code == 400


def test_renombrar_inexistente_da_400(tmp_path):
    cli, _ = _cli(tmp_path)
    assert cli.patch("/api/listas-precios/999", json={"nombre": "X"}).status_code == 400


def test_no_existe_delete(tmp_path):
    # Borrar una lista dejaría corridas huérfanas de su tarifa (no hay FK entre bases).
    cli, _ = _cli(tmp_path)
    assert cli.delete("/api/listas-precios/1").status_code == 405


def test_auditoria_registra_la_creacion(tmp_path):
    cli, _ = _cli(tmp_path, rol="admin")
    cli.post("/api/listas-precios", json={"nombre": "NP Calle 13"})
    acciones = [e["accion"] for e in cli.get("/api/auditoria").json()["items"]]
    assert "lista.crear" in acciones


def test_choque_de_carrera_en_crear_da_400_no_500(tmp_path, monkeypatch):
    """La detección de duplicados de la capa de datos es SELECT + comparación en
    Python (TOCTOU): con varios workers, dos POST simultáneos con el mismo nombre
    pueden pasar ambos el chequeo y solo el segundo INSERT choca contra la UNIQUE
    de la tabla. Como no podemos forzar una carrera real en un test síncrono,
    forzamos el mismo síntoma: `crear_lista` de la capa de datos lanza el
    IntegrityError crudo que dispararía ese segundo INSERT. El endpoint debe
    traducirlo a 400 con mensaje en español, no dejarlo escapar como 500."""
    cli, alm = _cli(tmp_path)

    def _choque(*a, **k):
        raise sqlite3.IntegrityError("UNIQUE constraint failed: lista_precios.nombre")

    monkeypatch.setattr(alm.precios, "crear_lista", _choque)
    r = cli.post("/api/listas-precios", json={"nombre": "NP Calle 13"})
    assert r.status_code == 400
    assert "NP Calle 13" in r.json()["detail"]


def test_choque_de_carrera_en_renombrar_da_400_no_500(tmp_path, monkeypatch):
    """Mismo TOCTOU que en crear, pero en renombrar_lista (UPDATE en vez de INSERT)."""
    cli, alm = _cli(tmp_path)
    lid = cli.post("/api/listas-precios", json={"nombre": "NP A"}).json()["id"]

    def _choque(*a, **k):
        raise sqlite3.IntegrityError("UNIQUE constraint failed: lista_precios.nombre")

    monkeypatch.setattr(alm.precios, "renombrar_lista", _choque)
    r = cli.patch(f"/api/listas-precios/{lid}", json={"nombre": "NP B"})
    assert r.status_code == 400
    assert "NP B" in r.json()["detail"]
