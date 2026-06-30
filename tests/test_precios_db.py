import sqlite3
import pytest
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
        # mismo código 100, insumo distinto -> debe convivir
        Insumo("100", "BASE GRANULAR", "M3", "MAT", 190300, "PRECIO IDU"),
    ])
    return d


def test_cumple_contrato(precios):
    assert isinstance(precios, RepositorioPrecios)

def test_codigo_repetido_convive(precios):
    cands = precios.get_candidatos("100")
    assert len(cands) == 2
    nombres = {c.nombre for c in cands}
    assert nombres == {"CEMENTO GRIS", "BASE GRANULAR"}

def test_candidato_trae_id_y_precio(precios):
    cem = [c for c in precios.get_candidatos("100") if c.nombre == "CEMENTO GRIS"][0]
    assert cem.id is not None and cem.precio == 1000
    assert precios.get_insumo_por_id(cem.id).nombre == "CEMENTO GRIS"

def test_clasificacion(precios):
    base = [c for c in precios.get_candidatos("100") if c.nombre == "BASE GRANULAR"][0]
    assert base.es_confidencial is False
    assert precios.get_candidatos("200")[0].es_confidencial is True

def test_set_precio_desambigua_por_nombre(precios):
    precios.set_precio("100", 1500, fuente="COMPRAS 2026", nombre="CEMENTO GRIS")
    cem = [c for c in precios.get_candidatos("100") if c.nombre == "CEMENTO GRIS"][0]
    base = [c for c in precios.get_candidatos("100") if c.nombre == "BASE GRANULAR"][0]
    assert cem.precio == 1500 and base.precio == 190300  # solo cambió el cemento
    hist = precios.price_history("100", nombre="CEMENTO GRIS")
    assert sum(h["vigente"] for h in hist) == 1 and len(hist) == 2

def test_set_precio_codigo_ambiguo_sin_nombre_falla(precios):
    with pytest.raises(ValueError):
        precios.set_precio("100", 1500)   # 100 es ambiguo, falta --nombre

def test_fk_precio_requiere_insumo(precios):
    with pytest.raises(sqlite3.IntegrityError):
        with precios.connect() as c:
            c.execute("INSERT INTO insumo_precios (insumo_id, precio, vigente) "
                      "VALUES (999999, 1, 1)")

def test_busqueda(precios):
    assert any(i.codigo == "100" for i in precios.search_insumos("CEMENTO"))
    assert any(i.codigo == "200" for i in precios.search_insumos_por_palabras(["ACERO"]))

def test_counts(precios):
    c = precios.counts()
    assert c["insumos"] == 3 and c["insumo_precios"] == 3


def test_crear_insumo_nuevo(precios):
    iid = precios.crear_insumo(Insumo("300", "GRAVA COMUN", "M3", "MAT", 80000, "PRECIO IDU"))
    assert isinstance(iid, int)
    ins = precios.get_insumo_por_id(iid)
    assert ins.codigo == "300" and ins.nombre == "GRAVA COMUN" and ins.precio == 80000
    assert ins.es_confidencial is False  # PRECIO IDU -> publico

def test_crear_insumo_duplicado_falla(precios):
    # misma identidad (codigo, nombre_norm) ya existe -> no se pisa
    with pytest.raises(ValueError):
        precios.crear_insumo(Insumo("100", "Cemento Gris", "KG", "MAT", 1, "PRECIO IDU"))

def test_crear_insumo_mismo_codigo_otro_nombre_ok(precios):
    iid = precios.crear_insumo(Insumo("100", "CAL HIDRATADA", "KG", "MAT", 2000, "PRECIO IDU"))
    assert precios.get_insumo_por_id(iid).nombre == "CAL HIDRATADA"
    assert len(precios.get_candidatos("100")) == 3  # convive con las 2 previas
