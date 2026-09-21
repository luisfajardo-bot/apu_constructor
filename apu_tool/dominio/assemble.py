"""
Orquestador del pipeline por ítem.

Para cada ítem de la lista de licitación:
  1. si el ítem trae código del presupuesto y ese APU existe -> AUTO, directo.
  2. matching determinístico contra el histórico (filtrado por turno):
       >= MATCH_ACCEPT -> AUTO
       >= MATCH_REVIEW -> el mejor candidato, marcado REVIEW
       por debajo      -> SIN APU, $0 con alerta (nunca se inventa nada)
  3. el motor determinístico costea la composición y arma el AssembledApu.

La IA NO participa del armado. Audita después, sobre la corrida ya armada
(ver dominio/revision.py) y siempre proponiendo, nunca aplicando.
"""
from __future__ import annotations

from typing import Callable, Optional

from apu_tool.dominio.ai_assist import ApuAdvisor
from apu_tool.datos.almacen import Almacen
from apu_tool.dominio.matching import Matcher
from apu_tool.nucleo.models import (
    AssembledApu,
    LicitacionItem,
    MatchResult,
    MatchStatus,
)
from apu_tool.dominio.pricing import PricingEngine

ProgressCb = Optional[Callable[[int, int, str], None]]


class Assembler:
    def __init__(self, almacen: Almacen, advisor: Optional[ApuAdvisor] = None,
                 lista_id: Optional[int] = None, contexto=None):
        self.alm = almacen
        # Costear con la tarifa de la corrida: armar y confirmar deben dar el mismo
        # número que la vista. None = Principal.
        self.lista_id = lista_id
        # Desviaciones del proyecto: armar/confirmar tienen que dar el mismo número
        # que la vista, así que el contexto viaja también por acá.
        self.pricing = PricingEngine(almacen, lista_id=lista_id, contexto=contexto)
        # Nadie lo usa ADENTRO: la composición se mudó a `composicion_agente.py`. Se
        # queda porque es donde `test_armado_nunca_llama_a_la_ia` mete su espía, que
        # es el candado de que el armado siga siendo determinístico.
        self.advisor = advisor or ApuAdvisor()
        # Matcher e índice de códigos son PEREZOSOS: construirlos lee el catálogo
        # completo de APUs (2 consultas) y arma un índice invertido en CPU.
        # El camino de confirmar/reasignar (reassemble_with_choice -> _build) NO los
        # usa, así que no se deben pagar ahí. Se materializan al primer acceso (armado).
        self._matcher: Optional[Matcher] = None
        self._codigos_apu_cache: Optional[set] = None

    @property
    def matcher(self) -> Matcher:
        if self._matcher is None:
            self._matcher = Matcher(self.alm.apus.apu_index())
        return self._matcher

    @property
    def _codigos_apu(self) -> set:
        if self._codigos_apu_cache is None:
            self._codigos_apu_cache = {cod for cod, _, _ in self.alm.apus.apu_index()}
        return self._codigos_apu_cache

    # ------------------------------------------------------------------ items
    def assemble_item(self, item: LicitacionItem,
                      match_result: Optional[MatchResult] = None) -> AssembledApu:
        # `match_result`: si se pasa el MatchResult ya calculado (p. ej. el stream lo
        # calcula una vez para mostrar candidatos), se reusa en vez de re-correr el
        # matcher — mismo resultado, sin el doble match. Si es None, se calcula aquí.
        # Armado por código directo (presupuesto): si el ítem trae un código IDU y
        # ese APU existe, se usa directo — el código es autoritativo, sin fuzzy/IA.
        if item.codigo_sugerido and item.codigo_sugerido in self._codigos_apu:
            return self._build(
                item, item.codigo_sugerido, item.shift, MatchStatus.AUTO, 1.0,
                f"Armado por código del presupuesto ({item.codigo_sugerido}).")

        result = match_result if match_result is not None else self.matcher.match(item)

        if result.status == MatchStatus.AUTO and result.elegido:
            return self._build(item, result.elegido.apu_codigo, item.shift,
                               MatchStatus.AUTO, result.confianza,
                               result.explicacion)

        # Dudoso o nuevo: SIN IA. El estado, la confianza y el motivo ya los decidió
        # `Matcher.match` con los mismos umbrales — acá NO se re-derivan, o el día que
        # alguien mueva MATCH_REVIEW los dos módulos dirán cosas distintas.
        # La IA ya no decide acá: audita después (dominio/revision.py), proponiendo.
        # Un 25% de parecido de nombre producía un APU con pinta de autoritativo —
        # caso real de 2026-08-04: una "Localización y replanteo" costeada como
        # PEDESTAL DE CONCRETO, 2010 veces el costo correcto.
        if result.status == MatchStatus.REVIEW and result.candidatos:
            return self._build(item, result.candidatos[0].apu_codigo, item.shift,
                               MatchStatus.REVIEW, result.confianza, result.explicacion)
        return AssembledApu(
            item=item, apu_codigo=None, apu_nombre="(sin base — armar manual)",
            unidad=item.unidad, shift=item.shift, componentes=[],
            costo_unitario=0.0, status=MatchStatus.NEW,
            confianza=result.confianza, origen="manual",
            explicacion=(f"{result.explicacion} Elige uno de los candidatos o ármalo "
                         f"a mano." if result.candidatos else
                         f"{result.explicacion} Ármalo a mano o agrega el APU a la "
                         f"biblioteca."),
        )

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
