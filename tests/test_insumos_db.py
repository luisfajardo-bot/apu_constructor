# tests/test_insumos_db.py
import pytest
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Insumo


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo("100", "Concreto 3000 PSI", "M3", "CONCRETOS", 350000.0, "COSTO INTERNO"),
        Insumo("200", "Acero de refuerzo", "KG", "ACEROS", 4500.0, "PRECIO IDU")])
    return alm


def test_set_precio_por_id_crea_historial(tmp_path):
    alm = _alm(tmp_path)
    ins = alm.precios.get_candidatos("100")[0]
    alm.precios.set_precio_por_id(ins.id, 400000.0, "COMPRAS 2026")
    actual = alm.precios.get_insumo_por_id(ins.id)
    assert actual.precio == 400000.0 and actual.fuente_precio == "COMPRAS 2026"
    hist = alm.precios.price_history("100")
    assert len(hist) == 2                       # original + nuevo
    assert sum(1 for h in hist if h["vigente"]) == 1


def test_set_precio_por_id_id_inexistente(tmp_path):
    alm = _alm(tmp_path)
    with pytest.raises(ValueError):
        alm.precios.set_precio_por_id(99999, 1.0, "X")
