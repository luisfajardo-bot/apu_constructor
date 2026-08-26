# tests/test_corridas_agregar_lineas.py
"""Agregar líneas a una corrida ya armada (y borrarlas)."""
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo, LicitacionItem
from apu_tool.servicio import corridas


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


def _lic(num, desc, cantidad=10.0, precio=400000.0, shift="DIURNO", unidad="M3"):
    return LicitacionItem(item=num, descripcion=desc, unidad=unidad, cantidad=cantidad,
                          precio_contractual=precio, shift=shift)


def _corrida_de_una(alm, **kw):
    return corridas.construir_corrida(alm, "lic.xlsx", [_lic("1", "Concreto clase D")],
                                      "DIURNO", use_ai=False, **kw)


def test_agregar_items_continua_el_seq_y_pasa_por_el_matcher(tmp_path):
    alm = _almacen_seed(tmp_path)
    cid = _corrida_de_una(alm)
    vista = corridas.agregar_items(alm, cid, [_lic("2", "Concreto clase D", cantidad=2.0)])
    assert [f["seq"] for f in vista["items"]] == [0, 1]
    nueva = vista["items"][1]
    assert nueva["apu_codigo"] == "A1"                       # la armó el matcher
    assert nueva["costo_unitario"] == 1.05 * 350000.0        # y la costeó
    assert vista["totales"]["n_items"] == 2


def test_agregar_items_numera_el_item_vacio(tmp_path):
    alm = _almacen_seed(tmp_path)
    cid = _corrida_de_una(alm)
    vista = corridas.agregar_items(alm, cid, [_lic("", "Concreto clase D")])
    assert vista["items"][1]["item"] == "2"                  # seq 1 -> ítem "2"


def test_agregar_items_bloqueado_si_congelada(tmp_path):
    alm = _almacen_seed(tmp_path)
    cid = _corrida_de_una(alm)
    corridas.congelar(alm, cid)
    with pytest.raises(corridas.CorridaCongelada):
        corridas.agregar_items(alm, cid, [_lic("2", "Concreto clase D")])
    assert len(alm.corridas.get_items(cid)) == 1             # no escribió nada


def test_agregar_items_reabre_la_corrida_finalizada(tmp_path):
    alm = _almacen_seed(tmp_path)
    cid = _corrida_de_una(alm)
    corridas.generar_cuadro(alm, cid)                        # finalizada + congelada
    corridas.activar(alm, cid)
    corridas.agregar_items(alm, cid, [_lic("2", "Concreto clase D")])
    assert alm.corridas.get_corrida(cid).estado == "en_revision"


def test_agregar_items_corrida_inexistente_es_none(tmp_path):
    alm = _almacen_seed(tmp_path)
    assert corridas.agregar_items(alm, 999, [_lic("1", "Concreto clase D")]) is None


def test_agregar_items_rechaza_vacio_y_pasado_de_tope(tmp_path):
    alm = _almacen_seed(tmp_path)
    cid = _corrida_de_una(alm)
    with pytest.raises(ValueError):
        corridas.agregar_items(alm, cid, [])
    muchas = [_lic(str(k), "Concreto clase D")
              for k in range(corridas.MAX_LINEAS_AGREGADAS + 1)]
    with pytest.raises(ValueError):
        corridas.agregar_items(alm, cid, muchas)
    assert len(alm.corridas.get_items(cid)) == 1


def test_agregar_items_costea_con_la_lista_de_la_corrida(tmp_path):
    # La línea nueva NO puede costearse con otra tarifa que el resto de la corrida.
    # En una lista de NP sin tarifa para el insumo, queda en $0 con alerta: jamás
    # cae al precio histórico (sería cobrar el no previsto con la tarifa contractual).
    alm = _almacen_seed(tmp_path)
    lid = alm.precios.crear_lista("NP Calle 13")
    cid = corridas.construir_corrida(alm, "lic.xlsx", [_lic("1", "Concreto clase D")],
                                     "DIURNO", use_ai=False, lista_precios_id=lid)
    vista = corridas.agregar_items(alm, cid, [_lic("2", "Concreto clase D")])
    assert vista["lista_precios_id"] == lid
    assert vista["items"][1]["costo_unitario"] == 0.0
    assert vista["items"][1]["alertas_costeo"]                # no queda en $0 callado


def test_preview_marca_duplicadas_por_descripcion_y_no_escribe(tmp_path):
    alm = _almacen_seed(tmp_path)
    cid = _corrida_de_una(alm)                                # seq 0 = "Concreto clase D"
    prev = corridas.preview_agregar(alm, cid, [
        _lic("9", "  concreto   CLASE d "),                   # misma actividad, otro formato
        _lic("10", "Sardinel A-10"),
    ])
    assert prev["total"] == 2
    assert [f["descripcion"] for f in prev["nuevas"]] == ["Sardinel A-10"]
    assert prev["duplicadas"][0]["seq_existente"] == 0
    assert prev["modo"] == "activa" and prev["tope"] == corridas.MAX_LINEAS_AGREGADAS
    assert len(alm.corridas.get_items(cid)) == 1              # el preview no escribe


def test_agregar_items_agrega_la_duplicada_igual(tmp_path):
    # El preview AVISA; aplicar hace lo que dice el archivo. Saltear en silencio
    # esconde el duplicado y nadie se enteraría.
    alm = _almacen_seed(tmp_path)
    cid = _corrida_de_una(alm)
    vista = corridas.agregar_items(alm, cid, [_lic("9", "Concreto clase D")])
    assert vista["totales"]["n_items"] == 2


def test_preview_corrida_inexistente_es_none(tmp_path):
    alm = _almacen_seed(tmp_path)
    assert corridas.preview_agregar(alm, 999, [_lic("1", "x")]) is None


def _corrida_de_dos(alm):
    """Dos líneas con APUs distintos: A1 (1.05) en seq 0, A2 (2.0) en seq 1."""
    alm.apus.insert_apus([Apu("A2", "Concreto clase E", "M3", "DIURNO", "ESTR")])
    alm.apus.insert_components([
        ApuComponent("A2", "DIURNO", "100", "Concreto 3000 PSI", "M3", 2.0, 350000.0)])
    return corridas.construir_corrida(
        alm, "lic.xlsx", [_lic("1", "Concreto clase D"), _lic("2", "Concreto clase E")],
        "DIURNO", use_ai=False)


def test_borrar_items_deja_hueco_sin_renumerar(tmp_path):
    alm = _almacen_seed(tmp_path)
    cid = _corrida_de_dos(alm)
    vista = corridas.borrar_items(alm, cid, [0])
    assert [f["seq"] for f in vista["items"]] == [1]          # el que queda NO pasó a 0
    assert vista["totales"]["n_items"] == 1


def test_borrar_y_despues_agregar_no_reusa_el_hueco(tmp_path):
    alm = _almacen_seed(tmp_path)
    cid = _corrida_de_dos(alm)
    corridas.borrar_items(alm, cid, [0])
    vista = corridas.agregar_items(alm, cid, [_lic("3", "Concreto clase D")])
    assert [f["seq"] for f in vista["items"]] == [1, 2]       # 0 quedó libre y libre se queda


def test_borrar_no_le_cambia_el_snapshot_al_sobreviviente(tmp_path):
    alm = _almacen_seed(tmp_path)
    cid = _corrida_de_dos(alm)
    corridas.congelar(alm, cid)                              # snapshots: seq 0 y seq 1
    corridas.activar(alm, cid)
    corridas.borrar_items(alm, cid, [0])
    alm.corridas.set_modo(cid, "congelada")                  # sin recongelar: snapshots viejos
    vista = corridas.vista_corrida(alm, cid)
    assert [f["seq"] for f in vista["items"]] == [1]
    assert vista["items"][0]["costo_unitario"] == 2.0 * 350000.0   # el snapshot de SU seq


def test_borrar_items_bloqueado_si_congelada(tmp_path):
    alm = _almacen_seed(tmp_path)
    cid = _corrida_de_dos(alm)
    corridas.congelar(alm, cid)
    with pytest.raises(corridas.CorridaCongelada):
        corridas.borrar_items(alm, cid, [0])
    assert len(alm.corridas.get_items(cid)) == 2


def test_borrar_items_seq_ajeno_se_saltea(tmp_path):
    alm = _almacen_seed(tmp_path)
    cid = _corrida_de_dos(alm)
    vista = corridas.borrar_items(alm, cid, [77])
    assert [f["seq"] for f in vista["items"]] == [0, 1]       # no borró nada, no explotó


def test_borrar_items_corrida_inexistente_es_none(tmp_path):
    alm = _almacen_seed(tmp_path)
    assert corridas.borrar_items(alm, 999, [0]) is None


def test_borrar_items_reabre_la_corrida_finalizada(tmp_path):
    alm = _almacen_seed(tmp_path)
    cid = _corrida_de_dos(alm)
    corridas.generar_cuadro(alm, cid)                        # finalizada + congelada
    corridas.activar(alm, cid)
    corridas.borrar_items(alm, cid, [0])
    assert alm.corridas.get_corrida(cid).estado == "en_revision"


def test_borrar_items_queda_auditado(tmp_path):
    from apu_tool.nucleo.models import Perfil
    alm = _almacen_seed(tmp_path)
    cid = _corrida_de_dos(alm)
    corridas.borrar_items(alm, cid, [0], actor=Perfil("u-1", "jefe@obra.co", "admin", "activo"))
    eventos, total = alm.auditoria.listar(accion="corrida.borrar_items")
    assert total == 1
    assert eventos[0]["antes"]["lineas"][0]["seq"] == 0
    assert eventos[0]["antes"]["lineas"][0]["descripcion"] == "Concreto clase D"


def test_agregar_items_rechaza_corrida_en_armado(tmp_path):
    # El armador asigna los seq con enumerate() precalculado: agregar a mitad del
    # armado pediría el mismo seq y la fila duplicada entraría callada.
    alm = _almacen_seed(tmp_path)
    cid = _corrida_de_una(alm)
    alm.corridas.set_estado(cid, "armando")
    with pytest.raises(ValueError):
        corridas.agregar_items(alm, cid, [_lic("2", "Concreto clase D")])
    assert len(alm.corridas.get_items(cid)) == 1          # no escribió nada
