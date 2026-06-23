import sqlite3
import pytest
from apu_tool import config
from apu_tool.datos.precios_db import PreciosDB
from apu_tool.datos.repositorio import RepositorioPrecios
from apu_tool.nucleo.models import Insumo


@pytest.fixture()
def precios(tmp_path):
    d = PreciosDB(tmp_path / "precios.db")
    d.reset()
    d.insert_insumos([
        Insumo("100", "CEMENTO GRIS", "KG", "MAT", 1000, "PRECIO IDU"),
        Insumo("200", "ACERO FIGURADO", "KG", "MAT", 5000, "COSTO INTERNO"),
    ])
    return d


def test_cumple_contrato(precios):
    assert isinstance(precios, RepositorioPrecios)

def test_precio_y_clasificacion(precios):
    assert precios.get_insumo("100").precio == 1000
    assert precios.get_insumo("100").es_confidencial is False
    assert precios.get_insumo("200").es_confidencial is True

def test_set_precio_vigente_e_historial(precios):
    precios.set_precio("100", 1500, fuente="COMPRAS 2026")
    assert precios.get_insumo("100").precio == 1500
    hist = precios.price_history("100")
    assert sum(h["vigente"] for h in hist) == 1 and len(hist) == 2

def test_fk_precio_requiere_insumo(precios):
    with pytest.raises(sqlite3.IntegrityError):
        with precios.connect() as c:
            c.execute("INSERT INTO insumo_precios (codigo, precio, vigente) "
                      "VALUES ('NOEXISTE', 1, 1)")

def test_busqueda(precios):
    assert any(i.codigo == "100" for i in precios.search_insumos("CEMENTO"))
    assert any(i.codigo == "200" for i in precios.search_insumos_por_palabras(["ACERO"]))

def test_counts(precios):
    c = precios.counts()
    assert c["insumos"] == 2 and c["insumo_precios"] == 2
