"""El costo mostrado en la biblioteca de APUs depende de la lista consultada."""
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo
from apu_tool.servicio import apus as apus_svc


@pytest.fixture()
def alm(tmp_path):
    a = Almacen(tmp_path / "p.db", tmp_path / "a.db", tmp_path / "c.db")
    a.reset()
    a.corridas.init_schema()
    a.precios.insert_insumos([
        Insumo("6140", "ACERO 60000 PSI", "KG", "MATERIAL", 3500.0, "PRECIO IDU")])
    a.apus.insert_apus([Apu("NP-3002", "DEMOLICION", "M3", "DIURNO")])
    a.apus.insert_components([
        ApuComponent("NP-3002", "DIURNO", "6140", "ACERO 60000 PSI", "KG", 2.0, 3000.0)])
    return a


@pytest.fixture()
def np(alm):
    lid = alm.precios.crear_lista("NP Calle 13")
    iid = alm.precios.get_candidatos("6140")[0].id
    alm.precios.set_precio_por_id(iid, 4200.0, "ACTA NP", lista_id=lid)
    return lid


def test_listar_costea_con_la_lista(alm, np):
    assert apus_svc.listar(alm)["items"][0]["costo_unitario"] == 7000
    assert apus_svc.listar(alm, lista_id=np)["items"][0]["costo_unitario"] == 8400


def test_detalle_costea_con_la_lista(alm, np):
    d = apus_svc.detalle(alm, "NP-3002", "DIURNO", lista_id=np)
    assert d["costo_unitario"] == 8400
    assert d["composicion"][0]["fuente_precio"] == "ACTA NP"
