"""
Lectura de la biblioteca de APUs (para la página de APUs).

Ve dinero (costea la composición con el precio vigente, como el cuadro), pero NUNCA
abre un camino hacia la IA (Invariante #1). Las escrituras (crear/importar) viven en
`autoria.py`; aquí solo se lista y se muestra el detalle costeado.
"""
from __future__ import annotations

from typing import Optional

from apu_tool.datos.almacen import Almacen
from apu_tool.dominio.pricing import PricingEngine


def listar(alm: Almacen, q: Optional[str] = None, grupo: Optional[str] = None,
           turno: Optional[str] = None, limit: int = 100, offset: int = 0) -> dict:
    items, total = alm.apus.list_apus(q, grupo, turno, limit, offset)
    counts = alm.apus.component_counts()
    # Costo unitario por APU de la página (para verlo sin desplegar). Un solo
    # PricingEngine reutiliza el caché de candidatos entre APUs. Ve dinero como el
    # cuadro, pero NUNCA lo pasa a la IA (Invariante #1).
    eng = PricingEngine(alm)
    out = []
    for a in items:
        _comp, costo = eng.cost_apu(a.codigo, a.shift)
        out.append({"codigo": a.codigo, "turno": a.shift, "nombre": a.nombre,
                    "unidad": a.unidad, "grupo": a.grupo,
                    "n_componentes": counts.get((a.codigo, a.shift), 0),
                    "costo_unitario": costo})
    return {"items": out, "total": total, "limit": limit, "offset": offset}


def detalle(alm: Almacen, codigo: str, turno: str) -> Optional[dict]:
    apu = alm.apus.get_apu(codigo, turno)
    if apu is None:
        return None
    costed, total = PricingEngine(alm).cost_apu(codigo, turno)
    return {
        "codigo": apu.codigo, "turno": apu.shift, "nombre": apu.nombre,
        "unidad": apu.unidad, "grupo": apu.grupo, "costo_unitario": total,
        "n_corridas": alm.corridas.contar_items_por_apu(codigo),
        "composicion": [{
            "insumo_codigo": c.insumo_codigo, "insumo_nombre": c.insumo_nombre,
            "unidad": c.unidad, "rendimiento": c.rendimiento,
            "precio_unitario": c.precio_unitario, "fuente_precio": c.fuente_precio,
            "costo": c.costo, "calidad_cruce": c.calidad_cruce,
            "tipo": c.tipo, "ref_shift": c.ref_shift} for c in costed],
    }
