"""
Lógica de servicio para la edición de insumos (precio + fuente).

Edición de catálogo/precios pura: NO toca la IA. Ve dinero (es para el equipo),
pero no abre ningún camino hacia la IA. Edita por id (los códigos se repiten) y
cada cambio crea historial vía PreciosDB.set_precio_por_id.
"""
from __future__ import annotations

import unicodedata
from typing import Optional

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.servicio.auditoria import nuevo_lote, registrar_auditoria

MSG_PRECIO_POSITIVO = ("El precio debe ser mayor que 0. Usa 1 si el ítem no tiene "
                       "costo (p. ej. material del cliente).")


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


def aplicar_cambios(alm: Almacen, cambios: list[dict], actor=None) -> dict:
    aplicados, errores = 0, []
    lote = nuevo_lote()
    for c in cambios:
        try:
            precio = float(c["precio"])
            if precio <= 0:
                raise ValueError(MSG_PRECIO_POSITIVO)
            iid = int(c["insumo_id"])
            fuente = str(c.get("fuente", "") or "")
            antes_ins = alm.precios.get_insumo_por_id(iid)   # estado previo (lectura)
            with alm.transaccion("precios") as conn:
                alm.precios.set_precio_por_id(iid, precio, fuente, conn=conn,
                                              creado_por=(actor.user_id if actor else None))
                registrar_auditoria(
                    alm, conn, actor, "precio.editar", "insumo", iid,
                    antes=({"precio": antes_ins.precio, "fuente": antes_ins.fuente_precio}
                           if antes_ins else None),
                    despues={"precio": precio, "fuente": fuente},
                    contexto={"origen": "edicion", "lote_id": lote})
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
