"""Backend Postgres de carpetas. Implementa RepositorioCarpetas. Port de carpetas_db.py."""
from __future__ import annotations

import datetime as _dt
from typing import Optional

from apu_tool.datos.pg.conexion import Conexion
from apu_tool.nucleo.models import AjusteProyecto, Carpeta, ParametrosProyecto


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

    # ---- parámetros de transporte del proyecto ----
    def get_parametros(self, carpeta_id: int) -> Optional[ParametrosProyecto]:
        with self.cx.connection() as conn:
            r = conn.execute("SELECT * FROM corridas.proyecto_parametros "
                             "WHERE carpeta_id=%s", (int(carpeta_id),)).fetchone()
        if r is None:
            return None
        def bool_o_none(v):
            return None if v is None else bool(v)
        return ParametrosProyecto(
            carpeta_id=r["carpeta_id"], km_botadero=r["km_botadero"],
            km_mezclas=r["km_mezclas"], km_granulares=r["km_granulares"],
            peaje_botadero_aplica=bool_o_none(r["peaje_botadero_aplica"]),
            peaje_botadero_valor=r["peaje_botadero_valor"],
            peaje_mezclas_aplica=bool_o_none(r["peaje_mezclas_aplica"]),
            peaje_mezclas_valor=r["peaje_mezclas_valor"],
            peaje_granulares_aplica=bool_o_none(r["peaje_granulares_aplica"]),
            peaje_granulares_valor=r["peaje_granulares_valor"],
            actualizado_en=r["actualizado_en"] or "",
            actualizado_por=r["actualizado_por"])

    def set_parametros(self, params: ParametrosProyecto, conn=None,
                       actualizado_por: Optional[str] = None) -> None:
        ahora = _dt.datetime.now().isoformat(timespec="seconds")
        sql = ("INSERT INTO corridas.proyecto_parametros "
               "(carpeta_id, km_botadero, km_mezclas, km_granulares, "
               " peaje_botadero_aplica, peaje_botadero_valor, "
               " peaje_mezclas_aplica, peaje_mezclas_valor, "
               " peaje_granulares_aplica, peaje_granulares_valor, "
               " actualizado_en, actualizado_por) "
               "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
               "ON CONFLICT (carpeta_id) DO UPDATE SET "
               "km_botadero=EXCLUDED.km_botadero, km_mezclas=EXCLUDED.km_mezclas, "
               "km_granulares=EXCLUDED.km_granulares, "
               "peaje_botadero_aplica=EXCLUDED.peaje_botadero_aplica, "
               "peaje_botadero_valor=EXCLUDED.peaje_botadero_valor, "
               "peaje_mezclas_aplica=EXCLUDED.peaje_mezclas_aplica, "
               "peaje_mezclas_valor=EXCLUDED.peaje_mezclas_valor, "
               "peaje_granulares_aplica=EXCLUDED.peaje_granulares_aplica, "
               "peaje_granulares_valor=EXCLUDED.peaje_granulares_valor, "
               "actualizado_en=EXCLUDED.actualizado_en, "
               "actualizado_por=EXCLUDED.actualizado_por")
        def int_o_none(v):
            return None if v is None else int(v)
        p = (int(params.carpeta_id), params.km_botadero, params.km_mezclas,
             params.km_granulares,
             int_o_none(params.peaje_botadero_aplica), params.peaje_botadero_valor,
             int_o_none(params.peaje_mezclas_aplica), params.peaje_mezclas_valor,
             int_o_none(params.peaje_granulares_aplica), params.peaje_granulares_valor,
             ahora, actualizado_por or params.actualizado_por)
        if conn is not None:
            conn.execute(sql, p)
            return
        with self.cx.connection() as c:
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
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM corridas.proyecto_ajuste WHERE carpeta_id=%s "
                "ORDER BY apu_codigo, shift, accion, insumo_codigo",
                (int(carpeta_id),)).fetchall()
        return [self._fila_ajuste(r) for r in rows]

    def crear_ajuste(self, ajuste: AjusteProyecto, conn=None,
                     creado_por: Optional[str] = None) -> int:
        creado_en = _dt.datetime.now().isoformat(timespec="seconds")
        sql = ("INSERT INTO corridas.proyecto_ajuste "
               "(carpeta_id, apu_codigo, shift, accion, insumo_codigo, insumo_nombre, "
               " unidad, rendimiento, insumo_nuevo_codigo, insumo_nuevo_nombre, tipo, "
               " ref_shift, nota, creado_en, creado_por) "
               "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
               "ON CONFLICT (carpeta_id, apu_codigo, shift, accion, insumo_codigo) "
               "DO UPDATE SET insumo_nombre=EXCLUDED.insumo_nombre, "
               "unidad=EXCLUDED.unidad, rendimiento=EXCLUDED.rendimiento, "
               "insumo_nuevo_codigo=EXCLUDED.insumo_nuevo_codigo, "
               "insumo_nuevo_nombre=EXCLUDED.insumo_nuevo_nombre, "
               "tipo=EXCLUDED.tipo, ref_shift=EXCLUDED.ref_shift, nota=EXCLUDED.nota "
               "RETURNING id")
        p = (int(ajuste.carpeta_id), ajuste.apu_codigo, ajuste.shift, ajuste.accion,
             ajuste.insumo_codigo, ajuste.insumo_nombre, ajuste.unidad,
             ajuste.rendimiento, ajuste.insumo_nuevo_codigo,
             ajuste.insumo_nuevo_nombre, ajuste.tipo or "insumo", ajuste.ref_shift,
             ajuste.nota, creado_en, creado_por or ajuste.creado_por)
        if conn is not None:
            return int(conn.execute(sql, p).fetchone()["id"])
        with self.cx.connection() as c:
            return int(c.execute(sql, p).fetchone()["id"])

    def borrar_ajuste(self, carpeta_id: int, ajuste_id: int, conn=None) -> bool:
        sql = "DELETE FROM corridas.proyecto_ajuste WHERE carpeta_id=%s AND id=%s"
        p = (int(carpeta_id), int(ajuste_id))
        if conn is not None:
            return conn.execute(sql, p).rowcount > 0
        with self.cx.connection() as c:
            return c.execute(sql, p).rowcount > 0
