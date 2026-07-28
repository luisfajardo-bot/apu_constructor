"""Los dos backends de precios son espejo 1:1. Sin Postgres real: se comparan firmas.

Es el guardia barato contra el drift: si alguien añade un parámetro en SQLite y se
olvida de Postgres, esto falla en CI aunque no haya TEST_DATABASE_URL.
"""
import inspect

from apu_tool.datos.precios_db import PreciosDB
from apu_tool.datos.pg.precios_pg import PreciosPg
from apu_tool.datos.repositorio import RepositorioPrecios


def _publicos(cls) -> dict:
    return {n: m for n, m in inspect.getmembers(cls, inspect.isfunction)
            if not n.startswith("_")}


def test_mismos_metodos_publicos():
    assert set(_publicos(PreciosDB)) == set(_publicos(PreciosPg))


def test_mismos_nombres_de_parametros():
    sq, pg = _publicos(PreciosDB), _publicos(PreciosPg)
    for nombre in sorted(sq):
        p_sq = list(inspect.signature(sq[nombre]).parameters)
        p_pg = list(inspect.signature(pg[nombre]).parameters)
        assert p_sq == p_pg, f"{nombre}: SQLite {p_sq} != Postgres {p_pg}"


def test_protocol_cubre_los_metodos_de_listas():
    for metodo in ("listar_listas", "get_lista", "crear_lista", "renombrar_lista"):
        assert hasattr(RepositorioPrecios, metodo), metodo


def test_ambos_backends_satisfacen_el_protocol():
    # runtime_checkable comprueba presencia de métodos (no firmas); la firma la cubre
    # test_mismos_nombres_de_parametros.
    assert isinstance(PreciosDB.__new__(PreciosDB), RepositorioPrecios)
    assert isinstance(PreciosPg.__new__(PreciosPg), RepositorioPrecios)
