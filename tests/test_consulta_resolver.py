"""El reemplazo de marcadores: el único punto del chat de consulta que toca dinero.
Las cifras se comparan contra las MISMAS funciones de la pantalla."""
import json
import logging

import pytest

from apu_tool.dominio.pricing import PricingEngine
from apu_tool.servicio import consulta
from apu_tool.servicio.consulta import NO_DISPONIBLE, SIN_PRECIO, pct, pesos, resolver
from apu_tool.servicio.corridas import vista_corrida
from apu_tool.nucleo.models import CorridaMeta
from tests.consulta_base import almacen_consulta


@pytest.fixture()
def base(tmp_path):
    return almacen_consulta(tmp_path)


def test_formatos():
    assert pesos(1234567) == "$1.234.567"
    assert pesos(-1500.5) == "$-1.500"             # Math.round de la web
    assert pesos(-2.5) == "$-2"
    assert pct(0.0625) == "6.3%"
    assert pct(0.1234) == "12.3%"                  # igual que la web
    assert pct(-0.0625) == "-6.3%"
    assert pct(0.1235) == "12.3%"                  # el binario exacto, como toFixed de JS


def test_llaves_mal_cerradas_no_pasan(base):
    alm, _ = base
    assert "{{" not in resolver(alm, "x {{costo:apu:4859|DIURNO}")


def test_marcador_con_mayusculas_igual_se_resuelve(base):
    alm, _ = base
    assert resolver(alm, "{{Costo:APU:A1|DIURNO}}") == "$22.000"


def test_tope_de_corridas_por_respuesta(base, monkeypatch):
    alm, ids = base
    monkeypatch.setattr(consulta, "MAX_CORRIDAS_POR_RESPUESTA", 1)
    texto = resolver(alm, f"{{{{costo:corrida:{ids['cali']}}}}} "
                          f"{{{{costo:corrida:{ids['calle13']}}}}}")
    assert texto.endswith(NO_DISPONIBLE) and not texto.startswith(NO_DISPONIBLE)


def test_precio_de_insumo(base):
    alm, ids = base
    assert resolver(alm, f"{{{{precio:insumo:{ids['insumo_tubo']}}}}}") == "$35.000"


def test_insumo_en_cero_dice_sin_precio_nunca_cero(base):
    alm, ids = base
    assert resolver(alm, f"{{{{precio:insumo:{ids['insumo_cero']}}}}}") == SIN_PRECIO


def test_costo_de_apu_es_el_del_motor(base):
    alm, _ = base
    _, total = PricingEngine(alm).cost_apu("A1", "DIURNO")
    assert resolver(alm, "{{costo:apu:A1|DIURNO}}") == pesos(total) == "$22.000"
    assert resolver(alm, "{{costo:apu:A1 N|NOCTURNO}}") == "$24.000"


def test_apu_con_componente_con_alerta_dice_revisar(base):
    alm, _ = base
    assert "revisar" in resolver(alm, "{{costo:apu:A3|DIURNO}}")


def test_totales_de_corrida_son_los_de_la_vista(base):
    alm, ids = base
    cid = ids["cali"]
    t = vista_corrida(alm, cid)["totales"]
    assert resolver(alm, f"{{{{contractual:corrida:{cid}}}}}") == pesos(t["contractual"])
    assert resolver(alm, f"{{{{costo:corrida:{cid}}}}}") == pesos(t["costo"])
    assert resolver(alm, f"{{{{diferencia:corrida:{cid}}}}}") == pesos(t["margen"])
    assert resolver(alm, f"{{{{margen:corrida:{cid}}}}}") == pct(t["margen_pct"])


def test_corrida_con_filas_sin_costear_es_parcial_menos_el_contractual(base):
    alm, ids = base
    cid = ids["calle13"]
    assert "parcial: 2 de 3 actividades costeadas" in resolver(
        alm, f"{{{{costo:corrida:{cid}}}}}")
    assert "parcial" not in resolver(alm, f"{{{{contractual:corrida:{cid}}}}}")


def test_capitulos(base):
    alm, ids = base
    cid = ids["calle13"]
    caps = {c["codigo"]: c for c in vista_corrida(alm, cid)["capitulos"]}
    assert resolver(alm, f"{{{{costo:capitulo:{cid}:1}}}}") == pesos(caps["1"]["costo"])
    assert resolver(alm, f"{{{{diferencia:capitulo:{cid}:2}}}}").startswith(
        pesos(caps["2"]["diferencia"]))
    assert "parcial: 1 de 2 actividades costeadas" in resolver(
        alm, f"{{{{costo:capitulo:{cid}:2}}}}")
    assert resolver(alm, f"{{{{contractual:capitulo:{cid}:2}}}}") == pesos(
        caps["2"]["contractual"])


@pytest.mark.parametrize("marcador", [
    "{{precio:corrida:1}}",          # campo que no va con ese tipo
    "{{costo:obra:1}}",              # tipo desconocido (queda crudo y _RESTO lo tapa)
    "{{precio:insumo:999999}}",      # id inexistente
    "{{precio:insumo:abc}}",         # id ilegible
    "{{costo:apu:NOEXISTE|DIURNO}}",
    "{{costo:corrida:999}}",
    "{{costo:capitulo:1:77}}",       # capítulo que la corrida no tiene
])
def test_marcador_invalido_no_adivina(base, marcador):
    alm, _ = base
    assert resolver(alm, marcador) == NO_DISPONIBLE


def test_corrida_a_medio_armar_es_parcial_en_todo(base, monkeypatch):
    alm, ids = base
    real = consulta.vista_corrida

    def armando(a, cid):
        v = real(a, cid)
        v["armado"] = {"hechos": 290, "total": 1939}
        return v
    monkeypatch.setattr(consulta, "vista_corrida", armando)
    for campo in ("contractual", "costo"):
        assert "parcial: armado 290 de 1939 actividades" in resolver(
            alm, f"{{{{{campo}:corrida:{ids['cali']}}}}}")


def test_una_vista_por_corrida_y_por_respuesta(base, monkeypatch):
    alm, ids = base
    llamadas = []
    real = consulta.vista_corrida
    monkeypatch.setattr(consulta, "vista_corrida",
                        lambda a, cid: llamadas.append(cid) or real(a, cid))
    cid = ids["calle13"]
    resolver(alm, f"{{{{costo:corrida:{cid}}}}} {{{{contractual:corrida:{cid}}}}} "
                  f"{{{{costo:capitulo:{cid}:1}}}}")
    assert llamadas == [cid]


def test_una_excepcion_no_tumba_la_respuesta(base, monkeypatch):
    alm, ids = base

    def revienta(a, cid):
        raise RuntimeError("boom")
    monkeypatch.setattr(consulta, "vista_corrida", revienta)
    texto = resolver(alm, f"Total: {{{{costo:corrida:{ids['cali']}}}}}.")
    assert texto == f"Total: {NO_DISPONIBLE}."


def test_el_texto_alrededor_no_se_toca(base):
    alm, _ = base
    assert resolver(alm, "Hola, sin cifras.") == "Hola, sin cifras."


def test_llaves_crudas_nunca_llegan_a_la_persona(base):
    alm, _ = base
    assert resolver(alm, "{{pesos:cop:1}}") == NO_DISPONIBLE


def test_bug_inesperado_queda_en_el_log(base, monkeypatch, caplog):
    alm, ids = base
    real = consulta.vista_corrida
    monkeypatch.setattr(consulta, "vista_corrida",
                        lambda a, cid: {k: v for k, v in real(a, cid).items()
                                        if k != "totales"})
    with caplog.at_level(logging.ERROR):
        assert resolver(alm, f"{{{{costo:corrida:{ids['cali']}}}}}") == NO_DISPONIBLE
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_corrida_que_falla_cuenta_para_el_tope_y_no_se_repite(base, monkeypatch):
    alm, ids = base
    llamadas = []

    def revienta(a, cid):
        llamadas.append(cid)
        raise RuntimeError("boom")
    monkeypatch.setattr(consulta, "vista_corrida", revienta)
    resolver(alm, " ".join(f"{{{{costo:corrida:{i}}}}}" for i in range(1, 21)))
    assert len(llamadas) <= consulta.MAX_CORRIDAS_POR_RESPUESTA
    llamadas.clear()
    resolver(alm, " ".join(["{{costo:corrida:7}}"] * 3))
    assert len(llamadas) == 1


def test_espacios_dentro_del_marcador(base):
    alm, ids = base
    assert resolver(alm, "{{ costo : apu : A1 | DIURNO }}") == "$22.000"
    cid = ids["calle13"]
    caps = {c["codigo"]: c for c in vista_corrida(alm, cid)["capitulos"]}
    assert resolver(alm, f"{{{{ costo : capitulo : {cid} : 1 }}}}") == pesos(
        caps["1"]["costo"])


def test_corrida_sin_filas_no_dice_cero(base):
    alm, _ = base
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-11-25T10:00:00", archivo="vacia.xlsx",
        turno_def="DIURNO", use_ai=None, estado="en_revision",
        carpeta_id=None, nombre="vacia"))
    assert resolver(alm, f"{{{{costo:corrida:{cid}}}}}") == "sin actividades"


# ------------------------------------------- corridas viejas del IDU (idu-f1/1)
def _origen(alm, cid, version):
    alm.corridas.set_origen(cid, json.dumps({"entidad": "IDU",
                                             "parser_version": version}))


def test_corrida_vieja_del_idu_dice_con_aiu_menos_en_el_costo(base):
    alm, ids = base
    cid = ids["cali"]
    _origen(alm, cid, "idu-f1/1")
    t = vista_corrida(alm, cid)["totales"]
    assert resolver(alm, f"{{{{contractual:corrida:{cid}}}}}") ==         pesos(t["contractual"]) + " (con AIU)"
    assert resolver(alm, f"{{{{diferencia:corrida:{cid}}}}}") ==         pesos(t["margen"]) + " (con AIU)"
    assert resolver(alm, f"{{{{margen:corrida:{cid}}}}}") ==         pct(t["margen_pct"]) + " (con AIU)"
    # El costo interno es costo directo en toda corrida: nunca lleva la nota.
    assert resolver(alm, f"{{{{costo:corrida:{cid}}}}}") == pesos(t["costo"])


def test_capitulo_de_una_corrida_vieja_dice_con_aiu(base):
    alm, ids = base
    cid = ids["calle13"]
    _origen(alm, cid, "idu-f1/1")
    cap = next(c for c in vista_corrida(alm, cid)["capitulos"] if c["codigo"] == "1")
    assert resolver(alm, f"{{{{contractual:capitulo:{cid}:1}}}}") ==         pesos(cap["contractual"]) + " (con AIU)"
    assert resolver(alm, f"{{{{costo:capitulo:{cid}:1}}}}") == pesos(cap["costo"])


def test_corrida_nueva_del_idu_no_lleva_nota(base):
    alm, ids = base
    cid = ids["cali"]
    _origen(alm, cid, "idu-f1/2")
    t = vista_corrida(alm, cid)["totales"]
    assert resolver(alm, f"{{{{contractual:corrida:{cid}}}}}") == pesos(t["contractual"])
    assert "AIU" not in resolver(alm, f"{{{{margen:corrida:{cid}}}}}")
