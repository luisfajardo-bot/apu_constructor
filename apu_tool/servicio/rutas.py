"""Endpoints de la API. Delgados: validan y delegan en apu_tool.servicio.corridas."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Optional

import httpx
from fastapi import (APIRouter, Depends, File, Form, HTTPException, UploadFile)
from fastapi.responses import FileResponse, StreamingResponse

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.dominio.licitacion import read_licitacion
from apu_tool.dominio.pipeline import ensure_seeded, generate_sample
from apu_tool.servicio import apus as apus_svc
from apu_tool.servicio import autoria
from apu_tool.servicio import corridas as svc
from apu_tool.servicio import insumos as insumos_svc
from apu_tool.servicio import usuarios as usuarios_svc
from apu_tool.servicio.auth import requiere_rol
from apu_tool.servicio.dependencias import get_almacen
from apu_tool.servicio.esquemas import (
    ApuNuevoIn, CambiosIn, ConfirmarIn, EstadoIn, InsumoNuevoIn, RolIn, StatusOut,
    TransformarIn, UsuarioInvitarIn)
from apu_tool.servicio.supabase_admin import AdminSupabase, AdminSupabaseHTTP

router = APIRouter()


def get_admin_supabase() -> AdminSupabase:
    return AdminSupabaseHTTP()

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/status", response_model=StatusOut)
def status(alm: Almacen = Depends(get_almacen)):
    c = alm.counts()
    return StatusOut(insumos=c.get("insumos", 0), apus=c.get("apus", 0),
                     ia=config.ai_available())


@router.get("/corridas")
def listar_corridas(alm: Almacen = Depends(get_almacen)):
    return svc.listar_corridas(alm)


@router.delete("/corridas/{cid}")
def eliminar_corrida(cid: int, alm: Almacen = Depends(get_almacen)):
    if not svc.eliminar_corrida(alm, cid):
        raise HTTPException(status_code=404, detail="Corrida no encontrada.")
    return {"eliminada": cid}


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
        items = read_licitacion(tmp_path, default_shift=turno, require_turno=True)
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


def _event_stream(gen):
    """Serializa los eventos del generador como SSE; cualquier fallo a mitad -> event: error."""
    try:
        for evento, payload in gen:
            yield f"event: {evento}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
    except Exception as e:  # nunca dejar el stream a medias sin avisar
        yield f"event: error\ndata: {json.dumps({'detail': str(e)}, ensure_ascii=False)}\n\n"


@router.post("/corridas/stream")
async def crear_corrida_stream(turno: str = Form(config.SHIFT_DIURNO),
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
        items = read_licitacion(tmp_path, default_shift=turno, require_turno=True)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        os.unlink(tmp_path)
    if not items:
        raise HTTPException(status_code=400, detail="La lista no tiene ítems legibles.")
    gen = svc.construir_corrida_stream(alm, archivo.filename or "licitacion", items, turno, use_ai)
    return StreamingResponse(_event_stream(gen), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


@router.post("/sample/stream")
def crear_sample_stream(alm: Almacen = Depends(get_almacen)):
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
    gen = svc.construir_corrida_stream(alm, "ejemplo.xlsx", items, config.SHIFT_DIURNO, False)
    return StreamingResponse(_event_stream(gen), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


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
                   fuente: Optional[str] = None, clasificacion: Optional[str] = None,
                   limit: int = 100, offset: int = 0,
                   alm: Almacen = Depends(get_almacen)):
    return insumos_svc.listar(alm, q, grupo, fuente, clasificacion, limit, offset)


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


# ---- autoría: crear / importar insumos y APUs ----
@router.post("/insumos/crear")
def crear_insumo(body: InsumoNuevoIn, alm: Almacen = Depends(get_almacen)):
    try:
        return autoria.crear_insumo(alm, body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/insumos/importar-crear/preview")
async def insumos_importar_crear_preview(archivo: UploadFile = File(...),
                                         alm: Almacen = Depends(get_almacen)):
    contenido = await archivo.read()
    try:
        return autoria.preview_importar_insumos(alm, contenido, archivo.filename or "insumos.xlsx")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/insumos/importar-crear")
async def insumos_importar_crear(archivo: UploadFile = File(...),
                                 alm: Almacen = Depends(get_almacen)):
    contenido = await archivo.read()
    try:
        return autoria.aplicar_importar_insumos(alm, contenido, archivo.filename or "insumos.xlsx")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/apus")
def listar_apus(q: Optional[str] = None, grupo: Optional[str] = None,
                turno: Optional[str] = None, limit: int = 100, offset: int = 0,
                alm: Almacen = Depends(get_almacen)):
    return apus_svc.listar(alm, q, grupo, turno, limit, offset)


@router.post("/apus/crear")
def crear_apu(body: ApuNuevoIn, alm: Almacen = Depends(get_almacen)):
    try:
        return autoria.crear_apu(alm, body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/apus/importar/preview")
async def apus_importar_preview(archivo: UploadFile = File(...),
                                alm: Almacen = Depends(get_almacen)):
    contenido = await archivo.read()
    try:
        return autoria.preview_importar_apus(alm, contenido)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/apus/importar")
async def apus_importar(archivo: UploadFile = File(...),
                        alm: Almacen = Depends(get_almacen)):
    contenido = await archivo.read()
    try:
        return autoria.aplicar_importar_apus(alm, contenido)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/apus/{codigo}/{turno}")
def detalle_apu(codigo: str, turno: str, alm: Almacen = Depends(get_almacen)):
    d = apus_svc.detalle(alm, codigo, turno)
    if d is None:
        raise HTTPException(status_code=404, detail="APU no encontrado.")
    return d


# ---- usuarios (solo Admin) ----
@router.get("/usuarios")
def usuarios_listar(alm: Almacen = Depends(get_almacen),
                    _: object = Depends(requiere_rol("admin"))):
    return usuarios_svc.listar(alm)


@router.post("/usuarios/invitar")
def usuarios_invitar(body: UsuarioInvitarIn, alm: Almacen = Depends(get_almacen),
                     admin=Depends(get_admin_supabase),
                     _: object = Depends(requiere_rol("admin"))):
    try:
        return usuarios_svc.invitar(alm, admin, body.email, body.rol, body.nombre)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPStatusError:
        raise HTTPException(status_code=400,
                            detail="No se pudo invitar (¿el email ya existe?).")


@router.patch("/usuarios/{user_id}/rol")
def usuarios_cambiar_rol(user_id: str, body: RolIn,
                         alm: Almacen = Depends(get_almacen),
                         actor=Depends(requiere_rol("admin"))):
    try:
        return usuarios_svc.cambiar_rol(alm, actor, user_id, body.rol)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/usuarios/{user_id}/estado")
def usuarios_cambiar_estado(user_id: str, body: EstadoIn,
                            alm: Almacen = Depends(get_almacen),
                            actor=Depends(requiere_rol("admin"))):
    try:
        return usuarios_svc.cambiar_estado(alm, actor, user_id, body.estado)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
