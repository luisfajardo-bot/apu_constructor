# tests/test_servicio_corridas.py
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import (
    Apu, ApuComponent, CorridaItemRow, CorridaMeta, Insumo, LicitacionItem,
)
from apu_tool.servicio import corridas
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


def test_construir_corrida_stream_emite_started_progreso_done(tmp_path):
    alm = _almacen_seed(tmp_path)
    items = [LicitacionItem(item="1", descripcion="Concreto clase D", unidad="M3",
                            cantidad=10.0, precio_contractual=400000.0, shift="DIURNO")]
    eventos = list(svc.construir_corrida_stream(alm, "lic.xlsx", items, "DIURNO", False))
    assert [e[0] for e in eventos] == ["started", "progress", "done"]
    started = eventos[0][1]
    assert isinstance(started["id"], int) and started["total"] == 1
    prog = eventos[1][1]
    assert prog["i"] == 1 and prog["total"] == 1 and prog["descripcion"] == "Concreto clase D"
    # El progress trae la fila ya costeada (para pintar la tabla en vivo).
    assert prog["fila"]["apu_codigo"] == "A1"
    assert prog["fila"]["costo_unitario"] == 1.05 * 350000.0
    done = eventos[2][1]
    assert done["id"] == started["id"] and done["resumen"]["n_items"] == 1


def test_construir_corrida_sigue_devolviendo_id(tmp_path):
    # REGRESION: el envoltorio debe comportarse igual que antes.
    alm = _almacen_seed(tmp_path)
    items = [LicitacionItem(item="1", descripcion="Concreto clase D", unidad="M3",
                            cantidad=10.0, precio_contractual=400000.0, shift="DIURNO")]
    cid = svc.construir_corrida(alm, "lic.xlsx", items, "DIURNO", False)
    assert isinstance(cid, int)
    assert svc.vista_corrida(alm, cid)["totales"]["n_items"] == 1


def test_svc_listar_y_eliminar(tmp_path):
    alm = _almacen_seed(tmp_path)
    items = [LicitacionItem(item="1", descripcion="Concreto clase D", unidad="M3",
                            cantidad=10.0, precio_contractual=400000.0, shift="DIURNO")]
    cid = svc.construir_corrida(alm, "lic.xlsx", items, "DIURNO", False)
    lista = svc.listar_corridas(alm)
    assert lista and lista[0]["id"] == cid
    assert lista[0]["n_items"] == 1 and "creada_en" in lista[0]
    assert svc.eliminar_corrida(alm, cid) is True
    assert svc.listar_corridas(alm) == []


def test_stream_persiste_duracion(tmp_path):
    alm = _almacen_seed(tmp_path)
    items = [LicitacionItem(item="1", descripcion="Concreto clase D", unidad="M3",
                            cantidad=10.0, precio_contractual=400000.0, shift="DIURNO")]
    eventos = list(svc.construir_corrida_stream(alm, "lic.xlsx", items, "DIURNO", False))
    done = next(p for ev, p in eventos if ev == "done")
    assert isinstance(done["duracion_ms"], int) and done["duracion_ms"] >= 0
    assert alm.corridas.get_corrida(done["id"]).duracion_ms == done["duracion_ms"]


def test_stream_arma_incremental_y_estado(tmp_path):
    # Armado incremental: la corrida nace 'armando' y cada ítem se persiste al
    # emitir su 'progress' (la tabla crece, no aparece toda al final); al terminar
    # queda 'en_revision'.
    alm = _almacen_seed(tmp_path)
    items = [LicitacionItem(item="1", descripcion="Concreto clase D", unidad="M3",
                            cantidad=10.0, precio_contractual=400000.0, shift="DIURNO"),
             LicitacionItem(item="2", descripcion="Concreto clase D", unidad="M3",
                            cantidad=5.0, precio_contractual=200000.0, shift="DIURNO")]
    gen = svc.construir_corrida_stream(alm, "lic.xlsx", items, "DIURNO", False)
    ev, payload = next(gen)                              # started
    assert ev == "started"
    cid = payload["id"]
    assert alm.corridas.get_corrida(cid).estado == "armando"
    assert len(alm.corridas.get_items(cid)) == 0        # aún sin ítems
    ev, _ = next(gen)                                    # progress 1
    assert ev == "progress"
    assert len(alm.corridas.get_items(cid)) == 1        # persistido al vuelo
    resto = list(gen)                                    # progress 2 + done
    assert resto[-1][0] == "done"
    assert len(alm.corridas.get_items(cid)) == 2
    assert alm.corridas.get_corrida(cid).estado == "en_revision"


def test_stream_cancela_si_borran_corrida(tmp_path):
    # Si la corrida se elimina durante el armado, el stream emite 'error' de
    # cancelación (no propaga FOREIGN KEY) y se detiene.
    alm = _almacen_seed(tmp_path)
    items = [LicitacionItem(item="1", descripcion="Concreto clase D", unidad="M3",
                            cantidad=10.0, precio_contractual=400000.0, shift="DIURNO"),
             LicitacionItem(item="2", descripcion="Concreto clase D", unidad="M3",
                            cantidad=5.0, precio_contractual=200000.0, shift="DIURNO")]
    gen = svc.construir_corrida_stream(alm, "lic.xlsx", items, "DIURNO", False)
    _, payload = next(gen)                               # started
    cid = payload["id"]
    next(gen)                                            # progress 1 (item 0 persistido)
    assert alm.corridas.eliminar_corrida(cid) is True    # el usuario la borra a mitad
    resto = list(gen)                                    # debe cerrar con 'error', sin excepción
    assert resto[-1][0] == "error"
    assert "cancel" in resto[-1][1]["detail"].lower()


def test_vista_y_lista_exponen_duracion(tmp_path):
    alm = _almacen_seed(tmp_path)
    items = [LicitacionItem(item="1", descripcion="Concreto clase D", unidad="M3",
                            cantidad=10.0, precio_contractual=400000.0, shift="DIURNO")]
    cid = svc.construir_corrida(alm, "lic.xlsx", items, "DIURNO", False)
    assert "duracion_ms" in svc.vista_corrida(alm, cid)
    assert "duracion_ms" in svc.listar_corridas(alm)[0]


def _alm_con_apu(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([Insumo("100", "CEMENTO", "KG", "MAT", 1000.0, "PRECIO IDU")])
    alm.apus.crear_apu(Apu("A1", "MURO", "M2", "DIURNO", "ESTR"),
                       [ApuComponent("A1", "DIURNO", "100", "CEMENTO", "KG", 2.0, 0.0)])
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="x", archivo="a.xlsx", turno_def="DIURNO",
        use_ai=False, estado="en_revision"))
    item = LicitacionItem(item="1", descripcion="muro", unidad="M2", cantidad=1.0,
                          precio_contractual=10000.0, shift="DIURNO")
    row = CorridaItemRow(
        seq=0, item=item, status="auto", apu_codigo="A1", apu_nombre="MURO",
        unidad="M2", shift="DIURNO", origen="historico", confianza=1.0, explicacion="",
        componentes=[{"insumo_codigo": "100", "insumo_nombre": "CEMENTO", "unidad": "KG",
                      "rendimiento": 2.0}], candidatos=[])
    alm.corridas.guardar_items(cid, [row])
    return alm, cid


def test_activa_relee_composicion_de_biblioteca(tmp_path):
    alm, cid = _alm_con_apu(tmp_path)
    v1 = corridas.vista_corrida(alm, cid)
    assert v1["modo"] == "activa"
    assert v1["items"][0]["costo_unitario"] == 2000.0        # 2.0 * 1000
    # editar el APU en la biblioteca: rendimiento 2.0 -> 3.0
    alm.apus.editar_apu(Apu("A1", "MURO", "M2", "DIURNO", "ESTR"),
                        [ApuComponent("A1", "DIURNO", "100", "CEMENTO", "KG", 3.0, 0.0)])
    v2 = corridas.vista_corrida(alm, cid)
    assert v2["items"][0]["costo_unitario"] == 3000.0        # activa re-leyó la biblioteca
