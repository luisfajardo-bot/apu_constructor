"""
Lógica de servicio para AGREGAR a la base: insumos y APUs nuevos.

Altas de catálogo —individual o por Excel—, separadas de la edición de precios
(`insumos.py`) y de las corridas. Ve dinero (es catálogo del equipo), pero NUNCA
abre un camino hacia la IA (Invariante #1: la frontera de privacidad).

El import de APUs reutiliza el parser de la hoja `APUS` del seed, así que el
formato es idéntico al del histórico que el usuario ya maneja. No aplica las
correcciones de código del seed (esas son del histórico original).
"""
from __future__ import annotations

import csv
import io

import openpyxl

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.datos.seed import _read_apus
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo
from apu_tool.nucleo.texto import normalizar
from apu_tool.servicio.auditoria import nuevo_lote, registrar_auditoria
from apu_tool.servicio.insumos import _insumo_out, _norm_h, _to_float


# ----------------------------------------------------------------- individual
def crear_insumo(alm: Almacen, datos: dict, actor=None) -> dict:
    codigo = str(datos.get("codigo", "") or "").strip()
    nombre = str(datos.get("nombre", "") or "").strip()
    if not codigo or not nombre:
        raise ValueError("Código y nombre son obligatorios.")
    precio = _to_float(datos.get("precio"))
    if precio < 0:
        raise ValueError("El precio no puede ser negativo.")
    ins = Insumo(codigo=codigo, nombre=nombre,
                 unidad=str(datos.get("unidad", "") or ""),
                 grupo=str(datos.get("grupo", "") or ""),
                 precio=precio, fuente_precio=str(datos.get("fuente", "") or ""))
    with alm.transaccion("precios") as conn:
        iid = alm.precios.crear_insumo(ins, conn=conn,
                                       creado_por=(actor.user_id if actor else None))
        registrar_auditoria(
            alm, conn, actor, "insumo.crear", "insumo", iid, antes=None,
            despues={"codigo": ins.codigo, "nombre": ins.nombre, "unidad": ins.unidad,
                     "grupo": ins.grupo, "precio": ins.precio, "fuente": ins.fuente_precio},
            contexto={"origen": "individual"})
    return _insumo_out(alm.precios.get_insumo_por_id(iid))


def _componentes_de(alm: Almacen, comp_dicts: list[dict], shift: str) -> list[ApuComponent]:
    comps: list[ApuComponent] = []
    for c in comp_dicts:
        cod = str(c.get("insumo_codigo", "") or "").strip()
        rend = _to_float(c.get("rendimiento"))
        if not cod:
            raise ValueError("Cada componente necesita un código de insumo.")
        if rend <= 0:
            raise ValueError(f"El rendimiento del insumo {cod} debe ser mayor que 0.")
        # Resuelve nombre/unidad desde la base si el insumo existe (respaldo embebido);
        # si no existe, se guarda lo que venga (enlace blando -> cruce huérfano al costear).
        cands = alm.precios.get_candidatos(cod)
        if cands:
            nombre, unidad = cands[0].nombre, cands[0].unidad
        else:
            nombre = str(c.get("insumo_nombre", "") or "")
            unidad = str(c.get("unidad", "") or "")
        comps.append(ApuComponent(
            apu_codigo="", shift=shift, insumo_codigo=cod, insumo_nombre=nombre,
            unidad=unidad, rendimiento=rend, precio_unitario_hist=0.0))
    return comps


def crear_apu(alm: Almacen, datos: dict, actor=None) -> dict:
    codigo = str(datos.get("codigo", "") or "").strip()
    nombre = str(datos.get("nombre", "") or "").strip()
    turno = str(datos.get("turno", "") or "").strip().upper()
    if not codigo or not nombre:
        raise ValueError("Código y nombre son obligatorios.")
    if turno not in (config.SHIFT_DIURNO, config.SHIFT_NOCTURNO):
        raise ValueError("El turno debe ser DIURNO o NOCTURNO.")
    comps = _componentes_de(alm, datos.get("componentes", []) or [], turno)
    apu = Apu(codigo=codigo, nombre=nombre, unidad=str(datos.get("unidad", "") or ""),
              shift=turno, grupo=str(datos.get("grupo", "") or ""))
    with alm.transaccion("apus") as conn:
        alm.apus.crear_apu(apu, comps, conn=conn)
        registrar_auditoria(
            alm, conn, actor, "apu.crear", "apu", codigo, antes=None,
            despues={"codigo": codigo, "turno": turno, "nombre": nombre,
                     "unidad": apu.unidad, "grupo": apu.grupo, "n_componentes": len(comps)},
            contexto={"origen": "individual"})
    return {"codigo": codigo, "shift": turno, "nombre": nombre,
            "unidad": apu.unidad, "grupo": apu.grupo, "n_componentes": len(comps)}


# ------------------------------------------------------------- import insumos
def _existe_identidad(alm: Almacen, codigo: str, nombre: str) -> bool:
    nn = normalizar(nombre)
    return any(normalizar(c.nombre) == nn for c in alm.precios.get_candidatos(codigo))


def _filas_insumos(contenido: bytes, nombre_archivo: str) -> list[dict]:
    """Lee una tabla con columnas codigo, nombre, unidad, grupo, precio, fuente."""
    if nombre_archivo.lower().endswith((".xlsx", ".xlsm")):
        wb = openpyxl.load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
        rows = [list(r) for r in wb.active.iter_rows(values_only=True)]
        wb.close()
    else:
        text = contenido.decode("utf-8-sig", errors="replace")
        rows = [r for r in csv.reader(io.StringIO(text))]
    rows = [r for r in rows if any(c not in (None, "") for c in r)]
    if not rows:
        return []
    headers = [_norm_h(c) for c in rows[0]]

    def col(*keys):
        for i, h in enumerate(headers):
            if any(k == h or k in h for k in keys):
                return i
        return None

    ci = {"codigo": col("codigo", "cod", "code"),
          "nombre": col("nombre", "descripcion", "name"),
          "unidad": col("unidad", "und", "unit"),
          "grupo": col("grupo", "group"),
          "precio": col("precio", "valor", "price"),
          "fuente": col("fuente", "source")}
    if ci["codigo"] is None or ci["nombre"] is None:
        raise ValueError("El archivo debe tener al menos columnas de código y nombre.")

    def g(r, i):
        return r[i] if (i is not None and i < len(r)) else None

    out = []
    for r in rows[1:]:
        out.append({"codigo": str(g(r, ci["codigo"]) or "").strip(),
                    "nombre": str(g(r, ci["nombre"]) or "").strip(),
                    "unidad": str(g(r, ci["unidad"]) or "").strip(),
                    "grupo": str(g(r, ci["grupo"]) or "").strip(),
                    "precio": _to_float(g(r, ci["precio"])),
                    "fuente": str(g(r, ci["fuente"]) or "").strip()})
    return out


def preview_importar_insumos(alm: Almacen, contenido: bytes, nombre_archivo: str) -> dict:
    crear, ya_existe, invalida = [], [], []
    for f in _filas_insumos(contenido, nombre_archivo):
        if not f["codigo"] or not f["nombre"]:
            invalida.append(f)
        elif _existe_identidad(alm, f["codigo"], f["nombre"]):
            ya_existe.append(f)
        else:
            crear.append(f)
    return {"crear": crear, "ya_existe": ya_existe, "invalida": invalida}


def aplicar_importar_insumos(alm: Almacen, contenido: bytes, nombre_archivo: str,
                             actor=None) -> dict:
    creados, errores = 0, []
    lote = nuevo_lote()
    for f in _filas_insumos(contenido, nombre_archivo):
        if not f["codigo"] or not f["nombre"]:
            continue                                   # inválida: se omite
        if _existe_identidad(alm, f["codigo"], f["nombre"]):
            continue                                   # ya existe: no se pisa
        try:
            ins = Insumo(codigo=f["codigo"], nombre=f["nombre"], unidad=f["unidad"],
                         grupo=f["grupo"], precio=f["precio"], fuente_precio=f["fuente"])
            with alm.transaccion("precios") as conn:
                iid = alm.precios.crear_insumo(ins, conn=conn,
                                               creado_por=(actor.user_id if actor else None))
                registrar_auditoria(
                    alm, conn, actor, "insumo.crear", "insumo", iid, antes=None,
                    despues={"codigo": ins.codigo, "nombre": ins.nombre, "unidad": ins.unidad,
                             "grupo": ins.grupo, "precio": ins.precio, "fuente": ins.fuente_precio},
                    contexto={"origen": "import", "lote_id": lote, "archivo": nombre_archivo})
            creados += 1
        except ValueError as e:
            errores.append({"codigo": f["codigo"], "error": str(e)})
    return {"creados": creados, "errores": errores}


# ---------------------------------------------------------------- import APUs
def _parse_apus(contenido: bytes):
    """Parsea un Excel con hoja 'APUS' (formato del histórico) reusando el parser
    del seed. Devuelve (apus, comps_por_clave[(codigo, shift)])."""
    wb = openpyxl.load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
    try:
        if "APUS" not in wb.sheetnames:
            raise ValueError(
                "El Excel debe tener una hoja llamada 'APUS' con el formato del histórico.")
        apus, comps = _read_apus(wb)
    finally:
        wb.close()
    comps_por: dict[tuple[str, str], list[ApuComponent]] = {}
    for c in comps:
        comps_por.setdefault((c.apu_codigo, c.shift), []).append(c)
    return apus, comps_por


def preview_importar_apus(alm: Almacen, contenido: bytes) -> dict:
    apus, comps_por = _parse_apus(contenido)
    crear, ya_existe = [], []
    for a in apus:
        info = {"codigo": a.codigo, "turno": a.shift, "nombre": a.nombre,
                "unidad": a.unidad, "grupo": a.grupo,
                "n_componentes": len(comps_por.get((a.codigo, a.shift), []))}
        (ya_existe if alm.apus.get_apu(a.codigo, a.shift) else crear).append(info)
    return {"crear": crear, "ya_existe": ya_existe}


def aplicar_importar_apus(alm: Almacen, contenido: bytes, actor=None) -> dict:
    apus, comps_por = _parse_apus(contenido)
    creados, errores = 0, []
    lote = nuevo_lote()
    for a in apus:
        if alm.apus.get_apu(a.codigo, a.shift):
            continue                                   # ya existe: no se pisa
        try:
            comps = comps_por.get((a.codigo, a.shift), [])
            with alm.transaccion("apus") as conn:
                alm.apus.crear_apu(a, comps, conn=conn)
                registrar_auditoria(
                    alm, conn, actor, "apu.crear", "apu", a.codigo, antes=None,
                    despues={"codigo": a.codigo, "turno": a.shift, "nombre": a.nombre,
                             "unidad": a.unidad, "grupo": a.grupo, "n_componentes": len(comps)},
                    contexto={"origen": "import", "lote_id": lote})
            creados += 1
        except ValueError as e:
            errores.append({"codigo": a.codigo, "turno": a.shift, "error": str(e)})
    return {"creados": creados, "errores": errores}
