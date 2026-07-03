"""
Acceso a corridas.db (SQLite): estado de aplicación de un armado en progreso.

Implementa RepositorioCorridas. Guarda DECISIONES y ESTRUCTURA, nunca dinero
derivado (el costo se recalcula con el precio vigente). El único valor monetario
que persiste es el precio_contractual de entrada, embebido en item_json.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Iterator, Optional

from apu_tool import config
from apu_tool.datos.repositorio import CorridaEliminada
from apu_tool.nucleo.models import CorridaItemRow, CorridaMeta, LicitacionItem

SCHEMA_PATH = config.PROJECT_ROOT / "db" / "corridas.sql"


def _load_schema() -> str:
    return SCHEMA_PATH.read_text(encoding="utf-8")


class CorridasDB:
    """Backend SQLite de corridas. Implementa RepositorioCorridas."""

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

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(_load_schema())
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(corrida)").fetchall()}
            if "duracion_ms" not in cols:
                conn.execute("ALTER TABLE corrida ADD COLUMN duracion_ms INTEGER")

    def reset(self) -> None:
        with self.connect() as conn:
            for t in ("corrida_item", "corrida"):
                conn.execute(f"DROP TABLE IF EXISTS {t}")
            conn.executescript(_load_schema())

    # ---- escritura ----
    _INSERT_ITEM_SQL = (
        "INSERT INTO corrida_item "
        "(corrida_id, seq, item_json, status, apu_codigo, apu_nombre, unidad, "
        " shift, origen, confianza, explicacion, componentes_json, candidatos_json) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)")

    @staticmethod
    def _item_tuple(corrida_id: int, it: CorridaItemRow) -> tuple:
        return (corrida_id, it.seq, json.dumps(asdict(it.item), ensure_ascii=False),
                it.status, it.apu_codigo, it.apu_nombre, it.unidad, it.shift,
                it.origen, it.confianza, it.explicacion,
                json.dumps(it.componentes, ensure_ascii=False),
                json.dumps(it.candidatos, ensure_ascii=False))

    def _insert_corrida(self, conn: sqlite3.Connection, meta: CorridaMeta) -> int:
        cur = conn.execute(
            "INSERT INTO corrida (creada_en, archivo, turno_def, use_ai, estado, "
            "cuadro_path, duracion_ms) VALUES (?,?,?,?,?,?,?)",
            (meta.creada_en, meta.archivo, meta.turno_def,
             None if meta.use_ai is None else int(meta.use_ai),
             meta.estado, meta.cuadro_path, meta.duracion_ms))
        return int(cur.lastrowid)

    def crear_corrida(self, meta: CorridaMeta) -> int:
        with self.connect() as conn:
            return self._insert_corrida(conn, meta)

    def guardar_items(self, corrida_id: int, items: list[CorridaItemRow]) -> int:
        rows = [self._item_tuple(corrida_id, it) for it in items]
        with self.connect() as conn:
            conn.executemany(self._INSERT_ITEM_SQL, rows)
        return len(rows)

    def agregar_item(self, corrida_id: int, fila: CorridaItemRow) -> None:
        """Inserta un ítem (armado incremental: se persiste cada APU al armarlo).

        Si la corrida ya no existe (la borraron o se reseteó durante el armado), el
        INSERT viola la FK; se traduce a ``CorridaEliminada`` para que la capa de
        servicio cancele el armado limpio en vez de propagar el error de integridad.
        """
        try:
            with self.connect() as conn:
                conn.execute(self._INSERT_ITEM_SQL, self._item_tuple(corrida_id, fila))
        except sqlite3.IntegrityError as e:
            raise CorridaEliminada(corrida_id) from e

    def actualizar_eleccion(self, corrida_id: int, seq: int, *, status: str,
                            apu_codigo: Optional[str], apu_nombre: str, unidad: str,
                            shift: str, origen: str, confianza: float,
                            explicacion: str, componentes: list[dict]) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE corrida_item SET status=?, apu_codigo=?, apu_nombre=?, unidad=?, "
                "shift=?, origen=?, confianza=?, explicacion=?, componentes_json=? "
                "WHERE corrida_id=? AND seq=?",
                (status, apu_codigo, apu_nombre, unidad, shift, origen, confianza,
                 explicacion, json.dumps(componentes, ensure_ascii=False),
                 corrida_id, seq))

    def set_cuadro(self, corrida_id: int, path: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE corrida SET cuadro_path=? WHERE id=?", (path, corrida_id))

    def set_estado(self, corrida_id: int, estado: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE corrida SET estado=? WHERE id=?", (estado, corrida_id))

    def set_duracion(self, corrida_id: int, duracion_ms: int) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE corrida SET duracion_ms=? WHERE id=?",
                         (int(duracion_ms), int(corrida_id)))

    # ---- lectura ----
    def _row_to_item(self, r: sqlite3.Row) -> CorridaItemRow:
        return CorridaItemRow(
            seq=r["seq"], item=LicitacionItem(**json.loads(r["item_json"])),
            status=r["status"], apu_codigo=r["apu_codigo"],
            apu_nombre=r["apu_nombre"] or "", unidad=r["unidad"] or "",
            shift=r["shift"] or "", origen=r["origen"] or "historico",
            confianza=r["confianza"] or 0.0, explicacion=r["explicacion"] or "",
            componentes=json.loads(r["componentes_json"] or "[]"),
            candidatos=json.loads(r["candidatos_json"] or "[]"))

    def _row_to_meta(self, r: sqlite3.Row) -> CorridaMeta:
        return CorridaMeta(
            id=r["id"], creada_en=r["creada_en"], archivo=r["archivo"],
            turno_def=r["turno_def"],
            use_ai=None if r["use_ai"] is None else bool(r["use_ai"]),
            estado=r["estado"], cuadro_path=r["cuadro_path"],
            duracion_ms=r["duracion_ms"])

    def get_corrida(self, corrida_id: int) -> Optional[CorridaMeta]:
        with self.connect() as conn:
            r = conn.execute("SELECT * FROM corrida WHERE id=?", (corrida_id,)).fetchone()
        return self._row_to_meta(r) if r else None

    def listar_corridas(self) -> list[CorridaMeta]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM corrida ORDER BY creada_en DESC, id DESC").fetchall()
        return [self._row_to_meta(r) for r in rows]

    def eliminar_corrida(self, corrida_id: int, conn=None) -> bool:
        if conn is not None:
            cur = conn.execute("DELETE FROM corrida WHERE id=?", (int(corrida_id),))
            return cur.rowcount > 0
        with self.connect() as c:
            cur = c.execute("DELETE FROM corrida WHERE id=?", (int(corrida_id),))
            return cur.rowcount > 0

    def get_items(self, corrida_id: int) -> list[CorridaItemRow]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM corrida_item WHERE corrida_id=? ORDER BY seq",
                (corrida_id,)).fetchall()
        return [self._row_to_item(r) for r in rows]

    def get_item(self, corrida_id: int, seq: int) -> Optional[CorridaItemRow]:
        with self.connect() as conn:
            r = conn.execute(
                "SELECT * FROM corrida_item WHERE corrida_id=? AND seq=?",
                (corrida_id, seq)).fetchone()
        return self._row_to_item(r) if r else None

    def counts(self) -> dict[str, int]:
        with self.connect() as conn:
            return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    for t in ("corrida", "corrida_item")}

    def contar_items_por_apu(self, apu_codigo: str) -> int:
        with self.connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM corrida_item WHERE apu_codigo = ?",
                (str(apu_codigo),)).fetchone()[0]
