"""Regresión de la revisión sobre commit e84c0e1 (Task 9: listas de precios NP),
Hallazgos 2, 3 y 4.

Todos giran sobre el mismo hecho: `Insumo.precio` viene de un LEFT JOIN contra la
lista consultada; cuando no hay tarifa ahí, `precio` es 0.0 y `sin_precio` es True.
Ese 0.0 es un ARTEFACTO de la ausencia, nunca un precio real (ver el docstring de
`Insumo.sin_precio` en `apu_tool/nucleo/models.py`). El camino de importación tenía
varios puntos que no distinguían "no hay tarifa" de "el precio es 0", todos
exclusivos del camino NP (Principal siempre tiene tarifa para lo que ya existe).
"""
import io

import openpyxl

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Insumo
from apu_tool.servicio import autoria
from apu_tool.servicio import insumos as insumos_svc
from apu_tool.servicio.insumos import MSG_PRECIO_POSITIVO


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo("6140", "ACERO 60000 PSI", "KG", "MATERIAL", 3500.0, "PRECIO IDU"),
        Insumo("100", "CEMENTO GRIS", "KG", "MAT", 1000.0, "PRECIO IDU")])
    return alm


def _alm_np(tmp_path):
    alm = _alm(tmp_path)
    lid = alm.precios.crear_lista("NP Calle 13")
    return alm, lid


def _xlsx(filas: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    for f in filas:
        wb.active.append(f)
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


# --------------------------------------------------------------------- Hallazgo 2
def test_import_valor_igual_a_principal_se_escribe_en_np(tmp_path):
    """Si `aplicar_importar_insumos` perdiera el `lista_id` al calcular el preview
    (autoria.py:262), el preview se calcularía contra Principal: un archivo que fija
    6140 -> 3500 en la lista NP, con 3500 siendo TAMBIÉN el precio de Principal,
    caería en el guard de no-op (precio_nuevo == precio_actual) y la tarifa NP nunca
    se escribiría, reportando éxito vacío."""
    alm, lid = _alm_np(tmp_path)
    contenido = _xlsx([["codigo", "nombre", "precio"],
                       ["6140", "ACERO 60000 PSI", 3500.0]])   # mismo precio que Principal
    res = autoria.aplicar_importar_insumos(alm, contenido, "f.xlsx", lista_id=lid)
    assert res == {"creados": 0, "actualizados": 1, "errores": []}
    ins_np = alm.precios.get_candidatos("6140", lista_id=lid)[0]
    assert ins_np.precio == 3500.0 and ins_np.sin_precio is False
    assert alm.precios.get_candidatos("6140")[0].precio == 3500.0   # Principal, sin tocar


# --------------------------------------------------------------------- Hallazgo 3
def test_import_sin_precio_y_sin_tarifa_en_lista_se_reporta_invalida(tmp_path):
    """Escenario 1: archivo con columna `fuente` y SIN columna de precio (modo
    soportado, pinneado para Principal en test_servicio_autoria.py:124-131), contra
    una lista NP sin tarifa para ese insumo. No debe colarse en 'actualizar' con un
    precio_nuevo=0.0 fantasma (que luego fallaría con MSG_PRECIO_POSITIVO al
    aplicar) -> debe reportarse en 'invalida'."""
    alm, lid = _alm_np(tmp_path)
    contenido = _xlsx([["codigo", "fuente"], ["6140", "NUEVA FUENTE"]])
    prev = autoria.preview_importar_insumos(alm, contenido, "f.xlsx", lista_id=lid)
    assert prev["actualizar"] == []
    assert len(prev["invalida"]) == 1 and prev["invalida"][0]["codigo"] == "6140"

    res = autoria.aplicar_importar_insumos(alm, contenido, "f.xlsx", lista_id=lid)
    assert res == {"creados": 0, "actualizados": 0, "errores": []}


def test_import_precio_cero_sin_tarifa_en_lista_falla_no_se_traga(tmp_path):
    """Escenario 2: archivo con precio=0 explícito y SIN columna `fuente`, contra una
    lista NP sin tarifa. precio_actual==precio_nuevo==0 y fuente_actual==fuente_nueva=="",
    pero NO es un no-op (no había tarifa que "no cambiara"): debe fallar con
    MSG_PRECIO_POSITIVO, igual que el mismo archivo contra Principal."""
    alm, lid = _alm_np(tmp_path)
    contenido = _xlsx([["codigo", "precio"], ["6140", 0]])
    res = autoria.aplicar_importar_insumos(alm, contenido, "f.xlsx", lista_id=lid)
    assert res["creados"] == 0 and res["actualizados"] == 0
    assert len(res["errores"]) == 1
    assert MSG_PRECIO_POSITIVO in res["errores"][0]["error"]


# --------------------------------------------------------------------- Hallazgo 4
def test_import_preview_solo_codigo_lee_precio_actual_de_la_lista(tmp_path):
    """autoria.py:248 (rama 'solo código', archivo sin columna de nombre): el
    precio_actual que el usuario aprueba debe venir de la lista destino, no de
    Principal."""
    alm, lid = _alm_np(tmp_path)
    iid = alm.precios.get_candidatos("6140")[0].id
    alm.precios.set_precio_por_id(iid, 4200.0, "ACTA NP", lista_id=lid)   # tarifa propia en NP
    contenido = _xlsx([["codigo", "precio"], ["6140", 5000.0]])           # sin columna nombre
    prev = autoria.preview_importar_insumos(alm, contenido, "f.xlsx", lista_id=lid)
    assert len(prev["actualizar"]) == 1
    assert prev["actualizar"][0]["precio_actual"] == 4200.0   # de NP, no 3500.0 (Principal)


def test_aplicar_cambios_auditoria_antes_lee_de_la_lista(tmp_path):
    """insumos.py:61: el 'antes' del evento de auditoría debe leerse de la lista
    destino, no de Principal. Si se leyera de Principal, el log diría
    'antes: 3500.0 (PRECIO IDU)' cuando en la lista NP no había tarifa -> degrada la
    trazabilidad que el lista_id en `contexto` vino a dar."""
    alm, lid = _alm_np(tmp_path)
    iid = alm.precios.get_candidatos("6140")[0].id
    insumos_svc.aplicar_cambios(
        alm, [{"insumo_id": iid, "precio": 4200.0, "fuente": "ACTA NP"}], lista_id=lid)
    items, _total = alm.auditoria.listar(accion="precio.editar")
    assert items[0]["antes"] == {"precio": 0.0, "fuente": ""}   # sin tarifa aún en NP


def test_import_actualizar_precio_cero_sobre_tarifa_real_falla(tmp_path):
    """autoria.py:288-289: el guard del $0 en la rama de actualización del import no
    tenía test. Pisar con 0 una tarifa REAL (no es un no-op: el precio cambia) debe
    fallar con MSG_PRECIO_POSITIVO y no escribirse."""
    alm = _alm(tmp_path)
    contenido = _xlsx([["codigo", "precio"], ["100", 0]])   # 100 tiene tarifa real: 1000.0
    res = autoria.aplicar_importar_insumos(alm, contenido, "f.xlsx")
    assert res["creados"] == 0 and res["actualizados"] == 0
    assert len(res["errores"]) == 1
    assert MSG_PRECIO_POSITIVO in res["errores"][0]["error"]
    assert alm.precios.get_candidatos("100")[0].precio == 1000.0   # no se pisó
