"""Acceso a la tabla `carpeta` (vive en corridas.db). Implementa RepositorioCarpetas.

Guarda solo estructura (nombre + jerarquía de 2 niveles). Las reglas de negocio
(profundidad, borrado bloqueado si no vacía) viven en servicio/carpetas.py; aquí
solo CRUD y conteos. La unicidad de hermanas la garantiza el índice ux_carpeta_hermanas.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from apu_tool import config
from apu_tool.nucleo.models import Carpeta


class CarpetasDB:
    """Backend SQLite de carpetas. Comparte el archivo corridas.db con CorridasDB."""

    def __init__(self, path: Path | str = config.CORRIDAS_DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _fila(self, r: sqlite3.Row) -> Carpeta:
        return Carpeta(id=r["id"], nombre=r["nombre"], parent_id=r["parent_id"],
                       creada_en=r["creada_en"], creado_por=r["creado_por"])

    def crear(self, nombre: str, parent_id: Optional[int] = None,
              creado_por: Optional[str] = None, conn: Optional[sqlite3.Connection] = None) -> int:
        import datetime as _dt
        creada_en = _dt.datetime.now().isoformat(timespec="seconds")
        sql = ("INSERT INTO carpeta (nombre, parent_id, creada_en, creado_por) "
               "VALUES (?,?,?,?)")
        params = (nombre, parent_id, creada_en, creado_por)
        if conn is not None:
            return int(conn.execute(sql, params).lastrowid)
        with self.connect() as c:
            return int(c.execute(sql, params).lastrowid)

    def get(self, carpeta_id: int) -> Optional[Carpeta]:
        with self.connect() as conn:
            r = conn.execute("SELECT * FROM carpeta WHERE id=?", (int(carpeta_id),)).fetchone()
        return self._fila(r) if r else None

    def listar(self) -> list[Carpeta]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM carpeta ORDER BY parent_id IS NOT NULL, nombre").fetchall()
        return [self._fila(r) for r in rows]

    def renombrar(self, carpeta_id: int, nombre: str,
                  conn: Optional[sqlite3.Connection] = None) -> None:
        sql = "UPDATE carpeta SET nombre=? WHERE id=?"
        params = (nombre, int(carpeta_id))
        if conn is not None:
            conn.execute(sql, params)
            return
        with self.connect() as c:
            c.execute(sql, params)

    def mover(self, carpeta_id: int, parent_id: Optional[int],
              conn: Optional[sqlite3.Connection] = None) -> None:
        sql = "UPDATE carpeta SET parent_id=? WHERE id=?"
        params = (parent_id, int(carpeta_id))
        if conn is not None:
            conn.execute(sql, params)
            return
        with self.connect() as c:
            c.execute(sql, params)

    def eliminar(self, carpeta_id: int, conn: Optional[sqlite3.Connection] = None) -> bool:
        sql = "DELETE FROM carpeta WHERE id=?"
        if conn is not None:
            return conn.execute(sql, (int(carpeta_id),)).rowcount > 0
        with self.connect() as c:
            return c.execute(sql, (int(carpeta_id),)).rowcount > 0

    def contar_hijas(self, carpeta_id: int) -> int:
        with self.connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM carpeta WHERE parent_id=?",
                                (int(carpeta_id),)).fetchone()[0]

    def contar_corridas(self, carpeta_id: int) -> int:
        with self.connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM corrida WHERE carpeta_id=?",
                                (int(carpeta_id),)).fetchone()[0]
