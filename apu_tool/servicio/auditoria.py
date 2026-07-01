"""Servicio de auditoría: helper transaccional para registrar eventos y lectura paginada.

`registrar_auditoria` escribe la fila de auditoría SOBRE la conexión de la unidad de
trabajo (misma transacción que la mutación → sin best-effort). NO ve la IA (Invariante #1).
"""
from __future__ import annotations

import datetime as dt
import re
import uuid
from typing import Optional

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import EventoAuditoria, Perfil

_FECHA_SOLA = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def nuevo_lote() -> str:
    """Id de lote para agrupar las filas de una misma operación por lote."""
    return uuid.uuid4().hex


def registrar_auditoria(alm: Almacen, conn, actor: Optional[Perfil], accion: str,
                        entidad_tipo: str, entidad_id, antes: Optional[dict] = None,
                        despues: Optional[dict] = None, contexto: Optional[dict] = None) -> None:
    ev = EventoAuditoria(
        ts=dt.datetime.now(dt.timezone.utc).isoformat(),
        rol=(actor.rol if actor else "sistema"),
        accion=accion, entidad_tipo=entidad_tipo, entidad_id=str(entidad_id),
        user_id=(actor.user_id if actor else None),
        user_email=(actor.email if actor else None),
        antes=antes, despues=despues, contexto=contexto)
    alm.auditoria.registrar(conn, ev)


def listar(alm: Almacen, *, user_id: Optional[str] = None, accion: Optional[str] = None,
           entidad_tipo: Optional[str] = None, desde: Optional[str] = None,
           hasta: Optional[str] = None, lote_id: Optional[str] = None,
           limit: int = 100, offset: int = 0) -> dict:
    # `ts` se guarda como timestamp ISO-8601 completo (con hora), pero el visor manda
    # `hasta` como fecha sola (p.ej. "2026-07-01"). Comparar lexicográficamente una
    # fecha sola contra un timestamp completo excluye todo el día ("...T10:00:00" no es
    # <= "2026-07-01"). Por eso, si `hasta` es solo fecha, la extendemos al final del día
    # (23:59:59.999999) para que el límite superior sea inclusivo de todo el día. Si ya
    # trae hora, se respeta tal cual.
    if hasta and _FECHA_SOLA.match(hasta):
        hasta = f"{hasta}T23:59:59.999999+00:00"
    items, total = alm.auditoria.listar(
        user_id=user_id, accion=accion, entidad_tipo=entidad_tipo, desde=desde,
        hasta=hasta, lote_id=lote_id, limit=limit, offset=offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}
