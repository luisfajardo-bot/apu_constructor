"""
Lógica de servicio para la edición de insumos (precio + fuente).

Edición de catálogo/precios pura: NO toca la IA. Ve dinero (es para el equipo),
pero no abre ningún camino hacia la IA. Edita por id (los códigos se repiten) y
cada cambio crea historial vía PreciosDB.set_precio_por_id.
"""
from __future__ import annotations

import csv
import io
import unicodedata
from typing import Optional

import openpyxl

from apu_tool import config
from apu_tool.datos.almacen import Almacen


def _insumo_out(ins) -> dict:
    return {"id": ins.id, "codigo": ins.codigo, "nombre": ins.nombre,
            "unidad": ins.unidad, "grupo": ins.grupo, "precio": ins.precio,
            "fuente": ins.fuente_precio,
            "clasificacion": config.classify_price_source(ins.fuente_precio)}


def listar(alm: Almacen, q: Optional[str] = None, grupo: Optional[str] = None,
           fuente: Optional[str] = None, clasificacion: Optional[str] = None,
           limit: int = 100, offset: int = 0) -> dict:
    items, total = alm.precios.list_insumos(q, grupo, fuente, clasificacion, limit, offset)
    return {"items": [_insumo_out(i) for i in items], "total": total,
            "limit": limit, "offset": offset}


def detalle(alm: Almacen, insumo_id: int) -> Optional[dict]:
    ins = alm.precios.get_insumo_por_id(insumo_id)
    if ins is None:
        return None
    return {"insumo": _insumo_out(ins),
            "historial": alm.precios.price_history(ins.codigo, nombre=ins.nombre)}


def aplicar_cambios(alm: Almacen, cambios: list[dict]) -> dict:
    aplicados, errores = 0, []
    for c in cambios:
        try:
            precio = float(c["precio"])
            if precio < 0:
                raise ValueError("El precio no puede ser negativo.")
            alm.precios.set_precio_por_id(int(c["insumo_id"]), precio,
                                          str(c.get("fuente", "") or ""))
            aplicados += 1
        except Exception as e:
            errores.append({"insumo_id": c.get("insumo_id"), "error": str(e)})
    return {"aplicados": aplicados, "errores": errores}


def _norm_h(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", str(s or ""))
                if unicodedata.category(c) != "Mn")
    return s.strip().lower()


def _to_float(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("$", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_tabla(contenido: bytes, nombre: str) -> list[dict]:
    if nombre.lower().endswith((".xlsx", ".xlsm")):
        wb = openpyxl.load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
        ws = wb.active
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
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
    c_cod = col("codigo", "cod", "code")
    c_pre = col("precio", "valor", "price")
    c_fue = col("fuente", "source")
    if c_cod is None or c_pre is None:
        raise ValueError("El archivo debe tener columnas de código y precio.")
    out = []
    for r in rows[1:]:
        def g(i):
            return r[i] if (i is not None and i < len(r)) else None
        cod = str(g(c_cod) or "").strip()
        if not cod:
            continue
        out.append({"codigo": cod, "precio": _to_float(g(c_pre)),
                    "fuente": str(g(c_fue) or "").strip()})
    return out


def _cambio(ins, precio_nuevo: float, fuente_nueva: str) -> dict:
    return {"insumo_id": ins.id, "codigo": ins.codigo, "nombre": ins.nombre,
            "precio_actual": ins.precio, "precio_nuevo": precio_nuevo,
            "fuente_actual": ins.fuente_precio, "fuente_nueva": fuente_nueva}


def preview_import(alm: Almacen, contenido: bytes, nombre: str) -> dict:
    filas = _parse_tabla(contenido, nombre)
    cambios, ambiguos, no_encontrados = [], [], []
    for f in filas:
        cands = alm.precios.get_candidatos(f["codigo"])
        if len(cands) == 1:
            ins = cands[0]
            cambios.append(_cambio(ins, f["precio"], f["fuente"] or ins.fuente_precio))
        elif len(cands) > 1:
            ambiguos.append({"codigo": f["codigo"], "precio": f["precio"],
                             "candidatos": [{"id": c.id, "nombre": c.nombre} for c in cands]})
        else:
            no_encontrados.append({"codigo": f["codigo"], "precio": f["precio"]})
    return {"cambios": cambios, "ambiguos": ambiguos, "no_encontrados": no_encontrados}


def preview_transformar(alm: Almacen, filtro: dict, operacion: dict) -> dict:
    items, _ = alm.precios.list_insumos(
        q=filtro.get("q"), grupo=filtro.get("grupo"), fuente=filtro.get("fuente"),
        limit=1_000_000, offset=0)
    tipo, valor = operacion.get("tipo"), operacion.get("valor")
    cambios = []
    for ins in items:
        nuevo_precio, nueva_fuente = ins.precio, ins.fuente_precio
        if tipo == "fuente":
            nueva_fuente = str(valor)
        elif tipo == "precio_factor":
            nuevo_precio = round(ins.precio * float(valor), 2)
        elif tipo == "precio_pct":
            nuevo_precio = round(ins.precio * (1 + float(valor) / 100), 2)
        elif tipo == "precio_set":
            nuevo_precio = float(valor)
        else:
            raise ValueError(f"Operación desconocida: {tipo}")
        cambios.append(_cambio(ins, nuevo_precio, nueva_fuente))
    return {"cambios": cambios, "afectados": len(cambios)}
