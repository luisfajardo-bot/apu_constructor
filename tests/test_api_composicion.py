"""Los cinco endpoints de la composición: roles, códigos de error e idempotencia."""
import pytest

from apu_tool.nucleo.models import (
    Apu, ApuComponent, ComposicionRow, CorridaItemRow, CorridaMeta, Insumo,
    LicitacionItem,
)
from tests.conftest import cliente


@pytest.fixture()
def app_alm(tmp_path):
    from apu_tool.datos.almacen import Almacen
    from apu_tool.servicio.app import create_app
    alm = Almacen(tmp_path / "precios.db", tmp_path / "apus.db",
                  tmp_path / "corridas.db")
    alm.init_schema()
    alm.reset()
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo("4279", "CUADRILLA", "HR", "MO", 40000, "PRECIO IDU"),
        Insumo("6092", "HERRAMIENTA MENOR", "GLB", "EQ", 2000, "PRECIO IDU"),
    ])
    alm.apus.insert_apus([Apu("A1", "EXCAVACION MANUAL", "M3", "DIURNO",
                              "EXCAVACIONES")])
    alm.apus.insert_components([
        ApuComponent("A1", "DIURNO", "4279", "CUADRILLA", "HR", 0.62, 40000)])
    app = create_app(almacen=alm)
    return app, alm


DESCRIPCION = "EXCAVACION MANUAL EN MATERIAL COMUN"


@pytest.fixture()
def corrida(app_alm):
    """Una corrida con una fila SIN APU en seq 1."""
    _, alm = app_alm
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-09-10T10:00:00", archivo="x.xlsx",
        turno_def="DIURNO", use_ai=None, estado="en_revision"))
    item = LicitacionItem("1.3", DESCRIPCION, "M3", 120.0, 180000.0, "DIURNO")
    alm.corridas.guardar_items(cid, [CorridaItemRow(
        seq=1, item=item, status="new", apu_codigo=None,
        apu_nombre="(sin base — armar manual)", unidad="M3", shift="DIURNO",
        origen="manual", confianza=0.0, explicacion="", componentes=[],
        candidatos=[])])
    return cid


COMPONENTES = [{"codigo": "4279", "tipo": "insumo", "funcion": "mano_de_obra",
                "rendimiento": 0.62, "origen": "copiado_de_antecedente",
                "referencias": [{"apu_codigo": "A1", "turno": "DIURNO"}],
                "hipotesis": {}, "calculo": None, "justificacion": "j",
                "nivel_evidencia": "alto", "ref_shift": ""}]


def _sembrar(alm, cid, *, version=1, estado="propuesta", valido=True,
             componentes=None, descripcion=DESCRIPCION):
    alm.composiciones.agregar(ComposicionRow(
        id=None, corrida_id=cid, seq=1, version=version, estado=estado,
        actividad={"item": "1.3", "descripcion": descripcion, "unidad": "M3",
                   "cantidad": 120.0, "shift": "DIURNO"},
        ficha=None,
        propuesta={"componentes": componentes or COMPONENTES, "supuestos": [],
                   "incertidumbre_declarada": 0.3, "justificacion": "g"},
        validacion={"valido": valido,
                    "errores": [] if valido else [
                        {"codigo": "PROPUESTA_VACIA", "mensaje": "x",
                         "componente": ""}],
                    "advertencias": [],
                    "metricas": {"superadas": 9, "totales": 9}},
        confianza="alta" if valido else "insuficiente", confianza_motivos=[],
        antecedentes={"codigos_permitidos": ["4279"],
                      "apus_referencia": [{"codigo": "A1", "turno": "DIURNO"}]},
        modelo="falso", prompt_version="composicion/v4", apu_codigo=None,
        apu_turno=None, autor="t@test.co", creada_en="2026-09-10T10:00:00",
        motivo=None))


# --- GET -------------------------------------------------------------------
def test_get_sin_composicion_devuelve_vacio(app_alm, corrida):
    app, _ = app_alm
    r = cliente(app, "consulta").get(f"/api/corridas/{corrida}/composicion/1")
    assert r.status_code == 200
    assert r.json() == {"vigente": None, "historial": [], "catalogo": {}}


def test_get_devuelve_la_vigente_y_el_historial(app_alm, corrida):
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    _sembrar(alm, corrida, version=2, estado="editada")
    d = cliente(app, "consulta").get(
        f"/api/corridas/{corrida}/composicion/1").json()
    assert d["vigente"]["version"] == 2
    assert len(d["historial"]) == 2


def test_get_de_una_fila_inexistente_es_404(app_alm, corrida):
    app, _ = app_alm
    assert cliente(app, "consulta").get(
        f"/api/corridas/{corrida}/composicion/99").status_code == 404


def test_un_expediente_de_otra_actividad_no_se_devuelve_como_vigente(app_alm,
                                                                     corrida):
    """El seq se reusa: borrar la última línea y agregar otra da el mismo número.
    El expediente de la actividad vieja no puede aparecer bajo la nueva."""
    app, alm = app_alm
    _sembrar(alm, corrida, descripcion="OTRA COSA QUE YA NO ESTA")
    d = cliente(app, "consulta").get(
        f"/api/corridas/{corrida}/composicion/1").json()
    assert d["vigente"] is None
    assert len(d["historial"]) == 1     # el historial no miente, se conserva


def test_la_respuesta_del_get_no_lleva_dinero(app_alm, corrida):
    from apu_tool.dominio import privacy
    app, alm = app_alm
    _sembrar(alm, corrida)
    privacy.assert_no_money(
        cliente(app, "consulta").get(
            f"/api/corridas/{corrida}/composicion/1").json())


# --- PUT (edición humana) --------------------------------------------------
def test_put_guarda_una_version_nueva_y_revalida(app_alm, corrida):
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    r = cliente(app, "editor").put(
        f"/api/corridas/{corrida}/composicion/1",
        json={"version_base": 1, "componentes": COMPONENTES})
    assert r.status_code == 200
    assert r.json()["vigente"]["version"] == 2
    assert r.json()["vigente"]["estado"] == "editada"


def test_put_con_una_version_vieja_es_409(app_alm, corrida):
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    _sembrar(alm, corrida, version=2, estado="editada")
    r = cliente(app, "editor").put(
        f"/api/corridas/{corrida}/composicion/1",
        json={"version_base": 1, "componentes": COMPONENTES})
    assert r.status_code == 409


def test_put_acepta_un_insumo_que_agrego_el_humano(app_alm, corrida):
    """La lista blanca frena al MODELO, no a una persona que elige del catálogo."""
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    nuevo = dict(COMPONENTES[0], codigo="6092", funcion="herramienta",
                 rendimiento=1.0, origen="supuesto_tecnico", referencias=[])
    r = cliente(app, "editor").put(
        f"/api/corridas/{corrida}/composicion/1",
        json={"version_base": 1, "componentes": COMPONENTES + [nuevo]})
    assert r.status_code == 200
    errores = r.json()["vigente"]["validacion"]["errores"]
    assert not [e for e in errores if e["codigo"] == "CODIGO_NO_AUTORIZADO"]


def test_put_rechaza_un_codigo_que_no_esta_en_el_catalogo(app_alm, corrida):
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    falso = dict(COMPONENTES[0], codigo="INVENTADO")
    r = cliente(app, "editor").put(
        f"/api/corridas/{corrida}/composicion/1",
        json={"version_base": 1, "componentes": [falso]})
    assert r.status_code == 200      # se guarda, pero inválida
    v = r.json()["vigente"]["validacion"]
    assert v["valido"] is False
    assert {"CODIGO_INEXISTENTE", "CODIGO_NO_AUTORIZADO"} & {
        e["codigo"] for e in v["errores"]}


def test_put_necesita_rol_editor(app_alm, corrida):
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    assert cliente(app, "consulta").put(
        f"/api/corridas/{corrida}/composicion/1",
        json={"version_base": 1, "componentes": COMPONENTES}).status_code == 403


# --- aprobar ---------------------------------------------------------------
APROBAR = {"version_base": 1, "codigo": "9001", "turno": "DIURNO",
           "nombre": "EXCAVACION MANUAL MATERIAL COMUN", "grupo": "EXCAVACIONES"}


def test_aprobar_crea_el_apu_por_autoria_y_lo_asigna_a_la_fila(app_alm, corrida):
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    r = cliente(app, "editor").post(
        f"/api/corridas/{corrida}/composicion/1/aprobar", json=APROBAR)
    assert r.status_code == 200
    assert alm.apus.get_apu("9001", "DIURNO") is not None
    assert alm.corridas.get_item(corrida, 1).apu_codigo == "9001"
    v = alm.composiciones.vigente(corrida, 1)
    assert v.estado == "aprobada" and v.apu_codigo == "9001"


def test_aprobar_dos_veces_no_crea_dos_apus(app_alm, corrida):
    """El doble clic lo frena el índice único, no un if."""
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    c = cliente(app, "editor")
    r1 = c.post(f"/api/corridas/{corrida}/composicion/1/aprobar", json=APROBAR)
    r2 = c.post(f"/api/corridas/{corrida}/composicion/1/aprobar", json=APROBAR)
    assert r1.status_code == 200
    assert r2.status_code == 409
    apus, _ = alm.apus.list_apus(q="9001")
    assert len(apus) == 1


def test_aprobar_con_errores_bloqueantes_es_422(app_alm, corrida):
    app, alm = app_alm
    _sembrar(alm, corrida, version=1, valido=False)
    assert cliente(app, "editor").post(
        f"/api/corridas/{corrida}/composicion/1/aprobar",
        json=APROBAR).status_code == 422


def test_aprobar_con_un_codigo_duplicado_sube_el_error_de_autoria(app_alm, corrida):
    """No se reimplementan las reglas de unicidad: son de autoria.py."""
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    r = cliente(app, "editor").post(
        f"/api/corridas/{corrida}/composicion/1/aprobar",
        json=dict(APROBAR, codigo="A1", nombre="EXCAVACION MANUAL"))
    assert r.status_code == 422


def test_aprobar_necesita_rol_editor(app_alm, corrida):
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    assert cliente(app, "consulta").post(
        f"/api/corridas/{corrida}/composicion/1/aprobar",
        json=APROBAR).status_code == 403


def test_no_se_aprueba_un_expediente_de_otra_actividad(app_alm, corrida):
    app, alm = app_alm
    _sembrar(alm, corrida, descripcion="OTRA COSA QUE YA NO ESTA")
    r = cliente(app, "editor").post(
        f"/api/corridas/{corrida}/composicion/1/aprobar", json=APROBAR)
    assert r.status_code in (404, 409)
    assert alm.apus.get_apu("9001", "DIURNO") is None


# --- rechazar --------------------------------------------------------------
def test_rechazar_escribe_una_version_y_no_toca_nada_mas(app_alm, corrida):
    app, alm = app_alm
    antes = alm.apus.counts()["apus"]
    _sembrar(alm, corrida, version=1)
    r = cliente(app, "editor").post(
        f"/api/corridas/{corrida}/composicion/1/rechazar",
        json={"version_base": 1, "motivo": "no aplica"})
    assert r.status_code == 200
    assert alm.composiciones.vigente(corrida, 1).estado == "rechazada"
    assert alm.corridas.get_item(corrida, 1).apu_codigo is None
    assert alm.apus.counts()["apus"] == antes


# --- generar (SSE) ---------------------------------------------------------
def test_generar_sin_credencial_es_503(app_alm, corrida, monkeypatch):
    app, _ = app_alm
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert cliente(app, "editor").post(
        f"/api/corridas/{corrida}/composicion/1/stream").status_code == 503


def test_generar_en_una_corrida_congelada_es_409(app_alm, corrida, monkeypatch):
    app, alm = app_alm
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    alm.corridas.set_modo(corrida, "congelada")
    assert cliente(app, "editor").post(
        f"/api/corridas/{corrida}/composicion/1/stream").status_code == 409


def test_generar_de_una_fila_inexistente_es_404(app_alm, corrida, monkeypatch):
    app, _ = app_alm
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert cliente(app, "editor").post(
        f"/api/corridas/{corrida}/composicion/99/stream").status_code == 404


# --- doble clic en los tres que escriben, y la corrida que se congela ------
def test_put_dos_veces_seguidas_es_409(app_alm, corrida):
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    c = cliente(app, "editor")
    cuerpo = {"version_base": 1, "componentes": COMPONENTES}
    r1 = c.put(f"/api/corridas/{corrida}/composicion/1", json=cuerpo)
    r2 = c.put(f"/api/corridas/{corrida}/composicion/1", json=cuerpo)
    assert (r1.status_code, r2.status_code) == (200, 409)
    assert len(alm.composiciones.historial(corrida, 1)) == 2


def test_rechazar_dos_veces_es_409(app_alm, corrida):
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    c = cliente(app, "editor")
    cuerpo = {"version_base": 1, "motivo": "no aplica"}
    r1 = c.post(f"/api/corridas/{corrida}/composicion/1/rechazar", json=cuerpo)
    r2 = c.post(f"/api/corridas/{corrida}/composicion/1/rechazar", json=cuerpo)
    assert (r1.status_code, r2.status_code) == (200, 409)
    assert len(alm.composiciones.historial(corrida, 1)) == 2


def test_congelar_entre_generar_y_aprobar_deja_la_aprobacion_en_409(app_alm,
                                                                    corrida):
    """La propuesta ya existe, pero la corrida es una foto: no entra ningún APU."""
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    alm.corridas.set_modo(corrida, "congelada")
    c = cliente(app, "editor")
    assert c.post(f"/api/corridas/{corrida}/composicion/1/aprobar",
                  json=APROBAR).status_code == 409
    assert c.put(f"/api/corridas/{corrida}/composicion/1",
                 json={"version_base": 1, "componentes": COMPONENTES}
                 ).status_code == 409
    assert c.post(f"/api/corridas/{corrida}/composicion/1/rechazar",
                  json={"version_base": 1}).status_code == 409
    assert alm.apus.get_apu("9001", "DIURNO") is None
    # Leer sí se puede: una corrida congelada se consulta, no se modifica.
    assert cliente(app, "consulta").get(
        f"/api/corridas/{corrida}/composicion/1").status_code == 200


def test_aprobar_audita_la_aprobacion_ademas_del_alta_del_apu(app_alm, corrida):
    """Dos eventos distintos a propósito: `apu.crear` es la biblioteca,
    `composicion.aprobar` es el agente (qué línea, qué versión, qué confianza)."""
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    assert cliente(app, "editor").post(
        f"/api/corridas/{corrida}/composicion/1/aprobar",
        json=APROBAR).status_code == 200
    acciones = {e["accion"] for e in alm.auditoria.listar(limit=50)[0]}
    assert {"apu.crear", "composicion.aprobar"} <= acciones


# --- la caché no es verdad, y la lista blanca solo crece -------------------
def test_aprobar_revalida_contra_el_estado_de_hoy(app_alm, corrida):
    """La validación guardada es caché de otro momento: entre generar y aprobar
    pueden borrar un insumo. La caché no es verdad."""
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    # El insumo de la propuesta deja de existir en el catálogo.
    alm.precios.reset()
    r = cliente(app, "editor").post(
        f"/api/corridas/{corrida}/composicion/1/aprobar", json=APROBAR)
    assert r.status_code == 422
    assert alm.apus.get_apu("9001", "DIURNO") is None


def test_el_put_no_pierde_la_lista_blanca_de_la_generacion(app_alm, corrida):
    """Un retrieve fresco puede dar una lista más chica y dejar sin autorizar un
    componente que el modelo propuso bien. La lista solo crece."""
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    alm.precios.reset()          # el catálogo cambió: un retrieve nuevo no trae 4279
    r = cliente(app, "editor").put(
        f"/api/corridas/{corrida}/composicion/1",
        json={"version_base": 1, "componentes": COMPONENTES})
    assert r.status_code == 200
    codigos = {e["codigo"] for e in r.json()["vigente"]["validacion"]["errores"]}
    assert "CODIGO_NO_AUTORIZADO" not in codigos


# --- los nombres del catálogo en la respuesta (no en la fila) --------------
def test_el_get_trae_los_nombres_del_catalogo(app_alm, corrida):
    """La mesa muestra códigos sin esto, y un código no se puede revisar."""
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    d = cliente(app, "consulta").get(
        f"/api/corridas/{corrida}/composicion/1").json()
    assert d["catalogo"]["4279"]["nombre"] == "CUADRILLA"
    assert d["catalogo"]["4279"]["unidad"] == "HR"


def test_el_catalogo_no_lleva_el_precio(app_alm, corrida):
    """`get_candidatos_bulk` devuelve Insumo, que tiene precio: se copia clave por
    clave, nunca el objeto entero."""
    from apu_tool.dominio import privacy
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    d = cliente(app, "consulta").get(
        f"/api/corridas/{corrida}/composicion/1").json()
    assert "precio" not in d["catalogo"]["4279"]
    privacy.assert_no_money(d)


def test_un_codigo_fuera_del_catalogo_no_aparece_en_el_mapa(app_alm, corrida):
    app, alm = app_alm
    _sembrar(alm, corrida, version=1,
             componentes=[dict(COMPONENTES[0], codigo="INVENTADO")])
    d = cliente(app, "consulta").get(
        f"/api/corridas/{corrida}/composicion/1").json()
    assert d["catalogo"] == {}


def test_guardar_una_edicion_no_pierde_los_nombres(app_alm, corrida):
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    d = cliente(app, "editor").put(
        f"/api/corridas/{corrida}/composicion/1",
        json={"version_base": 1, "componentes": COMPONENTES}).json()
    assert d["catalogo"]["4279"]["nombre"] == "CUADRILLA"


def test_aprobar_tambien_trae_el_catalogo(app_alm, corrida):
    """Los cuatro endpoints salen por `vista`: ninguno pierde los nombres."""
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    d = cliente(app, "editor").post(
        f"/api/corridas/{corrida}/composicion/1/aprobar", json=APROBAR).json()
    assert d["catalogo"]["4279"]["nombre"] == "CUADRILLA"


def test_rechazar_tambien_trae_el_catalogo(app_alm, corrida):
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    d = cliente(app, "editor").post(
        f"/api/corridas/{corrida}/composicion/1/rechazar",
        json={"version_base": 1, "motivo": "no aplica"}).json()
    assert d["catalogo"]["4279"]["nombre"] == "CUADRILLA"


# --- `rechazada` restringe; editar es la reapertura -----------------------
def test_una_composicion_rechazada_no_se_aprueba_de_una(app_alm, corrida):
    """`rechazada` restringe: para retomarla hay que editarla, y ese paso queda en
    el historial. Si no, el estado es decorativo."""
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    c = cliente(app, "editor")
    c.post(f"/api/corridas/{corrida}/composicion/1/rechazar",
           json={"version_base": 1, "motivo": "no aplica"})
    r = c.post(f"/api/corridas/{corrida}/composicion/1/aprobar",
               json=dict(APROBAR, version_base=2))
    assert r.status_code == 422
    assert alm.apus.get_apu("9001", "DIURNO") is None


def test_editar_una_rechazada_la_reabre(app_alm, corrida):
    """La vía de reapertura: editar y guardar da una versión `editada` aprobable."""
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    c = cliente(app, "editor")
    c.post(f"/api/corridas/{corrida}/composicion/1/rechazar",
           json={"version_base": 1, "motivo": "no aplica"})
    e = c.put(f"/api/corridas/{corrida}/composicion/1",
              json={"version_base": 2, "componentes": COMPONENTES})
    assert e.status_code == 200
    assert e.json()["vigente"]["estado"] == "editada"
    a = c.post(f"/api/corridas/{corrida}/composicion/1/aprobar",
               json=dict(APROBAR, version_base=3))
    assert a.status_code == 200
    assert alm.apus.get_apu("9001", "DIURNO") is not None
