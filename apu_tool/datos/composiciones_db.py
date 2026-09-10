"""Acceso a la tabla `composicion` (vive en corridas.db). Implementa
RepositorioComposiciones.

Append-only: `agregar` escribe una versión y nunca actualiza. La `version` la manda el
llamador (`version_base + 1`), NO se calcula acá con un MAX+1: si se calculara adentro,
dos clics seguidos sacarían 4 y 5 y los dos entrarían, y el índice único no protegería
nada. Con la versión explícita, el segundo choca y el servicio devuelve 409.

Como CarpetasDB, comparte el archivo corridas.db y no tiene init_schema propio: la
tabla se crea con el resto del esquema (`db/corridas.sql`, cargado por CorridasDB).
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from apu_tool import config
from apu_tool.datos.repositorio import CorridaEliminada, VersionYaExiste
from apu_tool.nucleo.models import ComposicionRow

_COLS = ("corrida_id", "seq", "version", "estado", "actividad_json", "ficha_json",
         "propuesta_json", "validacion_json", "confianza", "confianza_json",
         "antecedentes_json", "modelo", "prompt_version", "apu_codigo", "apu_turno",
         "autor", "creada_en", "motivo")


def _j(v: Any) -> Optional[str]:
    return None if v is None else json.dumps(v, ensure_ascii=False)


def _dj(v: Any) -> Any:
    return None if v in (None, "") else json.loads(v)


def _params(f: ComposicionRow) -> tuple:
    return (int(f.corrida_id), int(f.seq), int(f.version), f.estado,
            _j(f.actividad), _j(f.ficha), _j(f.propuesta), _j(f.validacion),
            f.confianza, _j(f.confianza_motivos), _j(f.antecedentes), f.modelo,
            f.prompt_version, f.apu_codigo, f.apu_turno, f.autor, f.creada_en,
            f.motivo)


def _fila(r) -> ComposicionRow:
    return ComposicionRow(
        id=r["id"], corrida_id=r["corrida_id"], seq=r["seq"], version=r["version"],
        estado=r["estado"], actividad=_dj(r["actividad_json"]) or {},
        ficha=_dj(r["ficha_json"]), propuesta=_dj(r["propuesta_json"]),
        validacion=_dj(r["validacion_json"]), confianza=r["confianza"],
        confianza_motivos=_dj(r["confianza_json"]),
        antecedentes=_dj(r["antecedentes_json"]), modelo=r["modelo"],
        prompt_version=r["prompt_version"], apu_codigo=r["apu_codigo"],
        apu_turno=r["apu_turno"], autor=r["autor"], creada_en=r["creada_en"],
        motivo=r["motivo"])


class ComposicionesDB:
    """Backend SQLite del expediente de composición."""

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

    def agregar(self, fila: ComposicionRow, conn=None) -> None:
        sql = (f"INSERT INTO composicion ({', '.join(_COLS)}) "
               f"VALUES ({', '.join('?' * len(_COLS))})")
        try:
            if conn is not None:
                conn.execute(sql, _params(fila))
                return
            with self.connect() as c:
                c.execute(sql, _params(fila))
        except sqlite3.IntegrityError as exc:
            # `IntegrityError` cubre DOS violaciones y significan cosas distintas para
            # el usuario: el índice único es "alguien más la cambió mientras
            # trabajabas" (un 409 de concurrencia), y el FK a `corrida` es "la corrida
            # ya no existe" (la borraron mientras componías). Confundirlas manda a
            # buscar un conflicto de edición que no pasó. Se distingue por
            # `sqlite_errorname` (no por el texto del mensaje, que no está
            # garantizado), mismo criterio que `corridas_db.agregar_item`.
            if getattr(exc, "sqlite_errorname", "") == "SQLITE_CONSTRAINT_FOREIGNKEY":
                raise CorridaEliminada(fila.corrida_id) from exc
            raise VersionYaExiste(fila.corrida_id, fila.seq, fila.version) from exc

    def vigente(self, corrida_id: int, seq: int) -> Optional[ComposicionRow]:
        with self.connect() as conn:
            r = conn.execute(
                "SELECT * FROM composicion WHERE corrida_id=? AND seq=? "
                "ORDER BY version DESC LIMIT 1",
                (int(corrida_id), int(seq))).fetchone()
        return _fila(r) if r else None

    def historial(self, corrida_id: int, seq: int) -> list[ComposicionRow]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM composicion WHERE corrida_id=? AND seq=? "
                "ORDER BY version", (int(corrida_id), int(seq))).fetchall()
        return [_fila(r) for r in rows]
