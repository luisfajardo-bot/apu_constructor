"""La vista de una corrida IDU trae capítulos; la de una plana, no."""
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import EntidadOrigen, LicitacionItem
from apu_tool.servicio import corridas as svc
from tests.fixtures_idu import escribir_formulario


def _almacen(tmp_path) -> Almacen:
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def _corrida_idu(tmp_path, alm) -> int:
    p = escribir_formulario(tmp_path / "f1.xlsx")
    lec = svc.leer_para_corrida(EntidadOrigen.IDU, p.read_bytes(), "f1.xlsx")
    return svc.construir_corrida(
        alm, "f1.xlsx", lec.items, "DIURNO", False,
        origen=svc.origen_de(EntidadOrigen.IDU, lec, "f1.xlsx", "yo@test.co"))


def test_la_vista_trae_el_resumen_por_capitulo(tmp_path):
    alm = _almacen(tmp_path)
    vista = svc.vista_corrida(alm, _corrida_idu(tmp_path, alm))
    assert [c["codigo"] for c in vista["capitulos"]] == ["1", "2"]
    assert vista["capitulos"][0]["actividades"] == 2
    assert vista["capitulos"][0]["contractual"] > 0
    # Biblioteca vacía: nada se pudo costear, y el capítulo lo dice.
    assert vista["capitulos"][0]["costo"] == 0
    assert vista["capitulos"][0]["sin_apu"] == 2
    assert vista["capitulos"][0]["completo"] is False


def test_el_resumen_de_la_vista_cuadra_con_los_totales(tmp_path):
    # Los capítulos y el total de la corrida salen de la misma lista de ensambles: si
    # no cuadran, la pantalla muestra dos verdades distintas a la vez.
    alm = _almacen(tmp_path)
    vista = svc.vista_corrida(alm, _corrida_idu(tmp_path, alm))
    assert sum(c["contractual"] for c in vista["capitulos"]) == \
        vista["totales"]["contractual"]
    assert sum(c["costo"] for c in vista["capitulos"]) == vista["totales"]["costo"]


def test_la_vista_trae_el_origen(tmp_path):
    alm = _almacen(tmp_path)
    vista = svc.vista_corrida(alm, _corrida_idu(tmp_path, alm))
    assert vista["origen"]["entidad"] == "IDU"
    assert vista["origen"]["hoja"] == "PROPUESTA ECONÓMICA"
    assert vista["origen"]["parser_version"] == "idu-f1/1"


def test_cada_item_trae_su_capitulo_y_las_dos_bases(tmp_path):
    alm = _almacen(tmp_path)
    vista = svc.vista_corrida(alm, _corrida_idu(tmp_path, alm))
    fila = vista["items"][0]
    assert fila["capitulo_codigo"] == "1"
    assert fila["capitulo_nombre"] == "PRELIMINARES"
    assert fila["item_pago_original"] == "1.001"
    assert fila["precio_contractual"] == 1351
    assert fila["precio_contractual_sin_aiu"] == 1056
    assert fila["contractual_total"] == 100 * 1351
    assert fila["contractual_total_sin_aiu"] == 100 * 1056


def test_una_corrida_plana_no_trae_capitulos_ni_origen(tmp_path):
    alm = _almacen(tmp_path)
    items = [LicitacionItem(item="1", descripcion="X", unidad="M2", cantidad=1.0,
                            precio_contractual=100.0, shift="DIURNO")]
    cid = svc.construir_corrida(alm, "plana.xlsx", items, "DIURNO", False)
    vista = svc.vista_corrida(alm, cid)
    assert vista["capitulos"] == []
    assert vista["origen"] is None
    assert vista["items"][0]["capitulo_codigo"] == ""
    assert vista["items"][0]["contractual_total_sin_aiu"] == 0


def test_los_capitulos_conservan_orden_y_asociacion_al_releer(tmp_path):
    alm = _almacen(tmp_path)
    cid = _corrida_idu(tmp_path, alm)
    primera = svc.vista_corrida(alm, cid)["capitulos"]
    # Otra instancia del almacén: se lee de disco, no de memoria.
    alm2 = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                   corridas_path=tmp_path / "c.db")
    segunda = svc.vista_corrida(alm2, cid)["capitulos"]
    assert primera == segunda
    assert [c["orden"] for c in segunda] == [1, 2]
