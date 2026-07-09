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


from apu_tool.nucleo.models import CorridaMeta


def _corrida_en(alm, carpeta_id):
    return alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-07-09", archivo="x.xlsx", turno_def="DIURNO",
        use_ai=False, estado="armando", carpeta_id=carpeta_id))


def test_renombrar_y_mover(tmp_path):
    alm = _alm(tmp_path)
    obra = svc.crear_carpeta(alm, "Obra", parent_id=None, actor=None)
    obra2 = svc.crear_carpeta(alm, "Obra 2", parent_id=None, actor=None)
    sub = svc.crear_carpeta(alm, "Sub", parent_id=obra["id"], actor=None)
    svc.renombrar_carpeta(alm, obra["id"], "Obra A", actor=None)
    assert alm.carpetas.get(obra["id"]).nombre == "Obra A"
    svc.mover_carpeta(alm, sub["id"], nuevo_parent_id=obra2["id"], actor=None)
    assert alm.carpetas.get(sub["id"]).parent_id == obra2["id"]


def test_mover_carpeta_con_hijas_no_puede_ser_nivel2(tmp_path):
    alm = _alm(tmp_path)
    obra = svc.crear_carpeta(alm, "Obra", parent_id=None, actor=None)
    otra = svc.crear_carpeta(alm, "Otra", parent_id=None, actor=None)
    svc.crear_carpeta(alm, "Hija", parent_id=obra["id"], actor=None)
    with pytest.raises(CarpetaInvalida):
        svc.mover_carpeta(alm, obra["id"], nuevo_parent_id=otra["id"], actor=None)


def test_eliminar_bloqueado_si_no_vacia(tmp_path):
    alm = _alm(tmp_path)
    obra = svc.crear_carpeta(alm, "Obra", parent_id=None, actor=None)
    sub = svc.crear_carpeta(alm, "Sub", parent_id=obra["id"], actor=None)
    with pytest.raises(CarpetaNoVacia):
        svc.eliminar_carpeta(alm, obra["id"], actor=None)      # tiene subcarpeta
    cid = _corrida_en(alm, sub["id"])
    with pytest.raises(CarpetaNoVacia):
        svc.eliminar_carpeta(alm, sub["id"], actor=None)       # tiene corrida
    # vaciamos de abajo hacia arriba: corrida -> sub -> obra
    alm.corridas.eliminar_corrida(cid)
    assert svc.eliminar_carpeta(alm, sub["id"], actor=None) is True    # sub ya vacía
    assert svc.eliminar_carpeta(alm, obra["id"], actor=None) is True   # obra ya vacía


def test_eliminar_carpeta_inexistente_devuelve_false(tmp_path):
    alm = _alm(tmp_path)
    assert svc.eliminar_carpeta(alm, 9999, actor=None) is False


def test_mover_corrida(tmp_path):
    alm = _alm(tmp_path)
    a = svc.crear_carpeta(alm, "A", parent_id=None, actor=None)
    b = svc.crear_carpeta(alm, "B", parent_id=None, actor=None)
    cid = _corrida_en(alm, a["id"])
    assert svc.mover_corrida(alm, cid, b["id"], actor=None) is True
    assert alm.corridas.get_corrida(cid).carpeta_id == b["id"]
    with pytest.raises(CarpetaInvalida):
        svc.mover_corrida(alm, cid, 9999, actor=None)          # carpeta destino inexistente
