# tests/test_servicio_corridas.py
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo, LicitacionItem
from apu_tool.servicio import corridas as svc


def _almacen_seed(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo("100", "Concreto 3000 PSI", "M3", "CONCRETOS", 350000.0, "COSTO INTERNO")])
    alm.apus.insert_apus([Apu("A1", "Concreto clase D", "M3", "DIURNO", "ESTRUCTURAS")])
    alm.apus.insert_components([
        ApuComponent("A1", "DIURNO", "100", "Concreto 3000 PSI", "M3", 1.05, 350000.0)])
    return alm


def test_construir_y_vista(tmp_path):
    alm = _almacen_seed(tmp_path)
    items = [LicitacionItem(item="1", descripcion="Concreto clase D", unidad="M3",
                            cantidad=10.0, precio_contractual=400000.0, shift="DIURNO")]
    cid = svc.construir_corrida(alm, "lic.xlsx", items, "DIURNO", use_ai=False)
    vista = svc.vista_corrida(alm, cid)
    assert vista["totales"]["n_items"] == 1
    fila = vista["items"][0]
    assert fila["apu_codigo"] == "A1"
    assert fila["status"] == "auto"                       # coincidencia exacta
    assert fila["costo_unitario"] == 1.05 * 350000.0      # 367500.0
    assert fila["contractual_total"] == 4000000.0
    assert fila["costo_total"] == 3675000.0


def test_vista_corrida_inexistente(tmp_path):
    alm = _almacen_seed(tmp_path)
    assert svc.vista_corrida(alm, 999) is None


def test_detalle_confirmar_y_cuadro(tmp_path):
    alm = _almacen_seed(tmp_path)
    # segundo APU para poder "elegir otro"
    alm.apus.insert_apus([Apu("A2", "Concreto clase E", "M3", "DIURNO", "ESTR")])
    alm.apus.insert_components([
        ApuComponent("A2", "DIURNO", "100", "Concreto 3000 PSI", "M3", 2.0, 350000.0)])
    items = [LicitacionItem(item="1", descripcion="Concreto clase D", unidad="M3",
                            cantidad=10.0, precio_contractual=400000.0, shift="DIURNO")]
    cid = svc.construir_corrida(alm, "lic.xlsx", items, "DIURNO", use_ai=False)

    det = svc.detalle_item(alm, cid, 0)
    assert det["apu_codigo"] == "A1"
    assert det["composicion"][0]["precio_unitario"] == 350000.0

    vista = svc.confirmar_item(alm, cid, 0, apu_codigo="A2")
    fila = vista["items"][0]
    assert fila["status"] == "confirmed" and fila["apu_codigo"] == "A2"
    assert fila["costo_unitario"] == 2.0 * 350000.0      # recosteado: 700000.0

    out = svc.generar_cuadro(alm, cid)
    assert out.exists()
    assert alm.corridas.get_corrida(cid).estado == "finalizada"


def test_detalle_item_inexistente(tmp_path):
    alm = _almacen_seed(tmp_path)
    assert svc.detalle_item(alm, 1, 0) is None
    assert svc.confirmar_item(alm, 1, 0, "A1") is None


def test_construir_corrida_stream_emite_progreso_y_done(tmp_path):
    alm = _almacen_seed(tmp_path)
    items = [LicitacionItem(item="1", descripcion="Concreto clase D", unidad="M3",
                            cantidad=10.0, precio_contractual=400000.0, shift="DIURNO")]
    eventos = list(svc.construir_corrida_stream(alm, "lic.xlsx", items, "DIURNO", False))
    tipos = [e[0] for e in eventos]
    assert tipos == ["progress", "done"]
    assert eventos[0][1] == {"i": 1, "total": 1, "descripcion": "Concreto clase D"}
    assert isinstance(eventos[1][1]["id"], int)
    assert eventos[1][1]["resumen"]["n_items"] == 1


def test_construir_corrida_sigue_devolviendo_id(tmp_path):
    # REGRESION: el envoltorio debe comportarse igual que antes.
    alm = _almacen_seed(tmp_path)
    items = [LicitacionItem(item="1", descripcion="Concreto clase D", unidad="M3",
                            cantidad=10.0, precio_contractual=400000.0, shift="DIURNO")]
    cid = svc.construir_corrida(alm, "lic.xlsx", items, "DIURNO", False)
    assert isinstance(cid, int)
    assert svc.vista_corrida(alm, cid)["totales"]["n_items"] == 1
