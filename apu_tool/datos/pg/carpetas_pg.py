"""Backend Postgres de carpetas. Implementa RepositorioCarpetas. Port de carpetas_db.py."""
from __future__ import annotations

import datetime as _dt
from typing import Optional

from apu_tool.datos.pg.conexion import Conexion
from apu_tool.nucleo.models import Carpeta


class CarpetasPg:
    def __init__(self, cx: Conexion):
        self.cx = cx

    def _fila(self, r) -> Carpeta:
        return Carpeta(id=r["id"], nombre=r["nombre"], parent_id=r["parent_id"],
                       creada_en=r["creada_en"], creado_por=r["creado_por"])

    def crear(self, nombre: str, parent_id: Optional[int] = None,
              creado_por: Optional[str] = None, conn=None) -> int:
        creada_en = _dt.datetime.now().isoformat(timespec="seconds")
        sql = ("INSERT INTO corridas.carpeta (nombre, parent_id, creada_en, creado_por) "
               "VALUES (%s,%s,%s,%s) RETURNING id")
        params = (nombre, parent_id, creada_en, creado_por)
        if conn is not None:
            return int(conn.execute(sql, params).fetchone()["id"])
        with self.cx.connection() as c:
            return int(c.execute(sql, params).fetchone()["id"])

    def get(self, carpeta_id: int) -> Optional[Carpeta]:
        with self.cx.connection() as conn:
            r = conn.execute("SELECT * FROM corridas.carpeta WHERE id=%s",
                             (int(carpeta_id),)).fetchone()
        return self._fila(r) if r else None

    def listar(self) -> list[Carpeta]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM corridas.carpeta ORDER BY parent_id IS NOT NULL, nombre").fetchall()
        return [self._fila(r) for r in rows]

    def renombrar(self, carpeta_id: int, nombre: str, conn=None) -> None:
        sql = "UPDATE corridas.carpeta SET nombre=%s WHERE id=%s"
        params = (nombre, int(carpeta_id))
        if conn is not None:
            conn.execute(sql, params); return
        with self.cx.connection() as c:
            c.execute(sql, params)

    def mover(self, carpeta_id: int, parent_id: Optional[int], conn=None) -> None:
        sql = "UPDATE corridas.carpeta SET parent_id=%s WHERE id=%s"
        params = (parent_id, int(carpeta_id))
        if conn is not None:
            conn.execute(sql, params); return
        with self.cx.connection() as c:
            c.execute(sql, params)

    def eliminar(self, carpeta_id: int, conn=None) -> bool:
        sql = "DELETE FROM corridas.carpeta WHERE id=%s"
        if conn is not None:
            return conn.execute(sql, (int(carpeta_id),)).rowcount > 0
        with self.cx.connection() as c:
            return c.execute(sql, (int(carpeta_id),)).rowcount > 0

    def contar_hijas(self, carpeta_id: int) -> int:
        with self.cx.connection() as conn:
            return conn.execute("SELECT COUNT(*) AS n FROM corridas.carpeta WHERE parent_id=%s",
                                (int(carpeta_id),)).fetchone()["n"]

    def contar_corridas(self, carpeta_id: int) -> int:
        with self.cx.connection() as conn:
            return conn.execute("SELECT COUNT(*) AS n FROM corridas.corrida WHERE carpeta_id=%s",
                                (int(carpeta_id),)).fetchone()["n"]
