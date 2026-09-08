"""Contrato del repositorio de corridas: la MISMA batería contra los dos backends.

SQLite corre siempre; Postgres solo con TEST_DATABASE_URL. Existe porque
`test_repositorios_contrato.py` cubre precios y apus pero NO corridas, y esa
brecha ya dejó pasar un bug de CorridasPg.
"""
import os
from contextlib import contextmanager

import pytest

from apu_tool.nucleo.models import CorridaItemRow, CorridaMeta, LicitacionItem


def _corridas_sqlite(tmp_path):
    from apu_tool.datos.corridas_db import CorridasDB
    r = CorridasDB(tmp_path / "corridas.db")
    r.init_schema()
    return r, None


def _corridas_postgres(tmp_path):
    from apu_tool.datos.pg.conexion import Conexion
    from apu_tool.datos.pg.corridas_pg import CorridasPg
    cx = Conexion(os.environ["TEST_DATABASE_URL"])
    r = CorridasPg(cx)
    r.reset()
    return r, cx


_BACKENDS = ["sqlite"]
if os.environ.get("TEST_DATABASE_URL"):
    _BACKENDS.append("postgres")


@pytest.fixture(params=_BACKENDS)
def repo(request, tmp_path):
    r, cx = (_corridas_sqlite(tmp_path) if request.param == "sqlite"
             else _corridas_postgres(tmp_path))
    yield r
    if cx is not None:
        cx.cerrar()


def _abrir_conn(repo):
    """Context manager de una conexión propia del llamador, por backend.

    Es el camino que usa el servicio: mete la escritura en la MISMA transacción que
    la auditoría. SQLite (`CorridasDB.connect`) commitea al salir OK y descarta si
    sale por excepción (cierra sin commit); Postgres delega en el pool, que hace
    commit o rollback al salir. `CorridasPg` tiene `.cx`, `CorridasDB` no.
    """
    cx = getattr(repo, "cx", None)
    return cx.transaccion() if cx is not None else repo.connect()


def _item(seq: int, contractual: float) -> CorridaItemRow:
    return CorridaItemRow(
        seq=seq,
        item=LicitacionItem(item=str(seq), descripcion=f"ACTIVIDAD {seq}", unidad="GLB",
                            cantidad=1.0, precio_contractual=contractual, shift="DIURNO"),
        status="new", apu_codigo=None, apu_nombre="", unidad="GLB", shift="DIURNO",
        origen="historico", confianza=0.0, explicacion="", componentes=[], candidatos=[])


def _corrida_con(repo, *filas) -> int:
    cid = repo.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-09-07T10:00:00", archivo="x.xlsx", turno_def="DIURNO",
        use_ai=None, estado="en_revision", cuadro_path=None, nombre="x"))
    repo.guardar_items(cid, list(filas))
    return cid


def test_costo_manual_arranca_en_none(repo):
    cid = _corrida_con(repo, _item(0, 1000.0))
    assert repo.get_items(cid)[0].costo_manual is None


def test_set_costo_manual_persiste_y_confirma(repo):
    """Un lote de verdad: varias filas en UNA llamada, y las no pedidas intactas."""
    cid = _corrida_con(repo, _item(0, 92106000.0), _item(1, 500.0),
                       _item(2, 10115000.0), _item(3, 700.0))
    repo.set_costo_manual(cid, {0: 92106000.0, 2: 10115000.0})
    filas = {r.seq: r for r in repo.get_items(cid)}
    assert filas[0].costo_manual == 92106000.0
    assert filas[0].status == "confirmed"      # la resolvió una persona a propósito
    assert filas[2].costo_manual == 10115000.0
    assert filas[2].status == "confirmed"
    for seq in (1, 3):                         # las que no se pidieron no se tocan
        assert filas[seq].costo_manual is None
        assert filas[seq].status == "new"


def test_set_costo_manual_es_float_no_decimal(repo):
    """Postgres devuelve numeric como Decimal y Decimal+float explota al sumar totales."""
    cid = _corrida_con(repo, _item(0, 1500.0))
    repo.set_costo_manual(cid, {0: 1500.0})
    assert isinstance(repo.get_items(cid)[0].costo_manual, float)


def test_actualizar_eleccion_borra_el_costo_manual(repo):
    """Armaste el APU de verdad y lo asignaste: el costo a mano ya no manda."""
    cid = _corrida_con(repo, _item(0, 1500.0))
    repo.set_costo_manual(cid, {0: 1500.0})
    repo.actualizar_eleccion(
        cid, 0, status="confirmed", apu_codigo="100", apu_nombre="EXCAVACION",
        unidad="M3", shift="DIURNO", origen="historico", confianza=1.0,
        explicacion="", componentes=[{"insumo_codigo": "4279", "insumo_nombre": "CUADRILLA",
                                      "unidad": "HR", "rendimiento": 1.0}])
    assert repo.get_items(cid)[0].costo_manual is None


def test_set_costo_manual_vacio_no_escribe(repo):
    cid = _corrida_con(repo, _item(0, 1000.0))
    repo.set_costo_manual(cid, {})
    fila = repo.get_items(cid)[0]
    assert fila.costo_manual is None
    assert fila.status == "new"      # sin esto el test no podría fallar: ya era None


def test_set_costo_manual_borra_el_veredicto(repo):
    """Poner el costo a mano ES un confirm: el veredicto de la IA hablaba de una fila
    que ya no es esta. Si sobreviviera, el badge quedaría al lado de un 'no tiene APU'."""
    cid = _corrida_con(repo, _item(0, 1500.0))
    repo.set_revision(cid, 0, {"dictamen": "sin_apu", "apu_evaluado": None})
    assert repo.get_items(cid)[0].revision is not None
    repo.set_costo_manual(cid, {0: 1500.0})
    assert repo.get_items(cid)[0].revision is None


def test_conn_del_llamador_commitea(repo):
    """El camino de producción: la escritura entra en la transacción del llamador
    (junto con la auditoría) y queda cuando esa transacción sale OK."""
    cid = _corrida_con(repo, _item(0, 1500.0))
    with _abrir_conn(repo) as conn:
        repo.set_costo_manual(cid, {0: 1500.0}, conn=conn)
    assert repo.get_items(cid)[0].costo_manual == 1500.0


def test_conn_del_llamador_descarta_si_revienta(repo):
    """Si la transacción del llamador falla (p.ej. la auditoría), el costo a mano no
    queda escrito a medias: se va con el rollback."""
    cid = _corrida_con(repo, _item(0, 1500.0))
    with pytest.raises(RuntimeError):
        with _abrir_conn(repo) as conn:
            repo.set_costo_manual(cid, {0: 1500.0}, conn=conn)
            raise RuntimeError("la auditoría falló")
    fila = repo.get_items(cid)[0]
    assert fila.costo_manual is None
    assert fila.status == "new"


def test_corrida_nace_con_los_campos_del_armado_en_cero(repo):
    """Los campos del armado tienen default seguro: una corrida vieja (o recién
    creada) no está reclamada por nadie y no acumuló intentos."""
    cid = repo.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-09-07T10:00:00", archivo="x.xlsx", turno_def="DIURNO",
        use_ai=None, estado="en_revision", cuadro_path=None, nombre="x"))
    m = repo.get_corrida(cid)
    assert m.intentos == 0
    assert m.ultimo_error is None
    assert m.armando_por is None
    assert m.armando_desde is None


def test_listar_corridas_no_pierde_ninguna_columna(repo):
    """Guarda de `_COLS_META`: `listar_corridas` dejó de usar `SELECT *` (plan_json
    pesa ~400 KB por corrida y ese listado las trae todas), y `_row_to_meta` decide
    campo por campo con "está en la fila?". O sea: si una columna se cae de la lista
    explícita, ese campo NO explota — queda en su default, EN SILENCIO, y una corrida
    se lista con el modo o la tarifa equivocados.

    Por eso se crea con valores distintos del default en todo lo que se pueda: si
    alguno vuelve como default, es que su columna se perdió."""
    cid = repo.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-09-07T11:00:00", archivo="lista.xlsx",
        turno_def="NOCTURNO", use_ai=True, estado="finalizada",
        cuadro_path="salidas/cuadro.xlsx", duracion_ms=4321, modo="congelada",
        nombre="Mi corrida", lista_precios_id=7))
    listada = next(c for c in repo.listar_corridas() if c.id == cid)
    completa = repo.get_corrida(cid)
    # Lo que trae el listado tiene que ser IDÉNTICO a leerla de a una.
    assert listada == completa


def test_plan_se_guarda_y_se_lee_igual(repo):
    cid = repo.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-09-07T10:00:00", archivo="x.xlsx", turno_def="DIURNO",
        use_ai=None, estado="en_revision", cuadro_path=None, nombre="x"))
    assert repo.get_plan(cid) is None          # sin plan todavía
    repo.set_plan(cid, '[{"descripcion": "EXCAVACION"}]')
    assert repo.get_plan(cid) == '[{"descripcion": "EXCAVACION"}]'


def test_max_seq_dice_donde_reanudar(repo):
    """-1 con la corrida vacía, para que `max_seq + 1` dé 0 y arranque del principio."""
    cid = repo.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-09-07T10:00:00", archivo="x.xlsx", turno_def="DIURNO",
        use_ai=None, estado="en_revision", cuadro_path=None, nombre="x"))
    assert repo.max_seq(cid) == -1
    repo.agregar_item(cid, _item(0, 1000.0))
    repo.agregar_item(cid, _item(1, 1000.0))
    assert repo.max_seq(cid) == 1


def test_max_seq_ignora_los_huecos(repo):
    """El worker reanuda en `max_seq + 1`. Si contara filas en vez de mirar el máximo,
    con un hueco reanudaría sobre un `seq` que YA existe y la fila entraría duplicada.

    El hueco es de DOS filas a propósito: borrando una sola no-máxima de una secuencia
    contigua, `COUNT(*)` y `MAX(seq)` dan siempre lo mismo y el test no distinguiría
    una implementación de la otra. Con 0,1,2,3 menos la 1 y la 2 quedan COUNT=2 y
    MAX=3, que es lo único que separa las dos implementaciones."""
    cid = repo.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-09-07T10:00:00", archivo="x.xlsx", turno_def="DIURNO",
        use_ai=None, estado="en_revision", cuadro_path=None, nombre="x"))
    for s in (0, 1, 2, 3):
        repo.agregar_item(cid, _item(s, 1000.0))
    repo.borrar_items(cid, [1, 2])
    assert repo.max_seq(cid) == 3


# ---- la cola del armado: reclama atómica ----

def _en_cola(repo, creada_en: str, estado: str = "armando") -> int:
    """Una corrida con la fecha y el estado que hace falta para probar la cola.

    Mismo `crear_corrida(CorridaMeta(...))` de arriba: lo único que varía entre estos
    tests es `creada_en` (el orden de la cola) y `estado` (quién entra a la cola)."""
    return repo.crear_corrida(CorridaMeta(
        id=None, creada_en=creada_en, archivo="x.xlsx", turno_def="DIURNO",
        use_ai=None, estado=estado, cuadro_path=None, nombre="x"))


def test_reclamar_toma_la_mas_vieja_y_solo_una_vez(repo):
    """La reclama es un UPDATE condicional: dos workers compitiendo, uno solo gana.
    Es lo que cierra la ventana del deploy, cuando la instancia nueva arranca
    mientras la vieja todavia esta armando."""
    vieja = _en_cola(repo, "2026-01-01T00:00:00")
    _en_cola(repo, "2026-01-02T00:00:00")

    ganada = repo.reclamar_armado("instancia-A", "2026-01-03T10:00:00", "2026-01-03T09:57:00")
    assert ganada == vieja                      # la más vieja primero

    # Segunda pasada con la reclama todavía fresca: NO la puede volver a tomar.
    otra = repo.reclamar_armado("instancia-B", "2026-01-03T10:00:10", "2026-01-03T09:57:10")
    assert otra != vieja


def test_una_reclama_vencida_se_puede_retomar(repo):
    cid = _en_cola(repo, "2026-01-01T00:00:00")
    repo.reclamar_armado("instancia-A", "2026-01-03T10:00:00", "2026-01-03T09:57:00")
    # El límite de vencimiento ya pasó la hora del latido de A: la instancia murió.
    assert repo.reclamar_armado("instancia-B", "2026-01-03T10:10:00",
                                "2026-01-03T10:07:00") == cid


def test_reclamar_sube_los_intentos(repo):
    cid = _en_cola(repo, "2026-01-01T00:00:00")
    repo.reclamar_armado("A", "2026-01-03T10:00:00", "2026-01-03T09:57:00")
    assert repo.get_corrida(cid).intentos == 1
    repo.reclamar_armado("B", "2026-01-03T10:10:00", "2026-01-03T10:07:00")
    assert repo.get_corrida(cid).intentos == 2


def test_reclamar_perdida_no_toca_la_corrida(repo):
    """El que pierde la carrera no deja rastro: ni sube `intentos` ni se roba la
    reclama. Si el perdedor sumara, dos deploys seguidos agotarían el tope de
    reintentos sin que hubiera fallado nada de verdad."""
    cid = _en_cola(repo, "2026-01-01T00:00:00")
    assert repo.reclamar_armado("A", "2026-01-03T10:00:00", "2026-01-03T09:57:00") == cid
    # B llega con la reclama de A todavía viva: no hay nada más en la cola.
    assert repo.reclamar_armado("B", "2026-01-03T10:00:01", "2026-01-03T09:57:01") is None
    m = repo.get_corrida(cid)
    assert (m.intentos, m.armando_por, m.armando_desde) == (
        1, "A", "2026-01-03T10:00:00")


def test_reclamar_ignora_lo_que_no_esta_armando(repo):
    _en_cola(repo, "2026-01-01T00:00:00", estado="en_revision")
    _en_cola(repo, "2026-01-01T00:00:00", estado="armado_detenido")
    assert repo.reclamar_armado("A", "2026-01-03T10:00:00", "2026-01-03T09:57:00") is None


def test_latir_corre_el_vencimiento(repo):
    cid = _en_cola(repo, "2026-01-01T00:00:00")
    repo.reclamar_armado("A", "2026-01-03T10:00:00", "2026-01-03T09:57:00")
    repo.latir_armado(cid, "2026-01-03T10:20:00")
    # Un límite que habría vencido la reclama original ya no alcanza.
    assert repo.reclamar_armado("B", "2026-01-03T10:21:00", "2026-01-03T10:18:00") is None


def test_finalizar_libera_la_reclama(repo):
    cid = _en_cola(repo, "2026-01-01T00:00:00")
    repo.reclamar_armado("A", "2026-01-03T10:00:00", "2026-01-03T09:57:00")
    repo.finalizar_armado(cid, "en_revision", duracion_ms=1234)
    m = repo.get_corrida(cid)
    assert (m.estado, m.armando_por, m.duracion_ms) == ("en_revision", None, 1234)


def test_finalizar_en_armando_suelta_la_reclama_sin_salir_de_la_cola(repo):
    """El camino del fallo que no es de un ítem: la corrida SIGUE en la cola y se
    puede retomar YA, sin esperar el TTL, pero `intentos` no se toca (el tope de
    reintentos tiene que seguir contando lo que de verdad se intentó)."""
    cid = _en_cola(repo, "2026-01-01T00:00:00")
    repo.reclamar_armado("A", "2026-01-03T10:00:00", "2026-01-03T09:57:00")
    repo.finalizar_armado(cid, "armando", error="se cayó la base")
    m = repo.get_corrida(cid)
    assert (m.estado, m.armando_por, m.armando_desde, m.intentos) == (
        "armando", None, None, 1)
    # Un límite que NO habría vencido la reclama de A: igual se puede retomar.
    assert repo.reclamar_armado("B", "2026-01-03T10:00:05", "2026-01-03T09:57:05") == cid


def test_finalizar_sin_duracion_no_borra_la_que_habia(repo):
    """`duracion_ms=None` significa "no la sé", no "borrala": el camino de detener
    una corrida no puede tirar la duración de un armado anterior."""
    cid = _en_cola(repo, "2026-01-01T00:00:00")
    repo.finalizar_armado(cid, "en_revision", duracion_ms=999)
    repo.finalizar_armado(cid, "armado_detenido", error="se murió")
    assert repo.get_corrida(cid).duracion_ms == 999


def test_detener_guarda_el_motivo(repo):
    cid = _en_cola(repo, "2026-01-01T00:00:00")
    repo.finalizar_armado(cid, "armado_detenido", error="El Excel no se pudo leer.")
    m = repo.get_corrida(cid)
    assert (m.estado, m.ultimo_error) == ("armado_detenido", "El Excel no se pudo leer.")


def test_finalizar_ok_borra_el_error_viejo(repo):
    """Terminar bien no puede dejar colgado el motivo del intento que falló: la
    pantalla mostraría un error al lado de una corrida que salió perfecta."""
    cid = _en_cola(repo, "2026-01-01T00:00:00")
    repo.finalizar_armado(cid, "armando", error="se cayó la base")
    repo.finalizar_armado(cid, "en_revision", duracion_ms=10)
    assert repo.get_corrida(cid).ultimo_error is None


def test_reencolar_limpia_intentos_y_error(repo):
    cid = _en_cola(repo, "2026-01-01T00:00:00", estado="armado_detenido")
    repo.finalizar_armado(cid, "armado_detenido", error="se murió")
    repo.reencolar_armado(cid)
    m = repo.get_corrida(cid)
    assert (m.estado, m.intentos, m.ultimo_error) == ("armando", 0, None)


def test_reencolar_la_deja_lista_para_tomar_ya(repo):
    """"Reanudar a mano" tiene que servir de inmediato. Si `reencolar_armado` dejara
    la reclama vieja puesta, la corrida volvería a la cola pero ningún worker podría
    tocarla hasta que venciera el TTL: la pantalla diría "en cola" sin que pase nada."""
    cid = _en_cola(repo, "2026-01-01T00:00:00")
    repo.reclamar_armado("A", "2026-01-03T10:00:00", "2026-01-03T09:57:00")
    repo.reencolar_armado(cid)
    m = repo.get_corrida(cid)
    assert (m.armando_por, m.armando_desde) == (None, None)
    # Límite que NO habría vencido la reclama de A: igual se puede tomar.
    assert repo.reclamar_armado("B", "2026-01-03T10:00:05", "2026-01-03T09:57:05") == cid


def test_posicion_en_cola_cuenta_las_mas_viejas(repo):
    a = _en_cola(repo, "2026-01-01T00:00:00")
    b = _en_cola(repo, "2026-01-02T00:00:00")
    assert repo.posicion_en_cola(a) == 0
    assert repo.posicion_en_cola(b) == 1


def test_posicion_en_cola_solo_cuenta_lo_que_esta_en_la_cola(repo):
    """Una corrida vieja que ya terminó no ocupa lugar: si contara, la pantalla
    diría "3ª en la cola" cuando es la próxima."""
    _en_cola(repo, "2026-01-01T00:00:00", estado="en_revision")
    _en_cola(repo, "2026-01-01T00:00:00", estado="armado_detenido")
    b = _en_cola(repo, "2026-01-02T00:00:00")
    assert repo.posicion_en_cola(b) == 0


def test_posicion_en_cola_desempata_por_id(repo):
    """Dos corridas creadas en el mismo segundo (el ISO va al segundo) no pueden
    compartir posición: el desempate por id es el mismo que usa la reclama, así que
    la posición que se muestra es la que de verdad se va a servir."""
    a = _en_cola(repo, "2026-01-01T00:00:00")
    b = _en_cola(repo, "2026-01-01T00:00:00")
    assert (repo.posicion_en_cola(a), repo.posicion_en_cola(b)) == (0, 1)
    assert repo.reclamar_armado("A", "2026-01-03T10:00:00", "2026-01-03T09:57:00") == a


class _ConnEspia:
    """Deja pasar todo a la conexión real y dispara `sabotaje` justo ANTES del 2º
    execute: en `reclamar_armado` eso cae exactamente entre el SELECT y el UPDATE.

    Antes y no después del 1º a propósito: en SQLite el cursor del SELECT retiene un
    lock de lectura hasta que se libera, así que sabotear con el cursor todavía vivo
    deja al saboteador esperando ("database is locked") en vez de ganar la carrera.
    """

    def __init__(self, real, sabotaje):
        self._real, self._sabotaje, self._n = real, sabotaje, 0

    def execute(self, *a, **k):
        self._n += 1
        if self._n == 2 and self._sabotaje is not None:
            disparar, self._sabotaje = self._sabotaje, None
            disparar()
        return self._real.execute(*a, **k)

    def __getattr__(self, nombre):
        return getattr(self._real, nombre)


@contextmanager
def _sabotear_entre_el_select_y_el_update(repo, sabotaje):
    """Mete `sabotaje` JUSTO entre el SELECT y el UPDATE de `reclamar_armado`.

    Es la ÚNICA forma de ejercitar la rama del `rowcount`, que es lo que hace atómica
    la reclama: en un test secuencial el SELECT ya filtra la corrida reclamada y el
    UPDATE ni se intenta, así que la guarda quedaría sin red y se podría borrar sin que
    fallara nada. Se parchea la fábrica de conexiones, que es lo único que difiere
    entre los dos backends (`CorridasDB.connect` / `Conexion.connection`), así que
    esto corre igual contra SQLite y contra Postgres.
    """
    cx = getattr(repo, "cx", None)
    objetivo, attr = (cx, "connection") if cx is not None else (repo, "connect")
    original = getattr(objetivo, attr)
    ya_disparo = []

    @contextmanager
    def fabrica():
        with original() as real:
            if ya_disparo:                 # la llamada anidada del sabotaje va derecho
                yield real
            else:
                ya_disparo.append(True)
                yield _ConnEspia(real, sabotaje)

    setattr(objetivo, attr, fabrica)
    try:
        yield
    finally:
        setattr(objetivo, attr, original)


def test_reclamar_no_devuelve_una_corrida_que_perdio_en_el_ultimo_instante(repo):
    """La carrera real del deploy, forzada: A hace el SELECT, B se la lleva entera, y
    recién ahí A intenta el UPDATE. El UPDATE repite el WHERE, no aplica, y A tiene
    que salir con las manos vacías. Si A devolviera el id igual, las DOS instancias
    armarían la misma corrida y el cuadro saldría con actividades duplicadas.

    Sin este test la guarda del `rowcount` se puede borrar y la suite queda verde.
    """
    cid = _en_cola(repo, "2026-01-01T00:00:00")

    def se_la_lleva_B():
        assert repo.reclamar_armado("B", "2026-01-03T10:00:00", "2026-01-03T09:57:00") == cid

    with _sabotear_entre_el_select_y_el_update(repo, se_la_lleva_B):
        assert repo.reclamar_armado("A", "2026-01-03T10:00:01", "2026-01-03T09:57:01") is None

    m = repo.get_corrida(cid)
    assert (m.armando_por, m.intentos) == ("B", 1)   # A no dejó rastro
