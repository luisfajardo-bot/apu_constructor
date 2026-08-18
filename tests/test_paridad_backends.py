"""Los dos backends de precios son espejo 1:1. Sin Postgres real: se comparan firmas.

Es el guardia barato contra el drift: si alguien añade un parámetro en SQLite y se
olvida de Postgres, esto falla en CI aunque no haya TEST_DATABASE_URL.
"""
import inspect

from apu_tool.datos.precios_db import PreciosDB
from apu_tool.datos.pg.precios_pg import PreciosPg
from apu_tool.datos.corridas_db import CorridasDB
from apu_tool.datos.pg.corridas_pg import CorridasPg
from apu_tool.datos.repositorio import RepositorioPrecios

# Métodos públicos que existen en un backend pero NO forman parte del contrato
# (RepositorioPrecios): son detalle de implementación de CADA backend, no algo
# que deba ser intercambiable entre sí. Hoy el único caso es `connect()` en
# PreciosDB (conexión "cruda" sqlite3.Row, dialecto '?', tablas sin schema; la
# usan 6 sitios del repo, todos contra SQLite). PreciosPg NO tiene un `connect()`
# equivalente a propósito: su conexión "cruda" tendría otro dialecto (%s), otro
# row factory (dict_row, sin acceso posicional r[0]), tablas `precios.`-
# calificadas y un slot arrendado de un pool compartido de 10 — no es portable,
# solo se podría hacer *presente* con un nombre engañoso. Precedente exacto en
# este repo (auditoría 2026-07-01): los casos C1 (PreciosPg sin `.path`) y C2
# (integridad.py llamaba `almacen.apus.connect()`) se resolvieron añadiendo el
# método que faltaba AL PROTOCOL (`descripcion()`, `componentes_para_integridad()`),
# no forzando un `connect()`/`.path` en el backend Postgres. Seguimos el mismo
# criterio acá: si algo debe ser intercambiable, se agrega al Protocol; si no,
# se excluye explícitamente de esta comparación.
_FUERA_DEL_CONTRATO = {"connect"}


def _publicos(cls) -> dict:
    return {n: m for n, m in inspect.getmembers(cls, inspect.isfunction)
            if not n.startswith("_") and n not in _FUERA_DEL_CONTRATO}


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
    # runtime_checkable comprueba presencia de métodos (no firmas); la firma la
    # cubren test_mismos_nombres_de_parametros y test_firmas_coinciden_con_el_protocol.
    assert isinstance(PreciosDB.__new__(PreciosDB), RepositorioPrecios)
    assert isinstance(PreciosPg.__new__(PreciosPg), RepositorioPrecios)


def test_firmas_coinciden_con_el_protocol():
    """Hallazgo 5: comparar los backends SOLO entre sí deja pasar un drift donde
    AMBOS cambian una firma a la vez y se olvidan del Protocol. El Protocol es
    el contrato real que consume el resto del programa (pipeline.py, servicio/),
    así que debe ser una TERCERA fuente de verdad, no solo el hasattr() de
    presencia de test_protocol_cubre_los_metodos_de_listas.

    Todo método público de PreciosDB (fuera de _FUERA_DEL_CONTRATO) debe estar
    declarado en el Protocol, con la misma firma exacta.
    """
    sq = _publicos(PreciosDB)
    for nombre in sorted(sq):
        fn_protocol = RepositorioPrecios.__dict__.get(nombre)
        assert fn_protocol is not None, (
            f"{nombre}: es público en PreciosDB pero el Protocol no lo declara")
        p_sq = list(inspect.signature(sq[nombre]).parameters)
        p_protocol = list(inspect.signature(fn_protocol).parameters)
        assert p_sq == p_protocol, (
            f"{nombre}: implementación {p_sq} != Protocol {p_protocol}")


# CorridasDB/CorridasPg no tenían ninguna red de paridad (a diferencia de Precios/Apus,
# que sí la tienen arriba): CorridasPg.borrar_items (el método destructivo que trajo
# "agregar líneas a la corrida") no corría contra ningún test en el repo. CorridasDB
# también tiene `connect()` (conexión cruda sqlite3.Row), así que la misma exclusión
# de _FUERA_DEL_CONTRATO aplica igual que en Precios.
def test_mismos_metodos_publicos_corridas():
    assert set(_publicos(CorridasDB)) == set(_publicos(CorridasPg))


def test_mismos_nombres_de_parametros_corridas():
    sq, pg = _publicos(CorridasDB), _publicos(CorridasPg)
    for nombre in sorted(sq):
        p_sq = list(inspect.signature(sq[nombre]).parameters)
        p_pg = list(inspect.signature(pg[nombre]).parameters)
        assert p_sq == p_pg, f"{nombre}: SQLite {p_sq} != Postgres {p_pg}"
