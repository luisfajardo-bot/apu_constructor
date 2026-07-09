import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.servicio import carpetas as svc
from apu_tool.servicio.carpetas import CarpetaInvalida, CarpetaNoVacia


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def test_crear_y_arbol(tmp_path):
    alm = _alm(tmp_path)
    obra = svc.crear_carpeta(alm, "Calle 13", parent_id=None, actor=None)
    svc.crear_carpeta(alm, "Lote 3", parent_id=obra["id"], actor=None)
    arbol = svc.listar_arbol(alm)
    # "Sin clasificar" + "Calle 13" en la raíz
    nombres_raiz = {n["nombre"] for n in arbol}
    assert {"Sin clasificar", "Calle 13"} <= nombres_raiz
    calle = next(n for n in arbol if n["nombre"] == "Calle 13")
    assert [h["nombre"] for h in calle["hijas"]] == ["Lote 3"]


def test_no_permite_tercer_nivel(tmp_path):
    alm = _alm(tmp_path)
    obra = svc.crear_carpeta(alm, "Obra", parent_id=None, actor=None)
    lote = svc.crear_carpeta(alm, "Lote", parent_id=obra["id"], actor=None)
    with pytest.raises(CarpetaInvalida):
        svc.crear_carpeta(alm, "Sub", parent_id=lote["id"], actor=None)


def test_nombre_duplicado_hermanas(tmp_path):
    alm = _alm(tmp_path)
    svc.crear_carpeta(alm, "Obra", parent_id=None, actor=None)
    with pytest.raises(CarpetaInvalida):
        svc.crear_carpeta(alm, "Obra", parent_id=None, actor=None)


def test_nombre_vacio(tmp_path):
    alm = _alm(tmp_path)
    with pytest.raises(CarpetaInvalida):
        svc.crear_carpeta(alm, "   ", parent_id=None, actor=None)
