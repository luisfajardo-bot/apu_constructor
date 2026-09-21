"""
Cuadro resumen agrupado por capítulos del presupuesto.

Hojas:
  - RESUMEN POR CAPÍTULO : un renglón por capítulo (contractual vs costo, margen) + gran total.
  - DETALLE              : ítems agrupados bajo cada capítulo, con subtotal por capítulo.
  - APUS                 : cada APU como bloque apilado (estilo de la pestaña APUS original).
  - ALERTAS              : ítems que requieren revisión o armado manual.
  - INFO                 : metadatos + nota de privacidad (la IA no vio dinero).

Reúsa los estilos de report.py para no duplicar formato.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import openpyxl
from openpyxl.styles import Font

from apu_tool.nucleo.models import AssembledApu, MatchStatus
from apu_tool.dominio.report import (_MONEY, _PCT, _REND, _STATUS_LABEL, _TOTAL_FILL,
                                     _WARN_FILL, _ALERT_FILL, _autosize, _style_header,
                                     _build_desviaciones)
from apu_tool.dominio.alertas import alertas_costeo, filas_alertadas, motivo_alerta


def agrupar_por_capitulo(apus: list[AssembledApu]) -> dict[str, list[AssembledApu]]:
    """Agrupa por capítulo preservando el orden de aparición."""
    grupos: dict[str, list[AssembledApu]] = {}
    for a in apus:
        cap = a.item.categoria or "(sin capítulo)"
        grupos.setdefault(cap, []).append(a)
    return grupos


SIN_CAPITULO = "(sin capítulo)"


def _costeada(a: AssembledApu) -> bool:
    """La actividad tiene costo válido.

    MISMA regla que `servicio/corridas.seqs_sin_apu`: con APU, o con un costo declarado
    a mano POSITIVO. Si las dos divergen, el resumen diría que un capítulo está completo
    mientras el candado del cuadro lo frena por esa misma fila.
    """
    return bool(a.apu_codigo) or a.costo_unitario > 0


def resumen_por_capitulo(apus: list[AssembledApu]) -> list[dict]:
    """Contractual, costo y cobertura por capítulo. LA fuente única de este cálculo.

    La consumen la API (`vista_corrida["capitulos"]`), la web (que solo pinta) y las dos
    hojas de Excel. Es deliberado: tener la misma suma en tres lados es cómo se llega a
    tres números distintos para la misma corrida en la misma pantalla.

    Redondeo: suma `contractual_total` y `costo_total`, que YA pasaron por
    `mul_redondeado`. No redondea dos veces ni vuelve a multiplicar.

    Las actividades sin APU no se esconden: cuentan en `sin_apu`, bajan la cobertura y
    dejan el capítulo en `completo: false`, que es lo que la web usa para mostrar el
    margen como parcial en vez de como cifra definitiva.
    """
    grupos: dict[str, list[AssembledApu]] = {}
    nombres: dict[str, str] = {}
    for a in apus:
        cod = a.item.capitulo_codigo
        nombres.setdefault(cod, (a.item.capitulo_nombre or SIN_CAPITULO) if cod
                           else SIN_CAPITULO)
        grupos.setdefault(cod, []).append(a)

    salida: list[dict] = []
    for orden, (cod, filas) in enumerate(grupos.items(), start=1):
        contractual = sum(a.contractual_total for a in filas)
        costo = sum(a.costo_total for a in filas)
        costeadas = [a for a in filas if _costeada(a)]
        salida.append({
            "codigo": cod,
            "nombre": nombres[cod],
            "orden": orden,
            "actividades": len(filas),
            "con_apu": len(costeadas),
            "sin_apu": len(filas) - len(costeadas),
            "contractual": contractual,
            "contractual_sin_aiu": sum(a.contractual_total_sin_aiu for a in filas),
            "costo": costo,
            "diferencia": contractual - costo,
            "margen_pct": ((contractual - costo) / contractual) if contractual else 0.0,
            "cobertura": (len(costeadas) / len(filas)) if filas else 0.0,
            # Ponderada por valor: un capítulo puede estar casi entero por conteo y a
            # media máquina por plata, si lo que falta son las actividades caras.
            # Medido en el archivo real: en PAVIMENTOS, 2 de 42 actividades son el 32 %
            # del capítulo; en RED DE GAS, 2 de 8 son el 57 %. Sin esta métrica, "95 %
            # costeado" puede significar que falta la mitad del dinero.
            "cobertura_valor": (sum(a.contractual_total for a in costeadas) / contractual
                                if contractual else 0.0),
            "completo": (len(costeadas) == len(filas)
                         and not any(alertas_costeo(a) for a in filas)),
        })
    return salida


HOJA_CAPITULOS = "RESUMEN POR CAPÍTULO"

_COLUMNAS_CAPITULO = ["Capítulo", "Nombre", "Actividades", "Con APU", "Sin APU",
                      "Contractual", "Contractual sin AIU", "Costo interno",
                      "Diferencia", "Margen %", "Cobertura", "Cobertura $", "Estado"]


def hay_capitulos(apus: list[AssembledApu]) -> bool:
    """Al menos una actividad trae capítulo. Es la condición para escribir la hoja."""
    return any(a.item.capitulo_codigo for a in apus)


def escribir_hoja_capitulos(ws, apus: list[AssembledApu]) -> None:
    """La hoja RESUMEN POR CAPÍTULO. La escriben los DOS cuadros (report.py y este).

    NO calcula: consume `resumen_por_capitulo`, la única función que suma por capítulo.
    Antes esta hoja tenía su propia suma; tenerla acá y en la API era el camino directo
    a dos números distintos para la misma corrida.
    """
    ws.append(_COLUMNAS_CAPITULO)
    _style_header(ws, 1, len(_COLUMNAS_CAPITULO))
    ws.freeze_panes = "A2"

    filas = resumen_por_capitulo(apus)
    for c in filas:
        ws.append([c["codigo"], c["nombre"], c["actividades"], c["con_apu"],
                   c["sin_apu"], c["contractual"], c["contractual_sin_aiu"],
                   c["costo"], c["diferencia"], c["margen_pct"], c["cobertura"],
                   c["cobertura_valor"],
                   "Completo" if c["completo"] else "Incompleto"])
        r = ws.max_row
        for col in (6, 7, 8, 9):
            ws.cell(row=r, column=col).number_format = _MONEY
        for col in (10, 11, 12):
            ws.cell(row=r, column=col).number_format = _PCT
        if not c["completo"]:
            # El capítulo tiene actividades sin costear: el margen NO es definitivo y la
            # fila se pinta para que no se lea como si lo fuera.
            for col in range(1, len(_COLUMNAS_CAPITULO) + 1):
                ws.cell(row=r, column=col).fill = _WARN_FILL

    contractual = sum(c["contractual"] for c in filas)
    costo = sum(c["costo"] for c in filas)
    ws.append(["", "GRAN TOTAL", sum(c["actividades"] for c in filas),
               sum(c["con_apu"] for c in filas), sum(c["sin_apu"] for c in filas),
               contractual, sum(c["contractual_sin_aiu"] for c in filas), costo,
               contractual - costo,
               ((contractual - costo) / contractual) if contractual else 0.0,
               None, None,
               "Completo" if all(c["completo"] for c in filas) else "Incompleto"])
    r = ws.max_row
    for col in (6, 7, 8, 9):
        celda = ws.cell(row=r, column=col)
        celda.number_format = _MONEY
        celda.font = Font(bold=True)
    ws.cell(row=r, column=10).number_format = _PCT
    for col in range(1, len(_COLUMNAS_CAPITULO) + 1):
        ws.cell(row=r, column=col).fill = _TOTAL_FILL
    ws.cell(row=r, column=2).font = Font(bold=True)
    _autosize(ws, {1: 10, 2: 42, 3: 12, 4: 10, 5: 10, 6: 18, 7: 20, 8: 16,
                   9: 16, 10: 10, 11: 11, 12: 12, 13: 12})


def _build_detalle(ws, grupos: dict[str, list[AssembledApu]]) -> None:
    headers = ["Ítem", "Descripción", "Und", "Cantidad",
               "P. Contractual", "P. Contractual sin AIU",
               "Costo Unit.", "Margen Unit.", "Margen %",
               "Total Contractual", "Total Contractual sin AIU",
               "Total Costo", "Margen Total", "Estado"]
    ws.append(headers)
    _style_header(ws, 1, len(headers))
    ws.freeze_panes = "A2"

    for cap, apus in grupos.items():
        ws.append([cap])
        cr = ws.max_row
        ws.cell(row=cr, column=1).font = Font(bold=True)
        for col in range(1, len(headers) + 1):
            ws.cell(row=cr, column=col).fill = _TOTAL_FILL

        for a in apus:
            ws.append([
                a.item.item, a.item.descripcion, a.unidad, a.item.cantidad,
                a.item.precio_contractual, a.item.precio_contractual_sin_aiu,
                a.costo_unitario, a.margen_unitario, a.margen_pct,
                a.contractual_total, a.contractual_total_sin_aiu,
                a.costo_total, a.margen_total,
                _STATUS_LABEL.get(a.status, a.status),
            ])
            r = ws.max_row
            ws.cell(row=r, column=4).number_format = _REND
            for col in (5, 6, 7, 8, 10, 11, 12, 13):
                ws.cell(row=r, column=col).number_format = _MONEY
            ws.cell(row=r, column=9).number_format = _PCT
            if alertas_costeo(a):
                for col in range(1, len(headers) + 1):
                    ws.cell(row=r, column=col).fill = _ALERT_FILL
            elif a.status in (MatchStatus.REVIEW, MatchStatus.NEW):
                for col in range(1, len(headers) + 1):
                    ws.cell(row=r, column=col).fill = _WARN_FILL

        sc = sum(a.contractual_total for a in apus)
        sc_sin = sum(a.contractual_total_sin_aiu for a in apus)
        sk = sum(a.costo_total for a in apus)
        ws.append(["", f"Subtotal {cap}", "", "", "", "", "", "", "",
                   sc, sc_sin, sk, sc - sk, ""])
        r = ws.max_row
        for col in (10, 11, 12, 13):
            cell = ws.cell(row=r, column=col)
            cell.number_format = _MONEY
            cell.font = Font(bold=True)
        ws.cell(row=r, column=2).font = Font(bold=True)
    _autosize(ws, {1: 9, 2: 46, 3: 6, 4: 12, 5: 16, 6: 20, 7: 14, 8: 14, 9: 10,
                   10: 18, 11: 20, 12: 16, 13: 16, 14: 12})


def _build_apus(ws, apus: list[AssembledApu]) -> None:
    """Cada APU como bloque apilado: título + insumos + costo unitario."""
    from openpyxl.styles import PatternFill
    sub = ["Insumo Cód", "Insumo", "Und", "Rendimiento", "Precio Unit.",
           "Fuente precio", "Costo", "Cruce"]
    for a in apus:
        titulo = f"{a.item.item}   {a.apu_nombre}   ({a.unidad})"
        ws.append([titulo])
        tr = ws.max_row
        ws.cell(row=tr, column=1).font = Font(bold=True, color="FFFFFF")
        for col in range(1, len(sub) + 1):
            ws.cell(row=tr, column=col).fill = PatternFill("solid", fgColor="1F4E78")

        ws.append(sub)
        _style_header(ws, ws.max_row, len(sub))

        if not a.componentes:
            nota = ("(costo puesto a mano)" if a.costo_a_mano
                    else "(sin composición — armar manual)")
            ws.append(["", nota, "", "", "", "", "", ""])
        for c in a.componentes:
            ws.append([c.insumo_codigo, c.insumo_nombre, c.unidad, c.rendimiento,
                       c.precio_unitario, c.fuente_precio, c.costo, c.calidad_cruce])
            r = ws.max_row
            ws.cell(row=r, column=4).number_format = _REND
            ws.cell(row=r, column=5).number_format = _MONEY
            ws.cell(row=r, column=7).number_format = _MONEY

        ws.append(["", "COSTO UNITARIO APU", "", "", "", "", a.costo_unitario, ""])
        r = ws.max_row
        ws.cell(row=r, column=2).font = Font(bold=True)
        ws.cell(row=r, column=7).number_format = _MONEY
        ws.cell(row=r, column=7).font = Font(bold=True)
        ws.append([])  # línea en blanco entre APUs
    _autosize(ws, {1: 12, 2: 46, 3: 8, 4: 14, 5: 14, 6: 18, 7: 14, 8: 12})


def _build_alertas(ws, apus: list[AssembledApu]) -> None:
    headers = ["Ítem", "Descripción", "Capítulo", "Estado", "Confianza",
               "APU propuesto", "Justificación / motivo"]
    ws.append(headers)
    _style_header(ws, 1, len(headers))
    ws.freeze_panes = "A2"
    flagged = filas_alertadas(apus)
    for a, ac in flagged:
        motivo = motivo_alerta(a, ac)
        ws.append([a.item.item, a.item.descripcion, a.item.categoria,
                   _STATUS_LABEL.get(a.status, a.status), round(a.confianza, 2),
                   a.apu_codigo or "", motivo])
        ws.cell(row=ws.max_row, column=5).number_format = '0.00'
    if not flagged:
        ws.append(["", "Sin alertas: todos los ítems se armaron con coincidencia clara."])
    _autosize(ws, {1: 9, 2: 45, 3: 30, 4: 12, 5: 10, 6: 14, 7: 50})


def write_report_categorizado(apus: list[AssembledApu], path: Path | str,
                              lista_nombre: str = "Principal",
                              parametros=None, ajustes=()) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    grupos = agrupar_por_capitulo(apus)

    wb = openpyxl.Workbook()
    escribir_hoja_capitulos(wb.active, apus)
    wb.active.title = HOJA_CAPITULOS
    _build_detalle(wb.create_sheet("DETALLE"), grupos)
    _build_apus(wb.create_sheet("APUS"), apus)
    _build_alertas(wb.create_sheet("ALERTAS"), apus)
    # Solo si el proyecto realmente se desvía de la biblioteca (ver report.py).
    if (parametros is not None and not parametros.vacio) or ajustes:
        _build_desviaciones(wb.create_sheet("DESVIACIONES DEL PROYECTO"),
                            parametros, list(ajustes))

    info = wb.create_sheet("INFO")
    info.append(["Generado", date.today().isoformat()])
    info.append(["Ítems", len(apus)])
    info.append(["Capítulos", len(grupos)])
    # Qué tarifa costeó este cuadro (ver write_report: misma razón).
    info.append(["Lista de precios", lista_nombre])
    info.append(["Precio contractual", "Valor unitario BÁSICO (sin AIU)"])
    info.append(["Nota", "Los precios de costo NO fueron vistos por la IA. "
                         "La IA solo decidió la estructura de los APUs."])
    wb.save(path)
    return path
