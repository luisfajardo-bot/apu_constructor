"""
Recuperación de insumos candidatos para la composición generativa.

Cuando una actividad no tiene un APU histórico adecuado, la IA arma el APU desde
cero. Para eso necesita un CONJUNTO de insumos entre los cuales elegir (no se le
pueden mandar los 7.500 del catálogo). Este módulo construye ese conjunto:

  - insumos que aparecen en los APUs históricos más parecidos a la actividad, y
  - insumos cuyo nombre coincide con palabras clave de la actividad.

Todo lo que sale de aquí es SIN dinero (tipos DePriced*): la IA nunca ve precios.
"""
from __future__ import annotations

from dataclasses import dataclass

from apu_tool.datos.almacen import Almacen
from apu_tool.dominio.matching import Matcher, similarity, _tokens
from apu_tool.nucleo.models import DePricedApu, DePricedComponent


@dataclass(frozen=True)
class CandidateInsumo:
    """Insumo candidato SIN dinero (código, nombre, unidad)."""
    codigo: str
    nombre: str
    unidad: str


class InsumoRetriever:
    def __init__(self, almacen: Almacen, matcher: Matcher | None = None):
        self.alm = almacen
        self.matcher = matcher or Matcher(almacen.apus.apu_index())

    def retrieve(
        self, descripcion: str, shift: str, max_insumos: int = 40,
        max_ejemplos: int = 3,
    ) -> tuple[list[CandidateInsumo], list[DePricedApu]]:
        """Devuelve (insumos_candidatos, apus_ejemplo) — todo sin dinero."""
        # 1) APUs análogos -> sus insumos + sirven de ejemplo.
        cands = self.matcher.candidates(descripcion, shift, top_n=8)
        ejemplos: list[DePricedApu] = []
        insumos: dict[str, CandidateInsumo] = {}
        for c in cands[:max_ejemplos]:
            dp = self.alm.apus.get_depriced_apu(c.apu_codigo, shift)
            if dp is None:
                continue
            ejemplos.append(dp)
        for c in cands:
            dp = self.alm.apus.get_depriced_apu(c.apu_codigo, shift)
            if dp is None:
                continue
            for comp in dp.componentes:
                if comp.insumo_codigo and comp.insumo_codigo not in insumos:
                    insumos[comp.insumo_codigo] = CandidateInsumo(
                        comp.insumo_codigo, comp.insumo_nombre, comp.unidad)

        # 2) Insumos por coincidencia de nombre con la actividad.
        palabras = [t for t in _tokens(descripcion) if len(t) >= 4]
        for ins in self.alm.precios.search_insumos_por_palabras(palabras, limit=60):
            if ins.codigo not in insumos:
                insumos[ins.codigo] = CandidateInsumo(ins.codigo, ins.nombre, ins.unidad)

        # Ordenar por afinidad del nombre del insumo con la actividad y recortar.
        ordenados = sorted(
            insumos.values(),
            key=lambda i: similarity(descripcion, i.nombre), reverse=True,
        )
        return ordenados[:max_insumos], ejemplos


def candidate_insumo_to_dict(c: CandidateInsumo) -> dict:
    return {"insumo_codigo": c.codigo, "insumo_nombre": c.nombre, "unidad": c.unidad}


@dataclass(frozen=True)
class RendimientoObservado:
    """Cómo se usa un insumo en la biblioteca. SIN dinero: son cantidades físicas."""
    insumo_codigo: str
    unidad: str
    n: int
    minimo: float
    mediana: float
    maximo: float

    def to_dict(self) -> dict:
        return {"insumo_codigo": self.insumo_codigo, "unidad": self.unidad,
                "n": self.n, "minimo": round(self.minimo, 6),
                "mediana": round(self.mediana, 6), "maximo": round(self.maximo, 6)}


def _mediana(xs: list[float]) -> float:
    ord_ = sorted(xs)
    m = len(ord_) // 2
    return ord_[m] if len(ord_) % 2 else (ord_[m - 1] + ord_[m]) / 2


def rendimientos_observados(almacen: Almacen, codigos) -> dict[str, RendimientoObservado]:
    """Estadística no monetaria de cada insumo en la biblioteca.

    Le da al modelo con qué declarar "copiado" o "ajustado", y al validador con qué
    llamar atípico a un rendimiento. Un insumo que no se usa en ningún APU no aparece:
    la ausencia es el dato (`SIN_ANTECEDENTES`), no un rango de ceros.
    """
    crudo = almacen.apus.rendimientos_por_insumo(codigos)
    out: dict[str, RendimientoObservado] = {}
    for cod, pares in crudo.items():
        # Un rendimiento <= 0 en la biblioteca es un dato roto, no un antecedente.
        vals = [r for _u, r in pares if r > 0]
        if not vals:
            continue
        unidades = [u for u, r in pares if r > 0 and u]
        out[cod] = RendimientoObservado(
            insumo_codigo=cod, unidad=(unidades[0] if unidades else ""),
            n=len(vals), minimo=min(vals), mediana=_mediana(vals), maximo=max(vals))
    return out
