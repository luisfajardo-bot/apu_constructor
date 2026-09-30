# tests/test_api_notas_listados.py
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, Insumo
from apu_tool.servicio.app import create_app
from tests.conftest import cliente


def _cli(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo("100", "Concreto 3000 PSI", "M3", "CONCRETOS", 350000.0, "COSTO INTERNO"),
        Insumo("100", "Concreto 4000 PSI", "M3", "CONCRETOS", 390000.0, "COSTO INTERNO")])
    alm.apus.insert_apus([Apu("A1", "EXCAVACION", "M3", "DIURNO", "EXC"),
                          Apu("A1", "EXCAVACION", "M3", "NOCTURNO", "EXC")])
    return cliente(create_app(almacen=alm), rol="editor"), alm


def test_insumos_marcan_solo_el_que_tiene_notas(tmp_path):
    cli, _ = _cli(tmp_path)
    cli.post("/api/notas", json={"entidad": "insumo", "codigo": "100",
                                 "nombre": "Concreto 4000 PSI", "texto": "x" * 200})
    items = {i["nombre"]: i for i in cli.get("/api/insumos?q=concreto").json()["items"]}
    assert items["Concreto 4000 PSI"]["tiene_notas"] is True
    assert items["Concreto 4000 PSI"]["ultima_nota"] == "x" * 120
    assert items["Concreto 3000 PSI"]["tiene_notas"] is False      # mismo código, otro insumo
    assert items["Concreto 3000 PSI"]["ultima_nota"] == ""


def test_apus_marcan_por_turno(tmp_path):
    cli, _ = _cli(tmp_path)
    cli.post("/api/notas", json={"entidad": "apu", "codigo": "A1", "turno": "NOCTURNO",
                                 "texto": "medido en obra"})
    items = {i["turno"]: i for i in cli.get("/api/apus").json()["items"]}
    assert items["NOCTURNO"]["tiene_notas"] is True
    assert items["NOCTURNO"]["ultima_nota"] == "medido en obra"
    assert items["DIURNO"]["tiene_notas"] is False


def test_una_sola_consulta_de_notas_por_pagina(tmp_path, monkeypatch):
    cli, alm = _cli(tmp_path)
    llamadas = []
    original = alm.notas.resumen_por_claves
    monkeypatch.setattr(alm.notas, "resumen_por_claves",
                        lambda e, c: llamadas.append(len(c)) or original(e, c))
    cli.get("/api/insumos?q=concreto")
    cli.get("/api/apus")
    assert llamadas == [2, 2]           # una por listado, con todas las claves de la página
