"""Pruebas del lector de presupuesto y del modelo extendido."""
from apu_tool.nucleo.models import LicitacionItem


def test_licitacion_item_campos_nuevos_opcionales():
    # El flujo plano construye sin los campos nuevos: deben quedar en "".
    plano = LicitacionItem(item="1", descripcion="X", unidad="M2",
                           cantidad=1.0, precio_contractual=100.0, shift="DIURNO")
    assert plano.categoria == ""
    assert plano.codigo_sugerido == ""
    # El flujo de presupuesto los puede pasar.
    ppto = LicitacionItem(item="7.101", descripcion="EXCAVACION", unidad="M3",
                          cantidad=10.0, precio_contractual=49473.0, shift="DIURNO",
                          categoria="7 · REDES ELÉCTRICAS EXTERNAS", codigo_sugerido="3009")
    assert ppto.categoria == "7 · REDES ELÉCTRICAS EXTERNAS"
    assert ppto.codigo_sugerido == "3009"


import openpyxl
from apu_tool.dominio.presupuesto import read_presupuesto


def _mini_ppto(path):
    """Crea un Excel mínimo con la estructura de FOR 1-PPTO OFICIAL.
    Columnas 0-idx relevantes: [2]=codigo, [3]=item de pago, [6]=desc/encabezado,
    [7]=und, [8]=cantidad, [9]=valor unit básico, [10]=valor+AIU."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "FOR 1-PPTO OFICIAL"

    # Python 3.14 requiere claves string en **kwargs; usamos dict posicional.
    def fila(cols=None):
        row = [None] * 12
        for idx, val in (cols or {}).items():
            row[idx] = val
        ws.append(row)

    fila()  # fila 1 vacía
    # Encabezado de tabla (fila de títulos): se ignora (no hay codigo+cantidad).
    fila({2: "N°", 3: "ITEM DE PAGO", 6: "DESCRIPCION", 7: "UND.", 8: "CANTIDAD",
          9: "VALOR UNITARIO BASICO", 10: "VALOR + AIU"})
    # Capítulo 7 (tiene número en [3]).
    fila({3: 7, 6: "REDES ELÉCTRICAS EXTERNAS"})
    fila({6: "TURNO DIURNO"})
    fila({6: "REDES ENERGÍA"})   # subgrupo (sin número)
    fila({2: 3009, 3: "7.101", 6: "EXCAVACION MANUAL PARA RED", 7: "M3",
          8: 6445, 9: 49473, 10: 67153})
    fila({2: 4489, 3: "7.104", 6: "SUBBASE GRANULAR CLASE B", 7: "M3",
          8: 2265, 9: 177852, 10: 241411})
    # Capítulo 9 + turno nocturno.
    fila({3: 9, 6: "OBRA CIVIL"})
    fila({6: "TURNO NOCTURNO"})
    fila({2: 3010, 3: "9.001", 6: "DEMOLICION PAVIMENTO", 7: "M3",
          8: 100, 9: 45548, 10: 61800})
    wb.save(path)


def test_read_presupuesto_items_y_herencia(tmp_path):
    p = tmp_path / "ppto.xlsx"
    _mini_ppto(p)
    items = read_presupuesto(p)

    assert len(items) == 3
    exc = items[0]
    assert exc.codigo_sugerido == "3009"
    assert exc.item == "7.101"
    assert exc.descripcion == "EXCAVACION MANUAL PARA RED"
    assert exc.unidad == "M3"
    assert exc.cantidad == 6445
    assert exc.precio_contractual == 49473      # columna [9], NO [10]
    assert exc.shift == "DIURNO"
    assert "REDES ELÉCTRICAS EXTERNAS" in exc.categoria

    # El tercer ítem hereda capítulo "OBRA CIVIL" y turno NOCTURNO.
    dem = items[2]
    assert dem.codigo_sugerido == "3010"
    assert "OBRA CIVIL" in dem.categoria
    assert dem.shift == "NOCTURNO"


def test_read_presupuesto_ignora_encabezados_y_vacias(tmp_path):
    p = tmp_path / "ppto.xlsx"
    _mini_ppto(p)
    items = read_presupuesto(p)
    # No deben colarse filas de encabezado/capítulo/turno como ítems.
    descripciones = [i.descripcion for i in items]
    assert "REDES ELÉCTRICAS EXTERNAS" not in descripciones
    assert "TURNO DIURNO" not in descripciones
    assert "REDES ENERGÍA" not in descripciones
