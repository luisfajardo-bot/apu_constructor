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
    # --- capítulo del presupuesto (ruta IDU) ---------------------------------
    # Todos con default: es lo que hace que una corrida encolada ANTES de este deploy
    # se rehidrate sin explotar (`plan_de` hace LicitacionItem(**d) sobre plan_json).
    # `categoria` se conserva y se DERIVA de estos dos en el lector, para que
    # report_categorizado.agrupar_por_capitulo y sus tests sigan funcionando igual.
    capitulo_codigo: str = ""          # "2" — la referencia estable, no el nombre
    capitulo_nombre: str = ""          # "PAVIMENTOS"
    item_pago_original: str = ""       # "2,001-N" tal cual venía, para auditoría
    fila_origen: int = 0               # fila del Excel de la que salió, 1-based
    # Valor unitario SIN AIU. Es DINERO: va a privacy._FORBIDDEN_KEYS y NO viaja en
    # licitacion_item_to_dict. `precio_contractual` sigue siendo el que manda (con AIU).
    precio_contractual_sin_aiu: float = 0.0


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
    # "historico" | "manual". Ya NADIE produce "generado": murió con la composición
    # de dos campos (`Assembler.generar_composicion`), que se mudó al orquestador
    # `dominio/composicion_agente.py` y propone en vez de armar. No lo revivas
    # creyendo que es un valor vivo. Se sigue leyendo como texto libre a propósito:
    # `corrida_item.origen` es una columna persistida y las filas armadas antes de
    # que la IA dejara de armar pueden traerlo, así que validarlo contra un
    # vocabulario cerrado rompería corridas viejas.
    origen: str = "historico"

    @property
    def costo_total(self) -> int:
        return mul_redondeado(self.costo_unitario, self.item.cantidad)

    @property
    def contractual_total(self) -> int:
        return mul_redondeado(self.item.precio_contractual, self.item.cantidad)

    @property
    def contractual_total_sin_aiu(self) -> int:
        """El contractual del ítem sin AIU. Misma regla de redondeo que su gemelo.

        La ruta IDU lee las DOS bases del Formulario 1: `precio_contractual` es el valor
        unitario CON AIU (el que concilia con el VALOR TOTAL del Excel) y este es el
        básico sin AIU. 0 en una corrida que no venga del IDU.
        """
        return mul_redondeado(self.item.precio_contractual_sin_aiu, self.item.cantidad)

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

    @property
    def costo_a_mano(self) -> bool:
        """El costo lo declaró una persona, no lo calculó el motor.

        Firma: sin componentes y con costo positivo. Es inequívoca porque el costo del
        motor es la suma de los componentes — sin componentes esa suma es 0 (un APU
        vacío, un sub-APU en ciclo o un insumo huérfano igual devuelven componentes).
        Vive acá y no en cada consumidor porque la leen cuatro lugares (la vista de la
        API, las alertas y los dos escritores de Excel) y `> 0` cambiado en uno solo
        sería un drift silencioso. Funciona igual con la corrida congelada: el snapshot
        guarda `composicion: []` con el mismo costo.
        """
        return not self.componentes and self.costo_unitario > 0


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
    # --- armado como trabajo del servidor (ver docs/superpowers/specs/2026-09-07-armado-reanudable-design.md) ---
    # `estado='armando'` ES la cola: nadie saca una corrida de ahí salvo el worker al
    # terminarla o `reencolar_armado`. Un set_estado sin guarda la borra de la cola.
    intentos: int = 0                      # +1 por cada reclama; al pasar el tope -> 'armado_detenido'
    ultimo_error: Optional[str] = None     # por qué se detuvo, en español, para la pantalla
    armando_por: Optional[str] = None      # id de la instancia que la reclamó
    armando_desde: Optional[str] = None    # ISO 8601 del último latido de esa reclama


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
    revision: Optional[dict] = None   # veredicto de la IA (sin dinero); None = sin revisar
    # Costo unitario puesto a mano (proyectos especiales). None = costear normal desde
    # la composición. NUNCA entra a un payload de la IA: es dinero (ver privacy.py).
    costo_manual: Optional[float] = None


@dataclass(frozen=True)
class ComposicionRow:
    """Una VERSIÓN del expediente de composición de una fila de corrida.

    Append-only: cada acción que cambia la propuesta (generar, regenerar, editar,
    aprobar, rechazar) escribe una fila nueva y la vigente es la de mayor `version`.
    El historial de correcciones sale gratis, y es lo que la fase 4 va a leer como
    evidencia.

    NO lleva dinero, y es deliberado: `actividad` guarda la vista des-monetizada
    (`privacy.licitacion_item_to_dict`), no el `LicitacionItem` crudo, que traería
    `precio_contractual`. Así la fila entera se puede reinyectar en un payload hacia la
    IA sin volver a filtrarla. Es la lección de `plan_json`, aplicada antes de tropezar.

    Tampoco hay campo para razonamiento del modelo: solo justificaciones cortas, datos
    estructurados, referencias y decisiones observables.
    """
    id: Optional[int]
    corrida_id: int
    seq: int
    version: int
    estado: str                       # de dominio.composicion.ESTADOS
    actividad: dict
    ficha: Optional[dict]             # fase 2; None en fase 1
    propuesta: Optional[dict]
    validacion: Optional[dict]
    confianza: Optional[str]          # alta | media | baja | insuficiente
    confianza_motivos: Optional[list]
    antecedentes: Optional[dict]
    modelo: Optional[str]
    prompt_version: Optional[str]
    apu_codigo: Optional[str]         # el APU creado, solo si estado == 'aprobada'
    apu_turno: Optional[str]
    autor: Optional[str]
    creada_en: str
    motivo: Optional[str]             # el error, o la razón del rechazo

    def to_dict(self) -> dict:
        return {
            "corrida_id": self.corrida_id, "seq": self.seq, "version": self.version,
            "estado": self.estado, "actividad": self.actividad, "ficha": self.ficha,
            "propuesta": self.propuesta, "validacion": self.validacion,
            "confianza": self.confianza, "confianza_motivos": self.confianza_motivos,
            "antecedentes": self.antecedentes, "modelo": self.modelo,
            "prompt_version": self.prompt_version, "apu_codigo": self.apu_codigo,
            "apu_turno": self.apu_turno, "autor": self.autor,
            "creada_en": self.creada_en, "motivo": self.motivo,
        }
