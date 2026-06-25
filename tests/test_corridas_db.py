from apu_tool.nucleo.models import CorridaItemRow, CorridaMeta, LicitacionItem
from apu_tool.datos.almacen import Almacen


def test_corrida_meta_y_item_row_se_construyen():
    meta = CorridaMeta(id=None, creada_en="2026-06-24T10:00:00", archivo="lic.xlsx",
                       turno_def="DIURNO", use_ai=False, estado="en_revision")
    assert meta.cuadro_path is None
    item = LicitacionItem(item="1", descripcion="Concreto", unidad="M3",
                          cantidad=10.0, precio_contractual=400000.0, shift="DIURNO")
    row = CorridaItemRow(seq=0, item=item, status="auto", apu_codigo="A1",
                         apu_nombre="Concreto clase D", unidad="M3", shift="DIURNO",
                         origen="historico", confianza=1.0, explicacion="",
                         componentes=[], candidatos=[])
    assert row.seq == 0 and row.item.precio_contractual == 400000.0


def _almacen_tmp(tmp_path):
    alm = Almacen(precios_path=tmp_path / "precios.db",
                  apus_path=tmp_path / "apus.db",
                  corridas_path=tmp_path / "corridas.db")
    alm.init_schema()
    return alm


def _fila(seq=0):
    item = LicitacionItem(item=str(seq + 1), descripcion="Concreto clase D",
                          unidad="M3", cantidad=10.0, precio_contractual=400000.0,
                          shift="DIURNO")
    return CorridaItemRow(
        seq=seq, item=item, status="review", apu_codigo="A1",
        apu_nombre="Concreto clase D", unidad="M3", shift="DIURNO",
        origen="historico", confianza=0.7, explicacion="dudoso",
        componentes=[{"insumo_codigo": "100", "insumo_nombre": "Concreto 3000 PSI",
                      "unidad": "M3", "rendimiento": 1.05}],
        candidatos=[{"apu_codigo": "A1", "apu_nombre": "Concreto clase D",
                     "score": 0.7, "motivo": ""}])


def test_corrida_roundtrip(tmp_path):
    alm = _almacen_tmp(tmp_path)
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-06-24T10:00:00", archivo="lic.xlsx",
        turno_def="DIURNO", use_ai=False, estado="en_revision"))
    assert isinstance(cid, int)
    assert alm.corridas.guardar_items(cid, [_fila(0), _fila(1)]) == 2

    meta = alm.corridas.get_corrida(cid)
    assert meta.archivo == "lic.xlsx" and meta.use_ai is False
    items = alm.corridas.get_items(cid)
    assert len(items) == 2
    assert items[0].item.precio_contractual == 400000.0
    assert items[0].componentes[0]["insumo_codigo"] == "100"
    assert items[0].candidatos[0]["apu_codigo"] == "A1"


def test_actualizar_eleccion_y_estado(tmp_path):
    alm = _almacen_tmp(tmp_path)
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="x", archivo="lic.xlsx", turno_def="DIURNO",
        use_ai=None, estado="en_revision"))
    alm.corridas.guardar_items(cid, [_fila(0)])
    alm.corridas.actualizar_eleccion(
        cid, 0, status="confirmed", apu_codigo="A2", apu_nombre="Otro APU",
        unidad="M3", shift="DIURNO", origen="historico", confianza=1.0,
        explicacion="Confirmado por el usuario.", componentes=[])
    row = alm.corridas.get_item(cid, 0)
    assert row.status == "confirmed" and row.apu_codigo == "A2"
    alm.corridas.set_estado(cid, "finalizada")
    assert alm.corridas.get_corrida(cid).estado == "finalizada"


def test_get_corrida_inexistente(tmp_path):
    alm = _almacen_tmp(tmp_path)
    assert alm.corridas.get_corrida(999) is None


def test_listar_y_eliminar_corridas(tmp_path):
    alm = _almacen_tmp(tmp_path)
    c1 = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-06-25T10:00:00", archivo="a.xlsx",
        turno_def="DIURNO", use_ai=False, estado="en_revision"))
    c2 = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-06-25T11:00:00", archivo="b.xlsx",
        turno_def="DIURNO", use_ai=False, estado="en_revision"))
    alm.corridas.guardar_items(c2, [_fila(0)])

    metas = alm.corridas.listar_corridas()
    assert [m.id for m in metas] == [c2, c1]          # más reciente primero
    assert metas[0].archivo == "b.xlsx"

    assert alm.corridas.eliminar_corrida(c2) is True
    assert alm.corridas.get_corrida(c2) is None       # se fue
    assert alm.corridas.get_items(c2) == []           # cascade borró los ítems
    assert [m.id for m in alm.corridas.listar_corridas()] == [c1]
    assert alm.corridas.eliminar_corrida(99999) is False
