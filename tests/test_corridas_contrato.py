"""Contrato del repositorio de corridas: la MISMA batería contra los dos backends.

SQLite corre siempre; Postgres solo con TEST_DATABASE_URL. Existe porque
`test_repositorios_contrato.py` cubre precios y apus pero NO corridas, y esa
brecha ya dejó pasar un bug de CorridasPg.
"""
import os
from contextlib import contextmanager

import pytest

from apu_tool.datos.repositorio import ArmadoDuplicado, CorridaEliminada
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
    esperada = CorridaMeta(
        id=cid, creada_en="2026-09-07T11:00:00", archivo="lista.xlsx",
        turno_def="NOCTURNO", use_ai=True, estado="finalizada",
        cuadro_path="salidas/cuadro.xlsx", duracion_ms=4321, modo="congelada",
        nombre="Mi corrida", lista_precios_id=7)
    # Se afirma contra valores EXPLÍCITOS y no una ruta contra la otra: las dos usan
    # `_COLS_META`, así que compararlas entre sí no detectaría una columna olvidada
    # (las dos devolverían el mismo default equivocado y el test pasaría igual).
    assert repo.get_corrida(cid) == esperada
    assert next(c for c in repo.listar_corridas() if c.id == cid) == esperada


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


def test_no_se_puede_duplicar_un_seq(repo):
    """Sin este indice una fila duplicada entra CALLADA y duplica la actividad en el
    cuadro. Con el indice, revienta: preferimos fallar a mentir.

    No puede ser CorridaEliminada: ese error dice "la corrida ya no existe" y aca
    la corrida existe, nomas que el seq esta repetido. Confundirlos seria un mensaje
    falso (peor que un error crudo)."""
    cid = repo.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-09-07T10:00:00", archivo="x.xlsx", turno_def="DIURNO",
        use_ai=None, estado="en_revision", cuadro_path=None, nombre="x"))
    repo.agregar_item(cid, _item(0, 1000.0))
    with pytest.raises(Exception) as exc_info:
        repo.agregar_item(cid, _item(0, 1000.0))
    assert not isinstance(exc_info.value, CorridaEliminada)


def _nombres_sql(repo):
    """(tabla de items, índice único) calificados según el backend."""
    if getattr(repo, "cx", None) is not None:
        return "corridas.corrida_item", "corridas.ux_corrida_item_seq"
    return "corrida_item", "ux_corrida_item_seq"


def test_arrancar_con_duplicados_viejos_no_tumba_la_app(repo, caplog):
    """`init_schema` corre en CADA arranque. Una base que YA trae (corrida_id, seq)
    duplicados —de armados muertos anteriores a esta feature— no puede impedir que
    la app levante: se quedaría sin servicio hasta que alguien limpie a mano.

    Entonces el índice se crea aparte y con try. Acá se monta ese caso exacto:
    se tira el índice, se meten duplicados, y se vuelve a arrancar."""
    tabla, indice = _nombres_sql(repo)
    cid = repo.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-09-07T10:00:00", archivo="x.xlsx", turno_def="DIURNO",
        use_ai=None, estado="en_revision", cuadro_path=None, nombre="x"))
    with _abrir_conn(repo) as conn:
        conn.execute(f"DROP INDEX IF EXISTS {indice}")
    repo.agregar_item(cid, _item(0, 1000.0))
    repo.agregar_item(cid, _item(0, 1000.0))      # sin índice, entra callada

    with caplog.at_level("ERROR"):
        repo.init_schema()                        # NO puede reventar

    assert "ux_corrida_item_seq" in caplog.text   # y tiene que gritarlo
    assert "duplicados" in caplog.text
    # La base sigue usable aunque el índice no se haya podido crear.
    assert len(repo.get_items(cid)) == 2


def test_reset_tambien_deja_el_indice_puesto(repo):
    """`reset()` es el camino de `seed --force`. Recrea el esquema desde el .sql, y el
    índice único NO vive en el .sql (tiene que crearse aparte, con try). Si `reset` se
    olvidara de crearlo, la protección desaparecería en silencio justo después de un
    re-semillado, y el próximo armado podría duplicar filas sin que nada avise."""
    repo.reset()
    cid = repo.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-09-07T10:00:00", archivo="x.xlsx", turno_def="DIURNO",
        use_ai=None, estado="en_revision", cuadro_path=None, nombre="x"))
    repo.agregar_item(cid, _item(0, 1000.0))
    with pytest.raises(Exception):
        repo.agregar_item(cid, _item(0, 1000.0))


# ---- un archivo, un solo armado a medias: ux_corrida_armando_archivo ----

def _crear_carpeta(repo, nombre: str) -> int:
    """Una carpeta, por SQL crudo: el fixture solo trae el repo de corridas (la tabla
    `carpeta` vive en la misma base) y estos tests necesitan carpetas REALES —el
    índice de armados duplicados es por (carpeta, archivo), y con `carpeta_id` NULL
    no aplica."""
    pg = getattr(repo, "cx", None) is not None
    tabla, marca = ("corridas.carpeta", "%s") if pg else ("carpeta", "?")
    sql = f"INSERT INTO {tabla} (nombre, creada_en) VALUES ({marca}, {marca})"
    with _abrir_conn(repo) as conn:
        cur = conn.execute(sql + (" RETURNING id" if pg else ""),
                           (nombre, "2026-09-08T10:00:00"))
        return int(cur.fetchone()["id"]) if pg else int(cur.lastrowid)


def _encolar_archivo(repo, carpeta_id: int, archivo: str = "lic.xlsx",
                     estado: str = "armando") -> int:
    return repo.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-09-08T10:00:00", archivo=archivo, turno_def="DIURNO",
        use_ai=None, estado=estado, cuadro_path=None, nombre=archivo,
        carpeta_id=carpeta_id))


def _indice_armado(repo) -> str:
    return ("corridas.ux_corrida_armando_archivo"
            if getattr(repo, "cx", None) is not None else "ux_corrida_armando_archivo")


def test_dos_armados_del_mismo_archivo_y_carpeta_no_coexisten(repo):
    """El doble clic: dos peticiones a milisegundos de distancia encolarían dos
    armados de tres horas del mismo Excel. Un `if ya_hay_una` no lo evita (las dos
    leen "no hay ninguna"), un índice único sí. Y la violación llega traducida:
    `ArmadoDuplicado`, no el error crudo del motor."""
    carpeta = _crear_carpeta(repo, "Obra")
    primera = _encolar_archivo(repo, carpeta)
    with pytest.raises(ArmadoDuplicado):
        _encolar_archivo(repo, carpeta)
    assert [m.id for m in repo.listar_corridas()] == [primera]   # UNA sola corrida


def test_un_armado_detenido_tambien_bloquea(repo):
    """`armado_detenido` es plan a medias: `reencolar_armado` la devuelve a la cola
    en cualquier momento, así que subir el mismo Excel otra vez dejaría dos armados
    del mismo archivo compitiendo por el mismo espacio de `seq`."""
    carpeta = _crear_carpeta(repo, "Obra")
    detenida = _encolar_archivo(repo, carpeta, estado="armado_detenido")
    with pytest.raises(ArmadoDuplicado):
        _encolar_archivo(repo, carpeta)
    assert [m.id for m in repo.listar_corridas()] == [detenida]


def test_el_indice_no_bloquea_lo_legitimo(repo):
    """Los tres casos que NO son un doble clic: la misma lista en otra obra, otra
    lista en la misma obra, y volver a subir la misma lista cuando la anterior ya
    terminó (para eso el índice es PARCIAL: si cubriera todos los estados, un
    archivo quedaría vetado para siempre)."""
    obra = _crear_carpeta(repo, "Obra")
    otra_obra = _crear_carpeta(repo, "Otra obra")
    primera = _encolar_archivo(repo, obra)
    _encolar_archivo(repo, otra_obra)                      # misma lista, otra obra
    _encolar_archivo(repo, obra, archivo="otra.xlsx")      # otra lista, misma obra
    repo.finalizar_armado(primera, "en_revision")
    _encolar_archivo(repo, obra)                           # ya terminó: entra de nuevo
    assert len(repo.listar_corridas()) == 4


def test_una_carpeta_inexistente_no_se_confunde_con_un_duplicado(repo):
    """Una FK rota también es una violación de integridad, y contarla como duplicado
    mandaría al usuario a buscar una corrida en curso que no existe."""
    with pytest.raises(Exception) as e:
        _encolar_archivo(repo, 999_999)          # carpeta que no existe
    assert not isinstance(e.value, ArmadoDuplicado)


def test_arrancar_con_armados_duplicados_viejos_no_tumba_la_app(repo, caplog):
    """Gemelo del de `ux_corrida_item_seq`: `init_schema` corre en CADA arranque, y
    una base que YA trae dos armados del mismo archivo —de antes de esta feature— no
    puede impedir que la app levante. Se grita en el log y se sigue."""
    carpeta = _crear_carpeta(repo, "Obra")
    with _abrir_conn(repo) as conn:
        conn.execute(f"DROP INDEX IF EXISTS {_indice_armado(repo)}")
    _encolar_archivo(repo, carpeta)
    _encolar_archivo(repo, carpeta)                # sin índice, entran las dos

    with caplog.at_level("ERROR"):
        repo.init_schema()                         # NO puede reventar

    assert "ux_corrida_armando_archivo" in caplog.text
    assert "duplicados" in caplog.text
    assert len(repo.listar_corridas()) == 2        # y la base sigue usable


def test_reset_tambien_deja_el_indice_de_armado_puesto(repo):
    """`reset()` es el camino de `seed --force`. El índice no vive en el .sql (se crea
    aparte, con try), así que si `reset` se olvidara de crearlo un re-semillado
    dejaría el doble clic suelto otra vez, en silencio."""
    repo.reset()
    carpeta = _crear_carpeta(repo, "Obra")
    _encolar_archivo(repo, carpeta)
    with pytest.raises(ArmadoDuplicado):
        _encolar_archivo(repo, carpeta)


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
    nueva = _en_cola(repo, "2026-01-02T00:00:00")

    ganada = repo.reclamar_armado("instancia-A", "2026-01-03T10:00:00", "2026-01-03T09:57:00")
    assert ganada == vieja                      # la más vieja primero

    # Segunda pasada con la reclama todavía fresca: NO la puede volver a tomar, y sigue
    # de largo con la que viene. Se afirma el POSITIVO (`== nueva`) y no `!= vieja`,
    # porque `None` también sería `!= vieja`: si el SELECT dejara de filtrar las
    # reclamas vivas, la corrida ya reclamada taparía la cola entera y ningún worker
    # podría tomar nunca la segunda. Eso pasaría el `!=` sin que nadie se entere.
    otra = repo.reclamar_armado("instancia-B", "2026-01-03T10:00:10", "2026-01-03T09:57:10")
    assert otra == nueva


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


# ---- fencing: el que ya no es dueño no toca la reclama ajena ----

def _reclama_robada(repo) -> int:
    """El montaje del deploy de Render: A arma, su reclama vence mientras drena, y B
    (la instancia nueva) se la lleva. A sigue vivo y todavía se cree el dueño."""
    cid = _en_cola(repo, "2026-01-01T00:00:00")
    repo.reclamar_armado("A", "2026-01-03T10:00:00", "2026-01-03T09:57:00")
    assert repo.reclamar_armado("B", "2026-01-03T10:10:00", "2026-01-03T10:07:00") == cid
    return cid


def test_un_zombi_no_le_suelta_la_reclama_al_dueno_nuevo(repo):
    """A ya no es el dueño: su `finalizar_armado` no puede sacar de la cola una
    corrida que B está armando. Sin el fencing, A la marcaría 'en_revision' con B a
    medio armar; y con estado='armando' una tercera instancia la reclamaría y
    quedarían DOS armando la misma corrida."""
    cid = _reclama_robada(repo)
    repo.finalizar_armado(cid, "en_revision", duracion_ms=1234, instancia="A")
    m = repo.get_corrida(cid)
    assert (m.estado, m.armando_por, m.armando_desde, m.duracion_ms) == (
        "armando", "B", "2026-01-03T10:10:00", None)


def test_un_zombi_no_puede_latir_sobre_la_reclama_ajena(repo):
    """Peor que inútil: el latido de A le estiraría a B una reclama que B ya no
    estuviera renovando, y taparía que B murió."""
    cid = _reclama_robada(repo)
    repo.latir_armado(cid, "2026-01-03T10:30:00", instancia="A")
    assert repo.get_corrida(cid).armando_desde == "2026-01-03T10:10:00"


def test_el_dueno_de_verdad_si_late_y_finaliza(repo):
    """La otra mitad: el fencing no puede trabar a quien SÍ es el dueño."""
    cid = _reclama_robada(repo)
    repo.latir_armado(cid, "2026-01-03T10:30:00", instancia="B")
    assert repo.get_corrida(cid).armando_desde == "2026-01-03T10:30:00"
    repo.finalizar_armado(cid, "en_revision", duracion_ms=1234, instancia="B")
    m = repo.get_corrida(cid)
    assert (m.estado, m.armando_por, m.duracion_ms) == ("en_revision", None, 1234)


def test_latir_y_finalizar_avisan_si_la_reclama_ya_no_es_tuya(repo):
    """El `bool` es el AVISO. El fencing evita que A pise a B, pero A no se entera de
    que lo desplazaron: seguiría armando en paralelo durante horas. El latido corre
    cada tanto, así que es el punto barato donde A puede darse cuenta y parar limpio.

    Se afirman los DOS sentidos: si devolviera `True` siempre (o `False` siempre) el
    aviso no sirve para nada."""
    cid = _reclama_robada(repo)                 # A perdió la reclama, ahora es de B
    assert repo.latir_armado(cid, "2026-01-03T10:30:00", instancia="A") is False
    assert repo.latir_armado(cid, "2026-01-03T10:30:00", instancia="B") is True
    assert repo.finalizar_armado(cid, "en_revision", instancia="A") is False
    assert repo.finalizar_armado(cid, "en_revision", instancia="B") is True


def test_latir_y_finalizar_sobre_una_corrida_que_no_existe_dan_false(repo):
    """La borraron mientras se armaba: el worker se entera por el mismo camino."""
    assert repo.latir_armado(999999, "2026-01-03T10:30:00") is False
    assert repo.finalizar_armado(999999, "en_revision") is False


def test_sin_instancia_se_puede_latir_y_finalizar_lo_que_nadie_reclamo(repo):
    """El camino sincrónico (`construir_corrida`, CLI y GUI): se crea y se arma en el
    acto, sin worker y sin reclama, así que `armando_por` es NULL y no hay dueño que
    verificar. Si el fencing fuera obligatorio, ese camino dejaría de escribir EN
    SILENCIO (NULL no matchea nada) y la corrida quedaría colgada en 'armando'."""
    cid = _en_cola(repo, "2026-01-01T00:00:00")
    assert repo.get_corrida(cid).armando_por is None
    assert repo.latir_armado(cid, "2026-01-03T10:30:00") is True
    assert repo.get_corrida(cid).armando_desde == "2026-01-03T10:30:00"
    assert repo.finalizar_armado(cid, "en_revision", duracion_ms=1234) is True
    m = repo.get_corrida(cid)
    assert (m.estado, m.duracion_ms) == ("en_revision", 1234)


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


def test_la_cola_va_por_fecha_y_no_por_id(repo):
    """La NUEVA se crea primero, así que se queda con el id MENOR y los dos criterios
    se contradicen. Sin esto, ordenar por `id` a secas da la misma respuesta que
    ordenar por `(creada_en, id)` y ningún test nota la diferencia — que es justo lo
    que pasaba: la cola es por antigüedad de la corrida, no por orden de alta.

    Importa el día que `creada_en` deje de venir de un solo lugar (una importación,
    una migración, una corrida creada con la fecha del archivo): ahí el id y la fecha
    divergen de verdad y la cola tiene que seguir la fecha."""
    nueva = _en_cola(repo, "2026-01-02T00:00:00")     # id menor, fecha mayor
    vieja = _en_cola(repo, "2026-01-01T00:00:00")     # id mayor, fecha menor
    assert (repo.posicion_en_cola(vieja), repo.posicion_en_cola(nueva)) == (0, 1)
    assert repo.reclamar_armado("A", "2026-01-03T10:00:00", "2026-01-03T09:57:00") == vieja


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


def test_set_candidatos_refresca_por_lote(repo):
    """Varias filas en UNA llamada, y las no pedidas intactas."""
    cid = _corrida_con(repo, _item(0, 1000.0), _item(1, 2000.0), _item(2, 3000.0))
    frescos = [{"apu_codigo": "A9", "apu_nombre": "APU NUEVO", "score": 0.7,
                "motivo": ""}]
    repo.set_candidatos(cid, {0: frescos, 2: frescos})
    filas = {r.seq: r for r in repo.get_items(cid)}
    assert filas[0].candidatos == frescos
    assert filas[2].candidatos == frescos
    assert filas[1].candidatos == []          # no se pidió: intacta


def test_set_candidatos_no_toca_el_apu_ni_el_veredicto_ni_el_costo_a_mano(repo):
    """Refrescar candidatos NO es cambiar de APU: por eso no pasa por
    `actualizar_eleccion`, que borra el veredicto y el costo puesto a mano."""
    cid = _corrida_con(repo, _item(0, 1000.0))
    repo.actualizar_eleccion(cid, 0, status="confirmed", apu_codigo="A1",
                             apu_nombre="APU UNO", unidad="M3", shift="DIURNO",
                             origen="historico", confianza=1.0, explicacion="ok",
                             componentes=[])
    # El orden importa: `set_costo_manual` BORRA el veredicto (poner el costo a mano
    # es un confirm), así que el veredicto se pone después, o este test probaría que
    # `set_candidatos` no borró algo que ya no estaba.
    repo.set_costo_manual(cid, {0: 5000.0})
    repo.set_revision(cid, 0, {"veredicto": "ok", "apu_evaluado": "A1"})
    repo.set_candidatos(cid, {0: [{"apu_codigo": "A2", "apu_nombre": "OTRO",
                                   "score": 0.6, "motivo": ""}]})
    fila = repo.get_items(cid)[0]
    assert fila.candidatos[0]["apu_codigo"] == "A2"
    assert fila.apu_codigo == "A1"
    assert fila.status == "confirmed"
    assert fila.revision is not None
    assert fila.costo_manual == 5000.0


def test_set_candidatos_vacio_no_escribe(repo):
    """Igual que `set_costo_manual`: un lote vacío es una no-operación, no un error."""
    cid = _corrida_con(repo, _item(0, 1000.0))
    repo.set_candidatos(cid, {})
    assert repo.get_items(cid)[0].candidatos == []


def test_limpiar_costo_manual_devuelve_la_fila_al_costeo(repo):
    """El reverso de set_costo_manual. Sin APU, la fila vuelve a `new`: es
    exactamente lo que era antes (así la deja `assemble.py` cuando no hay match)."""
    cid = _corrida_con(repo, _item(0, 1500.0), _item(1, 900.0))
    repo.set_costo_manual(cid, {0: 1500.0, 1: 900.0})
    repo.limpiar_costo_manual(cid, [0])
    filas = {r.seq: r for r in repo.get_items(cid)}
    assert filas[0].costo_manual is None
    assert filas[0].status == "new"
    assert filas[1].costo_manual == 900.0      # la que no se pidió no se toca
    assert filas[1].status == "confirmed"


def test_limpiar_costo_manual_con_apu_deja_la_fila_en_review(repo):
    """Con APU no se puede volver a `new` (la fila SÍ tiene match). No guardamos el
    status previo, y `review` —«mírala»— es la verdad honesta en vez de adivinar."""
    cid = _corrida_con(repo, _item(0, 1500.0))
    repo.actualizar_eleccion(
        cid, 0, status="auto", apu_codigo="100", apu_nombre="EXCAVACION",
        unidad="M3", shift="DIURNO", origen="historico", confianza=1.0,
        explicacion="", componentes=[])
    repo.set_costo_manual(cid, {0: 1500.0})
    repo.limpiar_costo_manual(cid, [0])
    fila = repo.get_items(cid)[0]
    assert fila.costo_manual is None
    assert fila.status == "review"


def test_limpiar_costo_manual_vacio_no_escribe(repo):
    """Sin esto el test no podría fallar: hay que dejar algo que borrar."""
    cid = _corrida_con(repo, _item(0, 1500.0))
    repo.set_costo_manual(cid, {0: 1500.0})
    repo.limpiar_costo_manual(cid, [])
    fila = repo.get_items(cid)[0]
    assert fila.costo_manual == 1500.0
    assert fila.status == "confirmed"
