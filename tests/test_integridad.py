from apu_tool.datos.almacen import Almacen
from apu_tool.dominio import integridad
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo


def _alm(tmp_path):
    a = Almacen(tmp_path / "p.db", tmp_path / "a.db")
    a.reset()
    return a


def test_detecta_huerfano(tmp_path):
    a = _alm(tmp_path)
    a.precios.insert_insumos([Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU")])
    a.apus.insert_apus([Apu("A1", "MURO", "M2", "DIURNO")])
    a.apus.insert_components([ApuComponent("A1", "DIURNO", "999", "X", "UN", 1.0, 0)])
    rep = integridad.revisar(a)
    assert rep["huerfanos"] == 1

def test_detecta_ambiguo(tmp_path):
    a = _alm(tmp_path)
    a.precios.insert_insumos([
        Insumo("4513", "DUCTO TELEFONICO PVC D=3", "ML", "MAT", 16925, "PRECIO IDU"),
        Insumo("4513", "BASE GRANULAR CLASE C", "M3", "MAT", 190300, "PRECIO IDU"),
    ])
    a.apus.insert_apus([Apu("A1", "RED", "ML", "DIURNO")])
    a.apus.insert_components([ApuComponent("A1", "DIURNO", "4513", "TORNILLO X", "UN", 1.0, 0)])
    rep = integridad.revisar(a)
    assert rep["ambiguos"] == 1

def test_detecta_aproximado(tmp_path):
    a = _alm(tmp_path)
    # un solo insumo bajo el código; el APU lo cita con un nombre casi igual
    a.precios.insert_insumos([Insumo("500", "CONCRETO 3000 PSI", "M3", "MAT", 600000, "PRECIO IDU")])
    a.apus.insert_apus([Apu("A1", "PLACA", "M3", "DIURNO")])
    a.apus.insert_components([ApuComponent("A1", "DIURNO", "500", "CONCRETO 3000", "M3", 1.0, 0)])
    rep = integridad.revisar(a)
    assert rep["aproximados"] == 1
    assert rep["detalles"][0]["cat_nom"] == "CONCRETO 3000 PSI"
