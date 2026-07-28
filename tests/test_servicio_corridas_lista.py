"""La corrida se costea contra su lista, de punta a punta."""
import openpyxl
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo, LicitacionItem
from apu_tool.servicio import corridas as svc


@pytest.fixture()
def alm(tmp_path):
    a = Almacen(tmp_path / "p.db", tmp_path / "a.db", tmp_path / "c.db")
    a.reset()
    a.corridas.init_schema()
    a.precios.insert_insumos([
        Insumo("6140", "ACERO 60000 PSI", "KG", "MATERIAL", 3500.0, "PRECIO IDU")])
    a.apus.insert_apus([Apu("NP-3002", "DEMOLICION MURO", "M3", "DIURNO")])
    a.apus.insert_components([
        ApuComponent("NP-3002", "DIURNO", "6140", "ACERO 60000 PSI", "KG", 2.0, 3000.0)])
    return a


@pytest.fixture()
def np(alm):
    lid = alm.precios.crear_lista("NP Calle 13")
    iid = alm.precios.get_candidatos("6140")[0].id
    alm.precios.set_precio_por_id(iid, 4200.0, "ACTA NP", lista_id=lid)
    return lid


def _items():
    return [LicitacionItem("1", "DEMOLICION MURO", "M3", 1.0, 20000.0, "DIURNO")]


def test_corrida_np_costea_con_su_lista(alm, np):
    cid = svc.construir_corrida(alm, "acta.xlsx", _items(), "DIURNO", False,
                                carpeta_id=None, lista_precios_id=np)
    v = svc.vista_corrida(alm, cid)
    assert v["lista_precios_id"] == np and v["lista_nombre"] == "NP Calle 13"
    assert v["items"][0]["costo_unitario"] == 8400        # 2 * 4200


def test_corrida_sin_lista_usa_principal(alm, np):
    cid = svc.construir_corrida(alm, "lic.xlsx", _items(), "DIURNO", False, carpeta_id=None)
    v = svc.vista_corrida(alm, cid)
    assert v["lista_precios_id"] is None and v["lista_nombre"] == "Principal"
    assert v["items"][0]["costo_unitario"] == 7000        # 2 * 3500


def test_listar_corridas_trae_el_nombre_de_la_lista(alm, np):
    svc.construir_corrida(alm, "acta.xlsx", _items(), "DIURNO", False,
                          carpeta_id=None, lista_precios_id=np)
    fila = svc.listar_corridas(alm)[0]
    assert fila["lista_nombre"] == "NP Calle 13" and fila["costo"] == 8400


def test_detalle_item_usa_la_lista(alm, np):
    cid = svc.construir_corrida(alm, "acta.xlsx", _items(), "DIURNO", False,
                                carpeta_id=None, lista_precios_id=np)
    d = svc.detalle_item(alm, cid, 0)
    assert d["composicion"][0]["precio_unitario"] == 4200.0
    assert d["composicion"][0]["fuente_precio"] == "ACTA NP"


def test_congelada_no_se_mueve_al_cambiar_la_lista(alm, np):
    cid = svc.construir_corrida(alm, "acta.xlsx", _items(), "DIURNO", False,
                                carpeta_id=None, lista_precios_id=np)
    svc.congelar(alm, cid)
    iid = alm.precios.get_candidatos("6140")[0].id
    alm.precios.set_precio_por_id(iid, 9999.0, "ACTA NP v2", lista_id=np)
    assert svc.vista_corrida(alm, cid)["items"][0]["costo_unitario"] == 8400


def test_confirmar_item_costea_con_la_lista(alm, np):
    cid = svc.construir_corrida(alm, "acta.xlsx", _items(), "DIURNO", False,
                                carpeta_id=None, lista_precios_id=np)
    v = svc.confirmar_item(alm, cid, 0, "NP-3002", "DIURNO")
    assert v["items"][0]["costo_unitario"] == 8400


def test_generar_cuadro_costea_con_la_lista(alm, np):
    """Sitio 5/5: `generar_cuadro` arma su PROPIO PricingEngine (no reusa el de
    `congelar`) para costear en vivo los ítems que, estando la corrida ya
    congelada, no tengan snapshot persistido (freeze parcial). Para ejercer esa
    rama con freeze parcial SIN pasar por `congelar()` (que congelaría TODOS los
    ítems y dejaría a `generar_cuadro` sin nada que costear en vivo), se fabrica
    a mano un snapshot para el ítem 0 y se pasa la corrida a 'congelada'
    directo. El ítem 1 llega sin snapshot: si el motor de `generar_cuadro` se
    queda sin la lista, se costea con Principal (7000) en vez de NP (8400)."""
    items = [LicitacionItem("1", "DEMOLICION MURO", "M3", 1.0, 20000.0, "DIURNO"),
             LicitacionItem("2", "DEMOLICION MURO", "M3", 1.0, 20000.0, "DIURNO")]
    cid = svc.construir_corrida(alm, "acta.xlsx", items, "DIURNO", False,
                                carpeta_id=None, lista_precios_id=np)
    alm.corridas.set_snapshot(cid, 0, {"composicion": [], "costo_unitario": 8400})
    alm.corridas.set_modo(cid, "congelada")
    out = svc.generar_cuadro(alm, cid)
    ws = openpyxl.load_workbook(out)["RESUMEN"]
    costo_item_2 = ws.cell(row=3, column=6).value   # "Costo Unit." del ítem SIN snapshot
    assert costo_item_2 == 8400
