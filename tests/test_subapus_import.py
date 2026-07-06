from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent
from apu_tool.servicio.subapus import (
    mapa_codigos_apu, detectar_subapus_lote, marcar_comps_subapu,
)


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def test_mapa_une_biblioteca_y_lote(tmp_path):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("B", "SUB", "M3", "DIURNO")])          # en biblioteca
    lote = [Apu("Z", "SUB2", "M3", "NOCTURNO")]                       # en el lote
    mapa = mapa_codigos_apu(alm, lote)
    assert mapa["B"] == {"DIURNO"} and mapa["Z"] == {"NOCTURNO"}


def test_detecta_subapu_de_biblioteca_y_de_lote(tmp_path):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("B", "SUB-BIBLIO", "M3", "DIURNO")])    # sub-APU ya existe
    # lote: A usa a B (biblioteca) y a C (viene en el lote); D es insumo normal
    apus_lote = [Apu("A", "PADRE", "M2", "DIURNO"), Apu("C", "SUB-LOTE", "M3", "DIURNO")]
    comps_por = {
        ("A", "DIURNO"): [
            ApuComponent("A", "DIURNO", "B", "SUB-BIBLIO", "M3", 1.0, 0.0),
            ApuComponent("A", "DIURNO", "C", "SUB-LOTE", "M3", 2.0, 0.0),
            ApuComponent("A", "DIURNO", "100", "CEMENTO", "KG", 3.0, 0.0),
        ],
        ("C", "DIURNO"): [ApuComponent("C", "DIURNO", "100", "CEMENTO", "KG", 1.0, 0.0)],
    }
    vinc = detectar_subapus_lote(alm, apus_lote, comps_por, solo=apus_lote)
    porcod = {v["sub_codigo"]: v for v in vinc if v["apu_codigo"] == "A"}
    assert set(porcod) == {"B", "C"}                                  # 100 (insumo) NO aparece
    assert porcod["B"]["origen"] == "biblioteca" and porcod["B"]["sub_turno"] == "DIURNO"
    assert porcod["C"]["origen"] == "lote" and porcod["C"]["sub_turno"] == "DIURNO"


def test_ref_shift_hereda_o_cae_a_diurno(tmp_path):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("B", "SUB", "M3", "DIURNO")])           # solo DIURNO
    apus_lote = [Apu("A", "PADRE", "M2", "NOCTURNO")]                 # padre NOCTURNO
    comps_por = {("A", "NOCTURNO"): [ApuComponent("A", "NOCTURNO", "B", "SUB", "M3", 1.0, 0.0)]}
    vinc = detectar_subapus_lote(alm, apus_lote, comps_por, solo=apus_lote)
    assert vinc[0]["sub_turno"] == "DIURNO"                            # cae a DIURNO


def test_marcar_comps_subapu(tmp_path):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("B", "SUB", "M3", "DIURNO")])
    mapa = mapa_codigos_apu(alm, [])
    comps = [ApuComponent("A", "DIURNO", "B", "SUB", "M3", 1.0, 0.0),
             ApuComponent("A", "DIURNO", "100", "CEMENTO", "KG", 3.0, 0.0)]
    marcados, n = marcar_comps_subapu(comps, "DIURNO", mapa)
    assert n == 1
    sub = [c for c in marcados if c.insumo_codigo == "B"][0]
    ins = [c for c in marcados if c.insumo_codigo == "100"][0]
    assert sub.tipo == "apu" and sub.ref_shift == "DIURNO"
    assert ins.tipo == "insumo"
