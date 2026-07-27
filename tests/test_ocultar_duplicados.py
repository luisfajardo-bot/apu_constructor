from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo
from apu_tool.servicio.insumos_ocultos import ocultar_apus_duplicados


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def test_oculta_insumo_sin_uso_que_coincide_con_apu(tmp_path):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("8044", "CODO EN ACERO", "UND", "DIURNO")])
    iid = alm.precios.crear_insumo(
        Insumo("8044", "CODO EN ACERO", "UND", "MAT", 500, "PRECIO IDU"))

    res = ocultar_apus_duplicados(alm)

    assert res == {"insumos_ocultados": 1}
    ocultos_ids = {iid_ for iid_, _c, _n in alm.precios.todos_no_ocultos()}
    assert iid not in ocultos_ids
    _, total = alm.auditoria.listar(accion="insumo.ocultar_duplicado_apu")
    assert total == 1


def test_no_oculta_colision_real_con_nombre_distinto(tmp_path):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("7439", "TAPA CIRCULAR", "UND", "DIURNO")])
    iid = alm.precios.crear_insumo(
        Insumo("7439", "MARTILLO DEMOLEDOR NEUMATICO", "UND", "EQUIPO", 100, "PRECIO IDU"))

    res = ocultar_apus_duplicados(alm)

    assert res == {"insumos_ocultados": 0}
    ocultos_ids = {iid_ for iid_, _c, _n in alm.precios.todos_no_ocultos()}
    assert iid in ocultos_ids


def test_no_oculta_si_todavia_hay_uso_real_con_mismo_nombre(tmp_path):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("8044", "CODO EN ACERO", "UND", "DIURNO"),
                          Apu("A", "OTRO APU", "M2", "DIURNO")])
    iid = alm.precios.crear_insumo(
        Insumo("8044", "CODO EN ACERO", "UND", "MAT", 500, "PRECIO IDU"))
    # Un componente SIN marcar (tipo='insumo' es el default) sigue usando 8044
    # con el mismo nombre — no debería pasar tras marcar-subapus, pero la
    # migración debe ser segura igual: no oculta si todavía hay uso real.
    alm.apus.insert_components([
        ApuComponent("A", "DIURNO", "8044", "CODO EN ACERO", "UND", 2.0, 500)])

    res = ocultar_apus_duplicados(alm)

    assert res == {"insumos_ocultados": 0}
    ocultos_ids = {iid_ for iid_, _c, _n in alm.precios.todos_no_ocultos()}
    assert iid in ocultos_ids


def test_idempotente(tmp_path):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("8044", "CODO EN ACERO", "UND", "DIURNO")])
    alm.precios.crear_insumo(
        Insumo("8044", "CODO EN ACERO", "UND", "MAT", 500, "PRECIO IDU"))

    ocultar_apus_duplicados(alm)
    res2 = ocultar_apus_duplicados(alm)

    assert res2 == {"insumos_ocultados": 0}
    _, total = alm.auditoria.listar(accion="insumo.ocultar_duplicado_apu")
    assert total == 1   # no re-audita
