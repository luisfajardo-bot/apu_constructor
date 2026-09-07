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
    cid = _corrida_con(repo, _item(0, 92106000.0), _item(1, 500.0))
    repo.set_costo_manual(cid, {0: 92106000.0})
    filas = {r.seq: r for r in repo.get_items(cid)}
    assert filas[0].costo_manual == 92106000.0
    assert filas[0].status == "confirmed"       # la resolvió una persona a propósito
    assert filas[1].costo_manual is None        # la otra fila no se toca
    assert filas[1].status == "new"


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
    assert repo.get_items(cid)[0].costo_manual is None
