"""Paridad SQLite ↔ Postgres del expediente de composición (criterio 33).

No repite CADA caso de `test_composiciones_db.py`: solo los que dependen del
backend (constraints, cascada, orden persistido, aislamiento por corrida/seq). Los
agnósticos del backend (que la fila no lleve dinero, que no haya columna de
razonamiento) no necesitan gemelo y viven una sola vez del lado SQLite. Reusa el
constructor de filas de ese archivo contra el otro backend: una lista de casos
aparte se desincroniza el día que alguien agrega uno en un solo lado.

Los de Postgres se saltan sin TEST_DATABASE_URL. OJO: hacen DROP SCHEMA — nunca
apuntarlos a producción (ver el guard autouse de tests/conftest.py).
"""
import os

import pytest

from apu_tool.datos.repositorio import CorridaEliminada, VersionYaExiste
from tests.test_composiciones_db import fila

pytest.importorskip("psycopg", reason="psycopg no instalado")
URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="sin TEST_DATABASE_URL")


@pytest.fixture()
def repo_pg():
    """Un ComposicionesPg sobre una base limpia, con UNA corrida real creada.

    La corrida se crea de verdad porque `composicion.corrida_id` tiene FK: un id
    inventado falla por falta de fila padre, no por la lógica de versiones.
    """
    from apu_tool.datos.pg.composiciones_pg import ComposicionesPg
    from apu_tool.datos.pg.conexion import Conexion
    from apu_tool.datos.pg.corridas_pg import CorridasPg
    cx = Conexion(URL)
    CorridasPg(cx).reset()
    with cx.connection() as c:
        c.execute("INSERT INTO corridas.corrida "
                  "(creada_en, archivo, turno_def, estado) "
                  "VALUES ('2026-09-10','x.xlsx','DIURNO','en_revision')")
    yield ComposicionesPg(cx)
    cx.cerrar()


def _cid(repo) -> int:
    with repo.cx.connection() as c:
        return int(c.execute("SELECT id FROM corridas.corrida "
                             "ORDER BY id DESC LIMIT 1").fetchone()["id"])


def test_pg_guarda_y_recupera_la_vigente(repo_pg):
    cid = _cid(repo_pg)
    repo_pg.agregar(fila(corrida_id=cid))
    v = repo_pg.vigente(cid, 7)
    assert v.version == 1 and v.estado == "propuesta"
    assert v.propuesta["componentes"][0]["codigo"] == "4279"
    assert v.confianza_motivos[0]["aporte"] == 2
    assert v.prompt_version == "composicion/v3"


def test_pg_la_vigente_es_la_de_mayor_version(repo_pg):
    cid = _cid(repo_pg)
    repo_pg.agregar(fila(corrida_id=cid, version=1, estado="propuesta"))
    repo_pg.agregar(fila(corrida_id=cid, version=2, estado="editada"))
    assert repo_pg.vigente(cid, 7).estado == "editada"


def test_pg_el_historial_viene_en_orden(repo_pg):
    cid = _cid(repo_pg)
    for n, est in enumerate(("propuesta", "editada", "aprobada"), start=1):
        repo_pg.agregar(fila(corrida_id=cid, version=n, estado=est))
    assert [f.estado for f in repo_pg.historial(cid, 7)] == [
        "propuesta", "editada", "aprobada"]


def test_pg_cada_fila_es_de_su_corrida_y_su_seq(repo_pg):
    """El índice único es (corrida_id, seq, version): dos corridas pueden compartir
    `seq` sin chocar entre sí. `repo_pg` solo trae UNA corrida creada; la segunda se
    crea acá mismo, igual que hace la fixture para la primera."""
    cid1 = _cid(repo_pg)
    with repo_pg.cx.connection() as c:
        c.execute("INSERT INTO corridas.corrida "
                  "(creada_en, archivo, turno_def, estado) "
                  "VALUES ('2026-09-10','y.xlsx','DIURNO','en_revision')")
    cid2 = _cid(repo_pg)
    repo_pg.agregar(fila(corrida_id=cid1, seq=7))
    repo_pg.agregar(fila(corrida_id=cid1, seq=8))
    repo_pg.agregar(fila(corrida_id=cid2, seq=7))
    assert repo_pg.vigente(cid1, 8).seq == 8
    assert repo_pg.vigente(cid2, 7).corrida_id == cid2


def test_pg_repetir_una_version_choca_igual_que_sqlite(repo_pg):
    cid = _cid(repo_pg)
    repo_pg.agregar(fila(corrida_id=cid, version=1))
    with pytest.raises(VersionYaExiste):
        repo_pg.agregar(fila(corrida_id=cid, version=1, estado="aprobada"))


def test_pg_una_corrida_inexistente_no_se_reporta_como_choque(repo_pg):
    """Las dos violaciones son de integridad pero significan cosas distintas."""
    with pytest.raises(CorridaEliminada):
        repo_pg.agregar(fila(corrida_id=999999))


def test_pg_sin_composicion_la_vigente_es_none(repo_pg):
    cid = _cid(repo_pg)
    assert repo_pg.vigente(cid, 99) is None
    assert repo_pg.historial(cid, 99) == []


def test_pg_los_campos_opcionales_aceptan_none(repo_pg):
    cid = _cid(repo_pg)
    repo_pg.agregar(fila(corrida_id=cid, ficha=None, propuesta=None, validacion=None,
                         confianza=None, confianza_motivos=None, antecedentes=None,
                         estado="error", motivo="la IA no contestó"))
    v = repo_pg.vigente(cid, 7)
    assert v.estado == "error" and v.propuesta is None
    assert v.confianza_motivos is None


def test_pg_borra_en_cascada_con_la_corrida(repo_pg):
    cid = _cid(repo_pg)
    repo_pg.agregar(fila(corrida_id=cid))
    with repo_pg.cx.connection() as c:
        c.execute("DELETE FROM corridas.corrida WHERE id=%s", (cid,))
    assert repo_pg.vigente(cid, 7) is None


def test_pg_y_sqlite_devuelven_la_misma_forma(repo_pg, tmp_path):
    """El contrato es el mismo tipo: si un backend pierde un campo, se ve acá."""
    from dataclasses import asdict
    from apu_tool.datos.almacen import Almacen
    cid = _cid(repo_pg)
    repo_pg.agregar(fila(corrida_id=cid))
    de_pg = repo_pg.vigente(cid, 7)

    alm = Almacen(tmp_path / "p.db", tmp_path / "a.db", tmp_path / "c.db")
    alm.init_schema()
    from apu_tool.nucleo.models import CorridaMeta
    sid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-09-10", archivo="x.xlsx", turno_def="DIURNO",
        use_ai=None, estado="en_revision"))
    alm.composiciones.agregar(fila(corrida_id=sid))
    de_sqlite = alm.composiciones.vigente(sid, 7)

    # `id` y `corrida_id` difieren por construcción; el resto tiene que ser idéntico.
    ignorar = {"id", "corrida_id"}
    assert ({k: v for k, v in asdict(de_pg).items() if k not in ignorar}
            == {k: v for k, v in asdict(de_sqlite).items() if k not in ignorar})
