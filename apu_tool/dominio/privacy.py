"""
Frontera de privacidad de precios.

Regla del negocio: la IA NUNCA debe ver valores monetarios (precios de insumos,
costos internos, totales). Solo puede ver actividades, insumos, unidades y
rendimientos para decidir la ESTRUCTURA de los APUs.

Este módulo construye los payloads que se envían a la IA y verifica, de forma
programática, que no traigan ninguna clave monetaria. Si algo se filtra,
`assert_no_money` levanta una excepción: preferimos fallar a filtrar. El chequeo
es por nombre de clave, NO por valor — ver la limitación en su docstring.
"""
from __future__ import annotations

import json
from typing import Any

from apu_tool.nucleo.models import DePricedApu, DePricedComponent, LicitacionItem

# Nombres de campo que jamás deben aparecer en un payload destinado a la IA.
_FORBIDDEN_KEYS = {
    "precio", "precio_unitario", "precio_contractual", "precio_unitario_hist",
    "costo", "costo_unitario", "costo_total", "valor", "valor_unitario",
    "valor_total", "margen", "price", "cost", "amount", "total",
    "fuente_precio", "costo_manual", "plan_json",
    # El valor del peaje de un proyecto es dinero. `valor` ya está en la lista,
    # pero el chequeo es por nombre EXACTO de clave.
    "peaje_valor",
    # --- ruta IDU (Formulario 1) ------------------------------------------------
    # Las dos bases del contractual y sus multiplicaciones.
    "precio_contractual_sin_aiu", "contractual_total_sin_aiu",
    "contractual_con_aiu", "contractual_sin_aiu",
    "unitario_sin_aiu", "unitario_con_aiu",
    # Lo que el Excel del IDU trae y el parser concilia.
    "total_excel", "subtotales_excel", "conciliacion",
    # Las claves del dict de `report_categorizado.resumen_por_capitulo`. Hoy NINGÚN
    # camino las lleva hacia la IA (sus tres consumidores son la API HTTP y las dos
    # hojas de Excel), pero son dinero con nombre genérico: el día que alguien quiera
    # darle a la IA "contexto del capítulo" pasando ese dict, se filtrarían en silencio.
    # El resto de sus claves ya estaba cubierto por `costo`, `margen` y las de arriba.
    "contractual", "diferencia", "margen_pct", "cobertura_valor",
    # `origen_json` va por la MISMA razón que `plan_json`: lleva la conciliación
    # —o sea dinero— adentro, así que el objeto entero no puede cruzar la frontera.
    "origen_json",
}


def depriced_component_to_dict(c: DePricedComponent) -> dict[str, Any]:
    return {
        "insumo_codigo": c.insumo_codigo,
        "insumo_nombre": c.insumo_nombre,
        "unidad": c.unidad,
        "rendimiento": round(c.rendimiento, 6),
        "tipo": c.tipo,
    }


def depriced_apu_to_dict(apu: DePricedApu) -> dict[str, Any]:
    return {
        "codigo": apu.codigo,
        "nombre": apu.nombre,
        "unidad": apu.unidad,
        "shift": apu.shift,
        "grupo": apu.grupo,
        "componentes": [depriced_component_to_dict(c) for c in apu.componentes],
    }


def licitacion_item_to_dict(item: LicitacionItem) -> dict[str, Any]:
    """Versión SIN dinero de un ítem de licitación.

    Se arma clave por clave a propósito: un campo nuevo del dataclass NO se cuela solo
    por existir. Por eso no están `precio_contractual` ni `precio_contractual_sin_aiu`.

    El capítulo sí viaja: es texto y es estructura — saber que una actividad pertenece a
    RED DE ACUEDUCTO ayuda a componerla, y no dice nada de lo que cuesta.
    """
    return {
        "item": item.item,
        "descripcion": item.descripcion,
        "unidad": item.unidad,
        "cantidad": round(item.cantidad, 6),
        "shift": item.shift,
        "capitulo_codigo": item.capitulo_codigo,
        "capitulo_nombre": item.capitulo_nombre,
    }


def assert_no_money(payload: Any) -> None:
    """Valida recursivamente que `payload` no contenga campos monetarios.

    Levanta PrivacyViolation si encuentra una clave de `_FORBIDDEN_KEYS`.

    LIMITACIÓN REAL, léela antes de agregar un payload nuevo: el chequeo es por
    **nombre de clave**, no por valor. Un monto embebido en un string de texto
    libre — `{"nota": "el m3 sale a $180.000"}` — pasa el guardián sin que salte
    nada, porque `nota` no está en la denylist y nadie mira el contenido.

    De ahí la regla operativa: **nunca metas en un payload hacia la IA texto
    generado por el motor de costos** (mensajes de `alertas.py`, explicaciones de
    `pricing.py`, cualquier cadena armada donde se ve dinero). Manda campos
    estructurados con nombre propio, que sí son los que este chequeo cubre.
    """
    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                key = str(k).strip().lower()
                if key in _FORBIDDEN_KEYS:
                    raise PrivacyViolation(
                        f"Campo monetario '{path}.{k}' destinado a la IA. "
                        f"La IA no puede ver precios."
                    )
                walk(v, f"{path}.{k}")
        elif isinstance(node, (list, tuple)):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(payload, "payload")


def safe_json(payload: Any) -> str:
    """Serializa a JSON tras verificar que no hay dinero. Úsalo para todo lo que
    salga hacia la IA."""
    assert_no_money(payload)
    return json.dumps(payload, ensure_ascii=False, indent=2)


def rendimiento_observado_to_dict(o) -> dict[str, Any]:
    """Estadística de uso de un insumo en la biblioteca. Cantidades físicas, no dinero.

    Se copia clave por clave y no se delega en `o.to_dict()`: este es el borde hacia
    la IA, y un campo agregado al tipo del dominio no debe viajar solo por existir.
    """
    return {"insumo_codigo": o.insumo_codigo, "unidad": o.unidad, "n": o.n,
            "minimo": round(o.minimo, 6), "mediana": round(o.mediana, 6),
            "maximo": round(o.maximo, 6),
            # El modelo tiene que saber que el rango dejó filas afuera: si no, un
            # "n=35" sobre un insumo que también se usa en otra unidad le parece
            # evidencia más firme de la que es.
            "descartados_otra_unidad": o.descartados_otra_unidad}


def payload_composicion(item, insumos, ejemplos, observados) -> dict[str, Any]:
    """El payload de la composición asistida (dominio/composicion_agente.py).

    Se arma clave por clave a propósito, nunca volcando objetos en bloque: es lo que
    hace que el test de FORMA sirva de algo. Los APUs de referencia entran como
    `DePricedApu`, un tipo que estructuralmente no puede llevar dinero — la frontera
    está en el tipo, no en acordarse de filtrar campos.

    `observados` es un dict {codigo: RendimientoObservado}; se ordena por código para
    que dos llamadas con los mismos datos produzcan el mismo texto (el prompt es
    cacheable y los tests, comparables).
    """
    from apu_tool.dominio.compose import candidate_insumo_to_dict
    return {
        "actividad": licitacion_item_to_dict(item),
        "insumos_disponibles": [candidate_insumo_to_dict(i) for i in insumos],
        "apus_referencia": [depriced_apu_to_dict(a) for a in ejemplos],
        "rendimientos_observados": [rendimiento_observado_to_dict(observados[k])
                                    for k in sorted(observados)],
    }


class PrivacyViolation(RuntimeError):
    """Se intentó enviar un valor monetario a la IA."""
