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
