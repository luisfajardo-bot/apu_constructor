"""Acceso SQLite a la tabla `auditoria` (vive en seguridad.db, junto a perfiles).

Implementa RepositorioAuditoria. `registrar` NUNCA abre su propia conexión: escribe
sobre la conexión de la unidad de trabajo (transaccional con la mutación auditada).
La tabla se nombra sin calificar; cuando la UdT ATTACHea seguridad.db a la conexión
de otro dominio, `auditoria` resuelve a la única base que la contiene.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from apu_tool import config
from apu_tool.nucleo.models import EventoAuditoria


def _dumps(x) -> Optional[str]:
    return None if x is None else json.dumps(x, ensure_ascii=False)


def _loads(x):
    return None if x is None else json.loads(x)


class AuditoriaDB:
    def __init__(self, path: Path | str = config.DATA_DIR / "seguridad.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def registrar(self, conn: sqlite3.Connection, ev: EventoAuditoria) -> None:
        # `auditoria` sin calificar: resuelve a seguridad.db (única base con esa tabla),
        # incluso cuando la UdT ATTACHea seguridad a otra base. Depende de que NINGUNA
        # tabla de dominio se llame `auditoria`.
        conn.execute(
            "INSERT INTO auditoria "
            "(ts, user_id, user_email, rol, accion, entidad_tipo, entidad_id, antes, despues, contexto) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ev.ts, ev.user_id, ev.user_email, ev.rol, ev.accion, ev.entidad_tipo,
             str(ev.entidad_id), _dumps(ev.antes), _dumps(ev.despues), _dumps(ev.contexto)))

    def _fila(self, r) -> dict:
        return {"id": r["id"], "ts": r["ts"], "user_id": r["user_id"],
                "user_email": r["user_email"], "rol": r["rol"], "accion": r["accion"],
                "entidad_tipo": r["entidad_tipo"], "entidad_id": r["entidad_id"],
                "antes": _loads(r["antes"]), "despues": _loads(r["despues"]),
                "contexto": _loads(r["contexto"])}

    def listar(self, *, user_id: Optional[str] = None, accion: Optional[str] = None,
               entidad_tipo: Optional[str] = None, desde: Optional[str] = None,
               hasta: Optional[str] = None, lote_id: Optional[str] = None,
               limit: int = 100, offset: int = 0) -> tuple[list[dict], int]:
        where, params = [], []
        if user_id:
            where.append("user_id = ?"); params.append(user_id)
        if accion:
            where.append("accion = ?"); params.append(accion)
        if entidad_tipo:
            where.append("entidad_tipo = ?"); params.append(entidad_tipo)
        if desde:
            where.append("ts >= ?"); params.append(desde)
        if hasta:
            where.append("ts <= ?"); params.append(hasta)
        if lote_id:
            where.append("json_extract(contexto, '$.lote_id') = ?"); params.append(lote_id)
        wsql = (" WHERE " + " AND ".join(where)) if where else ""
        with self.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM auditoria{wsql}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM auditoria{wsql} ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?",
                params + [int(limit), int(offset)]).fetchall()
        return [self._fila(r) for r in rows], int(total)
