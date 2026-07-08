# tests/test_servicio_corridas.py
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import (
    Apu, ApuComponent, CostedComponent, CorridaItemRow, CorridaMeta, Insumo, LicitacionItem,
)
from apu_tool.dominio.pricing import PricingEngine
from apu_tool.servicio import corridas
from apu_tool.servicio.corridas import _estructura, _costear_row


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
    cid = corridas.construir_corrida(alm, "lic.xlsx", items, "DIURNO", use_ai=False)
    vista = corridas.vista_corrida(alm, cid)
    assert vista["totales"]["n_items"] == 1
    fila = vista["items"][0]
    assert fila["apu_codigo"] == "A1"
    assert fila["status"] == "auto"                       # coincidencia exacta
    assert fila["costo_unitario"] == 1.05 * 350000.0      # 367500.0
    assert fila["contractual_total"] == 4000000.0
    assert fila["costo_total"] == 3675000.0


def test_vista_corrida_inexistente(tmp_path):
    alm = _almacen_seed(tmp_path)
    assert corridas.vista_corrida(alm, 999) is None


def test_detalle_confirmar_y_cuadro(tmp_path):
    alm = _almacen_seed(tmp_path)
    # segundo APU para poder "elegir otro"
    alm.apus.insert_apus([Apu("A2", "Concreto clase E", "M3", "DIURNO", "ESTR")])
    alm.apus.insert_components([
        ApuComponent("A2", "DIURNO", "100", "Concreto 3000 PSI", "M3", 2.0, 350000.0)])
    items = [LicitacionItem(item="1", descripcion="Concreto clase D", unidad="M3",
                            cantidad=10.0, precio_contractual=400000.0, shift="DIURNO")]
    cid = corridas.construir_corrida(alm, "lic.xlsx", items, "DIURNO", use_ai=False)

    det = corridas.detalle_item(alm, cid, 0)
    assert det["apu_codigo"] == "A1"
    assert det["composicion"][0]["precio_unitario"] == 350000.0

    vista = corridas.confirmar_item(alm, cid, 0, apu_codigo="A2")
    fila = vista["items"][0]
    assert fila["status"] == "confirmed" and fila["apu_codigo"] == "A2"
    assert fila["costo_unitario"] == 2.0 * 350000.0      # recosteado: 700000.0

    out = corridas.generar_cuadro(alm, cid)
    assert out.exists()
    assert alm.corridas.get_corrida(cid).estado == "finalizada"


def test_detalle_item_inexistente(tmp_path):
    alm = _almacen_seed(tmp_path)
    assert corridas.detalle_item(alm, 1, 0) is None
    assert corridas.confirmar_item(alm, 1, 0, "A1") is None


def test_construir_corrida_stream_emite_started_progreso_done(tmp_path):
    alm = _almacen_seed(tmp_path)
    items = [LicitacionItem(item="1", descripcion="Concreto clase D", unidad="M3",
                            cantidad=10.0, precio_contractual=400000.0, shift="DIURNO")]
    eventos = list(corridas.construir_corrida_stream(alm, "lic.xlsx", items, "DIURNO", False))
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
    cid = corridas.construir_corrida(alm, "lic.xlsx", items, "DIURNO", False)
    assert isinstance(cid, int)
    assert corridas.vista_corrida(alm, cid)["totales"]["n_items"] == 1


def test_svc_listar_y_eliminar(tmp_path):
    alm = _almacen_seed(tmp_path)
    items = [LicitacionItem(item="1", descripcion="Concreto clase D", unidad="M3",
                            cantidad=10.0, precio_contractual=400000.0, shift="DIURNO")]
    cid = corridas.construir_corrida(alm, "lic.xlsx", items, "DIURNO", False)
    lista = corridas.listar_corridas(alm)
    assert lista and lista[0]["id"] == cid
    assert lista[0]["n_items"] == 1 and "creada_en" in lista[0]
    assert corridas.eliminar_corrida(alm, cid) is True
    assert corridas.listar_corridas(alm) == []


def test_listar_corridas_totales_igual_a_vista(tmp_path):
    alm = _almacen_seed(tmp_path)
    items = [LicitacionItem(item="1", descripcion="Concreto clase D", unidad="M3",
                            cantidad=10.0, precio_contractual=400000.0, shift="DIURNO")]
    cid = corridas.construir_corrida(alm, "lic.xlsx", items, "DIURNO", use_ai=False)

    tot_v = corridas.vista_corrida(alm, cid)["totales"]
    fila = next(c for c in corridas.listar_corridas(alm) if c["id"] == cid)
    for k in ("contractual", "costo", "margen", "margen_pct"):
        assert fila[k] == pytest.approx(tot_v[k])

    corridas.congelar(alm, cid)                       # congelada: mismo invariante vs snapshot
    tot_v2 = corridas.vista_corrida(alm, cid)["totales"]
    fila2 = next(c for c in corridas.listar_corridas(alm) if c["id"] == cid)
    for k in ("contractual", "costo", "margen", "margen_pct"):
        assert fila2[k] == pytest.approx(tot_v2[k])


def test_listar_corridas_fila_robusta_ante_error_de_costeo(tmp_path, monkeypatch):
    alm = _almacen_seed(tmp_path)
    items = [LicitacionItem(item="1", descripcion="Concreto clase D", unidad="M3",
                            cantidad=10.0, precio_contractual=400000.0, shift="DIURNO")]
    corridas.construir_corrida(alm, "lic.xlsx", items, "DIURNO", use_ai=False)

    def _boom(*a, **k):
        raise RuntimeError("costeo falló")
    monkeypatch.setattr(corridas, "_ensamblar_corrida", _boom)

    fila = corridas.listar_corridas(alm)[0]
    assert fila["n_items"] == 1                        # conteos no dependen del costeo
    assert fila["contractual"] is None and fila["costo"] is None
    assert fila["margen"] is None and fila["margen_pct"] is None


def test_stream_persiste_duracion(tmp_path):
    alm = _almacen_seed(tmp_path)
    items = [LicitacionItem(item="1", descripcion="Concreto clase D", unidad="M3",
                            cantidad=10.0, precio_contractual=400000.0, shift="DIURNO")]
    eventos = list(corridas.construir_corrida_stream(alm, "lic.xlsx", items, "DIURNO", False))
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
    gen = corridas.construir_corrida_stream(alm, "lic.xlsx", items, "DIURNO", False)
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
    gen = corridas.construir_corrida_stream(alm, "lic.xlsx", items, "DIURNO", False)
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
    cid = corridas.construir_corrida(alm, "lic.xlsx", items, "DIURNO", False)
    assert "duracion_ms" in corridas.vista_corrida(alm, cid)
    assert "duracion_ms" in corridas.listar_corridas(alm)[0]


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


def test_congelar_fija_todo_y_activar_libera(tmp_path):
    alm, cid = _alm_con_apu(tmp_path)
    v = corridas.congelar(alm, cid)
    assert v["modo"] == "congelada"
    congelado = v["items"][0]["costo_unitario"]              # 2000.0
    # cambiar el APU y el precio del insumo: la congelada NO debe moverse
    alm.apus.editar_apu(Apu("A1", "MURO", "M2", "DIURNO", "ESTR"),
                        [ApuComponent("A1", "DIURNO", "100", "CEMENTO", "KG", 5.0, 0.0)])
    alm.precios.set_precio("100", 9999.0, "COMPRAS")
    assert corridas.vista_corrida(alm, cid)["items"][0]["costo_unitario"] == congelado
    # activar → vuelve a seguir la biblioteca
    v2 = corridas.activar(alm, cid)
    assert v2["modo"] == "activa"
    assert corridas.vista_corrida(alm, cid)["items"][0]["costo_unitario"] == 5.0 * 9999.0


def test_confirmar_bloqueado_si_congelada(tmp_path):
    alm, cid = _alm_con_apu(tmp_path)
    corridas.congelar(alm, cid)
    with pytest.raises(corridas.CorridaCongelada):
        corridas.confirmar_item(alm, cid, 0, "A1", "DIURNO")


def test_generar_cuadro_auto_congela(tmp_path):
    alm, cid = _alm_con_apu(tmp_path)
    out = corridas.generar_cuadro(alm, cid)
    assert out is not None
    meta = alm.corridas.get_corrida(cid)
    assert meta.modo == "congelada" and meta.estado == "finalizada"
    assert alm.corridas.get_snapshots(cid)                   # hay snapshots


def test_generar_cuadro_respeta_snapshot_si_ya_congelada(tmp_path):
    alm, cid = _alm_con_apu(tmp_path)
    corridas.congelar(alm, cid)                              # snapshot: costo_unitario 2000.0
    # editar el APU en la biblioteca DESPUÉS de congelar
    alm.apus.editar_apu(Apu("A1", "MURO", "M2", "DIURNO", "ESTR"),
                        [ApuComponent("A1", "DIURNO", "100", "CEMENTO", "KG", 5.0, 0.0)])
    corridas.generar_cuadro(alm, cid)                        # NO debe recongelar
    # la vista congelada sigue en 2000 (no 5000): el cuadro respetó el snapshot emitido
    assert corridas.vista_corrida(alm, cid)["items"][0]["costo_unitario"] == 2000.0
    assert alm.corridas.get_corrida(cid).estado == "finalizada"


def test_estructura_incluye_tipo_y_ref_shift():
    cc = CostedComponent("B", "SUBAPU", "M3", 3.0, 2000, "APU", 6000, "apu",
                         tipo="apu", ref_shift="DIURNO")
    d = _estructura([cc])[0]
    assert d["tipo"] == "apu" and d["ref_shift"] == "DIURNO"


def test_costear_row_respaldo_costea_subapu(tmp_path):
    alm = Almacen(tmp_path / "p.db", tmp_path / "a.db", tmp_path / "c.db")
    alm.reset()
    alm.precios.insert_insumos([Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU")])
    alm.apus.insert_apus([Apu("B", "SUBAPU", "M3", "DIURNO")])
    alm.apus.insert_components([ApuComponent("B", "DIURNO", "100", "CEMENTO", "KG", 2.0, 0.0)])
    # El APU padre "GONE" NO existe -> el respaldo usa row.componentes (con tipo='apu')
    row = CorridaItemRow(
        seq=0, item=LicitacionItem("1", "act", "M2", 1.0, 0.0, "DIURNO"),
        status="auto", apu_codigo="GONE", apu_nombre="X", unidad="M2", shift="DIURNO",
        origen="historico", confianza=1.0, explicacion="",
        componentes=[{"insumo_codigo": "B", "insumo_nombre": "SUBAPU", "unidad": "M3",
                      "rendimiento": 3.0, "tipo": "apu", "ref_shift": "DIURNO"}],
        candidatos=[])
    ens = _costear_row(alm, row)
    assert ens.costo_unitario == pytest.approx(6000)   # 3 * (2 * 1000), recursivo


def test_costear_row_motor_compartido_no_reconsulta_precios(tmp_path):
    """Optimización Fase 1: un PricingEngine compartido entre filas reusa el caché;
    un insumo compartido por dos ítems se consulta a la base UNA sola vez."""
    alm = Almacen(tmp_path / "p.db", tmp_path / "a.db", tmp_path / "c.db")
    alm.reset()
    alm.precios.insert_insumos([Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU")])
    alm.apus.insert_apus([Apu("A", "APU A", "M2", "DIURNO"), Apu("B", "APU B", "M2", "DIURNO")])
    alm.apus.insert_components([
        ApuComponent("A", "DIURNO", "100", "CEMENTO", "KG", 1.0, 0.0),
        ApuComponent("B", "DIURNO", "100", "CEMENTO", "KG", 2.0, 0.0)])

    llamadas: list[str] = []
    orig = alm.precios.get_candidatos
    alm.precios.get_candidatos = lambda cod: (llamadas.append(cod), orig(cod))[1]

    def _row(seq, cod):
        return CorridaItemRow(
            seq=seq, item=LicitacionItem(str(seq), "act", "M2", 1.0, 0.0, "DIURNO"),
            status="auto", apu_codigo=cod, apu_nombre=cod, unidad="M2", shift="DIURNO",
            origen="historico", confianza=1.0, explicacion="", componentes=[], candidatos=[])

    eng = PricingEngine(alm)
    ensA = _costear_row(alm, _row(0, "A"), eng)
    ensB = _costear_row(alm, _row(1, "B"), eng)
    assert ensA.costo_unitario == pytest.approx(1000) and ensB.costo_unitario == pytest.approx(2000)
    assert llamadas.count("100") == 1                 # motor compartido: 1 consulta, no 2


def _proj_ins(xs):
    return [(i.codigo, i.nombre, i.precio, i.id) for i in xs]


def _proj_comp(xs):
    return [(c.apu_codigo, c.shift, c.insumo_codigo, c.rendimiento, c.tipo, c.ref_shift) for c in xs]


def test_get_candidatos_bulk_igual_a_single(tmp_path):
    alm = Almacen(tmp_path / "p.db", tmp_path / "a.db", tmp_path / "c.db")
    alm.reset()
    alm.precios.insert_insumos([
        Insumo("100", "CEMENTO A", "KG", "MAT", 10, "F"),
        Insumo("100", "CEMENTO B", "KG", "MAT", 20, "F"),   # mismo código, otro insumo
        Insumo("200", "ARENA", "M3", "MAT", 30, "F")])
    bulk = alm.precios.get_candidatos_bulk(["100", "200", "999", ""])
    assert _proj_ins(bulk["100"]) == _proj_ins(alm.precios.get_candidatos("100"))
    assert _proj_ins(bulk["200"]) == _proj_ins(alm.precios.get_candidatos("200"))
    assert bulk["999"] == []                                # inexistente -> vacío
    assert "" not in bulk                                   # códigos vacíos se ignoran


def test_get_components_bulk_igual_a_single(tmp_path):
    alm = Almacen(tmp_path / "p.db", tmp_path / "a.db", tmp_path / "c.db")
    alm.reset()
    alm.apus.insert_apus([Apu("A", "AA", "M2", "DIURNO"), Apu("A", "AAN", "M2", "NOCTURNO"),
                          Apu("B", "BB", "M2", "DIURNO")])
    alm.apus.insert_components([
        ApuComponent("A", "DIURNO", "1", "x", "u", 1.0, 0.0),
        ApuComponent("A", "DIURNO", "2", "y", "u", 2.0, 0.0),
        ApuComponent("A", "NOCTURNO", "1", "x", "u", 5.0, 0.0),
        ApuComponent("B", "DIURNO", "3", "z", "u", 1.0, 0.0)])
    bulk = alm.apus.get_components_bulk([("A", "DIURNO"), ("A", "NOCTURNO"), ("B", "DIURNO"), ("Z", "DIURNO")])
    assert _proj_comp(bulk[("A", "DIURNO")]) == _proj_comp(alm.apus.get_components("A", "DIURNO"))
    assert _proj_comp(bulk[("A", "NOCTURNO")]) == _proj_comp(alm.apus.get_components("A", "NOCTURNO"))
    assert _proj_comp(bulk[("B", "DIURNO")]) == _proj_comp(alm.apus.get_components("B", "DIURNO"))
    assert ("Z", "DIURNO") not in bulk                      # inexistente no aparece


def test_precargar_costos_identicos_y_cero_consultas_individuales(tmp_path):
    """Fase 2: precargar en lote no cambia los costos y elimina las consultas 1x1
    (incluye sub-APU: el árbol se precarga con BFS)."""
    alm = Almacen(tmp_path / "p.db", tmp_path / "a.db", tmp_path / "c.db")
    alm.reset()
    alm.precios.insert_insumos([Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU"),
                                Insumo("200", "ARENA", "M3", "MAT", 500, "PRECIO IDU")])
    alm.apus.insert_apus([Apu("P", "PADRE", "M2", "DIURNO"), Apu("S", "SUB", "M3", "DIURNO")])
    alm.apus.insert_components([
        ApuComponent("P", "DIURNO", "100", "CEMENTO", "KG", 2.0, 0.0),
        ApuComponent("P", "DIURNO", "S", "SUB", "M3", 1.0, 0.0, tipo="apu", ref_shift="DIURNO"),
        ApuComponent("S", "DIURNO", "200", "ARENA", "M3", 3.0, 0.0)])

    def _row(seq):
        return CorridaItemRow(
            seq=seq, item=LicitacionItem(str(seq), "act", "M2", 1.0, 0.0, "DIURNO"),
            status="auto", apu_codigo="P", apu_nombre="PADRE", unidad="M2", shift="DIURNO",
            origen="historico", confianza=1.0, explicacion="", componentes=[], candidatos=[])
    rows = [_row(k) for k in range(3)]

    eng1 = PricingEngine(alm)                               # sin precarga
    costos1 = [_costear_row(alm, r, eng1).costo_unitario for r in rows]

    single = {"n": 0}                                       # contar consultas individuales
    for repo, meth in [(alm.precios, "get_candidatos"), (alm.apus, "get_components")]:
        orig = getattr(repo, meth)
        setattr(repo, meth,
                (lambda o: (lambda *a, **k: (single.__setitem__("n", single["n"] + 1), o(*a, **k))[1]))(orig))

    eng2 = PricingEngine(alm)
    eng2.precargar((r.apu_codigo, r.shift) for r in rows)   # BFS en lote
    costos2 = [_costear_row(alm, r, eng2).costo_unitario for r in rows]

    assert costos2[0] == pytest.approx(2 * 1000 + 1 * (3 * 500))   # 2000 + sub(1500) = 3500
    assert costos1 == costos2                               # idéntico con/sin precarga
    assert single["n"] == 0                                 # tras precargar: cero consultas 1x1


def test_precargar_falla_cae_a_individual_sin_romper(tmp_path):
    """Fase 2 fail-safe: si el batch revienta, precargar no rompe y el costeo sigue
    dando el costo correcto vía consultas individuales."""
    alm = Almacen(tmp_path / "p.db", tmp_path / "a.db", tmp_path / "c.db")
    alm.reset()
    alm.precios.insert_insumos([Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU")])
    alm.apus.insert_apus([Apu("A", "APU A", "M2", "DIURNO")])
    alm.apus.insert_components([ApuComponent("A", "DIURNO", "100", "CEMENTO", "KG", 2.0, 0.0)])

    def _boom(*_a, **_k):
        raise RuntimeError("batch no soportado")
    alm.apus.get_components_bulk = _boom          # simula fallo del batch

    row = CorridaItemRow(
        seq=0, item=LicitacionItem("1", "act", "M2", 1.0, 0.0, "DIURNO"),
        status="auto", apu_codigo="A", apu_nombre="A", unidad="M2", shift="DIURNO",
        origen="historico", confianza=1.0, explicacion="", componentes=[], candidatos=[])
    eng = PricingEngine(alm)
    eng.precargar([("A", "DIURNO")])              # no debe propagar la excepción
    ens = _costear_row(alm, row, eng)
    assert ens.costo_unitario == pytest.approx(2000)   # costo correcto vía individual


def test_costear_row_activa_no_duplica_rendimiento_en_autoreferencia(tmp_path):
    # FIX 2 (regresión): la rama ACTIVA de _costear_row debe sembrar la identidad de
    # la fila en pricing.cost_components; si no, un componente auto-referenciado
    # (dato inválido, pero posible) cuenta el rendimiento dos veces (2000 en vez de
    # 1000) porque el ciclo no se detecta hasta el segundo nivel de recursión.
    alm = Almacen(tmp_path / "p.db", tmp_path / "a.db", tmp_path / "c.db")
    alm.reset()
    alm.apus.insert_apus([Apu("Y", "AUTORREF", "M2", "DIURNO")])
    alm.apus.insert_components([ApuComponent(
        "Y", "DIURNO", "Y", "AUTORREF", "M2", 2.0, 500.0, tipo="apu", ref_shift="DIURNO")])
    item = LicitacionItem("1", "act", "M2", 1.0, 0.0, "DIURNO")
    row = CorridaItemRow(
        seq=0, item=item, status="auto", apu_codigo="Y", apu_nombre="AUTORREF",
        unidad="M2", shift="DIURNO", origen="historico", confianza=1.0, explicacion="",
        componentes=[], candidatos=[])
    ens = _costear_row(alm, row)
    assert ens.costo_unitario == pytest.approx(1000.0)   # 2 * 500 (histórico), guardado
    assert ens.componentes[0].calidad_cruce == "ciclo"
