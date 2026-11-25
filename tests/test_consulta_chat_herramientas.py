"""Las herramientas del chat de consulta: sin dinero, con refs."""
import pytest

from apu_tool.dominio import privacy
from apu_tool.dominio.consulta_chat import HerramientasConsulta
from tests.consulta_base import almacen_consulta


@pytest.fixture()
def base(tmp_path):
    return almacen_consulta(tmp_path)


def _sin_dinero(r):
    privacy.assert_no_money(r)
    texto = privacy.safe_json(r)
    for prohibido in ("35000", "40000", "30000", "50000", "10000", "25000", "900000",
                      "COSTO INTERNO", "PRECIO IDU"):
        assert prohibido not in texto


def test_buscar_insumos_trae_refs_por_id_y_sin_precio(base):
    alm, ids = base
    r = HerramientasConsulta(alm).ejecutar("buscar_insumos", {"texto": "tuberia pvc"})
    assert {i["ref"] for i in r["insumos"]} == {
        f"insumo:{ids['insumo_tubo']}", f"insumo:{ids['insumo_cero']}"}
    _sin_dinero(r)


def test_buscar_apus_trae_los_dos_turnos(base):
    alm, _ = base
    r = HerramientasConsulta(alm).ejecutar("buscar_apus", {"texto": "mezcla asfaltica"})
    refs = {a["ref"] for a in r["apus"]}
    assert "apu:A1|DIURNO" in refs and "apu:A1 N|NOCTURNO" in refs
    _sin_dinero(r)


def test_buscar_proyectos_trae_las_corridas_de_subcarpetas(base):
    alm, ids = base
    r = HerramientasConsulta(alm).ejecutar("buscar_proyectos", {"texto": "la cali"})
    assert [p["proyecto"] for p in r["proyectos"]] == ["LA CALI"]
    assert [c["ref"] for c in r["proyectos"][0]["corridas"]] == [f"corrida:{ids['cali']}"]
    assert r["proyectos"][0]["corridas"][0]["carpeta"] == "PRESUPUESTO"
    _sin_dinero(r)


def test_buscar_proyectos_por_numero_de_calle(base):
    alm, ids = base
    r = HerramientasConsulta(alm).ejecutar("buscar_proyectos", {"texto": "calle 13"})
    assert r["proyectos"][0]["corridas"][0]["ref"] == f"corrida:{ids['calle13']}"


def test_buscar_proyectos_encuentra_corridas_por_su_propio_nombre(base):
    alm, ids = base
    r = HerramientasConsulta(alm).ejecutar("buscar_proyectos", {"texto": "lote sl5"})
    assert r["proyectos"] == []
    assert [c["ref"] for c in r["corridas"]] == [f"corrida:{ids['calle13']}"]


def test_buscar_proyectos_sin_palabras_utiles_no_trae_nada(base):
    alm, _ = base
    r = HerramientasConsulta(alm).ejecutar("buscar_proyectos", {"texto": "la de"})
    assert r["proyectos"] == [] and r["corridas"] == []


def test_capitulos_cuenta_actividades_sin_costear(base):
    alm, ids = base
    cid = ids["calle13"]
    r = HerramientasConsulta(alm).ejecutar("capitulos", {"corrida_id": cid})
    assert r["capitulos"] == [
        {"ref": f"capitulo:{cid}:1", "codigo": "1", "nombre": "PRELIMINARES",
         "actividades": 1},
        {"ref": f"capitulo:{cid}:2", "codigo": "2", "nombre": "REDES HUMEDAS",
         "actividades": 2},
    ]
    _sin_dinero(r)


def test_capitulos_de_corrida_inexistente_o_invalida_es_error(base):
    alm, _ = base
    h = HerramientasConsulta(alm)
    assert "error" in h.ejecutar("capitulos", {"corrida_id": 999})
    assert "error" in h.ejecutar("capitulos", {"corrida_id": "x"})


def test_herramienta_desconocida(base):
    alm, _ = base
    assert "error" in HerramientasConsulta(alm).ejecutar("borrar", {"texto": "x"})
