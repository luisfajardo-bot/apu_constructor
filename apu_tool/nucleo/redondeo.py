"""Redondeo a la unidad (peso) en multiplicaciones monetarias.

Regla del negocio: no se trabaja con decimales en dinero. El resultado de CADA
multiplicación monetaria se redondea a la unidad más cercana (medio hacia arriba).
Si el producto es positivo pero redondearía a 0, se fija en 1 (invariante "nada en
$0": el redondeo nunca hace desaparecer un costo real). Un 0 genuino queda en 0.

Módulo puro (solo stdlib). No toca dinero hacia la IA (invariante #1 no aplica aquí).
"""
from __future__ import annotations

import math


def mul_redondeado(a: float, b: float) -> int:
    """Multiplica y redondea a la unidad más cercana, medio hacia arriba.

    - ``a * b <= 0``  -> 0 (0 genuino; lo marca la alerta de costeo).
    - ``a * b > 0`` que redondearía a 0 -> 1 (nada en $0 por redondeo).
    - resto -> ``floor(a * b + 0.5)``.
    """
    p = a * b
    if p <= 0:
        return 0
    r = math.floor(p + 0.5)
    return r if r != 0 else 1
