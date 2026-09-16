# tests/test_servicio_rebuscar.py
"""Volver a buscar APU: el re-match de una corrida activa contra la biblioteca de hoy."""
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo, LicitacionItem
from apu_tool.servicio import corridas


def _almacen(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo("100", "Concreto 3000 PSI", "M3", "CONCRETOS", 350000.0, "COSTO INTERNO")])
    alm.apus.insert_apus([Apu("A1", "Concreto clase D", "M3", "DIURNO", "ESTRUCTURAS")])
    alm.apus.insert_components([
        ApuComponent("A1", "DIURNO", "100", "Concreto 3000 PSI", "M3", 1.0, 350000.0)])
    return alm


def _agregar_apu(alm, codigo, nombre, rendimiento=2.0, shift="DIURNO"):
    alm.apus.insert_apus([Apu(codigo, nombre, "M3", shift, "ESTRUCTURAS")])
    alm.apus.insert_components([
        ApuComponent(codigo, shift, "100", "Concreto 3000 PSI", "M3",
                     rendimiento, 350000.0)])


def _item(desc, n="1"):
    return LicitacionItem(item=n, descripcion=desc, unidad="M3", cantidad=10.0,
                          precio_contractual=900000.0, shift="DIURNO")


def test_rebuscar_encuentra_un_apu_creado_despues_del_armado(tmp_path):
    alm = _almacen(tmp_path)
    cid = corridas.construir_corrida(
        alm, "lic.xlsx", [_item("Pantalla acustica modular en aluminio")],
        "DIURNO", use_ai=False)
    assert corridas.vista_corrida(alm, cid)["items"][0]["apu_codigo"] is None

    _agregar_apu(alm, "A9", "Pantalla acustica modular en aluminio")

    previa = corridas.rebuscar(alm, cid)
    assert previa["escaneadas"] == 1
    assert len(previa["propuestas"]) == 1
    p = previa["propuestas"][0]
    assert p["seq"] == 0
    assert p["apu_actual"] is None
    assert p["apu_propuesto"]["codigo"] == "A9"
    assert p["sin_apu"] is True                      # el frontend la marca por defecto
    assert p["status"] == "auto"
    assert p["costo_unitario"] == 2.0 * 350000.0     # ya viene costeada
    assert p["margen_unitario"] == 900000.0 - 700000.0


def test_rebuscar_no_escribe_nada(tmp_path):
    alm = _almacen(tmp_path)
    cid = corridas.construir_corrida(
        alm, "lic.xlsx", [_item("Pantalla acustica modular en aluminio")],
        "DIURNO", use_ai=False)
    _agregar_apu(alm, "A9", "Pantalla acustica modular en aluminio")
    # Los candidatos de ANTES, no una lista vacía: el armado nunca deja la lista
    # vacía — `_full_scan` guarda todo lo que puntúe > 0, y `SequenceMatcher` da > 0
    # para casi cualquier par de textos. La fila nace con un candidato basura de 0,09.
    # Lo que se prueba acá es que la previa no los TOCA: refrescarlos es del aplicar.
    antes = alm.corridas.get_items(cid)[0].candidatos
    corridas.rebuscar(alm, cid)
    fila = alm.corridas.get_items(cid)[0]
    assert fila.apu_codigo is None                   # la previa propone, no aplica
    assert fila.candidatos == antes
    assert "A9" not in [c["apu_codigo"] for c in fila.candidatos]


def test_rebuscar_no_toca_las_confirmadas(tmp_path):
    alm = _almacen(tmp_path)
    cid = corridas.construir_corrida(alm, "lic.xlsx", [_item("Concreto clase D")],
                                     "DIURNO", use_ai=False)
    corridas.confirmar_item(alm, cid, 0, apu_codigo="A1")
    _agregar_apu(alm, "A9", "Concreto clase D")      # gemelo con el mismo nombre
    previa = corridas.rebuscar(alm, cid)
    assert previa["escaneadas"] == 0
    assert previa["propuestas"] == []


def test_rebuscar_no_propone_lo_que_la_fila_ya_tiene(tmp_path):
    alm = _almacen(tmp_path)
    cid = corridas.construir_corrida(alm, "lic.xlsx", [_item("Concreto clase D")],
                                     "DIURNO", use_ai=False)
    previa = corridas.rebuscar(alm, cid)             # sin crear nada nuevo
    assert previa["escaneadas"] == 1
    assert previa["propuestas"] == []


def test_rebuscar_bloqueado_si_congelada(tmp_path):
    alm = _almacen(tmp_path)
    cid = corridas.construir_corrida(alm, "lic.xlsx", [_item("Concreto clase D")],
                                     "DIURNO", use_ai=False)
    corridas.congelar(alm, cid)
    with pytest.raises(corridas.CorridaCongelada):
        corridas.rebuscar(alm, cid)


def test_rebuscar_bloqueado_si_el_plan_esta_a_medias(tmp_path):
    alm = _almacen(tmp_path)
    cid = corridas.construir_corrida(alm, "lic.xlsx", [_item("Concreto clase D")],
                                     "DIURNO", use_ai=False)
    alm.corridas.set_estado(cid, "armado_detenido")
    with pytest.raises(ValueError, match="por armar"):
        corridas.rebuscar(alm, cid)


def test_rebuscar_corrida_inexistente(tmp_path):
    assert corridas.rebuscar(_almacen(tmp_path), 999) is None


def test_aplicar_asigna_solo_los_seq_marcados(tmp_path):
    alm = _almacen(tmp_path)
    cid = corridas.construir_corrida(
        alm, "lic.xlsx",
        [_item("Pantalla acustica modular en aluminio", "1"),
         _item("Barrera vegetal perimetral en guadua", "2")],
        "DIURNO", use_ai=False)
    _agregar_apu(alm, "A9", "Pantalla acustica modular en aluminio")
    _agregar_apu(alm, "A8", "Barrera vegetal perimetral en guadua", rendimiento=3.0)

    vista = corridas.aplicar_rebusqueda(alm, cid, [0])
    filas = {f["seq"]: f for f in vista["items"]}
    assert filas[0]["apu_codigo"] == "A9"
    assert filas[0]["costo_unitario"] == 2.0 * 350000.0   # recosteada
    assert filas[1]["apu_codigo"] is None                 # no se marcó: intacta
    assert vista["rebusqueda"]["aplicadas"] == [0]
    assert vista["rebusqueda"]["salteadas"] == []


def test_aplicar_conserva_el_nivel_de_parecido_no_confirma(tmp_path):
    """Aprobar la asignación no es auditar la fila: un match dudoso entra `review`
    y sigue contando en «por revisar»."""
    alm = _almacen(tmp_path)
    cid = corridas.construir_corrida(
        alm, "lic.xlsx", [_item("Pantalla acustica modular en aluminio")],
        "DIURNO", use_ai=False)
    _agregar_apu(alm, "A9", "Pantalla acustica modular en aluminio")
    corridas.aplicar_rebusqueda(alm, cid, [0])
    fila = alm.corridas.get_items(cid)[0]
    assert fila.status == "auto"            # 100% de parecido, no "confirmed"
    assert fila.confianza == 1.0
    assert "Coincidencia directa" in fila.explicacion


def test_aplicar_saltea_lo_que_cambio_desde_la_previa(tmp_path):
    """La previa de hace cinco minutos no manda sobre la fila de ahora: el servidor
    recalcula y solo aplica lo que sigue vigente."""
    alm = _almacen(tmp_path)
    cid = corridas.construir_corrida(
        alm, "lic.xlsx", [_item("Pantalla acustica modular en aluminio")],
        "DIURNO", use_ai=False)
    _agregar_apu(alm, "A9", "Pantalla acustica modular en aluminio")
    corridas.rebuscar(alm, cid)                     # el usuario ve la propuesta…
    corridas.confirmar_item(alm, cid, 0, apu_codigo="A1")   # …y otro confirma la fila
    vista = corridas.aplicar_rebusqueda(alm, cid, [0])
    assert vista["items"][0]["apu_codigo"] == "A1"          # no la pisó
    assert vista["rebusqueda"]["aplicadas"] == []
    assert vista["rebusqueda"]["salteadas"] == [0]


def test_aplicar_refresca_los_candidatos_de_las_escaneadas(tmp_path):
    alm = _almacen(tmp_path)
    cid = corridas.construir_corrida(
        alm, "lic.xlsx", [_item("Pantalla acustica modular en aluminio")],
        "DIURNO", use_ai=False)
    # Ojo: el armado NO deja la lista vacía (`_full_scan` guarda todo lo que puntúe
    # > 0), así que la fila nace con un candidato basura. Lo que se prueba es que
    # después del aplicar la lista es la de hoy, con el APU nuevo adentro.
    assert "A9" not in [c["apu_codigo"]
                        for c in alm.corridas.get_items(cid)[0].candidatos]
    _agregar_apu(alm, "A9", "Pantalla acustica modular en aluminio")
    corridas.aplicar_rebusqueda(alm, cid, [])       # sin marcar nada
    fila = alm.corridas.get_items(cid)[0]
    assert fila.apu_codigo is None                  # no se asignó nada
    assert [c["apu_codigo"] for c in fila.candidatos] == ["A9"]


def test_aplicar_no_pisa_los_candidatos_con_una_lista_vacia(tmp_path):
    """Una lista fresca vacía es «no encontré nada», no «olvidá lo que sabías»."""
    alm = _almacen(tmp_path)
    cid = corridas.construir_corrida(alm, "lic.xlsx", [_item("Concreto clase D")],
                                     "DIURNO", use_ai=False)
    alm.corridas.set_candidatos(cid, {0: [{"apu_codigo": "A1", "apu_nombre": "x",
                                           "score": 0.9, "motivo": ""}]})
    alm.apus.borrar_apu("A1", "DIURNO")
    corridas.aplicar_rebusqueda(alm, cid, [])
    assert alm.corridas.get_items(cid)[0].candidatos[0]["apu_codigo"] == "A1"


def test_aplicar_bloqueado_si_congelada(tmp_path):
    alm = _almacen(tmp_path)
    cid = corridas.construir_corrida(alm, "lic.xlsx", [_item("Concreto clase D")],
                                     "DIURNO", use_ai=False)
    corridas.congelar(alm, cid)
    with pytest.raises(corridas.CorridaCongelada):
        corridas.aplicar_rebusqueda(alm, cid, [0])


def test_aplicar_corrida_inexistente(tmp_path):
    assert corridas.aplicar_rebusqueda(_almacen(tmp_path), 999, [0]) is None
