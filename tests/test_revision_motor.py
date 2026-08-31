"""Barrido y profundización, con un revisor de doble (sin red)."""
import pytest

from apu_tool.dominio import revision
from apu_tool.nucleo.models import (
    CorridaItemRow, DePricedApu, DePricedComponent, LicitacionItem,
)


def _fila(seq, desc, apu):
    return CorridaItemRow(
        seq=seq,
        item=LicitacionItem(item=str(seq + 1), descripcion=desc, unidad="M3",
                            cantidad=1, precio_contractual=0, shift="DIURNO"),
        status="auto", apu_codigo=apu, apu_nombre=f"APU {apu}", unidad="M3",
        shift="DIURNO", origen="historico", confianza=0.9, explicacion="",
        componentes=[], candidatos=[])


def _dp(codigo, nombre, unidad="M3"):
    """Un APU sin dinero, como el que ve la IA en la profundizacion."""
    return DePricedApu(codigo=codigo, nombre=nombre, unidad=unidad, shift="DIURNO",
                       grupo="MOV",
                       componentes=(DePricedComponent(
                           insumo_codigo="4279", insumo_nombre="CUADRILLA", unidad="HR",
                           rendimiento=1.0, tipo="insumo"),))


class RevisorDoble(revision.Revisor):
    """Sustituye la ÚNICA llamada al SDK. Sin red, sin mocks del cliente.

    `enabled=False` en el super para que NO intente construir `anthropic.Anthropic()`
    (en CI no hay API key y el constructor caería a enabled=False); después se
    fuerza `enabled` a True porque `_pedir` está sustituido y el cliente nunca se usa.
    """
    def __init__(self, respuestas):
        super().__init__(enabled=False)
        self.enabled = True
        self.respuestas = list(respuestas)
        self.pedidos = []

    def _pedir(self, system, schema, payload, effort):
        self.pedidos.append({"payload": payload, "effort": effort})
        return self.respuestas.pop(0)


def test_barrido_marca_solo_lo_que_la_ia_senala():
    filas = [_fila(0, "EXCAVACION MANUAL", "100"), _fila(1, "CONCRETO 3000 PSI", "200")]
    r = RevisorDoble([{"filas": [{"seq": 0, "resultado": "ok"},
                                 {"seq": 1, "resultado": "revisar"}]}])
    marcadas = r.barrer(filas)
    assert marcadas == {1}


def test_barrido_parte_en_lotes_y_manda_el_indice_completo(monkeypatch):
    monkeypatch.setattr(revision, "TAM_LOTE", 2)
    filas = [_fila(i, f"ACTIVIDAD {i}", "100") for i in range(5)]
    r = RevisorDoble([{"filas": [{"seq": s, "resultado": "ok"}]} for s in (0, 2, 4)])
    r.barrer(filas)
    assert len(r.pedidos) == 3                       # 5 filas / lotes de 2
    for p in r.pedidos:
        assert len(p["payload"]["indice"]) == 5      # el presupuesto entero, siempre
    assert r.pedidos[0]["effort"] == "low"


def test_barrido_sin_respuesta_para_una_fila_no_la_da_por_buena():
    """Un lote que vuelve incompleto deja esas filas SIN veredicto, no en `ok`."""
    filas = [_fila(0, "A", "100"), _fila(1, "B", "200")]
    r = RevisorDoble([{"filas": [{"seq": 0, "resultado": "ok"}]}])
    assert r.barrer(filas) == set()
    assert r.sin_respuesta == {1}


@pytest.mark.parametrize("respuesta", [
    {},                                              # JSON inválido -> _pedir devuelve {}
    {"filas": []},                                   # lote vacío
    {"filas": [{"seq": "ninguno", "resultado": "revisar"}]},   # seq basura
    {"filas": [{"resultado": "ok"}]},                # sin seq
])
def test_barrido_con_respuesta_inutil_deja_todo_el_lote_sin_respuesta(respuesta):
    """Nadie sale en `ok` por accidente: sin veredicto legible, sin veredicto."""
    filas = [_fila(0, "A", "100"), _fila(1, "B", "200")]
    r = RevisorDoble([respuesta])
    assert r.barrer(filas) == set()
    assert r.sin_respuesta == {0, 1}


def test_barrido_reinicia_sin_respuesta_en_cada_llamada():
    filas = [_fila(0, "A", "100")]
    r = RevisorDoble([{}, {"filas": [{"seq": 0, "resultado": "revisar"}]}])
    r.barrer(filas)
    assert r.sin_respuesta == {0}
    assert r.barrer(filas) == {0}
    assert r.sin_respuesta == set()


def test_barrido_falla_si_la_ia_no_esta_disponible():
    r = revision.Revisor(enabled=False)
    with pytest.raises(revision.IANoDisponible):
        r.barrer([_fila(0, "A", "100")])


def test_barrido_de_una_corrida_vacia_tambien_falla_sin_ia():
    """Sin filas no hay llamada que reviente sola: el aviso lo da `barrer`, si no
    el orquestador creería que la revisión corrió bien sin haber corrido."""
    r = revision.Revisor(enabled=False)
    with pytest.raises(revision.IANoDisponible):
        r.barrer([])


# ------------------------------------------------------------------ profundizacion
def test_profundizar_devuelve_cambiar_con_el_apu_sugerido():
    fila = _fila(3, "EXCAVACION MECANICA", "100")
    r = RevisorDoble([{"dictamen": "cambiar", "apu_sugerido": "200",
                       "turno_sugerido": "DIURNO", "confianza": 0.85,
                       "justificacion": "la actividad es mecánica"}])
    v = r.profundizar(fila, asignado=_dp("100", "EXCAVACION MANUAL"),
                      candidatos=[_dp("200", "EXCAVACION MECANICA")])
    assert (v.dictamen, v.apu_sugerido, v.nivel) == ("cambiar", "200", "profundo")
    assert r.pedidos[0]["effort"] == "medium"


def test_sugerencia_que_no_esta_entre_los_candidatos_degrada_a_dudoso():
    """La IA no puede inventar un código: si sugiere uno que no le pasamos, se cae."""
    fila = _fila(3, "EXCAVACION MECANICA", "100")
    r = RevisorDoble([{"dictamen": "cambiar", "apu_sugerido": "9999",
                       "turno_sugerido": "DIURNO", "confianza": 0.9,
                       "justificacion": "x"}])
    v = r.profundizar(fila, asignado=_dp("100", "EXCAVACION MANUAL"),
                      candidatos=[_dp("200", "EXCAVACION MECANICA")])
    assert v.dictamen == "dudoso"
    assert v.apu_sugerido is None
    assert "9999" in v.justificacion


def test_dictamen_desconocido_degrada_a_dudoso():
    fila = _fila(3, "A", "100")
    r = RevisorDoble([{"dictamen": "explota", "apu_sugerido": None,
                       "turno_sugerido": None, "confianza": 0.5, "justificacion": ""}])
    v = r.profundizar(fila, asignado=_dp("100", "A"), candidatos=[])
    assert v.dictamen == "dudoso"


def test_respuesta_vacia_degrada_a_dudoso():
    fila = _fila(3, "A", "100")
    r = RevisorDoble([{}])
    v = r.profundizar(fila, asignado=_dp("100", "A"), candidatos=[])
    assert v.dictamen == "dudoso"


def test_confianza_no_numerica_no_revienta_y_cae_a_cero():
    fila = _fila(3, "A", "100")
    r = RevisorDoble([{"dictamen": "ok", "apu_sugerido": None, "turno_sugerido": None,
                       "confianza": "alta", "justificacion": "encaja"}])
    v = r.profundizar(fila, asignado=_dp("100", "A"), candidatos=[])
    assert (v.dictamen, v.confianza) == ("ok", 0.0)


def test_profundizar_falla_si_la_ia_no_esta_disponible():
    r = revision.Revisor(enabled=False)
    with pytest.raises(revision.IANoDisponible):
        r.profundizar(_fila(0, "A", "100"), asignado=_dp("100", "A"), candidatos=[])
