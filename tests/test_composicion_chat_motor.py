"""El chat de composición: herramientas y bucle. El SDK se sustituye."""
import json

import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.dominio.composicion_chat import Herramientas
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo, LicitacionItem

ITEM = LicitacionItem("1.3", "EXCAVACION MANUAL EN MATERIAL COMUN", "M3", 120.0,
                      180000.0, "DIURNO")


@pytest.fixture()
def alm(tmp_path):
    a = Almacen(tmp_path / "precios.db", tmp_path / "apus.db",
                tmp_path / "corridas.db")
    a.reset()
    a.precios.insert_insumos([
        Insumo("4279", "CUADRILLA OFICIAL MAS AYUDANTES", "HR", "SUELDOS Y JORNALES",
               40000, "PRECIO IDU"),
        Insumo("6092", "HERRAMIENTA MENOR", "GLB", "EQ", 2000, "PRECIO IDU"),
        Insumo("7001", "OFICIAL SOLDADOR CERTIFICADO", "HR", "SUELDOS Y JORNALES",
               55000, "COSTO INTERNO"),
        Insumo("7002", "SOLDADOR VIEJO", "HR", "SUELDOS Y JORNALES", 50000,
               "COSTO INTERNO"),
    ])
    oculto = a.precios.search_insumos("SOLDADOR VIEJO")[0]
    a.precios.set_oculto(oculto.id, True)
    a.apus.insert_apus([
        Apu("A1", "EXCAVACION MANUAL COMUN", "M3", "DIURNO", "EXCAVACIONES")])
    a.apus.insert_components([
        ApuComponent("A1", "DIURNO", "4279", "CUADRILLA", "HR", 0.62, 40000),
        ApuComponent("A1", "DIURNO", "6092", "HERRAMIENTA MENOR", "GLB", 1.0, 2000),
    ])
    return a


# --- herramientas ------------------------------------------------------------
def test_buscar_insumos_trae_visibles_sin_precio(alm):
    r = Herramientas(alm, "DIURNO").ejecutar("buscar_insumos", {"texto": "soldador"})
    codigos = [i["insumo_codigo"] for i in r["insumos"]]
    assert codigos == ["7001"]                       # 7002 está oculto
    texto = json.dumps(r)
    assert "55000" not in texto and "COSTO INTERNO" not in texto


def test_buscar_insumos_ordena_por_parecido_y_trae_lo_observado(alm):
    r = Herramientas(alm, "DIURNO").ejecutar("buscar_insumos",
                                             {"texto": "cuadrilla oficial"})
    assert r["insumos"][0]["insumo_codigo"] == "4279"
    assert r["insumos"][0]["rendimientos_observados"]["mediana"] == 0.62


def test_buscar_apus_trae_la_composicion_sin_precio(alm):
    r = Herramientas(alm, "DIURNO").ejecutar("buscar_apus",
                                             {"texto": "excavacion manual"})
    assert r["apus"][0]["codigo"] == "A1"
    assert {c["insumo_codigo"] for c in r["apus"][0]["componentes"]} == {"4279", "6092"}
    assert "40000" not in json.dumps(r)


def test_herramienta_desconocida_devuelve_error_y_no_revienta(alm):
    r = Herramientas(alm, "DIURNO").ejecutar("borrar_todo", {"texto": "x"})
    assert "error" in r


def test_una_busqueda_sin_palabras_utiles_devuelve_vacio(alm):
    r = Herramientas(alm, "DIURNO").ejecutar("buscar_insumos", {"texto": "de la"})
    assert r["insumos"] == []
