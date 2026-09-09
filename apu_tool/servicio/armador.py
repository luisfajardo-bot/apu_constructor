"""El worker del armado: un hilo que consume la cola que vive en la base.

`corrida.estado == 'armando'` ES la cola. No hay estructura en memoria que se pueda
perder en un reinicio: al arrancar, la instancia ve exactamente el mismo trabajo
pendiente que dejó la anterior.

Por qué un hilo acá y no un Background Worker de Render: un servicio aparte cuesta
plata y otro deploy, y sigue muriendo y reiniciándose — o sea, necesitarías reanudar
igual. El día que la web se ponga lenta durante un armado, mudarlo es cambiar quién
llama a `correr_para_siempre`: todo lo demás lee su trabajo de la base.

El FENCING (`instancia=` en cada latido y en cada finalización) no es decorativo: en un
deploy de Render la instancia nueva arranca mientras la vieja drena, y si la vieja tarda
más que el TTL la nueva reclama la corrida. Sin fencing, la vieja termina y le suelta la
reclama al dueño legítimo; con `estado='armando'` es peor, porque una tercera la reclama
y quedan dos armando la misma corrida. Si a alguna llamada de este módulo se le olvida
la instancia, el agujero vuelve por ahí.
"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from datetime import datetime, timedelta

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.servicio import corridas as svc

logger = logging.getLogger(__name__)

# Se levanta al crear una corrida para que el worker arranque YA en vez de esperar el
# poll. El poll sigue existiendo porque al bootear no hay ningún evento que levantar.
hay_trabajo = threading.Event()


def id_de_instancia() -> str:
    """Quién es esta instancia, para la reclama. En Render viene en el entorno; si no,
    un uuid alcanza. Lo único que importa es que dos procesos NO se llamen igual.

    Por eso lleva el PID pegado: `RENDER_INSTANCE_ID` identifica la MÁQUINA y los
    procesos de gunicorn (`WEB_CONCURRENCY`, hoy 1 pero por default 2) lo heredan
    idéntico. Dos dueños con el mismo nombre dejan el fencing sin efecto: al que le
    robaron la reclama le sigue pareciendo suya y la finaliza igual, que es justo el
    doble armado que el fencing existe para cortar."""
    maquina = os.environ.get("RENDER_INSTANCE_ID") or "local-%s" % uuid.uuid4().hex[:8]
    return "%s-%d" % (maquina, os.getpid())


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _acortar(texto: str, tope: int) -> str:
    """Un motivo tiene que entrar en una línea de la pantalla, no en una pared de texto."""
    texto = " ".join(texto.split())        # un traceback de varias líneas se aplana
    return texto if len(texto) <= tope else texto[:tope - 1].rstrip() + "…"


def _motivo_detenida(meta) -> str:
    """El mensaje que va a leer una persona cuando una corrida se rinde.

    Lleva pegado el último error REAL: sin él dice "se interrumpió 3 veces" y no de qué,
    y lo que la mató las tres veces queda solo en un log de Render que nadie va a abrir.
    Sin error previo (la mataron de golpe: OOM, deploy) no se agrega nada, para que el
    mensaje no quede con un cabo suelto."""
    detalle = _acortar(meta.ultimo_error or "", 200)
    return ("El armado se interrumpió %d veces seguidas. Puede ser un reinicio del "
            "servidor o un problema con el archivo. Reintentá; si vuelve a pasar, "
            "avisá.%s" % (meta.intentos, (" Último error: %s" % detalle) if detalle else ""))


def _limite_vencimiento() -> str:
    vencido = datetime.now() - timedelta(seconds=config.ARMADO_TTL_RECLAMA_S)
    return vencido.isoformat(timespec="seconds")


def un_ciclo(alm: Almacen, instancia: str, reloj=time.monotonic) -> bool:
    """Reclama UNA corrida y la arma entera. Devuelve si había trabajo.

    Separado de `correr_para_siempre` para poder testear el ciclo sin hilo, sin
    dormir y sin app: los tests llaman a esto.

    `reloj` es el cronómetro del latido y de la duración: monótono (no `datetime`, que
    un ajuste de hora corre para atrás) e inyectable, para que un test pueda adelantarlo
    a mano en vez de dormir un minuto.
    """
    corrida_id = alm.corridas.reclamar_armado(instancia, _ahora(), _limite_vencimiento())
    if corrida_id is None:
        return False

    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:                       # la borraron entre el UPDATE y el SELECT
        return True
    if meta.intentos > config.ARMADO_MAX_INTENTOS:
        # Sale de la cola o se reintentaría para siempre. El usuario la puede
        # reencolar a mano desde la pantalla (POST /corridas/{id}/reanudar).
        _finalizar(alm, corrida_id, "armado_detenido", instancia,
                   error=_motivo_detenida(meta))
        return True

    try:
        items = svc.plan_de(alm, corrida_id)
        if not items:
            # Encolada antes de que existiera el plan, o muerta entre `crear_corrida` y
            # `set_plan`. No hay forma de saber qué faltaba armar: el Excel no se guarda.
            _finalizar(alm, corrida_id, "armado_detenido", instancia,
                       error="La corrida no tiene guardadas las líneas a armar. "
                             "Volvé a subir el archivo en una corrida nueva.")
            return True
        # `max_seq + 1` y no la cantidad de filas: con un hueco en el medio, contar
        # reanudaría sobre un seq que ya existe.
        desde = alm.corridas.max_seq(corrida_id) + 1
        t0 = reloj()
        proximo_latido = t0 + config.ARMADO_LATIDO_S
        hechos = 0
        for evento, _payload in svc.armar_pendientes(alm, corrida_id, items, desde):
            if evento == "error":          # la corrida se borró a mitad
                return True
            hechos += 1
            # Por tiempo y no cada N ítems: lo que vence es un lease. Un tramo de
            # sub-APUs gordos o un pico de latencia hacían vencer la reclama con el
            # worker trabajando bien, y ahí se perdía una hora de armado por nada.
            ahora_mono = reloj()
            if ahora_mono >= proximo_latido:
                proximo_latido = ahora_mono + config.ARMADO_LATIDO_S
                if not alm.corridas.latir_armado(corrida_id, _ahora(), instancia):
                    # Nos desplazaron: la corrida ya tiene otro dueño y esto es un
                    # zombi. Parar acá es lo único que evita armar en paralelo con el
                    # dueño durante horas hasta chocar contra `ux_corrida_item_seq`.
                    # No se finaliza NADA: la corrida no es nuestra. Lo ya escrito no
                    # se pierde ni molesta — el dueño reanuda en `max_seq + 1`.
                    logger.warning(
                        "La corrida %s ya no es de %s (reclama perdida): se corta el "
                        "armado en el ítem %s", corrida_id, instancia, hechos)
                    return True
        # Si nos la robaron sobre el final, el fencing hace que esto no escriba nada
        # (`_finalizar` avisa). Se cura sola: el dueño nuevo la retoma, no encuentra
        # ítems pendientes y la cierra él.
        _finalizar(alm, corrida_id, "en_revision", instancia,
                   duracion_ms=round((reloj() - t0) * 1000))
    except Exception as exc:               # noqa: BLE001
        # Un fallo que NO es de un ítem (esos ya los absorbe `armar_pendientes`):
        # se deja la corrida EN LA COLA con el motivo, para que se reintente. Soltar la
        # reclama la hace reclamable en el acto, sin esperar el TTL; `intentos` no se
        # toca, así que el tope la termina deteniendo si el fallo es permanente.
        logger.exception("Fallo armando la corrida %s", corrida_id)
        _finalizar(alm, corrida_id, "armando", instancia, error=_acortar(str(exc), 500))
    return True


def _finalizar(alm: Almacen, corrida_id: int, estado: str, instancia: str,
               duracion_ms: int | None = None, error: str | None = None) -> bool:
    """`finalizar_armado` SIEMPRE con fencing, y avisando si la reclama ya no era nuestra.

    Existe para que no haya forma de escribir en este módulo una finalización sin
    `instancia`: son cuatro llamadas y con que a una se le olvide, el agujero del deploy
    vuelve y ningún test lo ve."""
    aplico = alm.corridas.finalizar_armado(corrida_id, estado, duracion_ms=duracion_ms,
                                           error=error, instancia=instancia)
    if not aplico:
        logger.warning("No se pudo dejar la corrida %s en '%s': la reclama ya no es de %s",
                       corrida_id, estado, instancia)
    return aplico


def correr_para_siempre(alm: Almacen, parar: threading.Event) -> None:
    """El bucle del hilo. Trabaja hasta vaciar la cola, después espera un evento (una
    corrida nueva) o el poll de respaldo."""
    instancia = id_de_instancia()
    logger.info("Worker de armado arrancado (instancia %s)", instancia)
    while not parar.is_set():
        try:
            while not parar.is_set() and un_ciclo(alm, instancia):
                pass
        except Exception:                  # noqa: BLE001 — el hilo NUNCA se muere
            # Si este hilo muere no lo revive nadie: los armados dejan de correr hasta
            # el próximo deploy y nadie se entera. Se loggea y se sigue.
            logger.exception("Error en el bucle del worker de armado")
        if parar.is_set():
            break                          # apagar no puede costar un poll de espera
        hay_trabajo.wait(timeout=config.ARMADO_POLL_S)
        # Se limpia DESPUÉS de esperar: un evento que llegue en esta rendija se pierde,
        # y lo cubre el poll (30 s de demora, no un armado colgado para siempre).
        hay_trabajo.clear()


def arrancar(alm: Almacen):
    """Lanza el hilo en daemon y devuelve (hilo, evento-de-parada)."""
    parar = threading.Event()
    hilo = threading.Thread(target=correr_para_siempre, args=(alm, parar),
                            name="armador", daemon=True)
    hilo.start()
    return hilo, parar
