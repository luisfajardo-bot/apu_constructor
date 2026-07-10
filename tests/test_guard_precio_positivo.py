import pytest
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Insumo
from apu_tool.servicio.insumos import aplicar_cambios, MSG_PRECIO_POSITIVO
from apu_tool.servicio import autoria


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo("100", "Concreto 3000 PSI", "M3", "CONCRETOS", 350000.0, "COSTO INTERNO")])
    return alm


def test_aplicar_cambios_rechaza_cero(tmp_path):
    alm = _alm(tmp_path)
    iid = alm.precios.get_candidatos("100")[0].id
    res = aplicar_cambios(alm, [{"insumo_id": iid, "precio": 0, "fuente": "X"}])
    assert res["aplicados"] == 0
    assert res["errores"] and "mayor que 0" in res["errores"][0]["error"]


def test_crear_insumo_rechaza_cero(tmp_path):
    alm = _alm(tmp_path)
    with pytest.raises(ValueError) as e:
        autoria.crear_insumo(alm, {"codigo": "Z9", "nombre": "Test", "precio": 0})
    assert "mayor que 0" in str(e.value)
