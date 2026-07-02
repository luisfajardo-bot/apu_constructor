"""Contrato de almacenamiento: la MISMA batería corre contra ambos backends.

SQLite corre siempre (temp files). Postgres solo si hay TEST_DATABASE_URL.
Es el oráculo de no-regresión del port a Postgres (Enfoque A).
"""
import os
import pytest

from apu_tool.nucleo.models import Apu, ApuComponent, Insumo
from apu_tool.datos.repositorio import RepositorioPrecios, RepositorioApus


def _repos_sqlite(tmp_path):
    from apu_tool.datos.precios_db import PreciosDB
    from apu_tool.datos.apus_db import ApusDB
    p = PreciosDB(tmp_path / "precios.db")
    a = ApusDB(tmp_path / "apus.db")
    p.init_schema()
    a.init_schema()
    return p, a, None


def _repos_postgres(tmp_path):
    from apu_tool.datos.pg.conexion import Conexion
    from apu_tool.datos.pg.precios_pg import PreciosPg
    from apu_tool.datos.pg.apus_pg import ApusPg
    cx = Conexion(os.environ["TEST_DATABASE_URL"])
    p, a = PreciosPg(cx), ApusPg(cx)
    p.reset()  # esquema limpio
    a.reset()
    return p, a, cx


_BACKENDS = ["sqlite"]
if os.environ.get("TEST_DATABASE_URL"):
    _BACKENDS.append("postgres")


@pytest.fixture(params=_BACKENDS)
def repos(request, tmp_path):
    if request.param == "sqlite":
        p, a, cx = _repos_sqlite(tmp_path)
    else:
        p, a, cx = _repos_postgres(tmp_path)
    yield p, a
    if cx is not None:
        cx.cerrar()


def test_protocols_existen():
    assert hasattr(RepositorioPrecios, "get_candidatos")
    assert hasattr(RepositorioApus, "get_depriced_apu")


def test_insumo_insert_y_candidato_vigente(repos):
    precios, _ = repos
    assert precios.insert_insumos([
        Insumo("6140", "ACERO 60000 PSI", "KG", "MATERIAL", 3500.0, "PRECIO IDU")]) == 1
    cands = precios.get_candidatos("6140")
    assert len(cands) == 1 and cands[0].precio == 3500.0
    assert cands[0].fuente_precio == "PRECIO IDU"


def test_insumo_identidad_no_duplica(repos):
    precios, _ = repos
    ins = Insumo("6140", "ACERO 60000 PSI", "KG", "MATERIAL", 3500.0, "PRECIO IDU")
    precios.insert_insumos([ins])
    precios.insert_insumos([ins])  # misma identidad (codigo, nombre_norm)
    assert precios.counts()["insumos"] == 1


def test_crear_insumo_duplicado_lanza(repos):
    precios, _ = repos
    ins = Insumo("9", "CEMENTO GRIS", "KG", "MATERIAL", 900.0, "COSTO INTERNO")
    precios.crear_insumo(ins)
    with pytest.raises(ValueError):
        precios.crear_insumo(ins)


def test_set_precio_marca_vigente_y_guarda_historial(repos):
    precios, _ = repos
    iid = precios.crear_insumo(
        Insumo("9", "CEMENTO GRIS", "KG", "MATERIAL", 900.0, "COSTO INTERNO"))
    precios.set_precio_por_id(iid, 1000.0, "COMPRAS 2026")
    assert precios.get_insumo_por_id(iid).precio == 1000.0
    hist = precios.price_history("9")
    assert len(hist) == 2
    assert sum(1 for h in hist if h["vigente"]) == 1


def test_list_insumos_filtra_por_clasificacion(repos):
    precios, _ = repos
    precios.insert_insumos([
        Insumo("1", "ARENA", "M3", "MATERIAL", 10.0, "PRECIO IDU"),
        Insumo("2", "CUADRILLA", "HC", "MANO OBRA", 20.0, "COSTO INTERNO")])
    pub, npub = precios.list_insumos(clasificacion="publico", limit=50, offset=0)
    assert {i.codigo for i in pub} == {"1"}
    intr, _ = precios.list_insumos(clasificacion="interno", limit=50, offset=0)
    assert {i.codigo for i in intr} == {"2"}


def test_apu_crear_get_components_orden_y_depriced(repos):
    _, apus = repos
    comps = [
        ApuComponent("A1", "DIURNO", "1", "ARENA", "M3", 0.5, 10.0),
        ApuComponent("A1", "DIURNO", "2", "CUADRILLA", "HC", 1.2, 20.0)]
    apus.crear_apu(Apu("A1", "EXCAVACION", "M3", "DIURNO", "MOV TIERRAS"), comps)
    got = apus.get_components("A1", "DIURNO")
    assert [c.insumo_codigo for c in got] == ["1", "2"]
    dep = apus.get_depriced_apu("A1", "DIURNO")
    # invariante #1: la vista DePriced no expone dinero
    assert not hasattr(dep.componentes[0], "precio_unitario_hist")
    assert dep.componentes[0].rendimiento == 0.5


def test_apu_crear_duplicado_lanza(repos):
    _, apus = repos
    apus.crear_apu(Apu("A1", "EXCAVACION", "M3", "DIURNO"), [])
    with pytest.raises(ValueError):
        apus.crear_apu(Apu("A1", "OTRA", "M3", "DIURNO"), [])


def test_descripcion_no_vacia(repos):
    precios, apus = repos
    dp, da = precios.descripcion(), apus.descripcion()
    assert isinstance(dp, str) and dp.strip()
    assert isinstance(da, str) and da.strip()


def test_componentes_para_integridad(repos):
    _, apus = repos
    apus.crear_apu(Apu("A1", "EXCAVACION", "M3", "DIURNO", "MOV"), [
        ApuComponent("A1", "DIURNO", "6140", "ACERO", "KG", 0.5, 10.0),
        ApuComponent("A1", "DIURNO", "9", "CEMENTO", "KG", 1.2, 20.0)])
    comps = apus.componentes_para_integridad()
    assert ("6140", "ACERO") in comps and ("9", "CEMENTO") in comps
    assert all(isinstance(c, tuple) and len(c) == 2 for c in comps)
