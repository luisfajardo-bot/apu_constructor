"""El worker del armado: un ciclo, sin hilo y sin dormir.

Todo se prueba contra `un_ciclo`, que reclama y arma UNA corrida y vuelve. El bucle
(`correr_para_siempre`) solo se prueba en lo suyo —que una excepción no lo mate— y con
los dos eventos ya puestos, así que ningún test de acá duerme ni lanza un hilo.
"""
import threading
from datetime import datetime, timedelta

import pytest

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import (
    Apu, ApuComponent, CorridaMeta, Insumo, LicitacionItem)
from apu_tool.servicio import armador, corridas as svc


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


def _al_armar_item(alm, seq_gatillo: int, accion):
    """Corre `accion()` justo después de que se persista la fila `seq_gatillo`.

    Es el único punto de enganche determinístico que hay a mitad de un armado, y sirve
    para meter la carrera real (otra instancia roba la reclama) sin hilos ni sleeps."""
    original = alm.corridas.agregar_item

    def espia(corrida_id, fila):
        original(corrida_id, fila)
        if fila.seq == seq_gatillo:
            accion()

    alm.corridas.agregar_item = espia


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
    """Algo la mata siempre en el mismo punto: deja de reintentarse para siempre."""
    alm = _almacen(tmp_path)
    cid = _encolar(alm, [_item("Concreto clase D")])
    _agotar_intentos(alm, config.ARMADO_MAX_INTENTOS)
    assert alm.corridas.get_corrida(cid).intentos == config.ARMADO_MAX_INTENTOS

    assert armador.un_ciclo(alm, "instancia-C") is True

    m = alm.corridas.get_corrida(cid)
    assert m.estado == "armado_detenido"
    assert "interrump" in (m.ultimo_error or "").lower()
    assert m.armando_por is None                       # y sale de la cola sin dueño
    assert alm.corridas.get_items(cid) == []           # no armó nada: se rindió


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


def test_la_corrida_borrada_a_mitad_no_revienta_el_ciclo(tmp_path):
    """La borran mientras arma: el ciclo termina limpio y devuelve True (había
    trabajo, ya no está). Sin esto, `agregar_item` levanta CorridaEliminada."""
    alm = _almacen(tmp_path)
    items = [_item("ACTIVIDAD %d" % i, item=str(i)) for i in range(4)]
    cid = _encolar(alm, items)
    _al_armar_item(alm, 0, lambda: alm.corridas.eliminar_corrida(cid))

    assert armador.un_ciclo(alm, "instancia-F") is True
    assert alm.corridas.get_corrida(cid) is None


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
    if escenario == "sin_plan":
        alm.corridas.crear_corrida(CorridaMeta(
            id=None, creada_en="2026-01-01T00:00:00", archivo="x.xlsx",
            turno_def="DIURNO", use_ai=None, estado="armando", cuadro_path=None,
            nombre="x"))
    else:
        n = 20 if escenario == "falla" else 2
        _encolar(alm, [_item("ACTIVIDAD %d" % i, item=str(i)) for i in range(n)])
        if escenario == "ok":
            monkeypatch.setattr(config, "ARMADO_LATIDO_CADA", 1)   # que lata en 2 ítems
        if escenario == "tope":
            _agotar_intentos(alm, config.ARMADO_MAX_INTENTOS)
        if escenario == "falla":
            _romper_el_armado(monkeypatch)

    llamadas = _espiar_reclama(alm)
    assert armador.un_ciclo(alm, "yo-mismo") is True

    assert {n for n, _ in llamadas} == esperados
    assert [quien for _, quien in llamadas] == ["yo-mismo"] * len(llamadas)


def test_late_cada_N_items_y_no_por_item(tmp_path, monkeypatch):
    """El latido es barato pero no gratis: uno por ítem son 1900 UPDATE de más."""
    alm = _almacen(tmp_path)
    monkeypatch.setattr(config, "ARMADO_LATIDO_CADA", 2)
    _encolar(alm, [_item("ACTIVIDAD %d" % i, item=str(i)) for i in range(5)])
    llamadas = _espiar_reclama(alm)

    armador.un_ciclo(alm, "yo")

    assert [n for n, _ in llamadas].count("latir_armado") == 2   # en el 2º y el 4º


def test_un_zombi_desplazado_para_de_armar(tmp_path, monkeypatch):
    """Deploy: el worker viejo tardó más que el TTL, otra instancia le robó la corrida.
    El `False` del latido es el aviso, y parar ahí es lo que evita que dos workers armen
    la misma corrida durante horas."""
    alm = _almacen(tmp_path)
    monkeypatch.setattr(config, "ARMADO_LATIDO_CADA", 1)   # late tras cada ítem
    items = [_item("ACTIVIDAD %d" % i, item=str(i)) for i in range(4)]
    cid = _encolar(alm, items)
    _al_armar_item(alm, 0, lambda: _robar(alm, cid))

    assert armador.un_ciclo(alm, "worker-viejo") is True

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


class _EventoQueNoSeEspera(threading.Event):
    def wait(self, timeout=None):
        raise AssertionError("el bucle esperó el poll con la parada ya puesta")


def test_el_bucle_sale_sin_esperar_el_poll(monkeypatch):
    """Con la parada puesta no se queda esperando: si esperara, apagar la app costaría
    hasta ARMADO_POLL_S de más por cada worker."""
    parar = threading.Event()
    monkeypatch.setattr(armador, "un_ciclo", lambda _alm, _i: parar.set() or False)
    monkeypatch.setattr(armador, "hay_trabajo", _EventoQueNoSeEspera())
    armador.correr_para_siempre(None, parar)
    assert parar.is_set()


def test_id_de_instancia(monkeypatch):
    monkeypatch.setenv("RENDER_INSTANCE_ID", "srv-abc-123")
    assert armador.id_de_instancia() == "srv-abc-123"
    monkeypatch.delenv("RENDER_INSTANCE_ID")
    # Lo único que importa fuera de Render: que dos procesos no se llamen igual.
    assert armador.id_de_instancia() != armador.id_de_instancia()
