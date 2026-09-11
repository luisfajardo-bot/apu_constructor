"""Barrido y profundización, con un revisor de doble (sin red)."""
from types import SimpleNamespace

import pytest

from apu_tool.dominio import privacy, revision
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
        r = self.respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def _barrer(revisor, filas):
    """Un solo lote, con el índice de la corrida entera — lo que hace `revisar` por
    cada lote. Antes esto era `Revisor.barrer`, que además partía en lotes."""
    return revisor.barrer_lote(filas, revision.indice_corrida(filas))


class _ClienteFalso:
    """Cliente de anthropic de mentira: `RevisorDoble` sustituye `_pedir` entero y deja
    su cuerpo SIN EJECUTAR — y ahí vive `privacy.safe_json`, que es donde el invariante
    #1 se aplica en runtime. Con este objeto `_pedir` corre de verdad."""

    def __init__(self, texto="{}", bloques=None):
        self.texto, self.bloques, self.visto, self.llamadas = texto, bloques, {}, 0

    @property
    def messages(self):
        return self

    def create(self, **kw):
        self.visto, self.llamadas = kw, self.llamadas + 1
        bloques = (self.bloques if self.bloques is not None
                   else [SimpleNamespace(type="text", text=self.texto)])
        return SimpleNamespace(content=bloques)


def _revisor_con_cliente(cliente):
    """Revisor real (su `_pedir` es el del módulo) con el SDK sustituido a mano."""
    r = revision.Revisor(enabled=True)
    r._client = cliente
    return r


def test_barrido_marca_solo_lo_que_la_ia_senala():
    filas = [_fila(0, "EXCAVACION MANUAL", "100"), _fila(1, "CONCRETO 3000 PSI", "200")]
    r = RevisorDoble([{"filas": [{"seq": 0, "resultado": "ok"},
                                 {"seq": 1, "resultado": "revisar"}]}])
    marcadas, sin_respuesta = _barrer(r, filas)
    assert marcadas == {1}
    assert sin_respuesta == set()


def test_barrido_parte_en_lotes_y_manda_el_indice_completo(monkeypatch):
    """La partición vive en `revisar`; el índice de la corrida ENTERA viaja en CADA
    lote, que es la razón de ser del barrido: ver el presupuesto como un todo."""
    monkeypatch.setattr(revision, "TAM_LOTE", 2)
    filas = [_fila(i, f"ACTIVIDAD {i}", "100") for i in range(5)]
    r = RevisorDoble([{"filas": [{"seq": s, "resultado": "ok"}]} for s in (0, 2, 4)])
    list(revision.revisar(None, filas, r))           # nadie marcado: no toca el almacén
    assert len(r.pedidos) == 3                       # 5 filas / lotes de 2
    for p in r.pedidos:
        assert len(p["payload"]["indice"]) == 5      # el presupuesto entero, siempre
        assert [f["seq"] for f in p["payload"]["indice"]] == [0, 1, 2, 3, 4]
    assert [len(p["payload"]["filas"]) for p in r.pedidos] == [2, 2, 1]
    assert r.pedidos[0]["effort"] == "low"


def test_revisar_reporta_progreso_despues_de_cada_lote(monkeypatch):
    """Sin esto el barrido corre mudo: con 300 líneas son minutos sin un solo byte,
    el proxy corta el stream y la interfaz no tiene cómo saber si avanza."""
    monkeypatch.setattr(revision, "TAM_LOTE", 2)
    filas = [_fila(i, f"ACTIVIDAD {i}", "100") for i in range(5)]
    r = RevisorDoble([{"filas": [{"seq": s, "resultado": "ok"} for s in ss]}
                      for ss in ((0, 1), (2, 3), (4,))])
    eventos = list(revision.revisar(None, filas, r))
    tipos = [e for e, _ in eventos]
    assert [p for e, p in eventos if e == "barriendo"] == [
        {"lote": 1, "lotes": 3}, {"lote": 2, "lotes": 3}, {"lote": 3, "lotes": 3}]
    # ... y todos ANTES del primer veredicto: es el progreso del barrido.
    assert tipos.index("barriendo") == 1             # justo después de `started`
    assert (max(i for i, e in enumerate(tipos) if e == "barriendo")
            < tipos.index("veredicto"))


def test_started_trae_lotes_y_cuadra_con_los_eventos_barriendo(monkeypatch):
    """La interfaz necesita el número de lotes ANTES de que termine el primero, para
    pintar "0 de N" en vez de un indeterminado durante casi un minuto."""
    monkeypatch.setattr(revision, "TAM_LOTE", 2)
    filas = [_fila(i, f"ACTIVIDAD {i}", "100") for i in range(5)]   # 5/2 -> 3 lotes
    r = RevisorDoble([{"filas": [{"seq": s, "resultado": "ok"} for s in ss]}
                      for ss in ((0, 1), (2, 3), (4,))])
    eventos = list(revision.revisar(None, filas, r))
    started = next(p for e, p in eventos if e == "started")
    assert started == {"total": 5, "lotes": 3}
    assert len([e for e, _ in eventos if e == "barriendo"]) == started["lotes"]


def test_started_de_una_corrida_vacia_trae_lotes_cero():
    r = RevisorDoble([])
    eventos = list(revision.revisar(None, [], r))
    started = next(p for e, p in eventos if e == "started")
    assert started == {"total": 0, "lotes": 0}


def test_barrido_sin_respuesta_para_una_fila_no_la_da_por_buena():
    """Un lote que vuelve incompleto deja esas filas SIN veredicto, no en `ok`."""
    filas = [_fila(0, "A", "100"), _fila(1, "B", "200")]
    r = RevisorDoble([{"filas": [{"seq": 0, "resultado": "ok"}]}])
    marcadas, sin_respuesta = _barrer(r, filas)
    assert marcadas == set()
    assert sin_respuesta == {1}


@pytest.mark.parametrize("respuesta", [
    {},                                              # JSON inválido -> _pedir devuelve {}
    {"filas": []},                                   # lote vacío
    {"filas": [{"seq": "ninguno", "resultado": "revisar"}]},   # seq basura
    {"filas": [{"resultado": "ok"}]},                # sin seq
    {"filas": [{"seq": 0, "resultado": "quizas"}]},  # vocabulario que no existe
    {"filas": [{"seq": 0, "resultado": None}]},      # resultado nulo
    {"filas": [{"seq": 0}]},                         # sin resultado
    {"filas": "ok"},                                 # `filas` no es una lista
    {"filas": [42, "ok"]},                           # elementos que no son dicts
    {"filas": 42},                                   # `filas` ni siquiera es iterable
])
def test_barrido_con_respuesta_inutil_deja_todo_el_lote_sin_respuesta(respuesta):
    """Nadie sale en `ok` por accidente: sin veredicto legible, sin veredicto.

    Ojo con los casos de `resultado`: un vocabulario que no entendemos NO cuenta como
    fila contestada. Darla por buena sería bendecir en silencio el APU que la IA no
    llegó a mirar, justo al revés de lo que dice el prompt ("ante la duda, revisar").
    """
    filas = [_fila(0, "A", "100"), _fila(1, "B", "200")]
    r = RevisorDoble([respuesta])
    marcadas, sin_respuesta = _barrer(r, filas)
    assert marcadas == set()
    assert sin_respuesta == {0, 1}


def test_barrido_tolera_espacios_y_mayusculas_en_el_resultado():
    """El vocabulario se valida normalizado: " REVISAR " sí es una respuesta."""
    filas = [_fila(0, "A", "100")]
    r = RevisorDoble([{"filas": [{"seq": 0, "resultado": " REVISAR "}]}])
    assert _barrer(r, filas) == ({0}, set())


def test_barrido_no_arrastra_estado_entre_llamadas():
    filas = [_fila(0, "A", "100")]
    r = RevisorDoble([{}, {"filas": [{"seq": 0, "resultado": "revisar"}]}])
    assert _barrer(r, filas) == (set(), {0})
    assert _barrer(r, filas) == ({0}, set())


def test_un_error_del_sdk_en_un_lote_no_tira_los_demas(monkeypatch, alm_apus):
    """Un 429 o un timeout en el lote 2 no puede perder el trabajo ya pagado: ese lote
    entero cae en `sin_respuesta` y el barrido sigue."""
    monkeypatch.setattr(revision, "TAM_LOTE", 1)
    filas = [_fila(i, f"ACTIVIDAD {i}", "100") for i in range(3)]
    r = RevisorDoble([{"filas": [{"seq": 0, "resultado": "revisar"}]},
                      RuntimeError("429 rate limit"),
                      {"filas": [{"seq": 2, "resultado": "ok"}]},
                      {"dictamen": "ok", "apu_sugerido": None, "turno_sugerido": None,
                       "confianza": 0.9, "justificacion": "encaja"}])
    eventos = list(revision.revisar(alm_apus, filas, r))
    assert next(p for e, p in eventos if e == "barrido") == {"revisar": 1,
                                                             "sin_respuesta": [1]}
    assert len([p for e, p in eventos if e == "barriendo"]) == 3
    assert len(r.pedidos) == 4          # 3 barridos (el error no abortó) + 1 profundo
    assert [p["seq"] for e, p in eventos if e == "veredicto"] == [0, 2]


def test_una_fuga_de_dinero_aborta_el_barrido_y_no_se_traga():
    """El `except Exception` del barrido NO puede convertir una violación del
    invariante #1 en un lote silenciosamente vacío."""
    r = RevisorDoble([privacy.PrivacyViolation("costo_unitario")])
    with pytest.raises(privacy.PrivacyViolation):
        _barrer(r, [_fila(0, "A", "100")])


def test_barrido_falla_si_la_ia_no_esta_disponible():
    """Tanto el lote suelto (lo levanta `_pedir`) como el orquestador."""
    r = revision.Revisor(enabled=False)
    with pytest.raises(revision.IANoDisponible):
        _barrer(r, [_fila(0, "A", "100")])
    with pytest.raises(revision.IANoDisponible):
        list(revision.revisar(None, [_fila(0, "A", "100")], r))


def test_revisar_una_corrida_vacia_tambien_falla_sin_ia():
    """Sin filas no hay lote que reviente solo: el aviso lo da `revisar`, si no el
    llamador creería que la revisión corrió bien sin haber corrido."""
    r = revision.Revisor(enabled=False)
    with pytest.raises(revision.IANoDisponible):
        list(revision.revisar(None, [], r))


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


def test_apu_sugerido_inventado_no_sobrevive_a_un_dictamen_que_no_es_cambiar():
    """Solo "cambiar" propone un APU: en cualquier otro dictamen el código sobrante
    se descarta, o viajaría a la base y a la interfaz como propuesta real."""
    fila = _fila(3, "A", "100")
    r = RevisorDoble([{"dictamen": "ok", "apu_sugerido": "9999",
                       "turno_sugerido": "NOCTURNO", "confianza": 0.9,
                       "justificacion": "encaja"}])
    v = r.profundizar(fila, asignado=_dp("100", "A"), candidatos=[])
    assert v.dictamen == "ok"
    assert v.apu_sugerido is None
    assert v.turno_sugerido is None


def test_barrido_ignora_un_seq_que_no_es_de_la_corrida():
    """La IA puede contestar por un `seq` que no le dimos; no hay fila que mirar, así
    que `revisar` lo filtra antes de contarlo y de profundizarlo."""
    filas = [_fila(0, "A", "100"), _fila(1, "B", "200")]
    r = RevisorDoble([{"filas": [{"seq": 0, "resultado": "ok"},
                                 {"seq": 1, "resultado": "ok"},
                                 {"seq": 99, "resultado": "revisar"}]}])
    eventos = list(revision.revisar(None, filas, r))
    assert next(p for e, p in eventos if e == "barrido") == {"revisar": 0,
                                                             "sin_respuesta": []}
    assert len(r.pedidos) == 1      # el seq fantasma no gastó una profundización
    assert [p["seq"] for e, p in eventos if e == "veredicto"] == [0, 1]


# --------------------------------------------------------------- orquestador
@pytest.fixture()
def alm_apus(tmp_path):
    """Almacén con los APUs 100 y 200, para que `revisar` pueda pedir sus DePriced."""
    from apu_tool.datos.almacen import Almacen
    from apu_tool.nucleo.models import Apu, ApuComponent, Insumo

    a = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                corridas_path=tmp_path / "c.db")
    a.init_schema()
    a.precios.insert_insumos([Insumo("4279", "CUADRILLA", "HR", "MO", 40000.0,
                                     "PRECIO IDU")])
    a.apus.insert_apus([Apu("100", "EXCAVACION MANUAL", "M3", "DIURNO", "MOV"),
                        Apu("200", "CONCRETO 3000 PSI", "M3", "DIURNO", "EST")])
    a.apus.insert_components([
        ApuComponent("100", "DIURNO", "4279", "CUADRILLA", "HR", 1.0, 40000.0),
        ApuComponent("200", "DIURNO", "4279", "CUADRILLA", "HR", 2.0, 40000.0)])
    return a


def test_revisar_emite_eventos_y_solo_profundiza_lo_marcado(alm_apus):
    filas = [_fila(0, "EXCAVACION MANUAL", "100"), _fila(1, "CONCRETO", "200")]
    r = RevisorDoble([
        {"filas": [{"seq": 0, "resultado": "ok"}, {"seq": 1, "resultado": "revisar"}]},
        {"dictamen": "ok", "apu_sugerido": None, "turno_sugerido": None,
         "confianza": 0.9, "justificacion": "correcto"},
    ])
    eventos = list(revision.revisar(alm_apus, filas, r))
    tipos = [e for e, _ in eventos]
    assert tipos[0] == "started"
    assert "barrido" in tipos
    assert tipos[-1] == "done"
    # Dos veredictos (uno por fila) pero UNA sola profundización.
    veredictos = [p["veredicto"] for e, p in eventos if e == "veredicto"]
    assert len(veredictos) == 2
    assert {v["nivel"] for v in veredictos} == {"barrido", "profundo"}
    assert len(r.pedidos) == 2      # 1 barrido + 1 profundización


def test_revisar_no_inventa_un_ok_para_la_fila_que_la_ia_no_contesto(alm_apus):
    """La fila 1 no aparece en la respuesta del barrido: se queda SIN veredicto."""
    filas = [_fila(0, "EXCAVACION MANUAL", "100"), _fila(1, "CONCRETO", "200")]
    r = RevisorDoble([{"filas": [{"seq": 0, "resultado": "ok"}]}])
    eventos = list(revision.revisar(alm_apus, filas, r))
    seqs = [p["seq"] for e, p in eventos if e == "veredicto"]
    assert seqs == [0]
    barrido = next(p for e, p in eventos if e == "barrido")
    assert barrido == {"revisar": 0, "sin_respuesta": [1]}
    done = next(p for e, p in eventos if e == "done")
    assert done["sin_veredicto"] == 1
    assert done["total"] == 2
    assert len(r.pedidos) == 1      # nadie marcado: no se profundiza nada


def test_revisar_cuenta_por_dictamen_en_el_done(alm_apus):
    filas = [_fila(0, "A", "100"), _fila(1, "B", "200"), _fila(2, "C", "100")]
    r = RevisorDoble([
        {"filas": [{"seq": 0, "resultado": "ok"},
                   {"seq": 1, "resultado": "revisar"},
                   {"seq": 2, "resultado": "revisar"}]},
        {"dictamen": "dudoso", "apu_sugerido": None, "turno_sugerido": None,
         "confianza": 0.4, "justificacion": "no se puede decidir"},
        {"dictamen": "sin_apu", "apu_sugerido": None, "turno_sugerido": None,
         "confianza": 0.8, "justificacion": "no hay nada en la biblioteca"},
    ])
    eventos = list(revision.revisar(alm_apus, filas, r))
    done = next(p for e, p in eventos if e == "done")
    assert done == {"total": 3, "ok": 1, "dudoso": 1, "cambiar": 0, "sin_apu": 1,
                    "sin_veredicto": 0}
    # El conteo cuadra con los veredictos que de verdad salieron.
    assert sum(done[d] for d in revision.DICTAMENES) == len(
        [e for e, _ in eventos if e == "veredicto"])


def test_revisar_omite_los_candidatos_que_no_estan_en_la_biblioteca(alm_apus):
    """Un candidato con código inexistente no revienta: sale de la lista y ya."""
    fila = _fila(0, "A", "100")
    fila.candidatos = [{"apu_codigo": "200", "apu_nombre": "CONCRETO 3000 PSI"},
                       {"apu_codigo": "9999", "apu_nombre": "FANTASMA"}]
    r = RevisorDoble([
        {"filas": [{"seq": 0, "resultado": "revisar"}]},
        {"dictamen": "cambiar", "apu_sugerido": "200", "turno_sugerido": "DIURNO",
         "confianza": 0.9, "justificacion": "encaja mejor"},
    ])
    eventos = list(revision.revisar(alm_apus, [fila], r))
    codigos = [c["codigo"] for c in r.pedidos[1]["payload"]["candidatos"]]
    assert codigos == ["200"]
    v = next(p["veredicto"] for e, p in eventos if e == "veredicto")
    assert (v["dictamen"], v["apu_sugerido"]) == ("cambiar", "200")


def test_revisar_de_una_corrida_vacia_emite_started_y_done(alm_apus):
    r = RevisorDoble([])
    eventos = list(revision.revisar(alm_apus, [], r))
    assert [e for e, _ in eventos] == ["started", "barrido", "done"]
    assert eventos[-1][1] == {"total": 0, "ok": 0, "dudoso": 0, "cambiar": 0,
                              "sin_apu": 0, "sin_veredicto": 0}
    assert r.pedidos == []


def test_revisar_con_una_fila_sin_apu_asignado(alm_apus):
    """Sin APU no hay `asignado` que pedirle a la biblioteca; con candidatos vivos se
    profundiza igual (sin ninguno se cortocircuita, ver el test del final)."""
    fila = _fila(0, "ACTIVIDAD RARA", None)
    fila.candidatos = [{"apu_codigo": "200", "apu_nombre": "CONCRETO 3000 PSI"}]
    r = RevisorDoble([
        {"filas": [{"seq": 0, "resultado": "revisar"}]},
        {"dictamen": "sin_apu", "apu_sugerido": None, "turno_sugerido": None,
         "confianza": 0.9, "justificacion": "no hay nada parecido"},
    ])
    eventos = list(revision.revisar(alm_apus, [fila], r))
    assert r.pedidos[1]["payload"]["apu_asignado"] is None
    v = next(p["veredicto"] for e, p in eventos if e == "veredicto")
    assert v["dictamen"] == "sin_apu"


def test_revisar_es_un_generador_perezoso(alm_apus):
    """Se puede consumir de a poco: el SSE reporta en vivo, no al final."""
    filas = [_fila(0, "A", "100")]
    r = RevisorDoble([{"filas": [{"seq": 0, "resultado": "ok"}]}])
    gen = revision.revisar(alm_apus, filas, r)
    assert r.pedidos == []                       # nada corrió todavía
    assert next(gen)[0] == "started"
    assert r.pedidos == []                       # el barrido aún no se pidió
    assert next(gen)[0] == "barriendo"           # el primer lote, ya reportado
    assert len(r.pedidos) == 1


# ------------------------------------------------- turno, confianza y mensajes
@pytest.mark.parametrize("turno", ["TARDE", "diurno-nocturno", "", "  ", "SI"])
def test_turno_sugerido_que_no_es_diurno_ni_nocturno_se_descarta(turno):
    """El turno es parte de la clave del APU: uno inventado describe un APU que no
    existe. `None` es correcto — el consumidor cae al turno de la fila."""
    fila = _fila(3, "A", "100")
    r = RevisorDoble([{"dictamen": "cambiar", "apu_sugerido": "200",
                       "turno_sugerido": turno, "confianza": 0.9,
                       "justificacion": "x"}])
    v = r.profundizar(fila, asignado=_dp("100", "A"),
                      candidatos=[_dp("200", "B")])
    assert (v.dictamen, v.apu_sugerido, v.turno_sugerido) == ("cambiar", "200", None)


def test_turno_sugerido_se_normaliza():
    fila = _fila(3, "A", "100")
    r = RevisorDoble([{"dictamen": "cambiar", "apu_sugerido": "200",
                       "turno_sugerido": " nocturno ", "confianza": 0.9,
                       "justificacion": "x"}])
    v = r.profundizar(fila, asignado=_dp("100", "A"), candidatos=[_dp("200", "B")])
    assert v.turno_sugerido == "NOCTURNO"


@pytest.mark.parametrize("cruda,esperada", [(42, 1.0), (-3, 0.0), (0.85, 0.85)])
def test_confianza_se_acota_entre_cero_y_uno(cruda, esperada):
    """El prompt promete 0..1; una interfaz que pinte 42 como porcentaje diría 4200%."""
    fila = _fila(3, "A", "100")
    r = RevisorDoble([{"dictamen": "ok", "apu_sugerido": None, "turno_sugerido": None,
                       "confianza": cruda, "justificacion": "encaja"}])
    v = r.profundizar(fila, asignado=_dp("100", "A"), candidatos=[])
    assert v.confianza == esperada


def test_cambiar_sin_apu_sugerido_lo_dice_sin_hablar_de_None():
    """Pedir cambiar sin decir por cuál es otro caso que sugerir uno inventado, y esta
    justificación la lee una persona en la base."""
    fila = _fila(3, "A", "100")
    r = RevisorDoble([{"dictamen": "cambiar", "apu_sugerido": None,
                       "turno_sugerido": None, "confianza": 0.9,
                       "justificacion": "es mecánica"}])
    v = r.profundizar(fila, asignado=_dp("100", "A"), candidatos=[_dp("200", "B")])
    assert v.dictamen == "dudoso"
    assert "None" not in v.justificacion
    assert "no indicó por cuál" in v.justificacion
    assert "es mecánica" in v.justificacion


# ------------------------------------------------------ la puerta real al SDK
def test_pedir_manda_los_parametros_esperados_del_sdk():
    c = _ClienteFalso('{"filas": []}')
    r = _revisor_con_cliente(c)
    assert r._pedir("sistema", {"type": "object"}, {"a": 1}, "low") == {"filas": []}
    assert c.visto["model"] == r.model
    assert c.visto["system"] == "sistema"
    assert c.visto["thinking"] == {"type": "adaptive"}
    assert c.visto["max_tokens"] == 16000
    assert c.visto["output_config"]["effort"] == "low"
    assert c.visto["output_config"]["format"] == {"type": "json_schema",
                                                  "schema": {"type": "object"}}
    assert c.visto["messages"][0]["role"] == "user"


@pytest.mark.parametrize("texto", ['[{"seq": 0}]', '"ok"', "42", "null", "no es json"])
def test_pedir_devuelve_dict_vacio_si_la_respuesta_no_es_un_objeto(texto):
    """`json.loads` valida sintaxis, no forma: una lista o un número parsean bien y
    reventarían el `.get` del llamador."""
    r = _revisor_con_cliente(_ClienteFalso(texto))
    assert r._pedir("s", {}, {"a": 1}, "low") == {}


def test_pedir_con_respuesta_solo_de_pensamiento_no_revienta():
    """Caso real: la respuesta se corta durante el pensamiento y no hay bloque `text`."""
    r = _revisor_con_cliente(_ClienteFalso(
        bloques=[SimpleNamespace(type="thinking", thinking="mmm")]))
    assert r._pedir("s", {}, {"a": 1}, "low") == {}


def test_el_cliente_del_sdk_es_perezoso():
    """Preguntar `disponible` no tiene por qué armar un cliente HTTP."""
    r = revision.Revisor(enabled=True)
    assert r.disponible is True
    assert r._client is None


def test_sin_api_key_no_hay_revision(monkeypatch):
    from apu_tool import config
    monkeypatch.delenv(config.AI_ENABLED_ENV, raising=False)
    assert revision.Revisor().disponible is False


# ---------------------------------- no gastar una llamada en lo que ya se sabe
def test_revisar_no_llama_a_la_ia_si_no_hay_apu_ni_candidatos_vivos(alm_apus):
    """Sin APU y con todos los candidatos fuera de la biblioteca, profundizar es
    pagarle a la IA para que mire una lista vacía y conteste lo obvio."""
    fila = _fila(0, "ACTIVIDAD RARA", None)
    fila.candidatos = [{"apu_codigo": "9999", "apu_nombre": "FANTASMA"}]
    r = RevisorDoble([{"filas": [{"seq": 0, "resultado": "revisar"}]}])
    eventos = list(revision.revisar(alm_apus, [fila], r))
    v = next(p["veredicto"] for e, p in eventos if e == "veredicto")
    assert (v["dictamen"], v["nivel"]) == ("sin_apu", "barrido")
    assert len(r.pedidos) == 1          # solo el barrido: no se profundizó
    done = next(p for e, p in eventos if e == "done")
    assert done["sin_apu"] == 1


# ----------------------------------- el veredicto dice QUÉ APU evaluó (carrera)
# La revisión lee las filas al abrir el request y corre por minutos, con la tabla sin
# bloquear: el usuario puede reasignar una fila mientras la IA piensa. El veredicto
# lleva el APU que evaluó para que quien hidrata la vista pueda descartarlo si ya no
# coincide (ver tests/test_api_revision.py).
def test_el_veredicto_del_barrido_dice_que_apu_evaluo(alm_apus):
    filas = [_fila(0, "EXCAVACION MANUAL", "100")]
    r = RevisorDoble([{"filas": [{"seq": 0, "resultado": "ok"}]}])
    eventos = list(revision.revisar(alm_apus, filas, r))
    v = next(p["veredicto"] for e, p in eventos if e == "veredicto")
    assert (v["dictamen"], v["apu_evaluado"]) == ("ok", "100")


def test_el_veredicto_profundo_dice_que_apu_evaluo():
    fila = _fila(3, "EXCAVACION MECANICA", "100")
    r = RevisorDoble([{"dictamen": "cambiar", "apu_sugerido": "200",
                       "turno_sugerido": "DIURNO", "confianza": 0.9,
                       "justificacion": "es mecánica"}])
    v = r.profundizar(fila, asignado=_dp("100", "EXCAVACION MANUAL"),
                      candidatos=[_dp("200", "EXCAVACION MECANICA")])
    # El evaluado es el que TENÍA la fila, no el sugerido: son cosas distintas.
    assert (v.apu_evaluado, v.apu_sugerido) == ("100", "200")


def test_una_fila_sin_apu_evalua_None_y_no_un_string_vacio(alm_apus):
    """`None` y `""` significan lo mismo acá, y quien compara normaliza; el veredicto
    de una fila sin APU guarda `None` para que el JSON no traiga un código falso."""
    fila = _fila(0, "ACTIVIDAD RARA", "")
    r = RevisorDoble([{"filas": [{"seq": 0, "resultado": "revisar"}]}])
    eventos = list(revision.revisar(alm_apus, [fila], r))
    v = next(p["veredicto"] for e, p in eventos if e == "veredicto")
    assert v["apu_evaluado"] is None


# ------------------------------------ una fila sin APU nunca puede salir en "ok"
def test_barrido_ok_en_una_fila_sin_apu_degrada_a_sin_apu(alm_apus):
    """El prompt le pide "revisar" a las filas sin APU, pero eso es una instrucción,
    no una restricción: si contesta "ok", un ✔ verde contradiría al candado rojo que
    cuenta esa misma fila como hueco y traba el congelar."""
    filas = [_fila(0, "ACTIVIDAD SIN APU", None)]
    r = RevisorDoble([{"filas": [{"seq": 0, "resultado": "ok"}]}])
    eventos = list(revision.revisar(alm_apus, filas, r))
    v = next(p["veredicto"] for e, p in eventos if e == "veredicto")
    assert v["dictamen"] == "sin_apu"
    assert "no tiene APU asignado" in v["justificacion"]
    done = next(p for e, p in eventos if e == "done")
    assert (done["ok"], done["sin_apu"]) == (0, 1)


def test_profundizacion_ok_en_una_fila_sin_apu_degrada_a_sin_apu(alm_apus):
    """"El APU asignado es el correcto" no significa nada sin APU asignado."""
    fila = _fila(0, "ACTIVIDAD SIN APU", None)
    fila.candidatos = [{"apu_codigo": "200", "apu_nombre": "CONCRETO 3000 PSI"}]
    r = RevisorDoble([
        {"filas": [{"seq": 0, "resultado": "revisar"}]},
        {"dictamen": "ok", "apu_sugerido": None, "turno_sugerido": None,
         "confianza": 0.9, "justificacion": "encaja"},
    ])
    eventos = list(revision.revisar(alm_apus, [fila], r))
    v = next(p["veredicto"] for e, p in eventos if e == "veredicto")
    assert v["dictamen"] == "sin_apu"
    assert v["nivel"] == "profundo"          # el degradado no borra de dónde salió
    assert "encaja" in v["justificacion"]    # ni lo que dijo la IA
    done = next(p for e, p in eventos if e == "done")
    assert (done["ok"], done["sin_apu"]) == (0, 1)


def test_un_ok_con_apu_asignado_no_se_toca(alm_apus):
    """El degradado mira SOLO las filas sin APU: el camino normal sigue igual."""
    filas = [_fila(0, "EXCAVACION MANUAL", "100")]
    r = RevisorDoble([{"filas": [{"seq": 0, "resultado": "ok"}]}])
    eventos = list(revision.revisar(alm_apus, filas, r))
    v = next(p["veredicto"] for e, p in eventos if e == "veredicto")
    assert v["dictamen"] == "ok"
    assert v["justificacion"] == "Sin objeciones en el barrido."


class _ErrorSDK(Exception):
    """Se parece a un `anthropic.APIStatusError` en lo único que se mira: `status_code`.
    No se importa el SDK: es dependencia opcional y en CI puede no estar."""
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class _ClienteQueFalla:
    """Cliente cuyo `messages.create` revienta con el código HTTP que se le pida."""
    def __init__(self, status_code):
        self.status_code = status_code

    @property
    def messages(self):
        return self

    def create(self, **kw):
        raise _ErrorSDK(self.status_code)


@pytest.mark.parametrize("codigo", [401, 403])
def test_credencial_invalida_no_se_disfraza_de_fila_sin_respuesta(codigo):
    """Una llave vencida o revocada NO puede salir como "la IA no contestó": el
    barrido entero caería en `sin_respuesta` y el usuario iría a buscar el problema
    a la corrida en vez de al servidor. Aborta con un mensaje que nombra la llave."""
    r = _revisor_con_cliente(_ClienteQueFalla(codigo))
    with pytest.raises(revision.IANoDisponible, match="ANTHROPIC_API_KEY"):
        _barrer(r, [_fila(0, "EXCAVACION MANUAL", "100")])


@pytest.mark.parametrize("codigo", [429, 500, 529])
def test_un_fallo_pasajero_sigue_cayendo_en_sin_respuesta(codigo):
    """Guarda del arreglo de arriba: distinguir la credencial NO puede convertir un
    429 o un 500 en un aborto. Esos se tragan, el lote se pierde y el barrido sigue."""
    r = _revisor_con_cliente(_ClienteQueFalla(codigo))
    assert _barrer(r, [_fila(0, "EXCAVACION MANUAL", "100")]) == (set(), {0})


class _ErrorSDKConMensaje(_ErrorSDK):
    """Como `_ErrorSDK`, pero con `message`: lo único que mira `sin_saldo` además del
    `status_code`, y que un 401/403/429 no necesita."""
    def __init__(self, status_code, message):
        super().__init__(status_code)
        self.message = message


class _ClienteQueFallaConMensaje(_ClienteQueFalla):
    def __init__(self, status_code, message):
        super().__init__(status_code)
        self.message = message

    def create(self, **kw):
        raise _ErrorSDKConMensaje(self.status_code, self.message)


def test_sin_saldo_no_se_disfraza_de_fila_sin_respuesta():
    """Mismo arreglo que la credencial inválida, para el 400 de saldo agotado: sin
    esto el barrido entero caería en `sin_respuesta` y el usuario buscaría el
    problema en la corrida en vez de en la consola de Anthropic."""
    r = _revisor_con_cliente(_ClienteQueFallaConMensaje(
        400, "Your credit balance is too low to access the Anthropic API. Please "
             "go to Plans & Billing to upgrade or purchase credits."))
    with pytest.raises(revision.IANoDisponible, match="saldo"):
        _barrer(r, [_fila(0, "EXCAVACION MANUAL", "100")])
