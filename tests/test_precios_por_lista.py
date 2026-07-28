"""Precios por lista: dos tarifas vivas a la vez sobre el mismo catálogo."""
import pytest

from apu_tool import config
from apu_tool.datos.precios_db import PreciosDB
from apu_tool.nucleo.models import Insumo


@pytest.fixture()
def precios(tmp_path):
    p = PreciosDB(tmp_path / "precios.db")
    p.init_schema()
    p.insert_insumos([
        Insumo("6140", "ACERO 60000 PSI", "KG", "MATERIAL", 3500.0, "PRECIO IDU"),
        Insumo("9", "CEMENTO GRIS", "KG", "MATERIAL", 900.0, "COSTO INTERNO"),
    ])
    return p


@pytest.fixture()
def np(precios):
    return precios.crear_lista("NP Calle 13")


def test_seed_queda_en_principal(precios):
    assert precios.get_candidatos("6140")[0].precio == 3500.0
    assert precios.get_candidatos("6140", lista_id=config.LISTA_PRINCIPAL_ID)[0].precio == 3500.0


def test_precio_en_np_no_toca_principal(precios, np):
    iid = precios.get_candidatos("6140")[0].id
    precios.set_precio_por_id(iid, 4200.0, "ACTA NP", lista_id=np)
    assert precios.get_candidatos("6140", lista_id=np)[0].precio == 4200.0
    assert precios.get_candidatos("6140")[0].precio == 3500.0          # Principal intacto


def test_vigente_es_por_lista(precios, np):
    iid = precios.get_candidatos("9")[0].id
    precios.set_precio_por_id(iid, 1100.0, "ACTA NP", lista_id=np)
    precios.set_precio_por_id(iid, 950.0, "COMPRAS 2026")               # Principal
    assert precios.get_insumo_por_id(iid, lista_id=np).precio == 1100.0
    assert precios.get_insumo_por_id(iid).precio == 950.0


def test_insumo_sin_precio_en_la_lista(precios, np):
    ins = precios.get_candidatos("6140", lista_id=np)[0]
    assert ins.precio == 0.0 and ins.sin_precio is True
    assert precios.get_candidatos("6140")[0].sin_precio is False


def test_bulk_respeta_la_lista(precios, np):
    iid = precios.get_candidatos("6140")[0].id
    precios.set_precio_por_id(iid, 4200.0, "ACTA NP", lista_id=np)
    bulk = precios.get_candidatos_bulk(["6140", "9"], lista_id=np)
    assert bulk["6140"][0].precio == 4200.0
    assert bulk["9"][0].sin_precio is True


def test_price_history_filtra_por_lista(precios, np):
    iid = precios.get_candidatos("9")[0].id
    precios.set_precio_por_id(iid, 1100.0, "ACTA NP", lista_id=np)
    assert len(precios.price_history("9")) == 1                          # solo el del seed
    assert len(precios.price_history("9", lista_id=np)) == 1
    assert precios.price_history("9", lista_id=np)[0]["precio"] == 1100.0


def test_crear_insumo_en_np_no_existe_en_principal(precios, np):
    iid = precios.crear_insumo(
        Insumo("NP-INS-1", "GEOTEXTIL NT 2500", "M2", "MATERIAL", 8000.0, "ACTA NP"),
        lista_id=np)
    assert precios.get_insumo_por_id(iid, lista_id=np).precio == 8000.0
    assert precios.get_insumo_por_id(iid).sin_precio is True             # sin precio en Principal


def test_list_insumos_devuelve_todo_el_catalogo_con_precio_nulo(precios, np):
    items, total = precios.list_insumos(lista_id=np, limit=50, offset=0)
    assert total == 2                                                     # catálogo completo
    assert all(i.sin_precio for i in items)


def test_list_insumos_filtro_sin_precio(precios, np):
    iid = precios.get_candidatos("6140")[0].id
    precios.set_precio_por_id(iid, 4200.0, "ACTA NP", lista_id=np)
    items, total = precios.list_insumos(lista_id=np, sin_precio=True, limit=50, offset=0)
    assert total == 1 and items[0].codigo == "9"


def test_sin_precio_es_excluyente_con_fuente_y_clasificacion(precios, np):
    with pytest.raises(ValueError):
        precios.list_insumos(lista_id=np, sin_precio=True, fuente="ACTA NP")
    with pytest.raises(ValueError):
        precios.list_insumos(lista_id=np, sin_precio=True, clasificacion="interno")


def test_fuentes_por_lista(precios, np):
    iid = precios.get_candidatos("6140")[0].id
    precios.set_precio_por_id(iid, 4200.0, "ACTA NP", lista_id=np)
    assert precios.fuentes(lista_id=np) == ["ACTA NP"]
    assert "ACTA NP" not in precios.fuentes()
