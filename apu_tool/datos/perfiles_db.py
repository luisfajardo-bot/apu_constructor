"""Acceso SQLite a la tabla perfiles (identidad + rol). Implementa RepositorioPerfiles."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from apu_tool import config
from apu_tool.nucleo.models import Perfil

SCHEMA_PATH = config.PROJECT_ROOT / "db" / "seguridad.sql"


class PerfilesDB:
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

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    def reset(self) -> None:
        with self.connect() as conn:
            # auditoria comparte este archivo con perfiles: un reset completo la limpia también.
            for t in ("auditoria", "perfiles"):
                conn.execute(f"DROP TABLE IF EXISTS {t}")
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    def _fila(self, r) -> Perfil:
        return Perfil(user_id=r["user_id"], email=r["email"], rol=r["rol"],
                      estado=r["estado"], nombre=r["nombre"] or "",
                      creado_en=r["creado_en"] or "")

    def get(self, user_id: str) -> Optional[Perfil]:
        with self.connect() as conn:
            r = conn.execute("SELECT * FROM perfiles WHERE user_id=?", (user_id,)).fetchone()
        return self._fila(r) if r else None

    def upsert(self, p: Perfil, conn=None) -> None:
        sql = ("INSERT INTO perfiles (user_id,email,rol,estado,nombre,creado_en) "
               "VALUES (?,?,?,?,?,?) "
               "ON CONFLICT(user_id) DO UPDATE SET email=excluded.email, rol=excluded.rol, "
               "estado=excluded.estado, nombre=excluded.nombre")
        params = (p.user_id, p.email, p.rol, p.estado, p.nombre, p.creado_en)
        if conn is not None:
            conn.execute(sql, params); return
        with self.connect() as c:
            c.execute(sql, params)

    def listar(self) -> list[Perfil]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM perfiles ORDER BY email").fetchall()
        return [self._fila(r) for r in rows]

    def set_rol(self, user_id: str, rol: str, conn=None) -> None:
        if conn is not None:
            conn.execute("UPDATE perfiles SET rol=? WHERE user_id=?", (rol, user_id)); return
        with self.connect() as c:
            c.execute("UPDATE perfiles SET rol=? WHERE user_id=?", (rol, user_id))

    def set_estado(self, user_id: str, estado: str, conn=None) -> None:
        if conn is not None:
            conn.execute("UPDATE perfiles SET estado=? WHERE user_id=?", (estado, user_id)); return
        with self.connect() as c:
            c.execute("UPDATE perfiles SET estado=? WHERE user_id=?", (estado, user_id))

    def contar_admins_activos(self) -> int:
        with self.connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM perfiles WHERE rol='admin' AND estado='activo'"
            ).fetchone()[0]

    _GUARD = ("NOT (rol='admin' AND estado='activo' AND "
              "(SELECT COUNT(*) FROM perfiles WHERE rol='admin' AND estado='activo') <= 1)")

    def set_rol_protegido(self, user_id: str, rol: str, conn=None) -> bool:
        sql = f"UPDATE perfiles SET rol=? WHERE user_id=? AND {self._GUARD}"
        if conn is not None:
            return conn.execute(sql, (rol, user_id)).rowcount > 0
        with self.connect() as c:
            return c.execute(sql, (rol, user_id)).rowcount > 0

    def set_estado_protegido(self, user_id: str, estado: str, conn=None) -> bool:
        sql = f"UPDATE perfiles SET estado=? WHERE user_id=? AND {self._GUARD}"
        if conn is not None:
            return conn.execute(sql, (estado, user_id)).rowcount > 0
        with self.connect() as c:
            return c.execute(sql, (estado, user_id)).rowcount > 0
