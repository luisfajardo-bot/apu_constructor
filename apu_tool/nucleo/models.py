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

from apu_tool.nucleo.redondeo import mul_redondeado


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
    # True = NO hay fila de precio vigente en la lista con la que se leyó este insumo.
    # Distingue "sin tarifa en esta lista" de un $0 genuino, que la regla de negocio
    # prohíbe y que las alertas de costeo deben seguir mostrando.
    sin_precio: bool = False

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
    tipo: str = "insumo"          # "insumo" | "apu" (sub-APU)
    ref_shift: str = ""           # turno del sub-APU cuando tipo == "apu"


@dataclass(frozen=True)
class Apu:
    codigo: str
    nombre: str
    unidad: str
    shift: str
    grupo: str = ""


@dataclass(frozen=True)
class Perfil:
    """Identidad + rol de un usuario (tabla seguridad.perfiles)."""
    user_id: str                  # UUID de Supabase Auth
    email: str
    rol: str                      # admin | editor | consulta
    estado: str                   # activo | inactivo
    nombre: str = ""
    creado_en: str = ""


@dataclass(frozen=True)
class Carpeta:
    """Carpeta para agrupar corridas. parent_id None = nivel 1; con valor = nivel 2."""
    id: Optional[int]
    nombre: str
    parent_id: Optional[int]
    creada_en: str                # ISO 8601
    creado_por: Optional[str] = None


@dataclass(frozen=True)
class ListaPrecios:
    """Una tarifa. 'Principal' (id 1) es la del catálogo; las demás son de obra (NP)."""
    id: Optional[int]
    nombre: str
    creada_en: str                # ISO 8601 (YYYY-MM-DD)
    creado_por: Optional[str] = None


@dataclass(frozen=True)
class ClaseTransporte:
    """Clasificación de un componente de transporte de la biblioteca.

    `volumen` = m³ esponjados que mueve el APU por unidad suya; el rendimiento
    efectivo es `volumen × km_del_proyecto`. `km_base` es la distancia que se
    asumió al clasificar (solo trazabilidad: `volumen = rendimiento / km_base`).
    La identidad es código + nombre porque los códigos se repiten en el catálogo.
    """
    apu_codigo: str
    shift: str
    insumo_codigo: str
    insumo_nombre: str
    categoria: str                # botadero | mezclas | granulares
    volumen: float
    km_base: Optional[float] = None
    actualizado_en: str = ""
    actualizado_por: Optional[str] = None


@dataclass(frozen=True)
class ParametrosProyecto:
    """Distancias y peaje de un proyecto (carpeta de nivel 1).

    Todo `None` = no definido: la regla no toca nada y el costeo es el de hoy.
    `peaje_valor` es dinero (por eso está en `privacy._FORBIDDEN_KEYS`).
    """
    carpeta_id: Optional[int] = None
    km_botadero: Optional[float] = None
    km_mezclas: Optional[float] = None
    km_granulares: Optional[float] = None
    peaje_aplica: Optional[bool] = None
    peaje_valor: Optional[float] = None
    actualizado_en: str = ""
    actualizado_por: Optional[str] = None

    def km(self, categoria: str) -> Optional[float]:
        return {"botadero": self.km_botadero,
                "mezclas": self.km_mezclas,
                "granulares": self.km_granulares}.get(categoria)

    @property
    def vacio(self) -> bool:
        """Sin nada definido la regla es un no-op (garantía de no regresión)."""
        return all(v is None for v in (self.km_botadero, self.km_mezclas,
                                       self.km_granulares, self.peaje_aplica))


@dataclass(frozen=True)
class AjusteProyecto:
    """Excepción puntual de composición para un proyecto. NO ve dinero."""
    apu_codigo: str
    shift: str
    accion: str                   # rendimiento | agregar | quitar | reemplazar
    insumo_codigo: str
    insumo_nombre: str = ""
    unidad: str = ""
    rendimiento: Optional[float] = None
    insumo_nuevo_codigo: str = ""
    insumo_nuevo_nombre: str = ""
    tipo: str = "insumo"          # insumo | apu (sub-APU)
    ref_shift: str = ""           # turno del sub-APU cuando tipo == "apu"
    nota: str = ""
    id: Optional[int] = None
    carpeta_id: Optional[int] = None
    creado_en: str = ""
    creado_por: Optional[str] = None


@dataclass(frozen=True)
class EventoAuditoria:
    """Un evento de auditoría (tabla seguridad.auditoria). SIN dinero directo:
    los precios viajan dentro de antes/despues como parte del estado, nunca hacia la IA."""
    ts: str                                  # ISO 8601 UTC
    rol: str                                 # rol del actor; "sistema" si no hay actor
    accion: str                              # taxonomía objeto.verbo (p.ej. "precio.editar")
    entidad_tipo: str                        # insumo | apu | corrida | usuario
    entidad_id: str
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    antes: Optional[dict] = None
    despues: Optional[dict] = None
    contexto: Optional[dict] = None


# ---------------------------------------------------------------------------
# Vistas SIN dinero — lo único que la IA puede ver
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class DePricedComponent:
    insumo_codigo: str
    insumo_nombre: str
    unidad: str
    rendimiento: float            # cantidad, no es dinero
    tipo: str = "insumo"          # estructura: "insumo" | "apu" (sin dinero)


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


# Vocabulario de CostedComponent.calidad_cruce/fuente_precio para los estados "sin
# tarifa" que decide el motor de precios (dominio/pricing.py, el único que ve dinero).
# Viven aquí y no en pricing.py porque son vocabulario del TIPO, no del motor: así
# alertas.py (que solo lee calidad_cruce) no necesita importar el motor de precios
# y arrastrar detrás `datos.almacen`/`precios_db`/`apus_db`/`corridas_db`/`sqlite3`.
FUENTE_SIN_PRECIO_LISTA = "sin precio en lista"      # insumo encontrado, sin fila de precio en una lista NP
FUENTE_SIN_RESPALDO = "sin respaldo"                 # sub-APU sin árbol costeable (ciclo/vacío) en una lista NP
CALIDAD_SIN_PRECIO_LISTA = "sin_precio_lista"        # ausencia de precio en una lista NP
CALIDAD_SIN_PRECIO_CATALOGO = "sin_precio_catalogo"  # insumo encontrado sin fila de precio en Principal
CALIDAD_SIN_DISTANCIA = "sin_distancia_proyecto"   # componente M3-KM sin clasificar


@dataclass
class CostedComponent:
    insumo_codigo: str
    insumo_nombre: str
    unidad: str
    rendimiento: float
    precio_unitario: float        # precio usado (catálogo actual o histórico)
    fuente_precio: str
    costo: float                  # rendimiento * precio_unitario
    calidad_cruce: str = "exacto" # exacto | aproximado | ambiguo | huerfano | apu | apu_vacio | ciclo | sin_precio_lista | sin_precio_catalogo
    tipo: str = "insumo"          # "insumo" | "apu"
    ref_shift: str = ""           # turno del sub-APU cuando tipo == "apu"


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
    def costo_total(self) -> int:
        return mul_redondeado(self.costo_unitario, self.item.cantidad)

    @property
    def contractual_total(self) -> int:
        return mul_redondeado(self.item.precio_contractual, self.item.cantidad)

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


# ---------------------------------------------------------------------------
# Estado de aplicación: la corrida (armado web en progreso)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CorridaMeta:
    id: Optional[int]
    creada_en: str                # ISO 8601
    archivo: str
    turno_def: str
    use_ai: Optional[bool]
    estado: str                   # 'en_revision' | 'finalizada'
    cuadro_path: Optional[str] = None
    duracion_ms: Optional[int] = None
    modo: str = "activa"
    carpeta_id: Optional[int] = None
    nombre: str = ""              # alias editable; vacío => se deriva de `archivo`
    # Tarifa contra la que se costea la corrida. None = Principal (el catálogo).
    # Se fija AL CREAR y no cambia: una corrida nunca debe mudar de tarifa por accidente.
    lista_precios_id: Optional[int] = None


@dataclass
class CorridaItemRow:
    seq: int
    item: LicitacionItem
    status: str                   # auto | review | new | confirmed | rejected
    apu_codigo: Optional[str]
    apu_nombre: str
    unidad: str
    shift: str
    origen: str
    confianza: float
    explicacion: str
    componentes: list[dict]       # [{insumo_codigo, insumo_nombre, unidad, rendimiento}] (sin dinero)
    candidatos: list[dict]        # [{apu_codigo, apu_nombre, score, motivo}] (sin dinero)
