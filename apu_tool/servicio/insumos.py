"""
Lógica de servicio para la edición de insumos (precio + fuente).

Edición de catálogo/precios pura: NO toca la IA. Ve dinero (es para el equipo),
pero no abre ningún camino hacia la IA. Edita por id (los códigos se repiten) y
cada cambio crea historial vía PreciosDB.set_precio_por_id.
"""
from __future__ import annotations

from typing import Optional

from apu_tool import config
from apu_tool.datos.almacen import Almacen


def _insumo_out(ins) -> dict:
    return {"id": ins.id, "codigo": ins.codigo, "nombre": ins.nombre,
            "unidad": ins.unidad, "grupo": ins.grupo, "precio": ins.precio,
            "fuente": ins.fuente_precio,
            "clasificacion": config.classify_price_source(ins.fuente_precio)}


def listar(alm: Almacen, q: Optional[str] = None, grupo: Optional[str] = None,
           fuente: Optional[str] = None, limit: int = 100, offset: int = 0) -> dict:
    items, total = alm.precios.list_insumos(q, grupo, fuente, limit, offset)
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
        except (ValueError, KeyError, TypeError) as e:
            errores.append({"insumo_id": c.get("insumo_id"), "error": str(e)})
    return {"aplicados": aplicados, "errores": errores}
