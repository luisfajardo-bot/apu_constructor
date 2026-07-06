from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent
from apu_tool.servicio.subapus import marcar_subapus


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def test_marca_subapus_y_audita(tmp_path):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("B", "SUBAPU", "M3", "DIURNO"), Apu("A", "COMP", "M2", "DIURNO")])
    alm.apus.insert_components([
        ApuComponent("A", "DIURNO", "B", "SUBAPU", "M3", 1.0, 0.0),    # código B = un APU
        ApuComponent("A", "DIURNO", "100", "CEMENTO", "KG", 2.0, 900),  # insumo normal
    ])
    res = marcar_subapus(alm)
    assert res == {"apus_afectados": 1, "componentes_marcados": 1}
    comps = alm.apus.get_components("A", "DIURNO")
    sub = [c for c in comps if c.insumo_codigo == "B"][0]
    ins = [c for c in comps if c.insumo_codigo == "100"][0]
    assert sub.tipo == "apu" and sub.ref_shift == "DIURNO"
    assert ins.tipo == "insumo"
    _, total = alm.auditoria.listar(accion="apu.componente.marcar_subapu")
    assert total == 1


def test_ref_shift_cae_a_diurno(tmp_path):
    alm = _alm(tmp_path)
    # B solo existe DIURNO; el padre A es NOCTURNO -> ref_shift = DIURNO
    alm.apus.insert_apus([Apu("B", "SUBAPU", "M3", "DIURNO"), Apu("A", "COMP", "M2", "NOCTURNO")])
    alm.apus.insert_components([ApuComponent("A", "NOCTURNO", "B", "SUBAPU", "M3", 1.0, 0.0)])
    marcar_subapus(alm)
    sub = alm.apus.get_components("A", "NOCTURNO")[0]
    assert sub.tipo == "apu" and sub.ref_shift == "DIURNO"


def test_idempotente(tmp_path):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("B", "SUBAPU", "M3", "DIURNO"), Apu("A", "COMP", "M2", "DIURNO")])
    alm.apus.insert_components([ApuComponent("A", "DIURNO", "B", "SUBAPU", "M3", 1.0, 0.0)])
    marcar_subapus(alm)
    res2 = marcar_subapus(alm)
    assert res2 == {"apus_afectados": 0, "componentes_marcados": 0}
    _, total = alm.auditoria.listar(accion="apu.componente.marcar_subapu")
    assert total == 1   # no re-audita
