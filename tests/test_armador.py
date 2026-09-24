"""El worker del armado: un ciclo, sin hilo y sin dormir.

Todo se prueba contra `un_ciclo`, que reclama y arma UNA corrida y vuelve. El bucle
(`correr_para_siempre`) solo se prueba en lo suyo —que una excepción no lo mate— y con
los dos eventos ya puestos, así que ningún test de acá duerme ni lanza un hilo.
"""
import os
import threading
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import (
    Apu, ApuComponent, CorridaMeta, Insumo, LicitacionItem)
from apu_tool.servicio import armador, corridas as svc
from apu_tool.servicio.app import create_app


# --------------------------------------------------------------------------
# Helpers. Mismo cuerpo que los de tests/test_api_corridas.py (`_cliente`,
# `_item_plan`, `_carpeta`), sin el TestClient: el worker no habla HTTP.
# --------------------------------------------------------------------------
def _almacen(tmp_path) -> Almacen:
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([Insumo("100", "Concreto 3000 PSI", "M3",
                                       "CONCRETOS", 350000.0, "COSTO INTERNO")])
    alm.apus.insert_apus([Apu("A1", "Concreto clase D", "M3", "DIURNO", "ESTR")])
    alm.apus.insert_components([ApuComponent("A1", "DIURNO", "100",
                               "Concreto 3000 PSI", "M3", 1.05, 350000.0)])
    return alm


def _item(desc: str, **kw) -> LicitacionItem:
    base = dict(item="1", descripcion=desc, unidad="M3", cantidad=10.0,
                precio_contractual=400000.0, shift="DIURNO")
    base.update(kw)
    return LicitacionItem(**base)


def _carpeta(alm) -> int:
    return alm.carpetas.crear("Obra")


def _encolar(alm, items) -> int:
    return svc.crear_corrida_encolada(alm, "x.xlsx", items, "DIURNO", None,
                                      carpeta_id=_carpeta(alm))


def _robar(alm, corrida_id: int, ladron: str = "instancia-ladrona") -> None:
    """Otra instancia le quita la reclama al worker, DE VERDAD (no un mock).

    Pide la corrida con el reloj adelantado una hora: así la reclama viva del worker le
    parece vencida, que es exactamente lo que pasa en un deploy cuando el worker viejo
    tarda más que el TTL en drenar."""
    futuro = (datetime.now() + timedelta(hours=1)).isoformat(timespec="seconds")
    assert alm.corridas.reclamar_armado(ladron, futuro, futuro) == corrida_id


def _al_armar_item(alm, seq_gatillo, accion):
    """Corre `accion()` justo después de que se persista la fila `seq_gatillo`
    (`None` = después de cada fila).

    Es el único punto de enganche determinístico que hay a mitad de un armado, y sirve
    para meter la carrera real (otra instancia roba la reclama) o para adelantar el
    reloj, sin hilos ni sleeps."""
    original = alm.corridas.agregar_item

    def espia(corrida_id, fila):
        original(corrida_id, fila)
        if seq_gatillo is None or fila.seq == seq_gatillo:
            accion()

    alm.corridas.agregar_item = espia


class _RelojFalso:
    """Cronómetro monótono que solo avanza cuando el test lo dice. Con esto el latido
    por tiempo se prueba en milisegundos en vez de en minutos."""

    def __init__(self):
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def avanzar(self, segundos: float) -> None:
        self.t += segundos


@pytest.fixture(autouse=True)
def _evento_limpio():
    """`hay_trabajo` es global del módulo: si un test lo deja levantado, el siguiente
    ve un evento que nadie mandó."""
    armador.hay_trabajo.clear()
    yield
    armador.hay_trabajo.clear()


# --------------------------------------------------------------------------
# El ciclo feliz
# --------------------------------------------------------------------------
def test_un_ciclo_arma_la_corrida_pendiente(tmp_path):
    alm = _almacen(tmp_path)
    items = [_item("Concreto clase D"), _item("ACTIVIDAD B")]
    cid = _encolar(alm, items)

    assert armador.un_ciclo(alm, "instancia-test") is True

    m = alm.corridas.get_corrida(cid)
    assert m.estado == "en_revision"
    assert m.armando_por is None and m.armando_desde is None   # reclama liberada
    assert m.duracion_ms is not None                           # cronómetro guardado
    assert len(alm.corridas.get_items(cid)) == 2


def test_un_ciclo_sin_trabajo_devuelve_false(tmp_path):
    alm = _almacen(tmp_path)
    # Una corrida que ya terminó NO es trabajo: la cola es `estado='armando'`.
    svc.construir_corrida(alm, "y.xlsx", [_item("Concreto clase D")], "DIURNO", None,
                          carpeta_id=_carpeta(alm))
    assert armador.un_ciclo(alm, "instancia-test") is False


def test_reanuda_desde_donde_quedo_y_no_duplica(tmp_path):
    """El caso entero de la feature: media corrida armada, la instancia murió, otra la
    retoma. Se afirma la lista de descripciones y no solo los seq: un `desde` corrido en
    uno armaría las filas correctas en cantidad pero con el ítem equivocado."""
    alm = _almacen(tmp_path)
    items = [_item("ACTIVIDAD %d" % i, item=str(i)) for i in range(5)]
    cid = _encolar(alm, items)
    for _ in svc.armar_pendientes(alm, cid, items[:2], desde_seq=0):
        pass                                    # la instancia vieja armó 0 y 1
    # Y murió dejando el motivo: el ciclo que completa la corrida tiene que limpiarlo.
    alm.corridas.finalizar_armado(cid, "armando", error="se cortó la anterior")

    assert armador.un_ciclo(alm, "instancia-B") is True

    filas = sorted(alm.corridas.get_items(cid), key=lambda r: r.seq)
    assert [r.seq for r in filas] == [0, 1, 2, 3, 4]           # completa, sin duplicados
    assert [r.item.descripcion for r in filas] == [i.descripcion for i in items]
    m = alm.corridas.get_corrida(cid)
    assert m.estado == "en_revision" and m.ultimo_error is None


# --------------------------------------------------------------------------
# Las salidas de la cola
# --------------------------------------------------------------------------
def _agotar_intentos(alm, veces: int) -> None:
    """Reclama y abandona `veces` veces, con relojes crecientes.

    El reloj tiene que avanzar: `reclamar_armado` solo toma una corrida cuya reclama
    esté vencida, así que reclamar dos veces con la misma hora no sube `intentos` (y el
    test no probaría nada)."""
    for k in range(veces):
        dia = "2026-01-%02dT00:00:00" % (k + 1)
        assert alm.corridas.reclamar_armado("murio", dia, dia) is not None


def test_al_pasar_el_tope_de_intentos_se_detiene(tmp_path):
    """Algo la mata siempre en el mismo punto: deja de reintentarse para siempre, y el
    motivo REAL viaja en el mensaje. Sin eso, la pantalla dice "se interrumpió 3 veces"
    y no de qué, y lo que la mató queda solo en un log de Render que nadie abre."""
    alm = _almacen(tmp_path)
    cid = _encolar(alm, [_item("Concreto clase D")])
    alm.corridas.finalizar_armado(cid, "armando",
                                  error="TypeError: falta el campo turno")
    _agotar_intentos(alm, config.ARMADO_MAX_INTENTOS)
    assert alm.corridas.get_corrida(cid).intentos == config.ARMADO_MAX_INTENTOS

    assert armador.un_ciclo(alm, "instancia-C") is True

    m = alm.corridas.get_corrida(cid)
    assert m.estado == "armado_detenido"
    # El NÚMERO importa: `intentos` ya cuenta la reclama que se rindió sin armar nada,
    # así que decir `intentos` a secas le inventa al usuario una interrupción de más.
    assert "se interrumpió %d veces" % config.ARMADO_MAX_INTENTOS in m.ultimo_error
    assert "TypeError: falta el campo turno" in m.ultimo_error
    assert m.armando_por is None                       # y sale de la cola sin dueño
    assert alm.corridas.get_items(cid) == []           # no armó nada: se rindió


def test_el_motivo_sin_error_previo_no_queda_con_un_cabo_suelto(tmp_path):
    """La mataron de golpe (OOM, deploy): no hay error que contar, y el mensaje no puede
    terminar en un "Último error:" vacío."""
    alm = _almacen(tmp_path)
    cid = _encolar(alm, [_item("Concreto clase D")])
    _agotar_intentos(alm, config.ARMADO_MAX_INTENTOS)

    armador.un_ciclo(alm, "instancia-C2")

    motivo = alm.corridas.get_corrida(cid).ultimo_error
    assert "Último error" not in motivo and motivo.endswith("avisá.")


def test_el_motivo_recorta_un_error_larguisimo(tmp_path):
    """Un traceback entero no entra en una línea de la interfaz."""
    alm = _almacen(tmp_path)
    cid = _encolar(alm, [_item("Concreto clase D")])
    alm.corridas.finalizar_armado(cid, "armando", error="ERR " + "x" * 3000)
    _agotar_intentos(alm, config.ARMADO_MAX_INTENTOS)

    armador.un_ciclo(alm, "instancia-C3")

    motivo = alm.corridas.get_corrida(cid).ultimo_error
    assert "ERR xxx" in motivo and motivo.endswith("…") and len(motivo) < 400


def test_justo_en_el_tope_todavia_arma(tmp_path):
    """El borde: con MAX_INTENTOS-1 reclamas previas, esta es la última que le toca y
    tiene que armar. Sin esto, un `>=` en vez de un `>` se lleva un intento entero."""
    alm = _almacen(tmp_path)
    cid = _encolar(alm, [_item("Concreto clase D")])
    _agotar_intentos(alm, config.ARMADO_MAX_INTENTOS - 1)

    assert armador.un_ciclo(alm, "instancia-D") is True
    assert alm.corridas.get_corrida(cid).estado == "en_revision"


def test_sin_plan_se_detiene_con_motivo(tmp_path):
    """Una corrida encolada antes de este deploy, o muerta entre crear y set_plan: no
    hay forma de saber qué faltaba armar, así que sale de la cola diciendo qué hacer."""
    alm = _almacen(tmp_path)
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-01-01T00:00:00", archivo="x.xlsx", turno_def="DIURNO",
        use_ai=None, estado="armando", cuadro_path=None, nombre="x"))

    assert armador.un_ciclo(alm, "instancia-E") is True

    m = alm.corridas.get_corrida(cid)
    assert m.estado == "armado_detenido"
    assert "líneas" in (m.ultimo_error or "")          # el motivo dice qué falta
    assert m.armando_por is None


def test_la_corrida_borrada_a_mitad_no_se_finaliza(tmp_path):
    """La borran mientras arma: el ciclo termina limpio y devuelve True (había trabajo,
    ya no está) SIN escribirle nada.

    Ojo con lo que prueba: el `CorridaEliminada` ya lo absorbe `armar_pendientes` y lo
    convierte en el evento 'error', así que el ciclo no reventaría igual. Lo que agrega
    la rama de `un_ciclo` —y lo único que este test puede afirmar— es que no se intente
    finalizar una corrida que ya no existe."""
    alm = _almacen(tmp_path)
    items = [_item("ACTIVIDAD %d" % i, item=str(i)) for i in range(4)]
    cid = _encolar(alm, items)
    _al_armar_item(alm, 0, lambda: alm.corridas.eliminar_corrida(cid))
    llamadas = _espiar_reclama(alm)

    assert armador.un_ciclo(alm, "instancia-F") is True

    assert alm.corridas.get_corrida(cid) is None
    assert llamadas == []          # ni un latido ni una finalización sobre lo borrado


def test_la_corrida_borrada_entre_la_reclama_y_la_lectura(tmp_path):
    """La ventana chica: el UPDATE de la reclama ya pasó y el SELECT no encuentra nada."""
    alm = _almacen(tmp_path)
    cid = _encolar(alm, [_item("Concreto clase D")])
    original = alm.corridas.reclamar_armado

    def reclamar_y_borrar(*a, **kw):
        ganada = original(*a, **kw)
        alm.corridas.eliminar_corrida(cid)
        return ganada

    alm.corridas.reclamar_armado = reclamar_y_borrar
    assert armador.un_ciclo(alm, "instancia-G") is True     # no explota


# --------------------------------------------------------------------------
# Fallo sistémico: la corrida se queda EN LA COLA
# --------------------------------------------------------------------------
def _romper_el_armado(monkeypatch) -> None:
    """Que reviente el armado de CADA ítem (el entorno caído, no un ítem venenoso).
    A los `MAX_FALLOS_SEGUIDOS_ARMADO` seguidos, `armar_pendientes` levanta."""
    def explota(*_a, **_kw):
        raise RuntimeError("la base se cayó")
    monkeypatch.setattr(svc, "_armar_fila", explota)


def test_un_fallo_sistemico_deja_la_corrida_en_la_cola(tmp_path, monkeypatch):
    """No es un ítem venenoso: es el entorno. La corrida NO se detiene, se queda en la
    cola con el motivo y sin reclama, para que se reintente ya mismo."""
    alm = _almacen(tmp_path)
    items = [_item("ACTIVIDAD %d" % i, item=str(i)) for i in range(20)]
    cid = _encolar(alm, items)
    _romper_el_armado(monkeypatch)

    assert armador.un_ciclo(alm, "instancia-H") is True

    m = alm.corridas.get_corrida(cid)
    assert m.estado == "armando"                       # SIGUE en la cola
    assert "seguidos fallaron" in (m.ultimo_error or "")
    assert m.armando_por is None and m.armando_desde is None   # reclama soltada
    # Se cortó a los 5 fallos seguidos: quedaron las 4 filas previas, no las 20.
    assert len(alm.corridas.get_items(cid)) == config.MAX_FALLOS_SEGUIDOS_ARMADO - 1


def test_un_fallo_sistemico_no_es_un_bucle_infinito(tmp_path, monkeypatch):
    """Soltar la reclama la hace reclamable EN EL ACTO, así que el bucle del worker la
    vuelve a tomar sin esperar el TTL. Lo que corta es `intentos`, que no se resetea:
    después de MAX_INTENTOS+1 ciclos queda detenida y la cola se vacía."""
    alm = _almacen(tmp_path)
    items = [_item("ACTIVIDAD %d" % i, item=str(i)) for i in range(60)]
    cid = _encolar(alm, items)
    _romper_el_armado(monkeypatch)

    ciclos = 0
    while armador.un_ciclo(alm, "instancia-I"):
        ciclos += 1
        assert ciclos <= config.ARMADO_MAX_INTENTOS + 1, "el worker no se rinde nunca"
    assert ciclos == config.ARMADO_MAX_INTENTOS + 1
    assert alm.corridas.get_corrida(cid).estado == "armado_detenido"


# --------------------------------------------------------------------------
# Fencing: la instancia viaja en TODAS las llamadas, y un zombi para
# --------------------------------------------------------------------------
# Dónde va `instancia` si se pasa por posición, para que el espía valga igual con
# `latir_armado(cid, ahora, yo)` que con `latir_armado(cid, ahora, instancia=yo)`.
_POS_INSTANCIA = {"latir_armado": 2, "finalizar_armado": 4}


def _espiar_reclama(alm) -> list:
    """Registra (metodo, instancia) de cada latido y cada finalización."""
    llamadas = []

    def envolver(nombre):
        original = getattr(alm.corridas, nombre)

        def espia(*a, **kw):
            quien = kw.get("instancia", (a[_POS_INSTANCIA[nombre]]
                                         if len(a) > _POS_INSTANCIA[nombre] else None))
            llamadas.append((nombre, quien))
            return original(*a, **kw)

        setattr(alm.corridas, nombre, espia)

    for nombre in _POS_INSTANCIA:
        envolver(nombre)
    return llamadas


@pytest.mark.parametrize("escenario, esperados", [
    ("ok", {"latir_armado", "finalizar_armado"}),
    ("sin_plan", {"finalizar_armado"}),
    ("tope", {"finalizar_armado"}),
    ("falla", {"finalizar_armado"}),
])
def test_el_worker_pasa_la_instancia_en_todas_las_llamadas(
        tmp_path, monkeypatch, escenario, esperados):
    """El fencing existe desde la reclama atómica, pero solo sirve si el worker lo usa.
    Una sola llamada sin `instancia` reabre el agujero del deploy (el worker viejo le
    suelta la reclama al dueño nuevo) y ningún otro test lo vería."""
    alm = _almacen(tmp_path)
    reloj = _RelojFalso()
    if escenario == "sin_plan":
        alm.corridas.crear_corrida(CorridaMeta(
            id=None, creada_en="2026-01-01T00:00:00", archivo="x.xlsx",
            turno_def="DIURNO", use_ai=None, estado="armando", cuadro_path=None,
            nombre="x"))
    else:
        n = 20 if escenario == "falla" else 2
        _encolar(alm, [_item("ACTIVIDAD %d" % i, item=str(i)) for i in range(n)])
        if escenario == "ok":
            # Que cada ítem cueste el intervalo: así el ciclo late de verdad.
            _al_armar_item(alm, None, lambda: reloj.avanzar(config.ARMADO_LATIDO_S))
        if escenario == "tope":
            _agotar_intentos(alm, config.ARMADO_MAX_INTENTOS)
        if escenario == "falla":
            _romper_el_armado(monkeypatch)

    llamadas = _espiar_reclama(alm)
    assert armador.un_ciclo(alm, "yo-mismo", reloj=reloj) is True

    assert {n for n, _ in llamadas} == esperados
    assert [quien for _, quien in llamadas] == ["yo-mismo"] * len(llamadas)


def _latidos(llamadas) -> int:
    return [n for n, _ in llamadas].count("latir_armado")


def test_no_late_por_item(tmp_path):
    """El latido es barato pero no gratis: uno por ítem son 1900 UPDATE de más. Con el
    reloj quieto, cinco ítems no justifican ni un latido."""
    alm = _almacen(tmp_path)
    _encolar(alm, [_item("ACTIVIDAD %d" % i, item=str(i)) for i in range(5)])
    llamadas = _espiar_reclama(alm)

    armador.un_ciclo(alm, "yo", reloj=_RelojFalso())

    assert _latidos(llamadas) == 0


def test_late_cuando_pasa_el_intervalo_aunque_sean_pocos_items(tmp_path):
    """El caso que se perdía contando ítems: DOS ítems lentos (un tramo de sub-APUs
    gordos, un pico de latencia) ya son minutos, y sin latido la reclama vence con el
    worker trabajando bien. Contando de a 25 ítems, acá no latía nadie."""
    alm = _almacen(tmp_path)
    reloj = _RelojFalso()
    _encolar(alm, [_item("ACTIVIDAD %d" % i, item=str(i)) for i in range(2)])
    # Cada ítem cuesta EXACTO el intervalo: prueba también el borde (>= y no >).
    _al_armar_item(alm, None, lambda: reloj.avanzar(config.ARMADO_LATIDO_S))
    llamadas = _espiar_reclama(alm)

    armador.un_ciclo(alm, "yo", reloj=reloj)

    assert _latidos(llamadas) == 2          # uno por ítem, porque cada ítem tardó el intervalo


def test_un_salto_largo_no_acumula_latidos_atrasados(tmp_path):
    """Un ítem que tardó TRES intervalos vale UN latido, no tres.

    La próxima cita se corre desde ahora (`= ahora + intervalo`) y no se acumula desde
    la anterior (`+= intervalo`): con la suma, después del salto quedan dos citas
    vencidas y el worker manda tres UPDATE para el mismo instante. Los otros tests del
    latido no lo ven porque avanzan el reloj en múltiplos exactos, donde las dos
    fórmulas dan lo mismo."""
    alm = _almacen(tmp_path)
    reloj = _RelojFalso()
    _encolar(alm, [_item("ACTIVIDAD %d" % i, item=str(i)) for i in range(3)])
    # Solo el primer ítem tarda; los otros dos son instantáneos.
    _al_armar_item(alm, 0, lambda: reloj.avanzar(config.ARMADO_LATIDO_S * 3))
    llamadas = _espiar_reclama(alm)

    armador.un_ciclo(alm, "yo", reloj=reloj)

    assert _latidos(llamadas) == 1


def test_el_intervalo_se_cuenta_desde_el_ultimo_latido(tmp_path):
    """Diez ítems que en total tardan un intervalo y medio: dos latidos, no diez."""
    alm = _almacen(tmp_path)
    reloj = _RelojFalso()
    _encolar(alm, [_item("ACTIVIDAD %d" % i, item=str(i)) for i in range(10)])
    _al_armar_item(alm, None, lambda: reloj.avanzar(config.ARMADO_LATIDO_S / 5))
    llamadas = _espiar_reclama(alm)

    armador.un_ciclo(alm, "yo", reloj=reloj)

    assert _latidos(llamadas) == 2          # en el ítem 5 y en el 10


def test_un_zombi_desplazado_para_de_armar(tmp_path):
    """Deploy: el worker viejo tardó más que el TTL, otra instancia le robó la corrida.
    El `False` del latido es el aviso, y parar ahí es lo que evita que dos workers armen
    la misma corrida durante horas."""
    alm = _almacen(tmp_path)
    reloj = _RelojFalso()
    items = [_item("ACTIVIDAD %d" % i, item=str(i)) for i in range(4)]
    cid = _encolar(alm, items)

    def roban_y_pasa_el_tiempo():
        _robar(alm, cid)
        reloj.avanzar(config.ARMADO_LATIDO_S)      # el primer ítem tardó el intervalo

    _al_armar_item(alm, 0, roban_y_pasa_el_tiempo)

    assert armador.un_ciclo(alm, "worker-viejo", reloj=reloj) is True

    # Paró en el primer ítem: si ignorara el `False` armaría los cuatro.
    assert len(alm.corridas.get_items(cid)) == 1
    m = alm.corridas.get_corrida(cid)
    assert m.armando_por == "instancia-ladrona"    # la reclama del dueño nuevo, intacta
    assert m.estado == "armando"                   # y el zombi no la sacó de la cola


def test_el_zombi_tampoco_finaliza_la_corrida_del_otro(tmp_path):
    """Le roban la reclama en el ÚLTIMO ítem, cuando ya no queda latido por hacer: el
    fencing de `finalizar_armado` es lo único que impide que el zombi le suelte la
    reclama al dueño nuevo (y peor, la deje 'armando' sin dueño para que una tercera
    instancia la tome y armen las dos)."""
    alm = _almacen(tmp_path)
    items = [_item("ACTIVIDAD %d" % i, item=str(i)) for i in range(3)]
    cid = _encolar(alm, items)                     # 3 ítems: no llega a ningún latido
    _al_armar_item(alm, 2, lambda: _robar(alm, cid))

    assert armador.un_ciclo(alm, "worker-viejo") is True

    m = alm.corridas.get_corrida(cid)
    assert m.estado == "armando"                   # NO la pasó a en_revision
    assert m.armando_por == "instancia-ladrona"
    # Y se cura sola: el dueño nuevo la retoma, no encuentra nada que armar y la cierra.
    assert armador.un_ciclo(alm, "instancia-ladrona") is False   # la reclama sigue viva
    alm.corridas.latir_armado(cid, "2026-01-01T00:00:00")        # la vence a mano
    assert armador.un_ciclo(alm, "instancia-nueva") is True
    assert alm.corridas.get_corrida(cid).estado == "en_revision"
    assert len(alm.corridas.get_items(cid)) == 3                 # sin duplicar nada


# --------------------------------------------------------------------------
# El bucle y la identidad (lo poco que no es `un_ciclo`)
# --------------------------------------------------------------------------
def test_el_bucle_no_se_muere_por_una_excepcion(monkeypatch):
    """El hilo es uno solo y no lo revive nadie: si se muere, los armados dejan de
    correr hasta el próximo deploy y nadie se entera."""
    parar = threading.Event()
    vueltas = []

    def un_ciclo_falso(_alm, instancia):
        vueltas.append(instancia)
        if len(vueltas) == 1:
            raise RuntimeError("la base se cayó")
        parar.set()                    # segunda vuelta: cortamos el bucle
        return False

    monkeypatch.setattr(armador, "un_ciclo", un_ciclo_falso)
    monkeypatch.setattr(config, "ARMADO_POLL_S", 0)   # ninguna espera puede colgar esto
    armador.hay_trabajo.set()          # el wait() no espera el poll: el test no duerme
    armador.correr_para_siempre(None, parar)

    assert len(vueltas) == 2           # hubo segunda vuelta: la excepción no lo mató


class _EventoQueCuenta(threading.Event):
    """El `hay_trabajo` del worker, contando cuántas veces lo esperaron. Nunca duerme."""

    def __init__(self):
        super().__init__()
        self.esperas = 0

    def wait(self, timeout=None):
        self.esperas += 1
        return super().wait(0)


def test_el_bucle_sale_sin_esperar_el_poll(monkeypatch):
    """Con la parada puesta no se queda esperando: si esperara, apagar la app costaría
    hasta ARMADO_POLL_S de más por cada worker."""
    parar = threading.Event()
    evento = _EventoQueCuenta()
    monkeypatch.setattr(armador, "un_ciclo", lambda _alm, _i: parar.set() or False)
    monkeypatch.setattr(armador, "hay_trabajo", evento)
    armador.correr_para_siempre(None, parar)
    assert parar.is_set() and evento.esperas == 0


def test_el_bucle_drena_la_cola_entera_sin_volver_a_esperar(monkeypatch):
    """Tres corridas en la cola se arman SEGUIDAS, en una vuelta. Con un `if` en vez del
    `while`, la cola se drenaría a una corrida por poll —30 s de aire entre armados de
    horas— y no lo notaría nadie."""
    parar = threading.Event()
    evento = _EventoQueCuenta()
    respuestas = [True, True, False]
    llamadas = []

    def un_ciclo_falso(_alm, _instancia):
        llamadas.append(1)
        hubo = respuestas.pop(0) if respuestas else False
        if not hubo:
            parar.set()                # la cola quedó vacía: cortamos el test acá
        return hubo

    monkeypatch.setattr(armador, "un_ciclo", un_ciclo_falso)
    monkeypatch.setattr(armador, "hay_trabajo", evento)
    armador.correr_para_siempre(None, parar)

    assert len(llamadas) == 3          # las tres seguidas...
    assert evento.esperas == 0         # ...sin pasar por el poll en el medio


def test_el_bucle_limpia_el_evento_despues_de_esperarlo(monkeypatch):
    """Sin el `clear()`, `wait()` sobre un Event ya levantado vuelve al instante: el
    worker martillaría `reclamar_armado` contra la base en bucle cerrado, con la cola
    vacía y sin ningún backoff."""
    parar = threading.Event()
    vueltas = []

    def un_ciclo_falso(_alm, _instancia):
        vueltas.append(1)
        if len(vueltas) == 2:
            parar.set()
        return False

    monkeypatch.setattr(armador, "un_ciclo", un_ciclo_falso)
    monkeypatch.setattr(config, "ARMADO_POLL_S", 0)   # ninguna espera puede colgar esto
    armador.hay_trabajo.set()

    armador.correr_para_siempre(None, parar)

    assert len(vueltas) == 2           # esperó el evento y volvió a trabajar
    assert not armador.hay_trabajo.is_set()


def test_id_de_instancia(monkeypatch):
    monkeypatch.setenv("RENDER_INSTANCE_ID", "srv-abc-123")
    yo = armador.id_de_instancia()
    assert yo.startswith("srv-abc-123")
    # El id de Render es de la MÁQUINA y los procesos de gunicorn lo heredan igual: sin
    # el PID, dos workers de la misma instancia se llaman igual y el fencing no filtra
    # nada (cada uno se cree dueño de la reclama del otro).
    assert str(os.getpid()) in yo
    monkeypatch.delenv("RENDER_INSTANCE_ID")
    assert armador.id_de_instancia() != armador.id_de_instancia()


# --------------------------------------------------------------------------
# La app enciende y apaga el worker (Tarea 9: el commit que prende la feature)
# --------------------------------------------------------------------------
def test_la_app_arranca_y_para_el_worker(tmp_path):
    alm = _almacen(tmp_path)
    app = create_app(almacen=alm)
    with TestClient(app):
        assert app.state.armador_hilo.is_alive()
    assert app.state.armador_parar.is_set()      # el lifespan lo apagó al salir


def test_la_app_arma_de_punta_a_punta_una_corrida_encolada(tmp_path):
    """El único test que prueba que el cableado quedó bien: `arrancar()` con el
    almacén correcto, sobre el hilo correcto, agarrando la cola de verdad. Los demás
    tests de este archivo prueban `un_ciclo` a mano y no verían un `arrancar(Almacen())`
    -con un almacén nuevo en vez de `app.state.almacen`- ni un `arrancar()` puesto
    DESPUÉS del `yield`.

    Determinístico sin dormir: la corrida ya está encolada ANTES de crear la app, así
    que el primer `un_ciclo` del bucle (que corre ANTES de esperar `hay_trabajo`, ver
    `correr_para_siempre`) la agarra apenas arranca el hilo, sin depender de ningún
    timing. Lo que el test espera no es un reloj: es un espía sobre `finalizar_armado`
    que levanta un `Event` cuando el ciclo termina; el `timeout` es solo una red por si
    algo se rompe, no la señal de éxito."""
    alm = _almacen(tmp_path)
    cid = _encolar(alm, [_item("Concreto clase D")])
    terminado = threading.Event()
    original = alm.corridas.finalizar_armado

    def espia(*a, **kw):
        try:
            return original(*a, **kw)
        finally:
            terminado.set()

    alm.corridas.finalizar_armado = espia
    app = create_app(almacen=alm)

    with TestClient(app):
        assert terminado.wait(timeout=5), "el worker de la app no armó la corrida"

    m = alm.corridas.get_corrida(cid)
    assert m.estado == "en_revision"
    assert len(alm.corridas.get_items(cid)) == 1


# ---------------------------------------------------------------------------
# El invariante: `estado='armando'` ES la cola.
# ---------------------------------------------------------------------------
def test_ninguna_operacion_de_fila_saca_la_corrida_de_la_cola(tmp_path):
    """`armando` no es una etiqueta informativa: es la cola del worker.

    Un `set_estado` sin guarda la borra de ahí para siempre — la corrida queda a
    medio armar, sin nadie que la retome y sin error que mirar. Hoy los puntos que
    escriben `estado` están todos guardados por `estado == "finalizada"`, así que
    nadie lo rompe; este test existe para el PRÓXIMO que agregue uno, que no va a
    tener este contexto.

    Se ejercitan las operaciones que actúan sobre filas de una corrida ya armada y
    que sí tocan `estado` en alguna rama (las dos vuelven a `en_revision` una corrida
    `finalizada`, porque el cuadro emitido dejó de decir la verdad).

    `igualar_costo_al_contractual` ahora tiene SU PROPIO candado de plan-a-medias
    (`_exigir_editable`, el mismo de `_exigir_rebuscable`) y rechaza de entrada con
    `ValueError` — ni siquiera llega a mirar `estado == "finalizada"`. Eso es MÁS
    estricto que "no saca la corrida de la cola", así que la excepción también prueba
    el invariante de este test: falla antes de tocar nada."""
    alm = _almacen(tmp_path)
    items = [_item("Concreto clase D"), _item("Concreto clase D")]
    cid = svc.crear_corrida_encolada(alm, "x.xlsx", items, "DIURNO", None,
                                     carpeta_id=_carpeta(alm))
    for _ in svc.armar_pendientes(alm, cid, items[:1]):
        pass                                   # media corrida: sigue en la cola

    svc.confirmar_items(alm, cid, [0])
    assert alm.corridas.get_corrida(cid).estado == "armando"

    with pytest.raises(ValueError):
        svc.igualar_costo_al_contractual(alm, cid, [0])
    assert alm.corridas.get_corrida(cid).estado == "armando"

    # Y sigue siendo reclamable: la cola no se rompió, no solo el rótulo.
    assert alm.corridas.reclamar_armado(
        "instancia-test", "2099-01-01T00:00:00", "2098-01-01T00:00:00") == cid
