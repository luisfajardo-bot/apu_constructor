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
