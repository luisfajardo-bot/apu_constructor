from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo


def _alm(tmp_path):
    a = Almacen(tmp_path / "p.db", tmp_path / "a.db")
    a.reset()
    return a


def test_detalle_expone_tipo_y_ref_shift(tmp_path):
    from apu_tool.servicio import apus as apus_svc

    alm = _alm(tmp_path)
    alm.precios.insert_insumos([Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU")])
    # sub-APU B
    alm.apus.insert_apus([Apu("B", "SUBAPU", "M3", "DIURNO")])
    alm.apus.insert_components([ApuComponent("B", "DIURNO", "100", "CEMENTO", "KG", 2.0, 0.0)])
    # APU A: un componente insumo + un componente sub-APU (B)
    alm.apus.insert_apus([Apu("A", "COMP", "M2", "DIURNO")])
    alm.apus.insert_components([
        ApuComponent("A", "DIURNO", "100", "CEMENTO", "KG", 1.0, 0.0),
        ApuComponent("A", "DIURNO", "B", "SUBAPU", "M3", 3.0, 0.0, tipo="apu", ref_shift="DIURNO"),
    ])
    d = apus_svc.detalle(alm, "A", "DIURNO")
    porcod = {l["insumo_codigo"]: l for l in d["composicion"]}
    assert porcod["B"]["tipo"] == "apu" and porcod["B"]["ref_shift"] == "DIURNO"
    assert porcod["100"]["tipo"] == "insumo" and porcod["100"]["ref_shift"] == ""
