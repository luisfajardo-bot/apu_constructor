"""Contrato del repositorio de corridas: la MISMA batería contra los dos backends.

SQLite corre siempre; Postgres solo con TEST_DATABASE_URL. Existe porque
`test_repositorios_contrato.py` cubre precios y apus pero NO corridas, y esa
brecha ya dejó pasar un bug de CorridasPg.
"""
import os
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
    """Con la fila 1 borrada, reanudar por CONTEO daría 1 y duplicaría la fila 1.
    Por eso se usa el máximo y no la cantidad."""
    cid = repo.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-09-07T10:00:00", archivo="x.xlsx", turno_def="DIURNO",
        use_ai=None, estado="en_revision", cuadro_path=None, nombre="x"))
    for s in (0, 1, 2):
        repo.agregar_item(cid, _item(s, 1000.0))
    repo.borrar_items(cid, [1])
    assert repo.max_seq(cid) == 2
