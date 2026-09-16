# tests/test_api_rebuscar.py
"""Contrato HTTP de volver a buscar APU."""
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo, LicitacionItem
from apu_tool.servicio import corridas as svc
from apu_tool.servicio.app import create_app
from tests.conftest import cliente


def _cliente(tmp_path):
    """Almacén con un APU (A1) y una corrida de una línea que NO matchea con nada."""
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([Insumo("100", "Concreto 3000 PSI", "M3",
                                       "CONCRETOS", 350000.0, "COSTO INTERNO")])
    alm.apus.insert_apus([Apu("A1", "Concreto clase D", "M3", "DIURNO", "ESTR")])
    alm.apus.insert_components([ApuComponent("A1", "DIURNO", "100",
                               "Concreto 3000 PSI", "M3", 1.0, 350000.0)])
    item = LicitacionItem(item="1", descripcion="Pantalla acustica modular en aluminio",
                          unidad="M2", cantidad=10.0, precio_contractual=900000.0,
                          shift="DIURNO")
    cid = svc.construir_corrida(alm, "lic.xlsx", [item], "DIURNO", use_ai=False)
    return cliente(create_app(almacen=alm), rol="admin"), alm, cid


def _apu_nuevo(alm):
    """El APU que aparece DESPUÉS del armado: es lo que la corrida no puede ver."""
    alm.apus.insert_apus([Apu("A9", "Pantalla acustica modular en aluminio", "M2",
                              "DIURNO", "ESTR")])
    alm.apus.insert_components([ApuComponent("A9", "DIURNO", "100",
                               "Concreto 3000 PSI", "M2", 2.0, 350000.0)])


def test_rebuscar_devuelve_la_previa_sin_escribir(tmp_path):
    cli, alm, cid = _cliente(tmp_path)
    _apu_nuevo(alm)
    r = cli.post(f"/api/corridas/{cid}/rebuscar")
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["escaneadas"] == 1
    assert cuerpo["propuestas"][0]["apu_propuesto"]["codigo"] == "A9"
    assert cuerpo["propuestas"][0]["sin_apu"] is True
    assert alm.corridas.get_items(cid)[0].apu_codigo is None      # no escribió


def test_aplicar_devuelve_la_corrida_recosteada(tmp_path):
    cli, alm, cid = _cliente(tmp_path)
    _apu_nuevo(alm)
    r = cli.post(f"/api/corridas/{cid}/rebuscar/aplicar", json={"seqs": [0]})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["items"][0]["apu_codigo"] == "A9"
    assert cuerpo["items"][0]["costo_unitario"] == 2.0 * 350000.0
    assert cuerpo["rebusqueda"]["aplicadas"] == [0]
    assert cuerpo["rebusqueda"]["salteadas"] == []


def test_rebuscar_congelada_da_409(tmp_path):
    cli, alm, cid = _cliente(tmp_path)
    alm.corridas.set_modo(cid, "congelada")
    r = cli.post(f"/api/corridas/{cid}/rebuscar")
    assert r.status_code == 409
    assert "congelada" in r.json()["detail"]


def test_rebuscar_corrida_inexistente_da_404(tmp_path):
    cli, _alm, _cid = _cliente(tmp_path)
    assert cli.post("/api/corridas/999/rebuscar").status_code == 404


def test_rebuscar_plan_a_medias_da_400(tmp_path):
    cli, alm, cid = _cliente(tmp_path)
    alm.corridas.set_estado(cid, "armado_detenido")
    r = cli.post(f"/api/corridas/{cid}/rebuscar")
    assert r.status_code == 400
    assert "por armar" in r.json()["detail"]
