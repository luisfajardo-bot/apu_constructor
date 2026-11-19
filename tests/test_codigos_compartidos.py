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

import pytest

from apu_tool.nucleo.models import Apu, ApuComponent
from apu_tool.servicio import autoria

SENAL = "SEÑAL VERTICAL SR 90X30 INCLUYE POSTE"
REDUCCION = "REDUCCION HD E.L. D=12 x 10"


def _crear(alm, componentes, codigo="N1"):
    return autoria.crear_apu(alm, {"codigo": codigo, "turno": "DIURNO", "nombre": "APU " + codigo,
                                   "unidad": "UN", "grupo": "G", "componentes": componentes})


def test_crear_con_la_senal_guarda_la_senal(tmp_path):
    alm = _alm(tmp_path)
    _crear(alm, [{"insumo_codigo": "7406", "insumo_nombre": SENAL, "rendimiento": 1}])
    (c,) = alm.apus.get_components("N1", "DIURNO")
    assert c.insumo_nombre == SENAL


def test_crear_sin_nombre_bloquea_con_las_dos_opciones(tmp_path):
    alm = _alm(tmp_path)
    with pytest.raises(autoria.CodigoCompartido) as e:
        _crear(alm, [{"insumo_codigo": "7406", "rendimiento": 1}])
    assert e.value.conflictos == [{"codigo": "7406", "opciones": [
        {"nombre": REDUCCION, "unidad": "UN", "oculto": False},
        {"nombre": SENAL, "unidad": "UN", "oculto": False}]}]
    assert "7406" in str(e.value) and "escoge" in str(e.value)
    assert alm.apus.get_apu("N1", "DIURNO") is None          # no escribió nada


def test_dos_codigos_ambiguos_salen_en_un_solo_error(tmp_path):
    alm = _alm(tmp_path)
    alm.precios.insert_insumos([
        Insumo("6092", "HERRAMIENTA MENOR", "GLB", "EQ", 2000, "PRECIO IDU"),
        Insumo("6092", "RELOCALIZACION DE MEDIDOR DE ACUEDUCTO", "UN", "REDES", 9, "PRECIO IDU")])
    with pytest.raises(autoria.CodigoCompartido) as e:
        _crear(alm, [{"insumo_codigo": "7406", "insumo_nombre": "TORNILLO", "rendimiento": 1},
                     {"insumo_codigo": "6092", "rendimiento": 1}])
    assert [c["codigo"] for c in e.value.conflictos] == ["7406", "6092"]


def test_un_codigo_de_un_solo_insumo_sigue_igual(tmp_path):
    alm = _alm(tmp_path)
    alm.precios.insert_insumos([Insumo("100", "CEMENTO GRIS", "KG", "MAT", 1000, "PRECIO IDU")])
    _crear(alm, [{"insumo_codigo": "100", "insumo_nombre": "OTRA COSA", "rendimiento": 2}])
    (c,) = alm.apus.get_components("N1", "DIURNO")
    assert c.insumo_nombre == "CEMENTO GRIS"


def test_editar_sin_cambios_conserva_la_segunda_fila(tmp_path):
    """El caso 4506 de producción: el APU usa la SEGUNDA fila del código y editarlo
    sin tocar nada la cambiaba por la primera, sin alerta."""
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("4506", "BACHEO", "M2", "DIURNO", "PAV")])
    alm.apus.insert_components([ApuComponent("4506", "DIURNO", "7406", SENAL, "UN", 1.0, 468040)])
    autoria.editar_apu(alm, "4506", "DIURNO", {
        "nombre": "BACHEO", "unidad": "M2", "grupo": "PAV",
        "componentes": [{"insumo_codigo": "7406", "insumo_nombre": SENAL, "rendimiento": 1.0}]})
    (c,) = alm.apus.get_components("4506", "DIURNO")
    assert c.insumo_nombre == SENAL
    assert c.precio_unitario_hist == 468040            # su histórico, no el de la otra


def test_cambiar_de_fila_no_hereda_el_historico_de_la_otra(tmp_path):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("4506", "BACHEO", "M2", "DIURNO", "PAV")])
    alm.apus.insert_components([ApuComponent("4506", "DIURNO", "7406", SENAL, "UN", 1.0, 468040)])
    autoria.editar_apu(alm, "4506", "DIURNO", {
        "nombre": "BACHEO", "unidad": "M2", "grupo": "PAV",
        "componentes": [{"insumo_codigo": "7406", "insumo_nombre": REDUCCION, "rendimiento": 1.0}]})
    (c,) = alm.apus.get_components("4506", "DIURNO")
    assert c.insumo_nombre == REDUCCION
    assert c.precio_unitario_hist == autoria.PISO_HIST


def test_un_sub_apu_no_pasa_por_la_eleccion_de_insumos(tmp_path):
    """Los componentes tipo "apu" se resuelven contra la biblioteca: un código de
    sub-APU que choca con un insumo compartido no se bloquea."""
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("7406", "SUB APU", "UN", "DIURNO", "G")])
    _crear(alm, [{"insumo_codigo": "7406", "rendimiento": 1, "tipo": "apu",
                  "ref_shift": "DIURNO"}])
    (c,) = alm.apus.get_components("N1", "DIURNO")
    assert c.tipo == "apu"


def test_un_nombre_aproximado_resuelve_a_su_fila(tmp_path):
    """Los 4 casos aproximados de producción (5225/5241 D y N): el nombre guardado es
    una variante del catálogo. Resuelven a SU fila y quedan con el nombre canónico."""
    catalogo = "TARIFA DIA - ALQUILER DE VEHICULO: CAMPERO, PICK-UP, CAMIONETA. INCLUYE CONDUCTOR"
    guardado = "TARIFA DIA - ALQUILER DE VEHICULO: CAMPERO, PICK-UP, CAMIONETA"
    alm = _alm(tmp_path)
    alm.precios.insert_insumos([
        Insumo("8324", catalogo, "DIA", "EQ", 1, "PRECIO IDU"),
        Insumo("8324", "EMPATE ORTOGONAL PVC-PVC 12X8 INCLUYE SUMINISTRO", "UN", "REDES", 1,
               "PRECIO IDU")])
    _crear(alm, [{"insumo_codigo": "8324", "insumo_nombre": guardado, "rendimiento": 1}])
    (c,) = alm.apus.get_components("N1", "DIURNO")
    assert c.insumo_nombre == catalogo
