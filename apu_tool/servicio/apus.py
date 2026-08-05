"""
Lectura de la biblioteca de APUs (para la página de APUs).

Ve dinero (costea la composición con el precio vigente, como el cuadro), pero NUNCA
abre un camino hacia la IA (Invariante #1). Las escrituras (crear/importar) viven en
`autoria.py`; aquí solo se lista y se muestra el detalle costeado.
"""
from __future__ import annotations

from typing import Optional

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.dominio.pricing import PricingEngine
from apu_tool.nucleo.texto import normalizar


def listar(alm: Almacen, q: Optional[str] = None, grupo: Optional[str] = None,
           turno: Optional[str] = None, limit: int = 100, offset: int = 0,
           lista_id: Optional[int] = None) -> dict:
    items, total = alm.apus.list_apus(q, grupo, turno, limit, offset)
    counts = alm.apus.component_counts()
    # Costo unitario por APU de la página (para verlo sin desplegar). Un solo
    # PricingEngine reutiliza el caché de candidatos entre APUs, y queda atado a
    # `lista_id` (None = Principal). Ve dinero como el cuadro, pero NUNCA lo pasa
    # a la IA (Invariante #1).
    eng = PricingEngine(alm, lista_id=lista_id)
    out = []
    for a in items:
        _comp, costo = eng.cost_apu(a.codigo, a.shift)
        out.append({"codigo": a.codigo, "turno": a.shift, "nombre": a.nombre,
                    "unidad": a.unidad, "grupo": a.grupo,
                    "n_componentes": counts.get((a.codigo, a.shift), 0),
                    "costo_unitario": costo})
    return {"items": out, "total": total, "limit": limit, "offset": offset}


def detalle(alm: Almacen, codigo: str, turno: str,
            lista_id: Optional[int] = None) -> Optional[dict]:
    apu = alm.apus.get_apu(codigo, turno)
    if apu is None:
        return None
    costed, total = PricingEngine(alm, lista_id=lista_id).cost_apu(codigo, turno)
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


def grupos(alm: Almacen) -> list[str]:
    """Vocabulario de grupos de APU: la lista base de config ∪ los grupos en uso.

    No hay tabla de grupos a propósito (ver el spec): así no hace falta migrar nada en
    Supabase, un Admin crea un grupo usándolo, y uno mal escrito se autolimpia cuando
    ningún APU lo usa. Dedup insensible a tildes/mayúsculas con `normalizar` (mismo
    criterio que servicio/listas.py); gana la ortografía de config.

    ponytail: el vocabulario se cierra en la pantalla, no acá — `crear_apu`/`editar_apu`
    siguen aceptando cualquier texto. Si algún día hay un segundo cliente de la API, el
    upgrade es exigir en esas dos escrituras que el grupo esté en este vocabulario salvo
    para rol == "admin".
    """
    vistos = {normalizar(g): g for g in alm.apus.grupos()}
    vistos.update({normalizar(g): g for g in config.GRUPOS_APU_BASE})
    return sorted(vistos.values())
