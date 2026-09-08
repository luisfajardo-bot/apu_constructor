import openpyxl
from apu_tool.dominio.report_categorizado import write_report_categorizado
from apu_tool.nucleo.models import AssembledApu, CostedComponent, LicitacionItem, MatchStatus


def _apu():
    item = LicitacionItem(item="1", descripcion="Losa", unidad="m3", cantidad=1.0,
                          precio_contractual=100.0, shift="DIURNO", categoria="CAP-1")
    comp = CostedComponent(insumo_codigo="7", insumo_nombre="Cemento", unidad="kg",
                           rendimiento=1.0, precio_unitario=0.0, fuente_precio="X",
                           costo=0.0, calidad_cruce="exacto")
    return AssembledApu(item=item, apu_codigo="A", apu_nombre="Losa", unidad="m3",
                        shift="DIURNO", componentes=[comp], costo_unitario=0.0,
                        status=MatchStatus.AUTO, confianza=1.0)


def _apu_sin_componentes(costo):
    item = LicitacionItem(item="1", descripcion="Losa", unidad="m3", cantidad=1.0,
                          precio_contractual=100.0, shift="DIURNO", categoria="CAP-1")
    return AssembledApu(item=item, apu_codigo="A", apu_nombre="Losa", unidad="m3",
                        shift="DIURNO", componentes=[], costo_unitario=costo,
                        status=MatchStatus.AUTO, confianza=1.0)


def test_apus_costo_a_mano_muestra_nota_correcta(tmp_path):
    """Sin componentes: costo positivo -> '(costo puesto a mano)'; costo 0 ->
    '(sin composición — armar manual)'. Cada bloque de APU ocupa 5 filas (título,
    encabezado, la fila con la nota, costo unitario, línea en blanco), así que el
    primer bloque queda en la fila 3 y el segundo en la 8."""
    a_mano = _apu_sin_componentes(1500.0)
    sin_composicion = _apu_sin_componentes(0.0)
    out = write_report_categorizado([a_mano, sin_composicion], tmp_path / "c.xlsx")
    ws = openpyxl.load_workbook(out)["APUS"]
    assert ws.cell(row=3, column=2).value == "(costo puesto a mano)"
    assert ws.cell(row=8, column=2).value == "(sin composición — armar manual)"


def test_detalle_resalta_costeo_cero(tmp_path):
    out = write_report_categorizado([_apu()], tmp_path / "c.xlsx")
    ws = openpyxl.load_workbook(out)["DETALLE"]
    tiene_alerta = any(ws.cell(row=r, column=1).fill.fgColor.rgb.endswith("F8CBAD")
                       for r in range(1, ws.max_row + 1))
    assert tiene_alerta


def test_alertas_incluye_costeo(tmp_path):
    out = write_report_categorizado([_apu()], tmp_path / "c.xlsx")
    ws = openpyxl.load_workbook(out)["ALERTAS"]
    textos = [ws.cell(row=r, column=7).value for r in range(2, ws.max_row + 1)]
    assert any(t and "en $0" in t for t in textos)
