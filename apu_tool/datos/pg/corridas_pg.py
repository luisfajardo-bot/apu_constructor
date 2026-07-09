"""Backend Postgres de corridas. Implementa RepositorioCorridas. Port de corridas_db.py."""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Optional

import psycopg

from apu_tool import config
from apu_tool.datos.pg.conexion import Conexion, ejecutar_script
from apu_tool.datos.repositorio import CorridaEliminada
from apu_tool.nucleo.models import CorridaItemRow, CorridaMeta, LicitacionItem

SCHEMA_PATH = config.PROJECT_ROOT / "db" / "pg" / "corridas.sql"


class CorridasPg:
    def __init__(self, cx: Conexion):
        self.cx = cx

    def init_schema(self) -> None:
        self.cx.ejecutar_migracion(SCHEMA_PATH.read_text(encoding="utf-8"))

    def reset(self) -> None:
        with self.cx.connection() as conn:
            conn.execute("DROP SCHEMA IF EXISTS corridas CASCADE")
            ejecutar_script(conn, SCHEMA_PATH.read_text(encoding="utf-8"))

    _INSERT_ITEM_SQL = (
        "INSERT INTO corridas.corrida_item "
        "(corrida_id, seq, item_json, status, apu_codigo, apu_nombre, unidad, "
        " shift, origen, confianza, explicacion, componentes_json, candidatos_json) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)")

    @staticmethod
    def _item_tuple(corrida_id: int, it: CorridaItemRow) -> tuple:
        return (corrida_id, it.seq, json.dumps(asdict(it.item), ensure_ascii=False),
                it.status, it.apu_codigo, it.apu_nombre, it.unidad, it.shift,
                it.origen, it.confianza, it.explicacion,
                json.dumps(it.componentes, ensure_ascii=False),
                json.dumps(it.candidatos, ensure_ascii=False))

    def _insert_corrida(self, conn, meta: CorridaMeta) -> int:
        cur = conn.execute(
            "INSERT INTO corridas.corrida (creada_en, archivo, turno_def, use_ai, estado, "
            "cuadro_path, duracion_ms, modo, carpeta_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (meta.creada_en, meta.archivo, meta.turno_def,
             None if meta.use_ai is None else int(meta.use_ai),
             meta.estado, meta.cuadro_path, meta.duracion_ms, meta.modo, meta.carpeta_id))
        return int(cur.fetchone()["id"])

    def crear_corrida(self, meta: CorridaMeta) -> int:
        with self.cx.connection() as conn:
            return self._insert_corrida(conn, meta)

    def guardar_items(self, corrida_id: int, items: list[CorridaItemRow]) -> int:
        rows = [self._item_tuple(corrida_id, it) for it in items]
        with self.cx.connection() as conn, conn.cursor() as cur:
            cur.executemany(self._INSERT_ITEM_SQL, rows)
        return len(rows)

    def agregar_item(self, corrida_id: int, fila: CorridaItemRow) -> None:
        try:
            with self.cx.connection() as conn:
                conn.execute(self._INSERT_ITEM_SQL, self._item_tuple(corrida_id, fila))
        except psycopg.errors.ForeignKeyViolation as e:
            raise CorridaEliminada(corrida_id) from e

    def actualizar_eleccion(self, corrida_id: int, seq: int, *, status: str,
                            apu_codigo: Optional[str], apu_nombre: str, unidad: str,
                            shift: str, origen: str, confianza: float,
                            explicacion: str, componentes: list[dict]) -> None:
        with self.cx.connection() as conn:
            conn.execute(
                "UPDATE corridas.corrida_item SET status=%s, apu_codigo=%s, apu_nombre=%s, "
                "unidad=%s, shift=%s, origen=%s, confianza=%s, explicacion=%s, "
                "componentes_json=%s WHERE corrida_id=%s AND seq=%s",
                (status, apu_codigo, apu_nombre, unidad, shift, origen, confianza,
                 explicacion, json.dumps(componentes, ensure_ascii=False),
                 corrida_id, seq))

    def set_cuadro(self, corrida_id: int, path: str) -> None:
        with self.cx.connection() as conn:
            conn.execute("UPDATE corridas.corrida SET cuadro_path=%s WHERE id=%s",
                         (path, corrida_id))

    def set_estado(self, corrida_id: int, estado: str) -> None:
        with self.cx.connection() as conn:
            conn.execute("UPDATE corridas.corrida SET estado=%s WHERE id=%s",
                         (estado, corrida_id))

    def set_duracion(self, corrida_id: int, duracion_ms: int) -> None:
        with self.cx.connection() as conn:
            conn.execute("UPDATE corridas.corrida SET duracion_ms=%s WHERE id=%s",
                         (int(duracion_ms), int(corrida_id)))

    def set_modo(self, corrida_id: int, modo: str) -> None:
        with self.cx.connection() as conn:
            conn.execute("UPDATE corridas.corrida SET modo=%s WHERE id=%s",
                         (modo, int(corrida_id)))

    def set_carpeta(self, corrida_id: int, carpeta_id: int, conn=None) -> None:
        sql = "UPDATE corridas.corrida SET carpeta_id=%s WHERE id=%s"
        params = (int(carpeta_id), int(corrida_id))
        if conn is not None:
            conn.execute(sql, params); return
        with self.cx.connection() as c:
            c.execute(sql, params)

    def set_snapshot(self, corrida_id: int, seq: int, payload: dict) -> None:
        with self.cx.connection() as conn:
            conn.execute(
                "UPDATE corridas.corrida_item SET snapshot_json=%s WHERE corrida_id=%s AND seq=%s",
                (json.dumps(payload, ensure_ascii=False), int(corrida_id), int(seq)))

    def get_snapshots(self, corrida_id: int) -> dict[int, dict]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT seq, snapshot_json FROM corridas.corrida_item "
                "WHERE corrida_id=%s AND snapshot_json IS NOT NULL", (int(corrida_id),)).fetchall()
        return {r["seq"]: json.loads(r["snapshot_json"]) for r in rows}

    # ---- lectura ----
    def _row_to_item(self, r) -> CorridaItemRow:
        return CorridaItemRow(
            seq=r["seq"], item=LicitacionItem(**json.loads(r["item_json"])),
            status=r["status"], apu_codigo=r["apu_codigo"],
            apu_nombre=r["apu_nombre"] or "", unidad=r["unidad"] or "",
            shift=r["shift"] or "", origen=r["origen"] or "historico",
            confianza=r["confianza"] or 0.0, explicacion=r["explicacion"] or "",
            componentes=json.loads(r["componentes_json"] or "[]"),
            candidatos=json.loads(r["candidatos_json"] or "[]"))

    def _row_to_meta(self, r) -> CorridaMeta:
        return CorridaMeta(
            id=r["id"], creada_en=r["creada_en"], archivo=r["archivo"],
            turno_def=r["turno_def"],
            use_ai=None if r["use_ai"] is None else bool(r["use_ai"]),
            estado=r["estado"], cuadro_path=r["cuadro_path"],
            duracion_ms=r["duracion_ms"], modo=(r["modo"] or "activa"),
            carpeta_id=r["carpeta_id"])

    def get_corrida(self, corrida_id: int) -> Optional[CorridaMeta]:
        with self.cx.connection() as conn:
            r = conn.execute("SELECT * FROM corridas.corrida WHERE id=%s",
                             (corrida_id,)).fetchone()
        return self._row_to_meta(r) if r else None

    def listar_corridas(self) -> list[CorridaMeta]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM corridas.corrida ORDER BY creada_en DESC, id DESC").fetchall()
        return [self._row_to_meta(r) for r in rows]

    def eliminar_corrida(self, corrida_id: int, conn=None) -> bool:
        if conn is not None:
            cur = conn.execute("DELETE FROM corridas.corrida WHERE id=%s", (int(corrida_id),))
            return cur.rowcount > 0
        with self.cx.connection() as c:
            cur = c.execute("DELETE FROM corridas.corrida WHERE id=%s", (int(corrida_id),))
            return cur.rowcount > 0

    def get_items(self, corrida_id: int) -> list[CorridaItemRow]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM corridas.corrida_item WHERE corrida_id=%s ORDER BY seq",
                (corrida_id,)).fetchall()
        return [self._row_to_item(r) for r in rows]

    def get_item(self, corrida_id: int, seq: int) -> Optional[CorridaItemRow]:
        with self.cx.connection() as conn:
            r = conn.execute(
                "SELECT * FROM corridas.corrida_item WHERE corrida_id=%s AND seq=%s",
                (corrida_id, seq)).fetchone()
        return self._row_to_item(r) if r else None

    def counts(self) -> dict[str, int]:
        with self.cx.connection() as conn:
            return {t: conn.execute(f"SELECT COUNT(*) AS n FROM corridas.{t}").fetchone()["n"]
                    for t in ("corrida", "corrida_item")}

    def contar_items_por_apu(self, apu_codigo: str) -> int:
        with self.cx.connection() as conn:
            return conn.execute(
                "SELECT COUNT(*) AS n FROM corridas.corrida_item WHERE apu_codigo = %s",
                (str(apu_codigo),)).fetchone()["n"]
