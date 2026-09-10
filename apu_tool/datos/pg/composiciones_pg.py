"""Backend Postgres del expediente de composición. Implementa RepositorioComposiciones.
Port de composiciones_db.py.

Duplica (no importa) `_COLS`/`_j`/`_dj`/`_params`/`_fila` del backend SQLite: ningún
módulo de este paquete importa de su gemelo `apu_tool/datos/*_db.py` (ver
`corridas_pg.py`, que define su propio `_item_tuple`/`_row_to_item` en vez de
reusar los de `corridas_db.py`). Son unas pocas líneas puras; duplicarlas es más
barato que acoplar los dos backends por un import.
"""
from __future__ import annotations

import json
from typing import Any, Optional

import psycopg

from apu_tool.datos.pg.conexion import Conexion
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


class ComposicionesPg:
    def __init__(self, cx: Conexion):
        self.cx = cx

    _INSERT_SQL = (f"INSERT INTO corridas.composicion ({', '.join(_COLS)}) "
                   f"VALUES ({', '.join(['%s'] * len(_COLS))})")

    def agregar(self, fila: ComposicionRow, conn=None) -> None:
        try:
            if conn is not None:
                conn.execute(self._INSERT_SQL, _params(fila))
                return
            with self.cx.connection() as c:
                c.execute(self._INSERT_SQL, _params(fila))
        except psycopg.errors.ForeignKeyViolation as exc:
            # Mismo criterio que corridas_pg.agregar_item: la FK a `corrida` rota es
            # "la corrida ya no existe" (la borraron mientras se componía), y no tiene
            # nada que ver con un choque de versiones.
            raise CorridaEliminada(fila.corrida_id) from exc
        except psycopg.errors.UniqueViolation as exc:
            # El índice único `ux_composicion_version`: "alguien más la cambió
            # mientras trabajabas" (un 409 de concurrencia), no una corrida borrada.
            raise VersionYaExiste(fila.corrida_id, fila.seq, fila.version) from exc

    def vigente(self, corrida_id: int, seq: int) -> Optional[ComposicionRow]:
        with self.cx.connection() as conn:
            r = conn.execute(
                "SELECT * FROM corridas.composicion WHERE corrida_id=%s AND seq=%s "
                "ORDER BY version DESC LIMIT 1",
                (int(corrida_id), int(seq))).fetchone()
        return _fila(r) if r else None

    def historial(self, corrida_id: int, seq: int) -> list[ComposicionRow]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM corridas.composicion WHERE corrida_id=%s AND seq=%s "
                "ORDER BY version", (int(corrida_id), int(seq))).fetchall()
        return [_fila(r) for r in rows]
