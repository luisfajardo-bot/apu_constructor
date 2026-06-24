"""Endpoints de la API. Delgados: validan y delegan en apu_tool.servicio.corridas."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.servicio.dependencias import get_almacen
from apu_tool.servicio.esquemas import StatusOut

router = APIRouter()


@router.get("/status", response_model=StatusOut)
def status(alm: Almacen = Depends(get_almacen)):
    c = alm.counts()
    return StatusOut(insumos=c.get("insumos", 0), apus=c.get("apus", 0),
                     ia=config.ai_available())
