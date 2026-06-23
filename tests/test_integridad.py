from apu_tool.datos.almacen import Almacen
from apu_tool.datos import integridad
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo

def test_detecta_huerfano(tmp_path):
    a = Almacen(tmp_path / "p.db", tmp_path / "a.db")
    a.reset()
    a.precios.insert_insumos([Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU")])
    a.apus.insert_apus([Apu("A1", "MURO", "M2", "DIURNO")])
    a.apus.insert_components([ApuComponent("A1", "DIURNO", "999", "X", "UN", 1.0, 0)])
    rep = integridad.revisar(a)
    assert rep["huerfanos"] == 1   # código 999 no está en precios
