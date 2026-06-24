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
