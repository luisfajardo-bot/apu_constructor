"""El cuadro dice con qué tarifa se emitió: sin eso, un cuadro NP y uno contractual
son indistinguibles en el archivo."""
import openpyxl
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.dominio.report import write_report
from apu_tool.nucleo.models import (
    Apu, ApuComponent, AssembledApu, CostedComponent, Insumo, LicitacionItem, MatchStatus,
)
from apu_tool.servicio import corridas as svc


def _assembled() -> AssembledApu:
    item = LicitacionItem("1", "DEMOLICION", "M3", 1.0, 20000.0, "DIURNO")
    comp = CostedComponent("6140", "ACERO", "KG", 2.0, 4200.0, "ACTA NP", 8400)
    return AssembledApu(item=item, apu_codigo="NP-3002", apu_nombre="DEMOLICION",
                        unidad="M3", shift="DIURNO", componentes=[comp],
                        costo_unitario=8400, status=MatchStatus.AUTO, confianza=1.0)


def _info(path) -> dict:
    wb = openpyxl.load_workbook(path)
    filas = {r[0]: r[1] for r in wb["INFO"].iter_rows(values_only=True) if r and r[0]}
    wb.close()
    return filas


def test_info_dice_principal_por_defecto(tmp_path):
    out = write_report([_assembled()], tmp_path / "cuadro.xlsx")
    assert _info(out)["Lista de precios"] == "Principal"


def test_info_dice_la_lista_pasada(tmp_path):
    out = write_report([_assembled()], tmp_path / "cuadro.xlsx",
                       lista_nombre="NP Calle 13")
    assert _info(out)["Lista de precios"] == "NP Calle 13"


def test_categorizado_tambien_declara_la_lista(tmp_path):
    from apu_tool.dominio.report_categorizado import write_report_categorizado
    out = write_report_categorizado([_assembled()], tmp_path / "cat.xlsx",
                                    lista_nombre="NP Calle 13")
    assert _info(out)["Lista de precios"] == "NP Calle 13"


def test_generar_cuadro_estampa_la_lista_de_la_corrida(tmp_path, monkeypatch):
    from apu_tool import config
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "salidas")
    alm = Almacen(tmp_path / "p.db", tmp_path / "a.db", tmp_path / "c.db")
    alm.reset()
    alm.corridas.init_schema()
    alm.precios.insert_insumos([
        Insumo("6140", "ACERO 60000 PSI", "KG", "MATERIAL", 3500.0, "PRECIO IDU")])
    alm.apus.insert_apus([Apu("NP-3002", "DEMOLICION", "M3", "DIURNO")])
    alm.apus.insert_components([
        ApuComponent("NP-3002", "DIURNO", "6140", "ACERO 60000 PSI", "KG", 2.0, 3000.0)])
    np = alm.precios.crear_lista("NP Calle 13")
    iid = alm.precios.get_candidatos("6140")[0].id
    alm.precios.set_precio_por_id(iid, 4200.0, "ACTA NP", lista_id=np)
    items = [LicitacionItem("1", "DEMOLICION", "M3", 1.0, 20000.0, "DIURNO")]
    cid = svc.construir_corrida(alm, "acta.xlsx", items, "DIURNO", False,
                                carpeta_id=None, lista_precios_id=np)
    out = svc.generar_cuadro(alm, cid)
    assert _info(out)["Lista de precios"] == "NP Calle 13"
