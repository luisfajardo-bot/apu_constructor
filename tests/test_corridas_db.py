from apu_tool.nucleo.models import CorridaItemRow, CorridaMeta, LicitacionItem


def test_corrida_meta_y_item_row_se_construyen():
    meta = CorridaMeta(id=None, creada_en="2026-06-24T10:00:00", archivo="lic.xlsx",
                       turno_def="DIURNO", use_ai=False, estado="en_revision")
    assert meta.cuadro_path is None
    item = LicitacionItem(item="1", descripcion="Concreto", unidad="M3",
                          cantidad=10.0, precio_contractual=400000.0, shift="DIURNO")
    row = CorridaItemRow(seq=0, item=item, status="auto", apu_codigo="A1",
                         apu_nombre="Concreto clase D", unidad="M3", shift="DIURNO",
                         origen="historico", confianza=1.0, explicacion="",
                         componentes=[], candidatos=[])
    assert row.seq == 0 and row.item.precio_contractual == 400000.0
