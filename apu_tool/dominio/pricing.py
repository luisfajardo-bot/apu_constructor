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

from apu_tool.datos.almacen import Almacen
from apu_tool.dominio import cruce
from apu_tool.nucleo.models import ApuComponent, CostedComponent


class PricingEngine:
    def __init__(self, almacen: Almacen):
        self.alm = almacen
        self._cache: dict[str, list] = {}          # codigo -> list[Insumo] candidatos
        self._apu_cost_cache: dict[tuple, float] = {}  # (codigo, shift) -> costo_unitario

    def _candidatos(self, codigo: str) -> list:
        if not codigo:
            return []
        if codigo not in self._cache:
            self._cache[codigo] = self.alm.precios.get_candidatos(codigo)
        return self._cache[codigo]

    def cost_component(self, comp: ApuComponent, _visitando: tuple = ()) -> CostedComponent:
        if (comp.tipo or "insumo") == "apu":
            return self._cost_subapu(comp, _visitando)
        r = cruce.resolver(self._candidatos(comp.insumo_codigo), comp.insumo_nombre)
        if r.insumo is not None and r.insumo.precio > 0:        # EXACTO o APROXIMADO
            precio, fuente = r.insumo.precio, r.insumo.fuente_precio
        else:                                                   # AMBIGUO o HUERFANO
            precio, fuente = comp.precio_unitario_hist, "histórico"
        costo = comp.rendimiento * precio
        return CostedComponent(
            insumo_codigo=comp.insumo_codigo, insumo_nombre=comp.insumo_nombre,
            unidad=comp.unidad, rendimiento=comp.rendimiento,
            precio_unitario=precio, fuente_precio=fuente, costo=costo,
            calidad_cruce=r.calidad.value, tipo="insumo", ref_shift="")

    def _cost_subapu(self, comp: ApuComponent, visitando: tuple) -> CostedComponent:
        sub_shift = comp.ref_shift or comp.shift
        clave = (comp.insumo_codigo, sub_shift)
        if clave in visitando:                                  # ciclo -> respaldo histórico
            precio = comp.precio_unitario_hist
            return CostedComponent(
                insumo_codigo=comp.insumo_codigo, insumo_nombre=comp.insumo_nombre,
                unidad=comp.unidad, rendimiento=comp.rendimiento,
                precio_unitario=precio, fuente_precio="histórico",
                costo=comp.rendimiento * precio, calidad_cruce="ciclo",
                tipo="apu", ref_shift=sub_shift)
        unit = self._costo_unitario_apu(comp.insumo_codigo, sub_shift, visitando + (clave,))
        return CostedComponent(
            insumo_codigo=comp.insumo_codigo, insumo_nombre=comp.insumo_nombre,
            unidad=comp.unidad, rendimiento=comp.rendimiento,
            precio_unitario=unit, fuente_precio="APU",
            costo=comp.rendimiento * unit, calidad_cruce="apu",
            tipo="apu", ref_shift=sub_shift)

    def _costo_unitario_apu(self, codigo: str, shift: str, visitando: tuple) -> float:
        clave = (codigo, shift)
        if clave in self._apu_cost_cache:                       # memoización por pasada
            return self._apu_cost_cache[clave]
        comps = self.alm.apus.get_components(codigo, shift)
        total = sum(self.cost_component(c, visitando).costo for c in comps)
        self._apu_cost_cache[clave] = total
        return total

    def cost_components(self, comps: list[ApuComponent]) -> tuple[list[CostedComponent], float]:
        costed = [self.cost_component(c) for c in comps]
        total = sum(c.costo for c in costed)
        return costed, total

    def cost_apu(self, apu_codigo: str, shift: str) -> tuple[list[CostedComponent], float]:
        comps = self.alm.apus.get_components(apu_codigo, shift)
        seed = ((apu_codigo, shift),)                           # detecta auto-referencia nivel 1
        costed = [self.cost_component(c, seed) for c in comps]
        return costed, sum(c.costo for c in costed)
