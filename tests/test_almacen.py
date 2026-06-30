from apu_tool.datos.almacen import Almacen
from apu_tool.datos.precios_db import PreciosDB
from apu_tool.datos.apus_db import ApusDB
from apu_tool.nucleo.models import Apu, CorridaMeta, Insumo


def test_fachada_expone_repos(tmp_path):
    alm = Almacen(tmp_path / "precios.db", tmp_path / "apus.db")
    alm.reset()
    assert isinstance(alm.precios, PreciosDB)
    assert isinstance(alm.apus, ApusDB)
    alm.precios.insert_insumos([Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU")])
    alm.apus.insert_apus([Apu("A1", "MURO", "M2", "DIURNO")])
    c = alm.counts()
    assert c["insumos"] == 1 and c["apus"] == 1


def test_reset_catalogo_preserva_corridas(tmp_path):
    # Re-sembrar el catálogo (precios+apus) NO debe borrar las corridas: son estado
    # de aplicación, aparte del catálogo.
    alm = Almacen(tmp_path / "p.db", tmp_path / "a.db", tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU")])
    alm.apus.insert_apus([Apu("A1", "MURO", "M2", "DIURNO")])
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="x", archivo="lic.xlsx", turno_def="DIURNO",
        use_ai=False, estado="en_revision"))

    alm.reset_catalogo()

    assert alm.counts()["insumos"] == 0 and alm.counts()["apus"] == 0   # catálogo borrado
    assert alm.corridas.get_corrida(cid) is not None                    # corrida sobrevive


def test_reset_completo_si_borra_todo(tmp_path):
    # reset() (completo) sigue borrando las tres bases, para un reseteo explícito.
    alm = Almacen(tmp_path / "p.db", tmp_path / "a.db", tmp_path / "c.db")
    alm.init_schema()
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="x", archivo="lic.xlsx", turno_def="DIURNO",
        use_ai=False, estado="en_revision"))
    alm.reset()
    assert alm.corridas.get_corrida(cid) is None
