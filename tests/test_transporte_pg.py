"""Los dos backends son espejo 1:1 en los métodos nuevos de transporte.

Sin Postgres real se comparan firmas (guardia barato contra el drift). Con
TEST_DATABASE_URL corre además el contrato real.
"""
import inspect
import os

import pytest

from apu_tool.datos.apus_db import ApusDB
from apu_tool.datos.carpetas_db import CarpetasDB
from apu_tool.datos.pg.apus_pg import ApusPg
from apu_tool.datos.pg.carpetas_pg import CarpetasPg
from apu_tool.nucleo.models import AjusteProyecto, ClaseTransporte, ParametrosProyecto

_APUS = ["get_clasificacion_transporte", "set_clasificacion_transporte",
         "componentes_transporte_candidatos"]
_CARPETAS = ["get_parametros", "set_parametros", "listar_ajustes", "crear_ajuste",
             "borrar_ajuste"]


@pytest.mark.parametrize("nombre", _APUS)
def test_apus_mismo_metodo_en_ambos_backends(nombre):
    a, b = getattr(ApusDB, nombre), getattr(ApusPg, nombre)
    assert inspect.signature(a) == inspect.signature(b), nombre


@pytest.mark.parametrize("nombre", _CARPETAS)
def test_carpetas_mismo_metodo_en_ambos_backends(nombre):
    a, b = getattr(CarpetasDB, nombre), getattr(CarpetasPg, nombre)
    assert inspect.signature(a) == inspect.signature(b), nombre


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"),
                    reason="requiere TEST_DATABASE_URL (Postgres desechable)")
def test_contrato_real_postgres():
    from apu_tool.datos.pg.conexion import Conexion
    cx = Conexion(os.environ["TEST_DATABASE_URL"])
    apus, carpetas = ApusPg(cx), CarpetasPg(cx)
    apus.reset()
    from apu_tool.datos.pg.corridas_pg import CorridasPg
    CorridasPg(cx).reset()
    cid = carpetas.crear("Metro")
    assert carpetas.get_parametros(cid) is None
    carpetas.set_parametros(ParametrosProyecto(carpeta_id=cid, km_botadero=34,
                                              peaje_aplica=True, peaje_valor=12400))
    p = carpetas.get_parametros(cid)
    assert p.km_botadero == 34 and p.peaje_aplica is True
    aid = carpetas.crear_ajuste(AjusteProyecto(
        carpeta_id=cid, apu_codigo="4390", shift="DIURNO", accion="quitar",
        insumo_codigo="6722", insumo_nombre="SUBBASE GRANULAR B-400"))
    assert len(carpetas.listar_ajustes(cid)) == 1
    assert carpetas.borrar_ajuste(cid, aid) is True
    apus.set_clasificacion_transporte([ClaseTransporte(
        apu_codigo="4200", shift="DIURNO", insumo_codigo="6878",
        insumo_nombre="TRANSPORTE DE BASES ASFALTICAS", categoria="mezclas",
        volumen=1.05, km_base=25.0)])
    assert len(apus.get_clasificacion_transporte()) == 1
    cx.cerrar()
