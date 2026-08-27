"""DTOs del contrato HTTP. Las respuestas de cuadro/ítems se devuelven como dict."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class StatusOut(BaseModel):
    insumos: int
    apus: int
    ia: bool


class ConfirmarIn(BaseModel):
    apu_codigo: str
    shift: Optional[str] = None


class ConfirmarLoteIn(BaseModel):
    seqs: list[int]
    apu_codigo: Optional[str] = None
    shift: Optional[str] = None


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


class TransporteParamsIn(BaseModel):
    km_botadero: Optional[float] = None
    km_mezclas: Optional[float] = None
    km_granulares: Optional[float] = None
    peaje_aplica: Optional[bool] = None
    peaje_valor: Optional[float] = None


class ClaseTransporteIn(BaseModel):
    apu_codigo: str
    shift: str
    insumo_codigo: str
    insumo_nombre: str = ""
    categoria: str
    volumen: float
    km_base: Optional[float] = None


class ClasificarIn(BaseModel):
    filas: list[ClaseTransporteIn]


class AjusteProyectoIn(BaseModel):
    apu_codigo: str
    shift: str
    accion: str                          # rendimiento | agregar | quitar | reemplazar
    insumo_codigo: str
    insumo_nombre: str = ""
    unidad: str = ""
    rendimiento: Optional[float] = None
    insumo_nuevo_codigo: str = ""
    insumo_nuevo_nombre: str = ""
    tipo: str = "insumo"
    ref_shift: str = ""
    nota: str = ""
