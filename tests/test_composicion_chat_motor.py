"""El chat de composición: herramientas y bucle. El SDK se sustituye."""
import json

import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.dominio.composicion_chat import Herramientas
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo, LicitacionItem

ITEM = LicitacionItem("1.3", "EXCAVACION MANUAL EN MATERIAL COMUN", "M3", 120.0,
                      180000.0, "DIURNO")


@pytest.fixture()
def alm(tmp_path):
    a = Almacen(tmp_path / "precios.db", tmp_path / "apus.db",
                tmp_path / "corridas.db")
    a.reset()
    a.precios.insert_insumos([
        Insumo("4279", "CUADRILLA OFICIAL MAS AYUDANTES", "HR", "SUELDOS Y JORNALES",
               40000, "PRECIO IDU"),
        Insumo("6092", "HERRAMIENTA MENOR", "GLB", "EQ", 2000, "PRECIO IDU"),
        Insumo("7001", "OFICIAL SOLDADOR CERTIFICADO", "HR", "SUELDOS Y JORNALES",
               55000, "COSTO INTERNO"),
        Insumo("7002", "SOLDADOR VIEJO", "HR", "SUELDOS Y JORNALES", 50000,
               "COSTO INTERNO"),
    ])
    oculto = a.precios.search_insumos("SOLDADOR VIEJO")[0]
    a.precios.set_oculto(oculto.id, True)
    a.apus.insert_apus([
        Apu("A1", "EXCAVACION MANUAL COMUN", "M3", "DIURNO", "EXCAVACIONES")])
    a.apus.insert_components([
        ApuComponent("A1", "DIURNO", "4279", "CUADRILLA", "HR", 0.62, 40000),
        ApuComponent("A1", "DIURNO", "6092", "HERRAMIENTA MENOR", "GLB", 1.0, 2000),
    ])
    return a


# --- herramientas ------------------------------------------------------------
def test_buscar_insumos_trae_visibles_sin_precio(alm):
    r = Herramientas(alm, "DIURNO").ejecutar("buscar_insumos", {"texto": "soldador"})
    codigos = [i["insumo_codigo"] for i in r["insumos"]]
    assert codigos == ["7001"]                       # 7002 está oculto
    texto = json.dumps(r)
    assert "55000" not in texto and "COSTO INTERNO" not in texto


def test_buscar_insumos_ordena_por_parecido_y_trae_lo_observado(alm):
    r = Herramientas(alm, "DIURNO").ejecutar("buscar_insumos",
                                             {"texto": "cuadrilla oficial"})
    assert r["insumos"][0]["insumo_codigo"] == "4279"
    assert r["insumos"][0]["rendimientos_observados"]["mediana"] == 0.62


def test_buscar_apus_trae_la_composicion_sin_precio(alm):
    r = Herramientas(alm, "DIURNO").ejecutar("buscar_apus",
                                             {"texto": "excavacion manual"})
    assert r["apus"][0]["codigo"] == "A1"
    assert {c["insumo_codigo"] for c in r["apus"][0]["componentes"]} == {"4279", "6092"}
    assert "40000" not in json.dumps(r)


def test_herramienta_desconocida_devuelve_error_y_no_revienta(alm):
    r = Herramientas(alm, "DIURNO").ejecutar("borrar_todo", {"texto": "x"})
    assert "error" in r


def test_pocos_resultados_traen_el_total_y_una_sugerencia(alm):
    """Smoke real: buscó «tuberia pvc sanitaria 12», la palabra «sanitaria» dejó
    afuera los tubos de 12" que SÍ estaban, y el agente no reformuló."""
    r = Herramientas(alm, "DIURNO").ejecutar("buscar_insumos", {"texto": "soldador"})
    assert r["encontrados"] == 1
    assert "menos palabras" in r["sugerencia"]
    nada = Herramientas(alm, "DIURNO").ejecutar("buscar_insumos",
                                                {"texto": "tuberia sanitaria 12"})
    assert nada["encontrados"] == 0 and "menos palabras" in nada["sugerencia"]


def test_con_resultados_suficientes_no_hay_sugerencia(alm, monkeypatch):
    insumo = alm.precios.list_insumos("cuadrilla", limit=1)[0][0]
    monkeypatch.setattr(alm.precios, "list_insumos",
                        lambda *a, **k: ([insumo] * 5, 40))
    r = Herramientas(alm, "DIURNO").ejecutar("buscar_insumos", {"texto": "cuadrilla"})
    assert r["encontrados"] == 40 and "sugerencia" not in r


def test_una_busqueda_sin_palabras_utiles_devuelve_vacio(alm):
    r = Herramientas(alm, "DIURNO").ejecutar("buscar_insumos", {"texto": "de la"})
    assert r["insumos"] == []


from apu_tool.dominio import privacy
from apu_tool.dominio.composicion_chat import MAX_HERRAMIENTAS, conversar
from tests.chat_falso import (
    AdvisorGuion, componente, resp_final, resp_herramienta,
)

TABLA = [{"codigo": "4279", "tipo": "insumo", "funcion": "mano_de_obra",
          "rendimiento": 0.62, "origen": "copiado_de_antecedente"}]


def charla(*textos):
    """Historial alternado usuario/agente (el primero es del usuario)."""
    roles = ["usuario", "agente"]
    return [{"rol": roles[i % 2], "texto": t} for i, t in enumerate(textos)]


def correr(alm, advisor, mensajes, tabla=TABLA):
    return list(conversar(alm, ITEM, tabla, mensajes, advisor))


# --- candados antes de la IA --------------------------------------------------
@pytest.mark.parametrize("mensajes", [
    charla("agrega el cemento, cuesta $45.000"),
    charla("nos lo cotizaron a 45000", "Entendido.", "agrega un oficial"),
])
def test_un_monto_en_un_mensaje_del_usuario_bloquea_sin_llamar(alm, mensajes):
    a = AdvisorGuion([])
    evs = correr(alm, a, mensajes)
    assert [e for e, _ in evs] == ["bloqueado"]
    assert "IA no puede ver precios" in evs[0][1]["motivo"]
    assert a.llamadas == []


def test_un_mensaje_del_agente_con_cifras_se_omite_y_no_envenena_el_chat(alm):
    """Revisión del plan: una respuesta legítima del agente ("cambié el valor a
    0,62") disparaba el detector y bloqueaba todos los turnos siguientes, sin que la
    persona pudiera sacarla del hilo. Se reemplaza y el turno sigue."""
    a = AdvisorGuion([resp_final()])
    evs = correr(alm, a, charla("sube el oficial", "Listo, cambié el valor a 0,62.",
                                "ahora agrega un ayudante"))
    assert evs[-1][0] == "respuesta"
    enviados = json.dumps([m["content"] for m in a.llamadas[0]["mensajes"]
                           if isinstance(m["content"], str)], ensure_ascii=False)
    assert "0,62" not in enviados and "[mensaje omitido" in enviados


def test_sin_mensaje_final_del_usuario_es_error_sin_llamar(alm):
    a = AdvisorGuion([])
    evs = correr(alm, a, charla("hola", "Hola, ¿qué agrego?"))
    assert evs[0][0] == "error" and a.llamadas == []


# --- el bucle -------------------------------------------------------------------
def test_busca_y_responde_con_los_eventos_en_orden(alm):
    a = AdvisorGuion([
        resp_herramienta(("buscar_insumos", "soldador")),
        resp_final("Te propongo el soldador.",
                   [{"op": "agregar", "codigo": "7001",
                     "componente": componente("7001", 0.1, "mano_de_obra")}]),
    ])
    evs = correr(alm, a, charla("busca un soldador certificado"))
    assert [e for e, _ in evs] == ["pensando", "buscando", "pensando", "respuesta"]
    assert evs[1][1] == {"herramienta": "buscar_insumos", "consulta": "soldador"}
    resp = evs[-1][1]
    assert resp["texto"] == "Te propongo el soldador."
    assert resp["cambios"][0]["codigo"] == "7001"
    assert resp["cambios"][0]["componente"]["rendimiento"] == 0.1
    assert resp["catalogo"]["7001"]["nombre"] == "OFICIAL SOLDADOR CERTIFICADO"
    assert resp["prompt_version"] == "chat/v4" and resp["modelo"] == "falso"
    # la segunda vuelta lleva el resultado de la herramienta, sin precios
    resultado = a.llamadas[1]["mensajes"][-1]["content"][0]
    assert resultado["type"] == "tool_result" and resultado["tool_use_id"] == "t0"
    assert "OFICIAL SOLDADOR" in resultado["content"]
    assert "55000" not in resultado["content"]


def test_el_contexto_lleva_la_tabla_y_no_el_contractual(alm):
    a = AdvisorGuion([resp_final()])
    correr(alm, a, charla("¿qué le falta?"))
    ultimo = a.llamadas[0]["mensajes"][-1]
    contexto, pregunta = ultimo["content"][0]["text"], ultimo["content"][1]["text"]
    assert "CUADRILLA OFICIAL MAS AYUDANTES" in contexto     # nombre del catálogo
    assert "180000" not in contexto
    assert pregunta == "¿qué le falta?"


def test_el_historial_viaja_como_turnos_y_se_acota(alm):
    textos = [f"mensaje {i}" for i in range(25)]          # 25: termina en usuario
    a = AdvisorGuion([resp_final()])
    correr(alm, a, charla(*textos))
    enviados = a.llamadas[0]["mensajes"]
    assert len(enviados) <= 20
    assert enviados[0]["role"] == "user"                   # nunca arranca en el agente


def test_respeta_el_tope_de_busquedas(alm):
    guion = [resp_herramienta(("buscar_insumos", f"q{i}"), prefijo=f"v{i}-")
             for i in range(MAX_HERRAMIENTAS + 1)]
    a = AdvisorGuion(guion + [resp_final()])
    evs = correr(alm, a, charla("busca de todo"))
    assert [c["con_herramientas"] for c in a.llamadas] == (
        [True] * MAX_HERRAMIENTAS + [False, False])
    # la búsqueda que se pasó del tope no se ejecuta: vuelve como error
    pasada = a.llamadas[-1]["mensajes"][-1]["content"][0]
    assert pasada.get("is_error") is True
    assert evs[-1][0] == "respuesta"


def test_un_codigo_compartido_entra_con_el_nombre_que_dice_el_agente(alm):
    """Smoke 2026-11-19: el agente propuso «7406 SEÑAL VERTICAL» y la tabla mostró la
    REDUCCION. Ahora el alta elige por nombre, así que la señal entra como señal."""
    alm.precios.insert_insumos([
        Insumo("8001", "REDUCCION HD E.L. D=12 x 10", "UN", "ACCESORIOS", 1000,
               "PRECIO IDU"),
        Insumo("8001", "SEÑAL VERTICAL SR 90X30 INCLUYE POSTE", "UN", "SEÑALIZACION",
               2000, "PRECIO IDU"),
    ])
    a = AdvisorGuion([resp_final("Te agrego la señal.", [
        {"op": "agregar", "codigo": "8001", "nombre": "SEÑAL VERTICAL SR 90X30 INCLUYE POSTE",
         "componente": componente("8001")}])])
    resp = correr(alm, a, charla("agrega la señal"))[-1][1]
    (c,) = resp["cambios"]
    assert c["componente"]["nombre"] == "SEÑAL VERTICAL SR 90X30 INCLUYE POSTE"
    assert resp["catalogo"]["8001"]["nombre"] == "SEÑAL VERTICAL SR 90X30 INCLUYE POSTE"
    assert resp["descartados"] == []


def test_el_nombre_guardado_es_el_del_catalogo_no_el_del_agente(alm):
    alm.precios.insert_insumos([
        Insumo("8001", "REDUCCION HD E.L. D=12 x 10", "UN", "ACCESORIOS", 1000,
               "PRECIO IDU"),
        Insumo("8001", "SEÑAL VERTICAL SR 90X30 INCLUYE POSTE", "UN", "SEÑALIZACION",
               2000, "PRECIO IDU"),
    ])
    a = AdvisorGuion([resp_final("Te agrego la reducción.", [
        {"op": "agregar", "codigo": "8001", "nombre": "REDUCCION HD E.L. D=12\" x 10\"",
         "componente": componente("8001")}])])
    resp = correr(alm, a, charla("agrega la reducción"))[-1][1]
    assert resp["cambios"][0]["componente"]["nombre"] == "REDUCCION HD E.L. D=12 x 10"


def test_un_codigo_compartido_sin_nombre_entra_y_lo_escoge_el_ingeniero(alm):
    alm.precios.insert_insumos([
        Insumo("8001", "REDUCCION HD E.L. D=12 x 10", "UN", "ACCESORIOS", 1000,
               "PRECIO IDU"),
        Insumo("8001", "SEÑAL VERTICAL SR 90X30 INCLUYE POSTE", "UN", "SEÑALIZACION",
               2000, "PRECIO IDU"),
    ])
    a = AdvisorGuion([resp_final("Ahí va.", [
        {"op": "agregar", "codigo": "8001", "componente": componente("8001")}])])
    resp = correr(alm, a, charla("agrega el 8001"))[-1][1]
    (c,) = resp["cambios"]
    assert c["componente"]["nombre"] == ""
    assert len(resp["catalogo"]["8001"]["opciones"]) == 2
    assert "precio" not in str(resp["catalogo"]["8001"])


def test_descarta_codigos_inexistentes_y_ocultos(alm):
    a = AdvisorGuion([resp_final("Ahí van.", [
        {"op": "agregar", "codigo": "INVENTADO", "componente": componente("INVENTADO")},
        {"op": "agregar", "codigo": "7002", "componente": componente("7002")},
        {"op": "agregar", "codigo": "6092", "componente": componente("6092")},
    ])])
    resp = correr(alm, a, charla("agrega cosas"))[-1][1]
    assert [c["codigo"] for c in resp["cambios"]] == ["6092"]
    assert {d["codigo"] for d in resp["descartados"]} == {"INVENTADO", "7002"}


def test_quitar_no_lleva_componente_y_modificar_si(alm):
    a = AdvisorGuion([resp_final("Ok.", [
        {"op": "quitar", "codigo": "4279", "componente": None},
        {"op": "modificar", "codigo": "6092", "componente": componente("6092", 2.0)},
        {"op": "modificar", "codigo": "6092", "componente": None},
    ])])
    resp = correr(alm, a, charla("cambia"))[-1][1]
    assert resp["cambios"][0] == {"op": "quitar", "codigo": "4279", "componente": None}
    assert resp["cambios"][1]["componente"]["rendimiento"] == 2.0
    assert len(resp["cambios"]) == 2 and resp["descartados"][0]["codigo"] == "6092"


def test_una_respuesta_ilegible_es_error_para_reintentar(alm):
    evs = correr(alm, AdvisorGuion([resp_final(crudo="{no es json")]), charla("x"))
    assert evs[-1][0] == "error"


def test_una_negativa_del_modelo_es_error(alm):
    evs = correr(alm, AdvisorGuion([resp_final(stop_reason="refusal")]), charla("x"))
    assert evs[-1][0] == "error"


def test_sin_credencial_es_un_evento_error(alm):
    a = AdvisorGuion([])
    a.enabled = False
    evs = correr(alm, a, charla("x"))
    assert evs[-1] == ("error", {"detail":
                       "Conversar con el agente necesita ANTHROPIC_API_KEY en el servidor."})


def test_un_fallo_de_red_es_error_y_no_tumba_el_stream(alm):
    class Caido(AdvisorGuion):
        def _pedir_chat_al_sdk(self, mensajes, con_herramientas):
            raise TimeoutError("se cayó")
    evs = correr(alm, Caido([]), charla("x"))
    assert evs[-1][0] == "error"
    assert "vuelve a intentar" in evs[-1][1]["detail"]


def test_la_privacy_violation_sube(alm, monkeypatch):
    monkeypatch.setattr(privacy, "payload_chat", lambda *a, **k: {"precio": 1})
    with pytest.raises(privacy.PrivacyViolation):
        correr(alm, AdvisorGuion([resp_final()]), charla("x"))


def test_la_privacy_violation_dentro_del_bucle_sube(alm, monkeypatch):
    """Parchear `payload_chat` (arriba) corre ANTES del `try`: no protege el
    `except PrivacyViolation: raise` del bucle. Este sí: la herramienta devuelve un
    campo monetario y `safe_json` tiene que reventar, no convertirse en `error`."""
    monkeypatch.setattr(privacy, "insumo_encontrado_to_dict",
                        lambda *a, **k: {"precio": 1})
    a = AdvisorGuion([resp_herramienta(("buscar_insumos", "soldador")), resp_final()])
    with pytest.raises(privacy.PrivacyViolation):
        correr(alm, a, charla("busca un soldador"))


def test_un_alta_con_homonimo_oculto_entra_si_nombra_el_visible(alm):
    alm.precios.insert_insumos([
        Insumo("8000", "NOMBRE VIEJO OCULTO", "UN", "EQ", 10, "COSTO INTERNO"),
        Insumo("8000", "NOMBRE VISIBLE", "UN", "EQ", 10, "COSTO INTERNO"),
    ])
    alm.precios.set_oculto(alm.precios.search_insumos("NOMBRE VIEJO OCULTO")[0].id, True)
    a = AdvisorGuion([resp_final("Ahí va.", [
        {"op": "agregar", "codigo": "8000", "nombre": "NOMBRE VISIBLE",
         "componente": componente("8000")}])])
    resp = correr(alm, a, charla("agrega el 8000"))[-1][1]
    assert resp["cambios"][0]["componente"]["nombre"] == "NOMBRE VISIBLE"


def test_un_alta_que_nombra_el_oculto_se_descarta(alm):
    alm.precios.insert_insumos([
        Insumo("8000", "NOMBRE VIEJO OCULTO", "UN", "EQ", 10, "COSTO INTERNO"),
        Insumo("8000", "NOMBRE VISIBLE", "UN", "EQ", 10, "COSTO INTERNO"),
    ])
    alm.precios.set_oculto(alm.precios.search_insumos("NOMBRE VIEJO OCULTO")[0].id, True)
    a = AdvisorGuion([resp_final("Ahí va.", [
        {"op": "agregar", "codigo": "8000", "nombre": "NOMBRE VIEJO OCULTO",
         "componente": componente("8000")}])])
    resp = correr(alm, a, charla("agrega el 8000"))[-1][1]
    assert resp["cambios"] == [] and "oculto" in resp["descartados"][0]["motivo"]


def test_la_respuesta_consulta_el_catalogo_una_sola_vez(alm, monkeypatch):
    """UNA consulta por respuesta, no una por cambio. Se llama a `_respuesta` directo
    para no contar la consulta del contexto de la mesa."""
    from apu_tool.dominio import composicion_chat
    llamadas = []
    original = alm.precios.get_candidatos_bulk
    monkeypatch.setattr(alm.precios, "get_candidatos_bulk",
                        lambda cods, *a, **k: llamadas.append(list(cods)) or original(cods, *a, **k))
    composicion_chat._respuesta(alm, {"texto": "Ok.", "cambios": [
        {"op": "agregar", "codigo": "6092", "componente": componente("6092")},
        {"op": "agregar", "codigo": "6092", "componente": componente("6092", 2.0)},
    ]}, "m")
    assert llamadas == [["6092"]]
