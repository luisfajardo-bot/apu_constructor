"""Backend Postgres de notas (seguridad.nota). Espejo 1:1 de datos/notas_db.py."""
from __future__ import annotations

from typing import Optional

from apu_tool.datos.pg.conexion import Conexion
from apu_tool.nucleo.models import Nota


def _fila(r) -> Nota:
    return Nota(id=int(r["id"]), entidad=r["entidad"], clave=r["clave"],
                etiqueta=r["etiqueta"], texto=r["texto"], autor_id=r["autor_id"],
                autor_email=r["autor_email"], creada_en=r["creada_en"],
                editada_en=r["editada_en"], borrada=bool(r["borrada"]),
                responde_a=r["responde_a"])


class NotasPg:
    def __init__(self, cx: Conexion):
        self.cx = cx

    def crear(self, conn, entidad: str, clave: str, etiqueta: str, texto: str,
              autor_id: str, autor_email: str, creada_en: str) -> int:
        r = conn.execute(
            "INSERT INTO seguridad.nota "
            "(entidad, clave, etiqueta, texto, autor_id, autor_email, creada_en) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (entidad, clave, etiqueta, texto, autor_id, autor_email, creada_en)).fetchone()
        return int(r["id"])

    def get(self, nota_id: int) -> Optional[Nota]:
        with self.cx.connection() as conn:
            r = conn.execute("SELECT * FROM seguridad.nota WHERE id=%s",
                             (int(nota_id),)).fetchone()
        return _fila(r) if r else None

    def listar(self, entidad: str, clave: str) -> list[Nota]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM seguridad.nota WHERE entidad=%s AND clave=%s AND borrada=0 "
                "ORDER BY id", (entidad, clave)).fetchall()
        return [_fila(r) for r in rows]

    def editar(self, conn, nota_id: int, texto: str, editada_en: str) -> None:
        conn.execute("UPDATE seguridad.nota SET texto=%s, editada_en=%s WHERE id=%s AND borrada=0",
                     (texto, editada_en, int(nota_id)))

    def borrar(self, conn, nota_id: int) -> None:
        conn.execute("UPDATE seguridad.nota SET borrada=1 WHERE id=%s", (int(nota_id),))

    def resumen_por_claves(self, entidad: str, claves: list[str]) -> dict[str, str]:
        if not claves:
            return {}
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT clave, texto FROM seguridad.nota WHERE entidad=%s AND borrada=0 "
                "AND clave = ANY(%s) ORDER BY id", (entidad, list(claves))).fetchall()
        return {r["clave"]: r["texto"] for r in rows}      # la última gana

    def buscar(self, *, entidad: Optional[str] = None, autor_id: Optional[str] = None,
               q: Optional[str] = None, limit: int = 100,
               offset: int = 0) -> tuple[list[Nota], int]:
        where, params = ["borrada=0"], []
        if entidad:
            where.append("entidad=%s"); params.append(entidad)
        if autor_id:
            where.append("autor_id=%s"); params.append(autor_id)
        if q:
            where.append("(texto ILIKE %s OR etiqueta ILIKE %s)")
            params += [f"%{q}%"] * 2
        wsql = " WHERE " + " AND ".join(where)
        with self.cx.connection() as conn:
            total = conn.execute(f"SELECT COUNT(*) AS n FROM seguridad.nota{wsql}",
                                 params).fetchone()["n"]
            rows = conn.execute(
                f"SELECT * FROM seguridad.nota{wsql} ORDER BY creada_en DESC, id DESC "
                f"LIMIT %s OFFSET %s", params + [int(limit), int(offset)]).fetchall()
        return [_fila(r) for r in rows], int(total)
