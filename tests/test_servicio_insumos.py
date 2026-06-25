# tests/test_servicio_insumos.py
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Insumo
from apu_tool.servicio import insumos as svc


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo("100", "Concreto 3000 PSI", "M3", "CONCRETOS", 350000.0, "COSTO INTERNO"),
        Insumo("200", "Acero de refuerzo", "KG", "ACEROS", 4500.0, "PRECIO IDU")])
    return alm


def test_listar_y_clasificacion(tmp_path):
    alm = _alm(tmp_path)
    out = svc.listar(alm)
    assert out["total"] == 2
    by_cod = {i["codigo"]: i for i in out["items"]}
    assert by_cod["200"]["clasificacion"] == "publico"      # PRECIO IDU
    assert by_cod["100"]["clasificacion"] == "interno"      # COSTO INTERNO


def test_detalle_con_historial(tmp_path):
    alm = _alm(tmp_path)
    iid = alm.precios.get_candidatos("100")[0].id
    d = svc.detalle(alm, iid)
    assert d["insumo"]["codigo"] == "100" and len(d["historial"]) >= 1
    assert svc.detalle(alm, 99999) is None


def test_aplicar_cambios_ok_y_errores(tmp_path):
    alm = _alm(tmp_path)
    iid = alm.precios.get_candidatos("100")[0].id
    iid2 = alm.precios.get_candidatos("200")[0].id
    res = svc.aplicar_cambios(alm, [
        {"insumo_id": iid, "precio": 380000.0, "fuente": "COMPRAS"},
        {"insumo_id": 99999, "precio": 1.0, "fuente": "X"},      # id malo
        {"insumo_id": iid2, "precio": -5.0, "fuente": "Y"}])     # precio inválido
    assert res["aplicados"] == 1 and len(res["errores"]) == 2
    assert alm.precios.get_insumo_por_id(iid).precio == 380000.0
