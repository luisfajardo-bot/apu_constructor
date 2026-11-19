"""El chat de la mesa: el PUT con instrucción, la mesa vacía y el endpoint SSE."""
from apu_tool import config
from apu_tool.servicio import composicion as composicion_svc
from tests.chat_falso import AdvisorGuion, componente, resp_final
from tests.conftest import cliente
from tests.test_api_composicion import (  # noqa: F401  (fixtures reusadas)
    COMPONENTES, _sembrar, app_alm, corrida,
)

URL = "/api/corridas/{cid}/composicion/1"


# --- PUT con instrucción -------------------------------------------------------
def test_put_con_instruccion_deja_el_rastro_del_chat(app_alm, corrida):
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    r = cliente(app, "editor").put(URL.format(cid=corrida), json={
        "version_base": 1, "componentes": COMPONENTES,
        "instruccion": "agrega un oficial"})
    assert r.status_code == 200
    v = alm.composiciones.vigente(corrida, 1)
    assert (v.version, v.estado) == (2, "editada")
    assert v.motivo == "chat: agrega un oficial"
    assert v.prompt_version == "chat/v1"
    assert v.modelo == config.AI_MODEL


def test_put_sin_instruccion_se_comporta_como_siempre(app_alm, corrida):
    """Regresión: la edición a mano hereda modelo y prompt de la generación."""
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    r = cliente(app, "editor").put(URL.format(cid=corrida), json={
        "version_base": 1, "componentes": COMPONENTES})
    assert r.status_code == 200
    v = alm.composiciones.vigente(corrida, 1)
    assert v.motivo is None
    assert (v.modelo, v.prompt_version) == ("falso", "composicion/v4")


def test_put_con_dinero_en_la_instruccion_es_422_y_no_escribe(app_alm, corrida):
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    r = cliente(app, "editor").put(URL.format(cid=corrida), json={
        "version_base": 1, "componentes": COMPONENTES,
        "instruccion": "pon el cemento a $45.000"})
    assert r.status_code == 422
    assert "IA no puede ver precios" in r.json()["detail"]
    assert len(alm.composiciones.historial(corrida, 1)) == 1


# --- mesa vacía ------------------------------------------------------------------
def test_mesa_vacia_el_primer_put_crea_la_version_1(app_alm, corrida):
    app, alm = app_alm
    r = cliente(app, "editor").put(URL.format(cid=corrida), json={
        "version_base": 0, "componentes": COMPONENTES,
        "instruccion": "arma una cuadrilla"})
    assert r.status_code == 200
    v = alm.composiciones.vigente(corrida, 1)
    assert (v.version, v.estado) == (1, "editada")
    assert v.antecedentes == {"codigos_permitidos": ["4279"], "apus_referencia": []}
    assert v.actividad["descripcion"] == alm.corridas.get_item(corrida, 1).item.descripcion


def test_mesa_vacia_con_version_base_distinta_de_0_es_404(app_alm, corrida):
    app, _ = app_alm
    r = cliente(app, "editor").put(URL.format(cid=corrida), json={
        "version_base": 1, "componentes": COMPONENTES})
    assert r.status_code == 404


def test_mesa_vacia_sobre_un_expediente_de_otra_actividad_sigue_la_numeracion(
        app_alm, corrida):
    """El seq se reusa: la versión nueva va después de la del expediente ajeno."""
    app, alm = app_alm
    _sembrar(alm, corrida, version=1, descripcion="OTRA ACTIVIDAD")
    r = cliente(app, "editor").put(URL.format(cid=corrida), json={
        "version_base": 0, "componentes": COMPONENTES})
    assert r.status_code == 200
    assert alm.composiciones.vigente(corrida, 1).version == 2


# --- POST .../chat (SSE) -----------------------------------------------------
CHAT = "/api/corridas/{cid}/composicion/{seq}/chat"
CUERPO = {"mensajes": [{"rol": "usuario", "texto": "agrega herramienta menor"}],
          "componentes": COMPONENTES}


def _con_guion(monkeypatch, respuestas):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    a = AdvisorGuion(respuestas)
    monkeypatch.setattr(composicion_svc, "ApuAdvisor", lambda: a)
    return a


def test_chat_responde_por_sse_y_no_persiste_nada(app_alm, corrida, monkeypatch):
    app, alm = app_alm
    _con_guion(monkeypatch, [resp_final("Te propongo esto.", [
        {"op": "agregar", "codigo": "6092", "componente": componente("6092")}])])
    r = cliente(app, "editor").post(CHAT.format(cid=corrida, seq=1), json=CUERPO)
    assert r.status_code == 200
    assert "event: respuesta" in r.text and "6092" in r.text
    assert alm.composiciones.historial(corrida, 1) == []


def test_chat_con_dinero_responde_bloqueado_sin_llamar(app_alm, corrida, monkeypatch):
    app, _ = app_alm
    a = _con_guion(monkeypatch, [])
    cuerpo = dict(CUERPO, mensajes=[{"rol": "usuario", "texto": "cuesta $45.000"}])
    r = cliente(app, "editor").post(CHAT.format(cid=corrida, seq=1), json=cuerpo)
    assert "event: bloqueado" in r.text
    assert a.llamadas == []


def test_chat_con_rol_consulta_es_403(app_alm, corrida, monkeypatch):
    app, _ = app_alm
    _con_guion(monkeypatch, [])
    r = cliente(app, "consulta").post(CHAT.format(cid=corrida, seq=1), json=CUERPO)
    assert r.status_code == 403


def test_chat_sin_credencial_es_503(app_alm, corrida, monkeypatch):
    app, _ = app_alm
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = cliente(app, "editor").post(CHAT.format(cid=corrida, seq=1), json=CUERPO)
    assert r.status_code == 503


def test_chat_en_corrida_congelada_es_409(app_alm, corrida, monkeypatch):
    app, alm = app_alm
    _con_guion(monkeypatch, [])
    alm.corridas.set_modo(corrida, "congelada")
    r = cliente(app, "editor").post(CHAT.format(cid=corrida, seq=1), json=CUERPO)
    assert r.status_code == 409


def test_chat_de_una_fila_inexistente_es_404(app_alm, corrida, monkeypatch):
    app, _ = app_alm
    _con_guion(monkeypatch, [])
    r = cliente(app, "editor").post(CHAT.format(cid=corrida, seq=99), json=CUERPO)
    assert r.status_code == 404


def test_la_vista_dice_si_la_ia_esta_disponible(app_alm, corrida, monkeypatch):
    app, _ = app_alm
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    v = cliente(app, "consulta").get(URL.format(cid=corrida)).json()
    assert v["ia_disponible"] is True
