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
