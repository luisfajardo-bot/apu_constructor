"""Acceso Postgres a seguridad.perfiles. Implementa RepositorioPerfiles. Port de perfiles_db."""
from __future__ import annotations

from typing import Optional

from apu_tool import config
from apu_tool.datos.pg.conexion import Conexion, ejecutar_script
from apu_tool.nucleo.models import Perfil

SCHEMA_PATH = config.PROJECT_ROOT / "db" / "pg" / "seguridad.sql"


class PerfilesPg:
    def __init__(self, cx: Conexion):
        self.cx = cx

    def init_schema(self) -> None:
        with self.cx.connection() as conn:
            ejecutar_script(conn, SCHEMA_PATH.read_text(encoding="utf-8"))

    def reset(self) -> None:
        with self.cx.connection() as conn:
            conn.execute("DROP SCHEMA IF EXISTS seguridad CASCADE")
            ejecutar_script(conn, SCHEMA_PATH.read_text(encoding="utf-8"))

    def _fila(self, r) -> Perfil:
        return Perfil(user_id=r["user_id"], email=r["email"], rol=r["rol"],
                      estado=r["estado"], nombre=r["nombre"] or "",
                      creado_en=r["creado_en"] or "")

    def get(self, user_id: str) -> Optional[Perfil]:
        with self.cx.connection() as conn:
            r = conn.execute("SELECT * FROM seguridad.perfiles WHERE user_id=%s",
                             (user_id,)).fetchone()
        return self._fila(r) if r else None

    def upsert(self, p: Perfil, conn=None) -> None:
        sql = ("INSERT INTO seguridad.perfiles (user_id,email,rol,estado,nombre,creado_en) "
               "VALUES (%s,%s,%s,%s,%s,%s) "
               "ON CONFLICT (user_id) DO UPDATE SET email=EXCLUDED.email, rol=EXCLUDED.rol, "
               "estado=EXCLUDED.estado, nombre=EXCLUDED.nombre")
        params = (p.user_id, p.email, p.rol, p.estado, p.nombre, p.creado_en)
        if conn is not None:
            conn.execute(sql, params); return
        with self.cx.connection() as c:
            c.execute(sql, params)

    def listar(self) -> list[Perfil]:
        with self.cx.connection() as conn:
            rows = conn.execute("SELECT * FROM seguridad.perfiles ORDER BY email").fetchall()
        return [self._fila(r) for r in rows]

    def set_rol(self, user_id: str, rol: str, conn=None) -> None:
        if conn is not None:
            conn.execute("UPDATE seguridad.perfiles SET rol=%s WHERE user_id=%s", (rol, user_id)); return
        with self.cx.connection() as c:
            c.execute("UPDATE seguridad.perfiles SET rol=%s WHERE user_id=%s", (rol, user_id))

    def set_estado(self, user_id: str, estado: str, conn=None) -> None:
        if conn is not None:
            conn.execute("UPDATE seguridad.perfiles SET estado=%s WHERE user_id=%s", (estado, user_id)); return
        with self.cx.connection() as c:
            c.execute("UPDATE seguridad.perfiles SET estado=%s WHERE user_id=%s", (estado, user_id))

    def contar_admins_activos(self) -> int:
        with self.cx.connection() as conn:
            return conn.execute(
                "SELECT COUNT(*) AS n FROM seguridad.perfiles "
                "WHERE rol='admin' AND estado='activo'").fetchone()["n"]
