"""Alta sin duplicados: el código y el nombre no se repiten, salvo el par día/noche.

Spec: docs/superpowers/specs/2026-08-10-sin-duplicados-alta-design.md
"""
import io

import openpyxl
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
    # La sugerencia tiene que ser la base del insumo EXISTENTE (4859), no la del que
    # se intenta crear (7777): es el código que la excepción del gemelo sí acepta.
    with pytest.raises(ValueError, match="4859 N"):
        autoria.crear_insumo(alm, _nuevo("7777", "BORDE CONTENEDOR DE RAICES A 70"))


def test_el_mensaje_del_nombre_no_sugiere_el_codigo_nocturno_si_ya_esta_tomado(tmp_path):
    """Si "4859 N" ya existe, sugerirlo como salida mandaría al usuario a un segundo error."""
    alm = _alm(tmp_path)
    alm.precios.insert_insumos([
        Insumo("4859 N", "BORDE CONTENEDOR DE RAICES A 70", "ML", "SARD", 95000, "PRECIO IDU")])
    with pytest.raises(ValueError) as exc:
        autoria.crear_insumo(alm, _nuevo("7777", "BORDE CONTENEDOR DE RAICES A 70"))
    assert "4859 N" not in str(exc.value)


# ------------------------------------------------------------------------- APUs
def _alm_apus(tmp_path):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("3010", "EXCAVACION MANUAL EN MATERIAL COMUN", "M3",
                              "DIURNO", "EXCAVACIONES Y RELLENOS")])
    return alm


def _apu_nuevo(codigo, turno, nombre):
    return {"codigo": codigo, "turno": turno, "nombre": nombre, "unidad": "M3",
            "grupo": "EXCAVACIONES Y RELLENOS", "componentes": []}


def test_apu_codigo_repetido_en_el_otro_turno_rechaza(tmp_path):
    """Hoy la identidad es (código, turno), así que 3010 NOCTURNO se creaba al lado del
    DIURNO con el código pelado — el mismo bug que ya se arregló en el importador."""
    alm = _alm_apus(tmp_path)
    with pytest.raises(ValueError, match="3010 N"):
        autoria.crear_apu(alm, _apu_nuevo("3010", "NOCTURNO", "OTRO NOMBRE CUALQUIERA"))


def test_apu_no_sugiere_el_codigo_nocturno_si_ya_esta_tomado(tmp_path):
    """Si "3010 N" ya existe, sugerirlo como salida mandaría al usuario a un segundo error."""
    alm = _alm_apus(tmp_path)
    alm.apus.insert_apus([Apu("3010 N", "OTRO APU DE NOCHE", "M3",
                              "NOCTURNO", "EXCAVACIONES Y RELLENOS")])
    with pytest.raises(ValueError) as exc:
        autoria.crear_apu(alm, _apu_nuevo("3010", "NOCTURNO", "OTRO NOMBRE CUALQUIERA"))
    assert "3010 N" not in str(exc.value)


def test_apu_gemelo_nocturno_puede_repetir_el_nombre(tmp_path):
    alm = _alm_apus(tmp_path)
    out = autoria.crear_apu(alm, _apu_nuevo("3010 N", "NOCTURNO",
                                            "EXCAVACION MANUAL EN MATERIAL COMUN"))
    assert out["codigo"] == "3010 N" and out["turno"] == "NOCTURNO"


def test_apu_nombre_repetido_con_codigo_sin_relacion_rechaza(tmp_path):
    alm = _alm_apus(tmp_path)
    with pytest.raises(ValueError, match="3010"):
        autoria.crear_apu(alm, _apu_nuevo("9999", "NOCTURNO",
                                          "EXCAVACION MANUAL EN MATERIAL COMUN"))


def test_apu_nombre_repetido_en_el_mismo_turno_rechaza(tmp_path):
    """El gemelo es del OTRO turno. Mismo nombre, mismo turno, sigue siendo duplicado."""
    alm = _alm_apus(tmp_path)
    with pytest.raises(ValueError):
        autoria.crear_apu(alm, _apu_nuevo("3010 N", "DIURNO",
                                          "EXCAVACION MANUAL EN MATERIAL COMUN"))


# --------------------------------------------------------------- import insumos
def _excel_insumos(filas):
    """Excel con las columnas que lee `_filas_insumos`."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["codigo", "nombre", "unidad", "grupo", "precio", "fuente"])
    for f in filas:
        ws.append(f)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_import_insumos_codigo_tomado_va_a_conflicto(tmp_path):
    alm = _alm(tmp_path)
    contenido = _excel_insumos([["10014", "ESTABILIZACION CON RAJON", "M3", "SUB", 7000, "PRECIO IDU"]])
    prev = autoria.preview_importar_insumos(alm, contenido, "x.xlsx")
    assert prev["crear"] == []
    assert len(prev["conflicto"]) == 1
    assert "10014" in prev["conflicto"][0]["motivo"]
    res = autoria.aplicar_importar_insumos(alm, contenido, "x.xlsx")
    assert res["creados"] == 0 and res["errores"] == []


def test_import_insumos_dos_filas_del_mismo_codigo_la_segunda_es_conflicto(tmp_path):
    """Sin el chequeo contra el propio archivo, el preview diría "crear 2" y el aplicar
    crearía 1 con un error: el preview mentiría."""
    alm = _alm(tmp_path)
    contenido = _excel_insumos([
        ["7777", "GRAVA COMUN", "M3", "MAT", 8000, "PRECIO IDU"],
        ["7777", "OTRA COSA DISTINTA", "M3", "MAT", 9000, "PRECIO IDU"]])
    prev = autoria.preview_importar_insumos(alm, contenido, "x.xlsx")
    assert len(prev["crear"]) == 1 and len(prev["conflicto"]) == 1
    res = autoria.aplicar_importar_insumos(alm, contenido, "x.xlsx")
    assert res["creados"] == 1 and res["errores"] == []


def test_import_insumos_el_gemelo_nocturno_del_archivo_si_se_crea(tmp_path):
    alm = _alm(tmp_path)
    contenido = _excel_insumos([
        ["8888", "GRAVA COMUN", "M3", "MAT", 8000, "PRECIO IDU"],
        ["8888 N", "GRAVA COMUN", "M3", "MAT", 9000, "PRECIO IDU"]])
    prev = autoria.preview_importar_insumos(alm, contenido, "x.xlsx")
    assert len(prev["crear"]) == 2 and prev["conflicto"] == []


# ------------------------------------------------------------------ import APUs
def _excel_apus(cabeceras):
    """Hoja 'APUS' del formato del histórico. `cabeceras` son (codigo, turno, nombre, unidad).

    Columnas: actividad(0) cod_idu(1) unidad(2) insumo(3) cod(4) und(5)
              rendimiento(6) inv(7) precio(8) costo(9) turno(10)   — ver seed.APUS_COLS.
    Cada APU lleva un componente para que no quede vacío."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "APUS"
    ws.append(["ACTIVIDAD", "COD IDU", "UN", "INSUMO", "COD", "UND", "RENDIMIENTO",
               "INV", "PRECIO", "COSTO", "TURNO"])
    for codigo, turno, nombre, unidad in cabeceras:
        ws.append([nombre, codigo, unidad, "", "", "", "", "", "", "", turno])
        ws.append(["", "", "", "CEMENTO", "100", "KG", 1.0, "", 900, "", ""])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()



def test_import_apus_el_par_diurno_nocturno_del_historico_sigue_entrando(tmp_path):
    """LA no-regresión: el importador convierte el nocturno en "3010 N" antes de
    cualquier chequeo (no choca por código) y el nombre repetido cae en la excepción
    del gemelo. Los 499 pares del histórico tienen que seguir importándose."""
    alm = _alm(tmp_path)                     # biblioteca de APUs vacía
    contenido = _excel_apus([
        ("3010", "DIURNO", "EXCAVACION MANUAL", "M3"),
        ("3010", "NOCTURNO", "EXCAVACION MANUAL", "M3")])
    prev = autoria.preview_importar_apus(alm, contenido)
    assert len(prev["crear"]) == 2 and prev["conflicto"] == []
    res = autoria.aplicar_importar_apus(alm, contenido)
    assert res["creados"] == 2 and res["errores"] == []
    assert alm.apus.get_apu("3010", "DIURNO") is not None
    assert alm.apus.get_apu("3010 N", "NOCTURNO") is not None


def test_import_apus_nombre_de_otro_apu_va_a_conflicto(tmp_path):
    alm = _alm_apus(tmp_path)                # ya tiene 3010 DIURNO "EXCAVACION MANUAL EN MATERIAL COMUN"
    contenido = _excel_apus([
        ("9999", "DIURNO", "EXCAVACION MANUAL EN MATERIAL COMUN", "M3")])
    prev = autoria.preview_importar_apus(alm, contenido)
    assert prev["crear"] == [] and len(prev["conflicto"]) == 1
    res = autoria.aplicar_importar_apus(alm, contenido)
    assert res["creados"] == 0 and len(res["errores"]) == 1
