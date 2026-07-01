import sqlite3
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.datos.precios_db import PreciosDB
from apu_tool.nucleo.models import Insumo


def _creado_por_vigente(repo, iid):
    with repo.connect() as c:
        r = c.execute("SELECT creado_por FROM insumo_precios WHERE insumo_id=? AND vigente=1",
                      (iid,)).fetchone()
    return r["creado_por"]


def test_set_precio_por_id_guarda_creado_por(tmp_path):
    repo = PreciosDB(tmp_path / "p.db"); repo.init_schema()
    iid = repo.crear_insumo(Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU"))
    repo.set_precio_por_id(iid, 1500, "COSTO INTERNO", creado_por="u-editor")
    assert _creado_por_vigente(repo, iid) == "u-editor"


def test_set_precio_por_id_con_conn_no_autocommite(tmp_path):
    # Con conn de la UdT, si la transacción revierte, el precio NO persiste.
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    iid = alm.precios.crear_insumo(Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU"))
    with pytest.raises(RuntimeError):
        with alm.transaccion("precios") as conn:
            alm.precios.set_precio_por_id(iid, 9999, "X", conn=conn, creado_por="u1")
            raise RuntimeError("aborta")
    with alm.precios.connect() as c:
        n = c.execute("SELECT COUNT(*) FROM insumo_precios WHERE precio=9999").fetchone()[0]
    assert n == 0


def test_crear_insumo_guarda_creado_por(tmp_path):
    repo = PreciosDB(tmp_path / "p.db"); repo.init_schema()
    iid = repo.crear_insumo(Insumo("200", "ARENA", "M3", "MAT", 500, "PRECIO IDU"),
                            creado_por="u-editor")
    assert _creado_por_vigente(repo, iid) == "u-editor"
