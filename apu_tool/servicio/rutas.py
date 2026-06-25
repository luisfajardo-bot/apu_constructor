"""Endpoints de la API. Delgados: validan y delegan en apu_tool.servicio.corridas."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import (APIRouter, Depends, File, Form, HTTPException, UploadFile)
from fastapi.responses import FileResponse

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.dominio.licitacion import read_licitacion
from apu_tool.dominio.pipeline import ensure_seeded, generate_sample
from apu_tool.servicio import corridas as svc
from apu_tool.servicio import insumos as insumos_svc
from apu_tool.servicio.dependencias import get_almacen
from apu_tool.servicio.esquemas import CambiosIn, ConfirmarIn, StatusOut, TransformarIn

router = APIRouter()

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/status", response_model=StatusOut)
def status(alm: Almacen = Depends(get_almacen)):
    c = alm.counts()
    return StatusOut(insumos=c.get("insumos", 0), apus=c.get("apus", 0),
                     ia=config.ai_available())


@router.post("/corridas")
async def crear_corrida(turno: str = Form(config.SHIFT_DIURNO),
                        use_ai: Optional[bool] = Form(None),
                        archivo: UploadFile = File(...),
                        alm: Almacen = Depends(get_almacen)):
    if alm.counts().get("apus", 0) == 0:
        ensure_seeded()
    suf = Path(archivo.filename or "lic.xlsx").suffix or ".xlsx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suf) as tmp:
        tmp.write(await archivo.read())
        tmp_path = tmp.name
    try:
        items = read_licitacion(tmp_path, default_shift=turno)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        os.unlink(tmp_path)
    if not items:
        raise HTTPException(status_code=400, detail="La lista no tiene ítems legibles.")
    cid = svc.construir_corrida(alm, archivo.filename or "licitacion", items, turno, use_ai)
    return {"id": cid, "resumen": svc.vista_corrida(alm, cid)["totales"]}


@router.post("/sample")
def crear_sample(alm: Almacen = Depends(get_almacen)):
    if alm.counts().get("apus", 0) == 0:
        ensure_seeded()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        sample_path = tmp.name
    try:
        generate_sample(out_path=Path(sample_path), alm=alm)
        items = read_licitacion(sample_path, default_shift=config.SHIFT_DIURNO)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        os.unlink(sample_path)
    if not items:
        raise HTTPException(status_code=400, detail="El ejemplo generado no tiene ítems legibles.")
    cid = svc.construir_corrida(alm, "ejemplo.xlsx", items, config.SHIFT_DIURNO, False)
    return {"id": cid, "resumen": svc.vista_corrida(alm, cid)["totales"]}


@router.get("/corridas/{cid}")
def get_corrida(cid: int, alm: Almacen = Depends(get_almacen)):
    v = svc.vista_corrida(alm, cid)
    if v is None:
        raise HTTPException(status_code=404, detail="Corrida no encontrada.")
    return v


@router.get("/corridas/{cid}/items/{seq}")
def get_item(cid: int, seq: int, alm: Almacen = Depends(get_almacen)):
    d = svc.detalle_item(alm, cid, seq)
    if d is None:
        raise HTTPException(status_code=404, detail="Ítem no encontrado.")
    return d


@router.post("/corridas/{cid}/items/{seq}/confirmar")
def confirmar(cid: int, seq: int, body: ConfirmarIn,
              alm: Almacen = Depends(get_almacen)):
    v = svc.confirmar_item(alm, cid, seq, body.apu_codigo, body.shift)
    if v is None:
        raise HTTPException(status_code=404, detail="Ítem no encontrado.")
    return v


@router.get("/corridas/{cid}/cuadro")
def cuadro(cid: int, alm: Almacen = Depends(get_almacen)):
    out = svc.generar_cuadro(alm, cid)
    if out is None:
        raise HTTPException(status_code=404, detail="Corrida no encontrada.")
    return FileResponse(str(out), filename=out.name, media_type=_XLSX)


@router.get("/insumos")
def listar_insumos(q: Optional[str] = None, grupo: Optional[str] = None,
                   fuente: Optional[str] = None, limit: int = 100, offset: int = 0,
                   alm: Almacen = Depends(get_almacen)):
    return insumos_svc.listar(alm, q, grupo, fuente, limit, offset)


@router.get("/insumos/grupos")
def insumos_grupos(alm: Almacen = Depends(get_almacen)):
    return alm.precios.grupos()


@router.get("/insumos/fuentes")
def insumos_fuentes(alm: Almacen = Depends(get_almacen)):
    return alm.precios.fuentes()


@router.get("/insumos/{insumo_id}")
def insumo_detalle(insumo_id: int, alm: Almacen = Depends(get_almacen)):
    d = insumos_svc.detalle(alm, insumo_id)
    if d is None:
        raise HTTPException(status_code=404, detail="Insumo no encontrado.")
    return d


@router.post("/insumos/cambios")
def insumos_cambios(body: CambiosIn, alm: Almacen = Depends(get_almacen)):
    return insumos_svc.aplicar_cambios(alm, [c.model_dump() for c in body.cambios])


@router.post("/insumos/importar/preview")
async def insumos_importar_preview(archivo: UploadFile = File(...),
                                   alm: Almacen = Depends(get_almacen)):
    contenido = await archivo.read()
    try:
        return insumos_svc.preview_import(alm, contenido, archivo.filename or "lista.xlsx")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/insumos/transformar/preview")
def insumos_transformar_preview(body: TransformarIn, alm: Almacen = Depends(get_almacen)):
    try:
        return insumos_svc.preview_transformar(alm, body.filtro, body.operacion)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
