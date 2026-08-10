"""Alta sin duplicados: el código y el nombre no se repiten, salvo el par día/noche.

Spec: docs/superpowers/specs/2026-08-10-sin-duplicados-alta-design.md
"""
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, Insumo
from apu_tool.servicio import autoria


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo("4859", "BORDE CONTENEDOR DE RAICES A 70", "ML", "SARD", 90000, "PRECIO IDU"),
        Insumo("10014", "USO DEL PENETROMETRO DINAMICO DE CONO", "UN", "ENS", 5000, "PRECIO IDU")])
    return alm


def _nuevo(codigo, nombre):
    return {"codigo": codigo, "nombre": nombre, "unidad": "ML", "grupo": "SARD",
            "precio": 1000, "fuente": "PRECIO IDU"}


def test_codigo_tomado_rechaza_aunque_el_nombre_sea_otro(tmp_path):
    """El caso real: 10014 es a la vez el penetrómetro y la estabilización de subrasante.
    Hoy la identidad es (código, nombre), así que esto se creaba."""
    alm = _alm(tmp_path)
    with pytest.raises(ValueError, match="10014"):
        autoria.crear_insumo(alm, _nuevo("10014", "ESTABILIZACION DE SUBRASANTE CON RAJON"))


def test_codigo_tomado_por_un_insumo_oculto_tambien_rechaza(tmp_path):
    alm = _alm(tmp_path)
    iid = alm.precios.get_candidatos("10014")[0].id
    alm.precios.set_oculto(iid, True)
    with pytest.raises(ValueError, match="oculto"):
        autoria.crear_insumo(alm, _nuevo("10014", "OTRA COSA DISTINTA"))


def test_nombre_tomado_con_codigo_sin_relacion_rechaza(tmp_path):
    alm = _alm(tmp_path)
    with pytest.raises(ValueError, match="4859"):
        autoria.crear_insumo(alm, _nuevo("7777", "BORDE CONTENEDOR DE RAICES A 70"))


def test_nombre_tomado_ignora_tildes_y_caso(tmp_path):
    alm = _alm(tmp_path)
    with pytest.raises(ValueError):
        autoria.crear_insumo(alm, _nuevo("7777", "borde contenedor de raíces a 70"))


def test_gemelo_nocturno_puede_repetir_el_nombre(tmp_path):
    """4859 y 4859 N son el mismo trabajo de día y de noche: se llaman igual a propósito."""
    alm = _alm(tmp_path)
    out = autoria.crear_insumo(alm, _nuevo("4859 N", "BORDE CONTENEDOR DE RAICES A 70"))
    assert out["codigo"] == "4859 N"


def test_el_mensaje_del_nombre_sugiere_el_codigo_nocturno(tmp_path):
    alm = _alm(tmp_path)
    with pytest.raises(ValueError, match="7777 N"):
        autoria.crear_insumo(alm, _nuevo("7777", "BORDE CONTENEDOR DE RAICES A 70"))
