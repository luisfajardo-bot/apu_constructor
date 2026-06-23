"""
Orquestador del pipeline por ítem.

Para cada ítem de la lista de licitación:
  1. matching determinístico contra el histórico (filtrado por turno).
  2. si el match es claro -> se usa directo (status AUTO).
     si es dudoso o nuevo -> la IA (acotada, sin dinero) propone el APU base
        y se marca REVIEW para que el usuario confirme.
  3. el motor determinístico costea la composición y arma el AssembledApu.

El armado por analogía nunca inventa precios: reutiliza la composición del APU
histórico elegido y la repreciar con los insumos vigentes.
"""
from __future__ import annotations

from typing import Callable, Optional

from apu_tool.dominio.ai_assist import ApuAdvisor, ComposeResult
from apu_tool.dominio.compose import InsumoRetriever
from apu_tool.datos.almacen import Almacen
from apu_tool.dominio.matching import Matcher
from apu_tool.nucleo.models import (
    ApuComponent,
    AssembledApu,
    DePricedApu,
    LicitacionItem,
    MatchStatus,
)
from apu_tool.dominio.pricing import PricingEngine

ProgressCb = Optional[Callable[[int, int, str], None]]


class Assembler:
    def __init__(self, almacen: Almacen, advisor: Optional[ApuAdvisor] = None):
        self.alm = almacen
        self.matcher = Matcher(almacen.apus.apu_index())
        self.pricing = PricingEngine(almacen)
        self.advisor = advisor or ApuAdvisor()
        self.retriever = InsumoRetriever(almacen, self.matcher)
        self._codigos_apu = {cod for cod, _, _ in almacen.apus.apu_index()}

    # ------------------------------------------------------------------ items
    def assemble_item(self, item: LicitacionItem) -> AssembledApu:
        # Armado por código directo (presupuesto): si el ítem trae un código IDU y
        # ese APU existe, se usa directo — el código es autoritativo, sin fuzzy/IA.
        if item.codigo_sugerido and item.codigo_sugerido in self._codigos_apu:
            return self._build(
                item, item.codigo_sugerido, item.shift, MatchStatus.AUTO, 1.0,
                f"Armado por código del presupuesto ({item.codigo_sugerido}).")

        result = self.matcher.match(item)

        if result.status == MatchStatus.AUTO and result.elegido:
            return self._build(item, result.elegido.apu_codigo, item.shift,
                               MatchStatus.AUTO, result.confianza,
                               result.explicacion)

        # Dudoso o nuevo: la IA elige el APU base entre los candidatos (sin dinero).
        depriced = {
            c.apu_codigo: self.alm.apus.get_depriced_apu(c.apu_codigo, item.shift)
            for c in result.candidatos
        }
        depriced = {k: v for k, v in depriced.items() if v is not None}
        decision = self.advisor.choose_apu(item, result.candidatos, depriced)

        if not decision.apu_codigo:
            # Sin base histórica adecuada -> intentar composición generativa (IA).
            generado = self._try_generate(item)
            if generado is not None:
                return generado
            return AssembledApu(
                item=item, apu_codigo=None, apu_nombre="(sin base — armar manual)",
                unidad=item.unidad, shift=item.shift, componentes=[],
                costo_unitario=0.0, status=MatchStatus.NEW,
                confianza=decision.confianza, origen="manual",
                explicacion=decision.justificacion or result.explicacion,
            )

        expl = f"[{decision.fuente}] {decision.justificacion}".strip()
        return self._build(item, decision.apu_codigo, item.shift,
                           MatchStatus.REVIEW, decision.confianza, expl)

    def reassemble_with_choice(self, item: LicitacionItem, apu_codigo: str,
                               shift: Optional[str] = None) -> AssembledApu:
        """Rearma un ítem con un APU elegido/confirmado por el usuario."""
        shift = shift or item.shift
        return self._build(item, apu_codigo, shift, MatchStatus.CONFIRMED, 1.0,
                           "Confirmado por el usuario.")

    def assemble_all(self, items: list[LicitacionItem],
                     progress: ProgressCb = None) -> list[AssembledApu]:
        out: list[AssembledApu] = []
        total = len(items)
        for i, item in enumerate(items, 1):
            if progress:
                progress(i, total, item.descripcion)
            out.append(self.assemble_item(item))
        return out

    # --------------------------------------------------- composición generativa
    def _try_generate(self, item: LicitacionItem) -> Optional[AssembledApu]:
        """Arma un APU desde cero con la IA para una actividad nueva.
        Devuelve None si no hay IA o si no se pudo componer (queda manual)."""
        insumos, ejemplos = self.retriever.retrieve(item.descripcion, item.shift)
        result: Optional[ComposeResult] = self.advisor.compose_apu(item, insumos, ejemplos)
        if result is None or not result.componentes:
            return None

        comps: list[ApuComponent] = []
        for cc in result.componentes:
            cands = self.alm.precios.get_candidatos(cc.insumo_codigo)
            if not cands:
                continue
            ins = cands[0]   # la IA solo da código; el costeo re-resuelve por nombre
            comps.append(ApuComponent(
                apu_codigo="", shift=item.shift, insumo_codigo=ins.codigo,
                insumo_nombre=ins.nombre, unidad=ins.unidad,
                rendimiento=cc.rendimiento, precio_unitario_hist=0.0))
        if not comps:
            return None

        costed, total = self.pricing.cost_components(comps)
        expl = f"[IA: composición generada] {result.justificacion}".strip()
        return AssembledApu(
            item=item, apu_codigo=None, apu_nombre=item.descripcion,
            unidad=item.unidad, shift=item.shift, componentes=costed,
            costo_unitario=total, status=MatchStatus.REVIEW,
            confianza=result.confianza, origen="generado", explicacion=expl)

    # --------------------------------------------------------------- interno
    def _build(self, item: LicitacionItem, apu_codigo: str, shift: str,
               status: MatchStatus, confianza: float, expl: str) -> AssembledApu:
        apu = self.alm.apus.get_apu(apu_codigo, shift)
        if apu is None:
            # El APU existe en otro turno: caer a ese turno.
            for alt in self.alm.apus.all_apus():
                if alt.codigo == apu_codigo:
                    apu = alt
                    shift = alt.shift
                    break
        costed, total = self.pricing.cost_apu(apu_codigo, shift)
        return AssembledApu(
            item=item,
            apu_codigo=apu_codigo,
            apu_nombre=apu.nombre if apu else item.descripcion,
            unidad=apu.unidad if apu else item.unidad,
            shift=shift,
            componentes=costed,
            costo_unitario=total,
            status=status,
            confianza=confianza,
            explicacion=expl,
        )
