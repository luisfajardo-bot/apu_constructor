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


class CambioIn(BaseModel):
    insumo_id: int
    precio: float
    fuente: str = ""


class CambiosIn(BaseModel):
    cambios: list[CambioIn]


class TransformarIn(BaseModel):
    filtro: dict
    operacion: dict


class InsumoNuevoIn(BaseModel):
    codigo: str
    nombre: str
    unidad: str = ""
    grupo: str = ""
    precio: float = 0.0
    fuente: str = ""


class ComponenteIn(BaseModel):
    insumo_codigo: str
    rendimiento: float
    insumo_nombre: str = ""
    unidad: str = ""


class ApuNuevoIn(BaseModel):
    codigo: str
    turno: str
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
