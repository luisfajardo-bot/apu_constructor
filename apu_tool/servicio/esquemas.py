"""DTOs del contrato HTTP. Las respuestas de cuadro/ítems se devuelven como dict."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class StatusOut(BaseModel):
    insumos: int
    apus: int
    ia: bool


class ConfirmarIn(BaseModel):
    apu_codigo: str
    shift: Optional[str] = None


class AsignacionIn(BaseModel):
    """Una sugerencia aplicada: a esta fila, este APU."""
    seq: int
    apu_codigo: str
    shift: Optional[str] = None


class ConfirmarLoteIn(BaseModel):
    seqs: list[int]
    apu_codigo: Optional[str] = None
    shift: Optional[str] = None
    # Un APU distinto por fila (aplicar sugerencias de la IA). Cuando viene, manda
    # sobre `seqs` y `apu_codigo`.
    asignaciones: Optional[list[AsignacionIn]] = None


class LineaNuevaIn(BaseModel):
    """Una actividad que faltó en la corrida, cargada a mano."""
    descripcion: str
    unidad: str = ""
    cantidad: float = Field(default=1.0, ge=0)
    precio_contractual: float = Field(default=0.0, ge=0)
    shift: Optional[str] = None    # None/vacío = el turno por defecto de la corrida
    item: str = ""                 # nº de ítem del pliego; vacío = se numera solo


class AgregarLineasIn(BaseModel):
    lineas: list[LineaNuevaIn]


class BorrarLineasIn(BaseModel):
    seqs: list[int]


class IgualarCostoIn(BaseModel):
    seqs: list[int]


class CambioIn(BaseModel):
    insumo_id: int
    precio: float
    fuente: str = ""


class CambiosIn(BaseModel):
    cambios: list[CambioIn]
    lista_id: Optional[int] = None      # None = Principal


class ListaPreciosIn(BaseModel):
    nombre: str


class InsumoNuevoIn(BaseModel):
    codigo: str
    nombre: str
    unidad: str = ""
    grupo: str = ""
    precio: float = 0.0
    fuente: str = ""
    lista_id: Optional[int] = None      # None = Principal


class ComponenteIn(BaseModel):
    insumo_codigo: str
    rendimiento: float
    insumo_nombre: str = ""
    unidad: str = ""
    tipo: str | None = None      # 'insumo' | 'apu'; None = preservar el existente al editar
    ref_shift: str = ""          # turno del sub-APU si tipo == 'apu'


class DuplicadoDeIn(BaseModel):
    """APU del que sale una copia. Presente solo cuando el alta es un duplicado."""
    codigo: str
    turno: str


class ApuNuevoIn(BaseModel):
    codigo: str
    turno: str
    nombre: str
    unidad: str = ""
    grupo: str = ""
    componentes: list[ComponenteIn] = []
    duplicado_de: Optional[DuplicadoDeIn] = None   # None = alta normal


class ApuEditIn(BaseModel):
    nombre: str
    unidad: str = ""
    grupo: str = ""
    componentes: list[ComponenteIn] = []


class UsuarioInvitarIn(BaseModel):
    email: str
    rol: str
    nombre: str = ""


class RolIn(BaseModel):
    rol: str


class EstadoIn(BaseModel):
    estado: str


# ------------------------------------------------------- composición asistida
class ComponenteComposicionIn(BaseModel):
    """Un componente tal como lo deja el humano en la mesa de revisión."""
    codigo: str
    tipo: str = "insumo"
    funcion: str = ""
    rendimiento: float
    origen: str = "supuesto_tecnico"
    referencias: list[dict] = []
    hipotesis: dict = {}
    calculo: Optional[dict] = None
    justificacion: str = ""
    nivel_evidencia: str = "bajo"
    ref_shift: str = ""


class ComposicionEditarIn(BaseModel):
    # La versión sobre la que trabajó el usuario. Si ya hay una mayor, 409: alguien
    # más la cambió mientras tanto.
    version_base: int
    componentes: list[ComponenteComposicionIn]
    supuestos_confirmados: bool = False


class ComposicionAprobarIn(BaseModel):
    """La identidad del APU la pone el humano; los componentes salen de la versión
    vigente, no del cuerpo: aprobar no es una oportunidad de editar."""
    version_base: int
    codigo: str
    turno: str
    nombre: str
    grupo: str = ""
    unidad: str = ""


class ComposicionRechazarIn(BaseModel):
    version_base: int
    motivo: str = ""
