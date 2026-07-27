"""Listas de precios: tabla, semilla de Principal y CRUD."""
import pytest

from apu_tool import config
from apu_tool.datos.precios_db import PreciosDB


@pytest.fixture()
def precios(tmp_path):
    p = PreciosDB(tmp_path / "precios.db")
    p.init_schema()
    return p


def test_principal_existe_con_id_1(precios):
    listas = precios.listar_listas()
    assert [(l.id, l.nombre) for l in listas] == [(config.LISTA_PRINCIPAL_ID, "Principal")]


def test_init_schema_es_idempotente(precios):
    precios.init_schema()
    precios.init_schema()
    assert len(precios.listar_listas()) == 1


def test_crear_lista_devuelve_id_y_aparece_en_listar(precios):
    lid = precios.crear_lista("NP Calle 13", creado_por="u1")
    assert lid != config.LISTA_PRINCIPAL_ID
    lista = precios.get_lista(lid)
    assert lista.nombre == "NP Calle 13" and lista.creado_por == "u1"
    assert lista.creada_en                      # fecha ISO no vacía
    assert {l.nombre for l in precios.listar_listas()} == {"Principal", "NP Calle 13"}


def test_crear_lista_rechaza_nombre_vacio(precios):
    with pytest.raises(ValueError):
        precios.crear_lista("   ")


def test_crear_lista_rechaza_duplicado_sin_importar_mayusculas(precios):
    precios.crear_lista("NP Calle 13")
    with pytest.raises(ValueError):
        precios.crear_lista("np calle 13")


def test_renombrar_lista(precios):
    lid = precios.crear_lista("NP Calle 13")
    precios.renombrar_lista(lid, "NP Calle 13 - Acta 2")
    assert precios.get_lista(lid).nombre == "NP Calle 13 - Acta 2"


def test_renombrar_principal_esta_prohibido(precios):
    with pytest.raises(ValueError):
        precios.renombrar_lista(config.LISTA_PRINCIPAL_ID, "Otra cosa")


def test_renombrar_lista_inexistente_lanza(precios):
    with pytest.raises(ValueError):
        precios.renombrar_lista(999, "X")


def test_get_lista_inexistente_devuelve_none(precios):
    assert precios.get_lista(999) is None


def test_reset_deja_principal_de_nuevo(precios):
    precios.crear_lista("NP Calle 13")
    precios.reset()
    assert [l.nombre for l in precios.listar_listas()] == ["Principal"]
