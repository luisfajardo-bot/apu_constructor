import sqlite3
import pytest
from apu_tool.datos.apus_db import ApusDB
from apu_tool.datos.repositorio import RepositorioApus
from apu_tool.nucleo.models import Apu, ApuComponent


@pytest.fixture()
def apus(tmp_path):
    d = ApusDB(tmp_path / "apus.db")
    d.reset()
    d.insert_apus([Apu("A1", "MURO", "M2", "DIURNO")])
    d.insert_components([ApuComponent("A1", "DIURNO", "100", "CEMENTO", "KG", 3.0, 900)])
    return d


def test_cumple_contrato(apus):
    assert isinstance(apus, RepositorioApus)

def test_componentes_y_apu(apus):
    assert apus.get_apu("A1", "DIURNO").nombre == "MURO"
    comps = apus.get_components("A1", "DIURNO")
    assert len(comps) == 1 and comps[0].insumo_codigo == "100"

def test_seq_continua_entre_llamadas(apus):
    apus.insert_components([ApuComponent("A1", "DIURNO", "200", "ARENA", "M3", 1.0, 50)])
    assert len(apus.get_components("A1", "DIURNO")) == 2  # sin choque de PK

def test_componente_admite_insumo_huerfano(apus):
    apus.insert_components([ApuComponent("A1", "DIURNO", "GRA-99", "GRAVA", "M3", 1.0, 50)])
    assert any(c.insumo_codigo == "GRA-99" for c in apus.get_components("A1", "DIURNO"))

def test_depriced_no_tiene_dinero(apus):
    dp = apus.get_depriced_apu("A1", "DIURNO")
    assert not any(hasattr(c, "precio") or hasattr(c, "precio_unitario_hist")
                   for c in dp.componentes)

def test_fk_componente_requiere_apu(apus):
    with pytest.raises(sqlite3.IntegrityError):
        with apus.connect() as c:
            c.execute("INSERT INTO apu_componentes (apu_codigo, shift, seq) "
                      "VALUES ('NOEXISTE', 'DIURNO', 0)")


def test_crear_apu_con_componentes(apus):
    apus.crear_apu(
        Apu("B2", "PISO EN CONCRETO", "M2", "DIURNO", "ACABADOS"),
        [ApuComponent("B2", "DIURNO", "100", "CEMENTO", "KG", 2.0, 900),
         ApuComponent("B2", "DIURNO", "200", "ARENA", "M3", 0.5, 50)])
    assert apus.get_apu("B2", "DIURNO").nombre == "PISO EN CONCRETO"
    comps = apus.get_components("B2", "DIURNO")
    assert [c.insumo_codigo for c in comps] == ["100", "200"]   # seq correlativo

def test_crear_apu_duplicado_falla(apus):
    with pytest.raises(ValueError):
        apus.crear_apu(Apu("A1", "MURO", "M2", "DIURNO"), [])   # (A1, DIURNO) ya existe

def test_crear_apu_mismo_codigo_otro_turno_ok(apus):
    apus.crear_apu(Apu("A1", "MURO", "M2", "NOCTURNO"), [])     # misma PK distinta -> ok
    assert apus.get_apu("A1", "NOCTURNO") is not None

def test_list_apus_filtra_y_pagina(apus):
    apus.crear_apu(Apu("B2", "PISO CERAMICO", "M2", "DIURNO", "ACABADOS"), [])
    items, total = apus.list_apus()
    assert total == 2
    items_f, total_f = apus.list_apus(q="PISO")
    assert total_f == 1 and items_f[0].codigo == "B2"
    _, total_g = apus.list_apus(grupo="ACABADOS")
    assert total_g == 1


def test_round_trip_subapu(apus):
    apus.crear_apu(
        Apu("C3", "COMPUESTO", "M2", "DIURNO"),
        [ApuComponent("C3", "DIURNO", "3017", "SUB APU", "M3", 1.0, 0.0,
                      tipo="apu", ref_shift="DIURNO"),
         ApuComponent("C3", "DIURNO", "100", "CEMENTO", "KG", 2.0, 900)])
    comps = apus.get_components("C3", "DIURNO")
    sub = [c for c in comps if c.insumo_codigo == "3017"][0]
    ins = [c for c in comps if c.insumo_codigo == "100"][0]
    assert sub.tipo == "apu" and sub.ref_shift == "DIURNO"
    assert ins.tipo == "insumo" and ins.ref_shift == ""


def test_depriced_propaga_tipo(apus):
    apus.crear_apu(
        Apu("C4", "COMP", "M2", "DIURNO"),
        [ApuComponent("C4", "DIURNO", "3017", "SUB", "M3", 1.0, 0.0,
                      tipo="apu", ref_shift="DIURNO")])
    dp = apus.get_depriced_apu("C4", "DIURNO")
    assert dp.componentes[0].tipo == "apu"
