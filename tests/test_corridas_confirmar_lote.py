"""Confirmar/asignar APU en lote: un recosteo para N ítems."""
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo, LicitacionItem
from apu_tool.servicio import corridas as svc


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([Insumo("100", "CEMENTO", "KG", "MAT", 1000.0, "PRECIO IDU")])
    alm.apus.crear_apu(Apu("A1", "MURO", "M2", "DIURNO", "ESTR"),
                       [ApuComponent("A1", "DIURNO", "100", "CEMENTO", "KG", 2.0, 0.0)])
    alm.apus.crear_apu(Apu("A2", "MURO REFORZADO", "M2", "DIURNO", "ESTR"),
                       [ApuComponent("A2", "DIURNO", "100", "CEMENTO", "KG", 3.0, 0.0)])
    return alm, alm.carpetas.crear("Obra")


def _corrida(alm, sc, n=3):
    items = [LicitacionItem(item=str(i + 1), descripcion="muro", unidad="M2",
                            cantidad=1.0, precio_contractual=10000.0, shift="DIURNO")
             for i in range(n)]
    return svc.construir_corrida(alm, "lic.xlsx", items, "DIURNO", False, carpeta_id=sc)


def _estado(alm, cid):
    return {r.seq: (r.status, r.apu_codigo) for r in alm.corridas.get_items(cid)}


def test_asignar_un_apu_a_varios_seqs(tmp_path):
    alm, sc = _alm(tmp_path)
    cid = _corrida(alm, sc)
    v = svc.confirmar_items(alm, cid, [0, 1, 2], apu_codigo="A2", shift="DIURNO")
    assert v is not None
    assert _estado(alm, cid) == {0: ("confirmed", "A2"), 1: ("confirmed", "A2"),
                                 2: ("confirmed", "A2")}
    # una sola vista, coherente con lo persistido
    assert {it["apu_codigo"] for it in v["items"]} == {"A2"}
    assert v["totales"]["n_items"] == 3


def test_asignar_solo_toca_los_seqs_pedidos(tmp_path):
    alm, sc = _alm(tmp_path)
    cid = _corrida(alm, sc)
    antes = _estado(alm, cid)
    svc.confirmar_items(alm, cid, [1], apu_codigo="A2", shift="DIURNO")
    despues = _estado(alm, cid)
    assert despues[1] == ("confirmed", "A2")
    assert despues[0] == antes[0] and despues[2] == antes[2]


def test_sin_apu_codigo_confirma_el_que_ya_tiene(tmp_path):
    alm, sc = _alm(tmp_path)
    cid = _corrida(alm, sc)
    previos = {seq: cod for seq, (_, cod) in _estado(alm, cid).items()}
    svc.confirmar_items(alm, cid, [0, 1, 2])            # sin apu_codigo
    for seq, (status, cod) in _estado(alm, cid).items():
        assert status == "confirmed"
        assert cod == previos[seq]                       # no se reasignó nada


def test_apu_inexistente_no_toca_nada(tmp_path):
    """Sin esto el ítem queda con composición vacía y costeado en $0
    (regla de negocio: nada en $0 en silencio)."""
    alm, sc = _alm(tmp_path)
    cid = _corrida(alm, sc)
    antes = _estado(alm, cid)
    with pytest.raises(ValueError):
        svc.confirmar_items(alm, cid, [0, 1, 2], apu_codigo="NOEXISTE", shift="DIURNO")
    assert _estado(alm, cid) == antes


def test_sin_shift_cae_al_turno_de_la_fila(tmp_path):
    """Confirmar sin turno es un camino real (el botón "Elegir" de los candidatos y
    "Confirmar APU actual" llaman sin él), así que NO puede ser un error."""
    alm, sc = _alm(tmp_path)
    cid = _corrida(alm, sc)
    v = svc.confirmar_items(alm, cid, [0], apu_codigo="A2")      # sin shift
    assert v is not None
    assert _estado(alm, cid)[0] == ("confirmed", "A2")


def test_seq_inexistente_se_saltea(tmp_path):
    alm, sc = _alm(tmp_path)
    cid = _corrida(alm, sc)
    svc.confirmar_items(alm, cid, [0, 999], apu_codigo="A2", shift="DIURNO")
    est = _estado(alm, cid)
    assert est[0] == ("confirmed", "A2") and 999 not in est


def test_lista_vacia_no_hace_nada_y_devuelve_la_vista(tmp_path):
    alm, sc = _alm(tmp_path)
    cid = _corrida(alm, sc)
    antes = _estado(alm, cid)
    v = svc.confirmar_items(alm, cid, [])
    assert v is not None and _estado(alm, cid) == antes


def test_corrida_inexistente_devuelve_none(tmp_path):
    alm, _ = _alm(tmp_path)
    assert svc.confirmar_items(alm, 999, [0], apu_codigo="A1", shift="DIURNO") is None


def test_corrida_congelada_rechaza_el_lote(tmp_path):
    alm, sc = _alm(tmp_path)
    cid = _corrida(alm, sc)
    svc.congelar(alm, cid)
    with pytest.raises(svc.CorridaCongelada):
        svc.confirmar_items(alm, cid, [0], apu_codigo="A2", shift="DIURNO")


def test_confirmar_item_sigue_funcionando_igual(tmp_path):
    """El wrapper de 1 seq no cambia de comportamiento."""
    alm, sc = _alm(tmp_path)
    cid = _corrida(alm, sc)
    v = svc.confirmar_item(alm, cid, 1, "A2", "DIURNO")
    assert v is not None
    assert _estado(alm, cid)[1] == ("confirmed", "A2")


def test_endpoint_confirmar_lote(tmp_path):
    from apu_tool.servicio.app import create_app
    from tests.conftest import cliente

    alm, sc = _alm(tmp_path)
    cid = _corrida(alm, sc)
    cli = cliente(create_app(almacen=alm), rol="admin")
    r = cli.post(f"/api/corridas/{cid}/items/confirmar-lote",
                 json={"seqs": [0, 2], "apu_codigo": "A2", "shift": "DIURNO"})
    assert r.status_code == 200, r.text
    est = _estado(alm, cid)
    assert est[0] == ("confirmed", "A2") and est[2] == ("confirmed", "A2")
    # APU inexistente -> 400, nada cambia
    assert cli.post(f"/api/corridas/{cid}/items/confirmar-lote",
                    json={"seqs": [1], "apu_codigo": "NOPE", "shift": "DIURNO"}
                    ).status_code == 400
    # corrida inexistente -> 404
    assert cli.post("/api/corridas/999/items/confirmar-lote",
                    json={"seqs": [0]}).status_code == 404
    # congelada -> 409
    svc.congelar(alm, cid)
    assert cli.post(f"/api/corridas/{cid}/items/confirmar-lote",
                    json={"seqs": [1], "apu_codigo": "A2", "shift": "DIURNO"}
                    ).status_code == 409
