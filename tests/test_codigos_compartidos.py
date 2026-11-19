"""Códigos compartidos: un código del catálogo que es de dos insumos distintos."""
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Insumo


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo("7406", "REDUCCION HD E.L. D=12 x 10", "UN", "ACCESORIOS", 1785000,
               "PRECIO IDU"),
        Insumo("7406", "SEÑAL VERTICAL SR 90X30 INCLUYE POSTE", "UN", "SEÑALIZACION",
               468040, "PRECIO IDU"),
    ])
    return alm


def test_los_candidatos_traen_si_estan_ocultos(tmp_path):
    alm = _alm(tmp_path)
    reduccion = alm.precios.get_candidatos("7406")[0]
    alm.precios.set_oculto(reduccion.id, True)
    cands = alm.precios.get_candidatos("7406")
    assert [c.oculto for c in cands] == [True, False]
    assert [c.oculto for c in alm.precios.get_candidatos_bulk(["7406"])["7406"]] == [True, False]
    items, _ = alm.precios.list_insumos(q="SEÑAL VERTICAL")
    assert items and items[0].oculto is False
