"""El endpoint del chat de consulta."""
import pytest

from apu_tool.servicio import consulta as consulta_svc
from tests.chat_falso import AdvisorGuion, resp_texto
from tests.conftest import cliente
from tests.consulta_base import almacen_consulta

URL = "/api/consulta/chat"


@pytest.fixture()
def app_ids(tmp_path):
    from apu_tool.servicio.app import create_app
    alm, ids = almacen_consulta(tmp_path)
    return create_app(almacen=alm), ids


def _con_guion(monkeypatch, respuestas):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    a = AdvisorGuion(respuestas)
    monkeypatch.setattr(consulta_svc, "ApuAdvisor", lambda: a)
    return a


def test_rol_consulta_recibe_las_cifras_resueltas(app_ids, monkeypatch):
    app, ids = app_ids
    _con_guion(monkeypatch, [resp_texto(
        f"El tubo vale {{{{precio:insumo:{ids['insumo_tubo']}}}}}.")])
    r = cliente(app, "consulta").post(URL, json={
        "mensajes": [{"rol": "usuario", "texto": "cuanto vale la tuberia de 6"}]})
    assert r.status_code == 200
    assert "event: respuesta" in r.text
    assert "$35.000" in r.text                          # texto con la cifra
    assert "{{precio:insumo:" in r.text                 # y el crudo para el historial


def test_mensaje_con_dinero_bloquea(app_ids, monkeypatch):
    app, _ = app_ids
    a = _con_guion(monkeypatch, [])
    r = cliente(app, "consulta").post(URL, json={
        "mensajes": [{"rol": "usuario", "texto": "mas de $50.000"}]})
    assert "event: bloqueado" in r.text and a.llamadas == []


def test_sin_credencial_es_503(app_ids, monkeypatch):
    app, _ = app_ids
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = cliente(app, "consulta").post(URL, json={
        "mensajes": [{"rol": "usuario", "texto": "hola"}]})
    assert r.status_code == 503


def test_cuerpo_absurdo_es_422(app_ids, monkeypatch):
    app, _ = app_ids
    _con_guion(monkeypatch, [])
    r = cliente(app, "consulta").post(URL, json={
        "mensajes": [{"rol": "usuario", "texto": "x"}] * 101})
    assert r.status_code == 422
