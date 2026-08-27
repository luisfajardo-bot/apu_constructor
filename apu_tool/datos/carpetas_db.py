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
from apu_tool.nucleo.models import AjusteProyecto, Carpeta, ParametrosProyecto


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

    # ---- parámetros de transporte del proyecto ----
    def get_parametros(self, carpeta_id: int) -> Optional[ParametrosProyecto]:
        with self.connect() as conn:
            r = conn.execute("SELECT * FROM proyecto_parametros WHERE carpeta_id=?",
                             (int(carpeta_id),)).fetchone()
        if r is None:
            return None
        return ParametrosProyecto(
            carpeta_id=r["carpeta_id"], km_botadero=r["km_botadero"],
            km_mezclas=r["km_mezclas"], km_granulares=r["km_granulares"],
            peaje_aplica=None if r["peaje_aplica"] is None else bool(r["peaje_aplica"]),
            peaje_valor=r["peaje_valor"], actualizado_en=r["actualizado_en"] or "",
            actualizado_por=r["actualizado_por"])

    def set_parametros(self, params: ParametrosProyecto, conn=None,
                       actualizado_por: Optional[str] = None) -> None:
        import datetime as _dt
        ahora = _dt.datetime.now().isoformat(timespec="seconds")
        sql = ("INSERT OR REPLACE INTO proyecto_parametros "
               "(carpeta_id, km_botadero, km_mezclas, km_granulares, peaje_aplica, "
               " peaje_valor, actualizado_en, actualizado_por) VALUES (?,?,?,?,?,?,?,?)")
        p = (int(params.carpeta_id), params.km_botadero, params.km_mezclas,
             params.km_granulares,
             None if params.peaje_aplica is None else int(params.peaje_aplica),
             params.peaje_valor, ahora, actualizado_por or params.actualizado_por)
        if conn is not None:
            conn.execute(sql, p)
            return
        with self.connect() as c:
            c.execute(sql, p)

    # ---- ajustes puntuales del proyecto ----
    def _fila_ajuste(self, r) -> AjusteProyecto:
        return AjusteProyecto(
            id=r["id"], carpeta_id=r["carpeta_id"], apu_codigo=r["apu_codigo"],
            shift=r["shift"], accion=r["accion"], insumo_codigo=r["insumo_codigo"],
            insumo_nombre=r["insumo_nombre"] or "", unidad=r["unidad"] or "",
            rendimiento=r["rendimiento"],
            insumo_nuevo_codigo=r["insumo_nuevo_codigo"] or "",
            insumo_nuevo_nombre=r["insumo_nuevo_nombre"] or "",
            tipo=r["tipo"] or "insumo", ref_shift=r["ref_shift"] or "",
            nota=r["nota"] or "", creado_en=r["creado_en"] or "",
            creado_por=r["creado_por"])

    def listar_ajustes(self, carpeta_id: int) -> list[AjusteProyecto]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM proyecto_ajuste WHERE carpeta_id=? "
                "ORDER BY apu_codigo, shift, accion, insumo_codigo",
                (int(carpeta_id),)).fetchall()
        return [self._fila_ajuste(r) for r in rows]

    def crear_ajuste(self, ajuste: AjusteProyecto, conn=None,
                     creado_por: Optional[str] = None) -> int:
        import datetime as _dt
        creado_en = _dt.datetime.now().isoformat(timespec="seconds")
        # UPSERT explícito (no INSERT OR REPLACE): ante conflicto por la UNIQUE, un
        # REPLACE borra la fila e inserta otra con rowid NUEVO, así que el id que la
        # UI guardó quedaría colgado y su borrado fallaría en silencio. El DO UPDATE
        # conserva el id, igual que el `ON CONFLICT ... RETURNING id` del espejo
        # Postgres: los dos backends deben devolver el mismo id para el mismo ajuste.
        sql = ("INSERT INTO proyecto_ajuste "
               "(carpeta_id, apu_codigo, shift, accion, insumo_codigo, insumo_nombre, "
               " unidad, rendimiento, insumo_nuevo_codigo, insumo_nuevo_nombre, tipo, "
               " ref_shift, nota, creado_en, creado_por) "
               "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
               "ON CONFLICT (carpeta_id, apu_codigo, shift, accion, insumo_codigo) "
               "DO UPDATE SET insumo_nombre=excluded.insumo_nombre, "
               "unidad=excluded.unidad, rendimiento=excluded.rendimiento, "
               "insumo_nuevo_codigo=excluded.insumo_nuevo_codigo, "
               "insumo_nuevo_nombre=excluded.insumo_nuevo_nombre, "
               "tipo=excluded.tipo, ref_shift=excluded.ref_shift, nota=excluded.nota "
               "RETURNING id")
        p = (int(ajuste.carpeta_id), ajuste.apu_codigo, ajuste.shift, ajuste.accion,
             ajuste.insumo_codigo, ajuste.insumo_nombre, ajuste.unidad,
             ajuste.rendimiento, ajuste.insumo_nuevo_codigo,
             ajuste.insumo_nuevo_nombre, ajuste.tipo or "insumo", ajuste.ref_shift,
             ajuste.nota, creado_en, creado_por or ajuste.creado_por)
        if conn is not None:
            return int(conn.execute(sql, p).fetchone()["id"])
        with self.connect() as c:
            return int(c.execute(sql, p).fetchone()["id"])

    def borrar_ajuste(self, carpeta_id: int, ajuste_id: int, conn=None) -> bool:
        sql = "DELETE FROM proyecto_ajuste WHERE carpeta_id=? AND id=?"
        p = (int(carpeta_id), int(ajuste_id))
        if conn is not None:
            return conn.execute(sql, p).rowcount > 0
        with self.connect() as c:
            return c.execute(sql, p).rowcount > 0
