from apu_tool.datos.almacen import Almacen
from apu_tool.datos.precios_db import PreciosDB
from apu_tool.datos.apus_db import ApusDB
from apu_tool.nucleo.models import Apu, Insumo


def test_fachada_expone_repos(tmp_path):
    alm = Almacen(tmp_path / "precios.db", tmp_path / "apus.db")
    alm.reset()
    assert isinstance(alm.precios, PreciosDB)
    assert isinstance(alm.apus, ApusDB)
    alm.precios.insert_insumos([Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU")])
    alm.apus.insert_apus([Apu("A1", "MURO", "M2", "DIURNO")])
    c = alm.counts()
    assert c["insumos"] == 1 and c["apus"] == 1
