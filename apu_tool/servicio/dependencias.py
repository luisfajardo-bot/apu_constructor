"""Inyección de dependencias de la API: el Almacen vive en app.state."""
from __future__ import annotations

from fastapi import Request

from apu_tool.datos.almacen import Almacen


def get_almacen(request: Request) -> Almacen:
    return request.app.state.almacen
