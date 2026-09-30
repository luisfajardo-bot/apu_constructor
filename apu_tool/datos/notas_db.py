"""Acceso SQLite a la tabla `nota` (vive en seguridad.db). Implementa RepositorioNotas.

Las escrituras reciben la conexión de la unidad de trabajo (`alm.transaccion("seguridad")`)
para ir en la misma transacción que su auditoría; las lecturas abren la suya.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from apu_tool import config
from apu_tool.nucleo.models import Nota


def _fila(r) -> Nota:
    return Nota(id=int(r["id"]), entidad=r["entidad"], clave=r["clave"],
                etiqueta=r["etiqueta"], texto=r["texto"], autor_id=r["autor_id"],
                autor_email=r["autor_email"], creada_en=r["creada_en"],
                editada_en=r["editada_en"], borrada=bool(r["borrada"]),
                responde_a=r["responde_a"])


class NotasDB:
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

    def crear(self, conn, entidad: str, clave: str, etiqueta: str, texto: str,
              autor_id: str, autor_email: str, creada_en: str) -> int:
        cur = conn.execute(
            "INSERT INTO nota (entidad, clave, etiqueta, texto, autor_id, autor_email, creada_en) "
            "VALUES (?,?,?,?,?,?,?)",
            (entidad, clave, etiqueta, texto, autor_id, autor_email, creada_en))
        return int(cur.lastrowid)

    def get(self, nota_id: int) -> Optional[Nota]:
        with self.connect() as conn:
            r = conn.execute("SELECT * FROM nota WHERE id=?", (int(nota_id),)).fetchone()
        return _fila(r) if r else None

    def listar(self, entidad: str, clave: str) -> list[Nota]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM nota WHERE entidad=? AND clave=? AND borrada=0 ORDER BY id",
                (entidad, clave)).fetchall()
        return [_fila(r) for r in rows]

    def editar(self, conn, nota_id: int, texto: str, editada_en: str) -> None:
        conn.execute("UPDATE nota SET texto=?, editada_en=? WHERE id=?",
                     (texto, editada_en, int(nota_id)))

    def borrar(self, conn, nota_id: int) -> None:
        conn.execute("UPDATE nota SET borrada=1 WHERE id=?", (int(nota_id),))

    def resumen_por_claves(self, entidad: str, claves: list[str]) -> dict[str, str]:
        if not claves:
            return {}
        marcas = ",".join("?" * len(claves))
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT clave, texto FROM nota WHERE entidad=? AND borrada=0 "
                f"AND clave IN ({marcas}) ORDER BY id", [entidad, *claves]).fetchall()
        return {r["clave"]: r["texto"] for r in rows}      # la última gana

    def buscar(self, *, entidad: Optional[str] = None, autor_id: Optional[str] = None,
               q: Optional[str] = None, limit: int = 100,
               offset: int = 0) -> tuple[list[Nota], int]:
        where, params = ["borrada=0"], []
        if entidad:
            where.append("entidad=?"); params.append(entidad)
        if autor_id:
            where.append("autor_id=?"); params.append(autor_id)
        if q:
            where.append("(lower(texto) LIKE ? OR lower(etiqueta) LIKE ?)")
            params += [f"%{q.lower()}%"] * 2
        wsql = " WHERE " + " AND ".join(where)
        with self.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM nota{wsql}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM nota{wsql} ORDER BY creada_en DESC, id DESC LIMIT ? OFFSET ?",
                params + [int(limit), int(offset)]).fetchall()
        return [_fila(r) for r in rows], int(total)
