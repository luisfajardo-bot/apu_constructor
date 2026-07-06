"""
Frontera de privacidad de precios.

Regla del negocio: la IA NUNCA debe ver valores monetarios (precios de insumos,
costos internos, totales). Solo puede ver actividades, insumos, unidades y
rendimientos para decidir la ESTRUCTURA de los APUs.

Este módulo construye los payloads que se envían a la IA y verifica, de forma
programática, que no contengan ningún número que pueda ser dinero. Si algo se
filtra, `assert_no_money` levanta una excepción: preferimos fallar a filtrar.
"""
from __future__ import annotations

import json
import re
from typing import Any

from apu_tool.nucleo.models import DePricedApu, DePricedComponent, LicitacionItem

# Nombres de campo que jamás deben aparecer en un payload destinado a la IA.
_FORBIDDEN_KEYS = {
    "precio", "precio_unitario", "precio_contractual", "precio_unitario_hist",
    "costo", "costo_unitario", "costo_total", "valor", "valor_unitario",
    "valor_total", "margen", "price", "cost", "amount", "total",
    "fuente_precio",
}

# Claves que SÍ son cantidades (no dinero) y por tanto se permiten.
_ALLOWED_NUMERIC_KEYS = {"rendimiento", "cantidad", "seq", "score", "confianza"}


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
    """Versión SIN dinero de un ítem de licitación (se omite precio_contractual)."""
    return {
        "item": item.item,
        "descripcion": item.descripcion,
        "unidad": item.unidad,
        "cantidad": round(item.cantidad, 6),
        "shift": item.shift,
    }


def assert_no_money(payload: Any) -> None:
    """Valida recursivamente que `payload` no contenga campos monetarios.

    Levanta PrivacyViolation si encuentra una clave prohibida con valor.
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


class PrivacyViolation(RuntimeError):
    """Se intentó enviar un valor monetario a la IA."""
