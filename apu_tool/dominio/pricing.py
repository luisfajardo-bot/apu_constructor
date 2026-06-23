"""
Motor de precios determinístico.

Es el ÚNICO módulo que toca dinero. Toma un APU (su composición de insumos con
rendimientos) y calcula el costo unitario, llamando a los precios de la base de
insumos. Idea central del usuario: los APUs siempre llaman al precio vigente del
insumo; si el insumo no está en el catálogo, se usa el precio histórico embebido
en la composición como respaldo.

Este módulo NO se le pasa nunca a la IA.
"""
from __future__ import annotations

from typing import Optional

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import ApuComponent, CostedComponent


class PricingEngine:
    def __init__(self, almacen: Almacen):
        self.alm = almacen
        self._cache: dict[str, Optional[tuple[float, str]]] = {}

    def _insumo_price(self, codigo: str) -> Optional[tuple[float, str]]:
        """Devuelve (precio, fuente) del catálogo, o None si no está."""
        if not codigo:
            return None
        if codigo in self._cache:
            return self._cache[codigo]
        ins = self.alm.precios.get_insumo(codigo)
        result = (ins.precio, ins.fuente_precio) if ins else None
        self._cache[codigo] = result
        return result

    def cost_component(self, comp: ApuComponent) -> CostedComponent:
        cat = self._insumo_price(comp.insumo_codigo)
        if cat is not None and cat[0] > 0:
            precio, fuente = cat
        else:
            # Respaldo: precio histórico embebido en la composición.
            precio, fuente = comp.precio_unitario_hist, "histórico"
        costo = comp.rendimiento * precio
        return CostedComponent(
            insumo_codigo=comp.insumo_codigo,
            insumo_nombre=comp.insumo_nombre,
            unidad=comp.unidad,
            rendimiento=comp.rendimiento,
            precio_unitario=precio,
            fuente_precio=fuente,
            costo=costo,
        )

    def cost_components(self, comps: list[ApuComponent]) -> tuple[list[CostedComponent], float]:
        costed = [self.cost_component(c) for c in comps]
        total = sum(c.costo for c in costed)
        return costed, total

    def cost_apu(self, apu_codigo: str, shift: str) -> tuple[list[CostedComponent], float]:
        comps = self.alm.apus.get_components(apu_codigo, shift)
        return self.cost_components(comps)
