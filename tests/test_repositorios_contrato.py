"""Contrato de almacenamiento: la MISMA batería corre contra ambos backends.

SQLite corre siempre (temp files). Postgres solo si hay TEST_DATABASE_URL.
Es el oráculo de no-regresión del port a Postgres (Enfoque A).
"""
import os
import pytest

from apu_tool.nucleo.models import Apu, ApuComponent, Insumo
from apu_tool.datos.repositorio import RepositorioPrecios, RepositorioApus


def _repos_sqlite(tmp_path):
    from apu_tool.datos.precios_db import PreciosDB
    from apu_tool.datos.apus_db import ApusDB
    p = PreciosDB(tmp_path / "precios.db")
    a = ApusDB(tmp_path / "apus.db")
    p.init_schema()
    a.init_schema()
    return p, a, None


def _repos_postgres(tmp_path):
    from apu_tool.datos.pg.conexion import Conexion
    from apu_tool.datos.pg.precios_pg import PreciosPg
    from apu_tool.datos.pg.apus_pg import ApusPg
    cx = Conexion(os.environ["TEST_DATABASE_URL"])
    p, a = PreciosPg(cx), ApusPg(cx)
    p.reset()  # esquema limpio
    a.reset()
    return p, a, cx


_BACKENDS = ["sqlite"]
if os.environ.get("TEST_DATABASE_URL"):
    _BACKENDS.append("postgres")


@pytest.fixture(params=_BACKENDS)
def repos(request, tmp_path):
    if request.param == "sqlite":
        p, a, cx = _repos_sqlite(tmp_path)
    else:
        p, a, cx = _repos_postgres(tmp_path)
    yield p, a
    if cx is not None:
        cx.cerrar()


def test_protocols_existen():
    assert hasattr(RepositorioPrecios, "get_candidatos")
    assert hasattr(RepositorioApus, "get_depriced_apu")


def test_insumo_insert_y_candidato_vigente(repos):
    precios, _ = repos
    assert precios.insert_insumos([
        Insumo("6140", "ACERO 60000 PSI", "KG", "MATERIAL", 3500.0, "PRECIO IDU")]) == 1
    cands = precios.get_candidatos("6140")
    assert len(cands) == 1 and cands[0].precio == 3500.0
    assert cands[0].fuente_precio == "PRECIO IDU"


def test_insumo_identidad_no_duplica(repos):
    precios, _ = repos
    ins = Insumo("6140", "ACERO 60000 PSI", "KG", "MATERIAL", 3500.0, "PRECIO IDU")
    precios.insert_insumos([ins])
    precios.insert_insumos([ins])  # misma identidad (codigo, nombre_norm)
    assert precios.counts()["insumos"] == 1


def test_crear_insumo_duplicado_lanza(repos):
    precios, _ = repos
    ins = Insumo("9", "CEMENTO GRIS", "KG", "MATERIAL", 900.0, "COSTO INTERNO")
    precios.crear_insumo(ins)
    with pytest.raises(ValueError):
        precios.crear_insumo(ins)


def test_set_precio_marca_vigente_y_guarda_historial(repos):
    precios, _ = repos
    iid = precios.crear_insumo(
        Insumo("9", "CEMENTO GRIS", "KG", "MATERIAL", 900.0, "COSTO INTERNO"))
    precios.set_precio_por_id(iid, 1000.0, "COMPRAS 2026")
    assert precios.get_insumo_por_id(iid).precio == 1000.0
    hist = precios.price_history("9")
    assert len(hist) == 2
    assert sum(1 for h in hist if h["vigente"]) == 1


def test_list_insumos_filtra_por_clasificacion(repos):
    precios, _ = repos
    precios.insert_insumos([
        Insumo("1", "ARENA", "M3", "MATERIAL", 10.0, "PRECIO IDU"),
        Insumo("2", "CUADRILLA", "HC", "MANO OBRA", 20.0, "COSTO INTERNO")])
    pub, npub = precios.list_insumos(clasificacion="publico", limit=50, offset=0)
    assert {i.codigo for i in pub} == {"1"}
    intr, _ = precios.list_insumos(clasificacion="interno", limit=50, offset=0)
    assert {i.codigo for i in intr} == {"2"}


def test_apu_crear_get_components_orden_y_depriced(repos):
    _, apus = repos
    comps = [
        ApuComponent("A1", "DIURNO", "1", "ARENA", "M3", 0.5, 10.0),
        ApuComponent("A1", "DIURNO", "2", "CUADRILLA", "HC", 1.2, 20.0)]
    apus.crear_apu(Apu("A1", "EXCAVACION", "M3", "DIURNO", "MOV TIERRAS"), comps)
    got = apus.get_components("A1", "DIURNO")
    assert [c.insumo_codigo for c in got] == ["1", "2"]
    dep = apus.get_depriced_apu("A1", "DIURNO")
    # invariante #1: la vista DePriced no expone dinero
    assert not hasattr(dep.componentes[0], "precio_unitario_hist")
    assert dep.componentes[0].rendimiento == 0.5


def test_apu_crear_duplicado_lanza(repos):
    _, apus = repos
    apus.crear_apu(Apu("A1", "EXCAVACION", "M3", "DIURNO"), [])
    with pytest.raises(ValueError):
        apus.crear_apu(Apu("A1", "OTRA", "M3", "DIURNO"), [])


def test_descripcion_no_vacia(repos):
    precios, apus = repos
    dp, da = precios.descripcion(), apus.descripcion()
    assert isinstance(dp, str) and dp.strip()
    assert isinstance(da, str) and da.strip()


def test_busqueda_insensible_a_acentos_y_caso(repos):
    precios, _ = repos
    precios.insert_insumos([Insumo("100", "HORMIGÓN 3000 PSI", "M3", "MAT", 1.0, "PRECIO IDU")])
    for termino in ("hormigon", "HORMIGÓN", "Hormigon"):
        items, n = precios.list_insumos(q=termino, limit=50, offset=0)
        assert n == 1 and items[0].codigo == "100", termino
    assert [i.codigo for i in precios.search_insumos("hormigon")] == ["100"]
    assert [i.codigo for i in precios.search_insumos_por_palabras(["hormigon"])] == ["100"]


def test_componentes_para_integridad(repos):
    _, apus = repos
    apus.crear_apu(Apu("A1", "EXCAVACION", "M3", "DIURNO", "MOV"), [
        ApuComponent("A1", "DIURNO", "6140", "ACERO", "KG", 0.5, 10.0),
        ApuComponent("A1", "DIURNO", "9", "CEMENTO", "KG", 1.2, 20.0)])
    comps = apus.componentes_para_integridad()
    assert ("6140", "ACERO") in comps and ("9", "CEMENTO") in comps
    assert all(isinstance(c, tuple) and len(c) == 2 for c in comps)


def test_apu_editar_reemplaza_cabecera_y_composicion(repos):
    _, apus = repos
    apus.crear_apu(Apu("A1", "MURO", "M2", "DIURNO", "ESTR"),
                   [ApuComponent("A1", "DIURNO", "1", "ARENA", "M3", 0.5, 10.0)])
    apus.editar_apu(
        Apu("A1", "MURO REFORZADO", "M2", "DIURNO", "ESTR"),
        [ApuComponent("A1", "DIURNO", "2", "CEMENTO", "KG", 3.0, 20.0),
         ApuComponent("A1", "DIURNO", "1", "ARENA", "M3", 0.8, 10.0)])
    apu = apus.get_apu("A1", "DIURNO")
    assert apu.nombre == "MURO REFORZADO"
    comps = apus.get_components("A1", "DIURNO")
    assert [c.insumo_codigo for c in comps] == ["2", "1"]   # reemplazada, seq 0..n
    assert comps[1].rendimiento == 0.8


def test_apu_editar_inexistente_lanza(repos):
    _, apus = repos
    with pytest.raises(ValueError):
        apus.editar_apu(Apu("NOPE", "X", "M2", "DIURNO"), [])


def test_apu_borrar_elimina_cabecera_y_componentes(repos):
    _, apus = repos
    apus.crear_apu(Apu("A1", "MURO", "M2", "DIURNO"),
                   [ApuComponent("A1", "DIURNO", "1", "ARENA", "M3", 0.5, 10.0)])
    assert apus.borrar_apu("A1", "DIURNO") is True
    assert apus.get_apu("A1", "DIURNO") is None
    assert apus.get_components("A1", "DIURNO") == []


def test_apu_borrar_inexistente_devuelve_false(repos):
    _, apus = repos
    assert apus.borrar_apu("NOPE", "DIURNO") is False


def test_precio_cero_genuino_no_es_sin_precio(repos):
    """Regla de negocio: nada puede costar $0; un $0 SIEMPRE es alerta (dura), nunca
    una ausencia de tarifa (alerta blanda). `sin_precio` debe derivarse de "no hay
    fila de precio vigente en la lista" (IS NULL por el LEFT JOIN), jamás de
    `precio == 0`: un insumo con una fila de precio de 0.0 genuina es un DATO."""
    precios, _ = repos
    lista_np = precios.crear_lista("NP Cero Genuino")
    iid_cero = precios.crear_insumo(
        Insumo("T1", "TRANSPORTE CERO", "VJ", "TRANSPORTE", 0.0, "ACTA NP"),
        lista_id=lista_np)
    iid_ausente = precios.crear_insumo(
        Insumo("T2", "TRANSPORTE AUSENTE", "VJ", "TRANSPORTE", 100.0, "PRECIO IDU"))

    # fila de precio 0.0 EN la lista: es un dato real, no una ausencia.
    con_cero = precios.get_insumo_por_id(iid_cero, lista_id=lista_np)
    assert con_cero.precio == 0.0
    assert con_cero.sin_precio is False

    # sin fila de precio en la lista: sí es ausencia.
    sin_fila = precios.get_insumo_por_id(iid_ausente, lista_id=lista_np)
    assert sin_fila.sin_precio is True

    # el filtro "sin precio en esta lista" no debe confundir un $0 con una ausencia.
    items, total = precios.list_insumos(lista_id=lista_np, sin_precio=True,
                                        limit=50, offset=0)
    codigos = {i.codigo for i in items}
    assert "T1" not in codigos    # el de $0 NO es "sin precio"
    assert "T2" in codigos
    assert total == 1


def test_interno_excluye_insumos_sin_tarifa_en_la_lista(repos):
    """En una lista no-Principal, `clasificacion="interno"` no debe devolver el
    catálogo completo: un insumo sin ninguna fila de precio en esa lista no es
    ni público ni interno, debe quedar fuera de ambas clasificaciones."""
    precios, _ = repos
    lista_np = precios.crear_lista("NP Clasificacion")
    precios.insert_insumos([
        Insumo("C1", "ARENA CLAS", "M3", "MATERIAL", 10.0, "PRECIO IDU"),
        Insumo("C2", "CEMENTO CLAS", "KG", "MATERIAL", 20.0, "COSTO INTERNO")])
    iid_c1 = precios.get_candidatos("C1")[0].id
    precios.set_precio_por_id(iid_c1, 15.0, "ACTA NP", lista_id=lista_np)
    # C2 NO tiene tarifa en lista_np.

    pub, _ = precios.list_insumos(lista_id=lista_np, clasificacion="publico",
                                  limit=50, offset=0)
    intr, _ = precios.list_insumos(lista_id=lista_np, clasificacion="interno",
                                   limit=50, offset=0)
    assert {i.codigo for i in pub} == set()
    assert {i.codigo for i in intr} == {"C1"}    # C2 no debe colar por no tener fila


def test_interno_publico_particionan_catalogo_en_principal(repos):
    """Invariante de no-regresión: en Principal, todo insumo tiene su fila de precio
    desde que se crea, así que la corrección del Hallazgo 2 (exigir fila de precio
    en la rama "interno") es inocua ahí: publico + interno siguen particionando el
    catálogo completo, igual que antes del cambio."""
    precios, _ = repos
    precios.insert_insumos([
        Insumo("P1", "ARENA PART", "M3", "MATERIAL", 10.0, "PRECIO IDU"),
        Insumo("P2", "CEMENTO PART", "KG", "MATERIAL", 20.0, "COSTO INTERNO"),
        Insumo("P3", "GRAVA PART", "M3", "MATERIAL", 15.0, "COMPRAS 2026")])
    pub, total_pub = precios.list_insumos(clasificacion="publico", limit=50, offset=0)
    intr, total_intr = precios.list_insumos(clasificacion="interno", limit=50, offset=0)
    _, total = precios.list_insumos(limit=50, offset=0)
    assert {i.codigo for i in pub} == {"P1"}
    assert {i.codigo for i in intr} == {"P2", "P3"}
    assert total_pub + total_intr == total == 3


def test_apu_componente_tipo_y_ref_shift_round_trip(repos):
    # FIX 4: paridad de contrato dual-backend para las marcas de sub-APU.
    _, apus = repos
    apus.crear_apu(Apu("B", "SUBAPU", "M3", "DIURNO"), [])
    apus.crear_apu(Apu("A1", "COMPUESTO", "M2", "DIURNO", "ESTR"), [
        ApuComponent("A1", "DIURNO", "1", "ARENA", "M3", 0.5, 10.0),
        ApuComponent("A1", "DIURNO", "B", "SUBAPU", "M3", 2.0, 0.0,
                     tipo="apu", ref_shift="DIURNO")])
    comps = apus.get_components("A1", "DIURNO")
    assert comps[0].tipo == "insumo" and comps[0].ref_shift == ""
    assert comps[1].tipo == "apu" and comps[1].ref_shift == "DIURNO"
