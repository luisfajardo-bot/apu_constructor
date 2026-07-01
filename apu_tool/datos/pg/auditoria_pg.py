"""Backend Postgres de auditoría (seguridad.auditoria). Implementa RepositorioAuditoria.

`registrar` escribe sobre la conexión de la unidad de trabajo (compartida con la
mutación). Las columnas JSON son jsonb (se adaptan con psycopg Jsonb / se leen como dict).
"""
from __future__ import annotations

from typing import Optional

from psycopg.types.json import Jsonb

from apu_tool.datos.pg.conexion import Conexion
from apu_tool.nucleo.models import EventoAuditoria


def _jb(x):
    return None if x is None else Jsonb(x)


class AuditoriaPg:
    def __init__(self, cx: Conexion):
        self.cx = cx

    def registrar(self, conn, ev: EventoAuditoria) -> None:
        conn.execute(
            "INSERT INTO seguridad.auditoria "
            "(ts, user_id, user_email, rol, accion, entidad_tipo, entidad_id, antes, despues, contexto) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (ev.ts, ev.user_id, ev.user_email, ev.rol, ev.accion, ev.entidad_tipo,
             str(ev.entidad_id), _jb(ev.antes), _jb(ev.despues), _jb(ev.contexto)))

    def _fila(self, r) -> dict:
        # psycopg (dict_row) ya devuelve jsonb como dict/None y ts como str (columna TEXT).
        return {"id": r["id"], "ts": r["ts"], "user_id": r["user_id"],
                "user_email": r["user_email"], "rol": r["rol"], "accion": r["accion"],
                "entidad_tipo": r["entidad_tipo"], "entidad_id": r["entidad_id"],
                "antes": r["antes"], "despues": r["despues"], "contexto": r["contexto"]}

    def listar(self, *, user_id: Optional[str] = None, accion: Optional[str] = None,
               entidad_tipo: Optional[str] = None, desde: Optional[str] = None,
               hasta: Optional[str] = None, lote_id: Optional[str] = None,
               limit: int = 100, offset: int = 0) -> tuple[list[dict], int]:
        where, params = [], []
        if user_id:
            where.append("user_id = %s"); params.append(user_id)
        if accion:
            where.append("accion = %s"); params.append(accion)
        if entidad_tipo:
            where.append("entidad_tipo = %s"); params.append(entidad_tipo)
        if desde:
            where.append("ts >= %s"); params.append(desde)
        if hasta:
            where.append("ts <= %s"); params.append(hasta)
        if lote_id:
            where.append("contexto->>'lote_id' = %s"); params.append(lote_id)
        wsql = (" WHERE " + " AND ".join(where)) if where else ""
        with self.cx.connection() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS n FROM seguridad.auditoria{wsql}", params).fetchone()["n"]
            rows = conn.execute(
                f"SELECT * FROM seguridad.auditoria{wsql} ORDER BY ts DESC, id DESC "
                f"LIMIT %s OFFSET %s", params + [int(limit), int(offset)]).fetchall()
        return [self._fila(r) for r in rows], int(total)
