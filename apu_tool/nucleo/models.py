"""
Estructuras de datos del dominio.

Separación deliberada:
  - Insumo / ApuComponent / Apu      : datos de la base (pueden contener precios).
  - DePricedActivity / DePricedApu    : vistas SIN dinero, lo único que ve la IA.
  - MatchResult / AssembledApu / ...  : resultados del pipeline.

La frontera de privacidad se hace explícita en el tipo: lo que la IA recibe son
las clases *DePriced*, que por construcción no tienen campos monetarios.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Catálogos (capa de datos)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Insumo:
    codigo: str
    nombre: str
    unidad: str
    grupo: str
    precio: float
    fuente_precio: str          # "PRECIO IDU", "COSTO INTERNO", etc.
    id: Optional[int] = None    # id interno del catálogo (None si aún no persistido)

    @property
    def es_confidencial(self) -> bool:
        from apu_tool.config import PUBLIC_PRICE_SOURCES
        return (self.fuente_precio or "").strip().upper() not in {
            s.upper() for s in PUBLIC_PRICE_SOURCES
        }


@dataclass(frozen=True)
class ApuComponent:
    apu_codigo: str
    shift: str
    insumo_codigo: str
    insumo_nombre: str
    unidad: str
    rendimiento: float
    precio_unitario_hist: float   # costo histórico embebido (NO se expone a la IA)


@dataclass(frozen=True)
class Apu:
    codigo: str
    nombre: str
    unidad: str
    shift: str
    grupo: str = ""


# ---------------------------------------------------------------------------
# Vistas SIN dinero — lo único que la IA puede ver
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DePricedComponent:
    insumo_codigo: str
    insumo_nombre: str
    unidad: str
    rendimiento: float            # cantidad, no es dinero


@dataclass(frozen=True)
class DePricedApu:
    codigo: str
    nombre: str
    unidad: str
    shift: str
    grupo: str
    componentes: tuple[DePricedComponent, ...]


# ---------------------------------------------------------------------------
# Entrada (lista de licitación)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LicitacionItem:
    item: str                     # número/código de ítem en la licitación
    descripcion: str
    unidad: str
    cantidad: float
    precio_contractual: float     # precio unitario contractual (lo pone el cliente)
    shift: str                    # DIURNO / NOCTURNO (del ítem o global)
    categoria: str = ""           # capítulo del presupuesto (vacío en el flujo plano)
    codigo_sugerido: str = ""     # código IDU dado por el presupuesto (armado directo)


# ---------------------------------------------------------------------------
# Resultados del pipeline
# ---------------------------------------------------------------------------
class MatchStatus(str, Enum):
    AUTO = "auto"          # match determinístico claro
    REVIEW = "review"      # candidato dudoso, requiere confirmación
    NEW = "new"            # sin match -> armar por analogía / manual
    CONFIRMED = "confirmed"  # confirmado por el usuario
    REJECTED = "rejected"    # rechazado por el usuario


@dataclass
class MatchCandidate:
    apu_codigo: str
    apu_nombre: str
    score: float
    motivo: str = ""


@dataclass
class MatchResult:
    item: LicitacionItem
    status: MatchStatus
    elegido: Optional[MatchCandidate] = None
    candidatos: list[MatchCandidate] = field(default_factory=list)
    explicacion: str = ""         # justificación (de la IA o del matcher)
    confianza: float = 0.0        # 0..1


@dataclass
class CostedComponent:
    insumo_codigo: str
    insumo_nombre: str
    unidad: str
    rendimiento: float
    precio_unitario: float        # precio usado (catálogo actual o histórico)
    fuente_precio: str
    costo: float                  # rendimiento * precio_unitario


@dataclass
class AssembledApu:
    item: LicitacionItem
    apu_codigo: Optional[str]
    apu_nombre: str
    unidad: str
    shift: str
    componentes: list[CostedComponent]
    costo_unitario: float
    status: MatchStatus
    confianza: float
    explicacion: str = ""
    origen: str = "historico"     # "historico" | "generado" | "manual"

    @property
    def costo_total(self) -> float:
        return self.costo_unitario * self.item.cantidad

    @property
    def contractual_total(self) -> float:
        return self.item.precio_contractual * self.item.cantidad

    @property
    def margen_unitario(self) -> float:
        return self.item.precio_contractual - self.costo_unitario

    @property
    def margen_total(self) -> float:
        return self.contractual_total - self.costo_total

    @property
    def margen_pct(self) -> float:
        base = self.item.precio_contractual
        return (self.margen_unitario / base) if base else 0.0
