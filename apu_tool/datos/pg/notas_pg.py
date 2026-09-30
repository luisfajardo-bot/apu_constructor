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

    # ---- Fase 2: menciones (espejo de notas_db.py) ----
    def set_menciones(self, conn, nota_id: int, user_ids: list[str],
                      creada_en: str) -> list[str]:
        actuales = {r["user_id"] for r in conn.execute(
            "SELECT user_id FROM seguridad.nota_mencion WHERE nota_id=%s",
            (int(nota_id),)).fetchall()}
        deseados = list(dict.fromkeys(user_ids))
        for u in actuales - set(deseados):
            conn.execute("DELETE FROM seguridad.nota_mencion WHERE nota_id=%s AND user_id=%s",
                         (int(nota_id), u))
        nuevos = [u for u in deseados if u not in actuales]
        for u in nuevos:
            conn.execute("INSERT INTO seguridad.nota_mencion (nota_id, user_id, creada_en) "
                         "VALUES (%s,%s,%s)", (int(nota_id), u, creada_en))
        return nuevos

    def reasignar_mencionado(self, conn, viejo: str, nuevo: str) -> None:
        conn.execute("UPDATE seguridad.nota_mencion SET user_id=%s WHERE user_id=%s",
                     (nuevo, viejo))

    def menciones_de_notas(self, nota_ids: list[int]) -> dict[int, list[str]]:
        if not nota_ids:
            return {}
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT nota_id, user_id FROM seguridad.nota_mencion "
                "WHERE nota_id = ANY(%s) ORDER BY nota_id, user_id",
                ([int(i) for i in nota_ids],)).fetchall()
        out: dict[int, list[str]] = {}
        for r in rows:
            out.setdefault(int(r["nota_id"]), []).append(r["user_id"])
        return out

    def contar_sin_leer(self, user_id: str) -> int:
        with self.cx.connection() as conn:
            return int(conn.execute(
                "SELECT COUNT(*) AS n FROM seguridad.nota_mencion m "
                "JOIN seguridad.nota n ON n.id = m.nota_id "
                "WHERE m.user_id=%s AND m.leida_en IS NULL AND n.borrada=0",
                (user_id,)).fetchone()["n"])

    def listar_menciones(self, user_id: str,
                         limit: int = 50) -> list[tuple[Nota, Optional[str]]]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT n.*, m.leida_en AS mencion_leida_en FROM seguridad.nota_mencion m "
                "JOIN seguridad.nota n ON n.id = m.nota_id "
                "WHERE m.user_id=%s AND n.borrada=0 "
                "ORDER BY m.creada_en DESC, n.id DESC LIMIT %s",
                (user_id, int(limit))).fetchall()
        return [(_fila(r), r["mencion_leida_en"]) for r in rows]

    def marcar_leida(self, conn, user_id: str, nota_id: int, leida_en: str) -> None:
        conn.execute("UPDATE seguridad.nota_mencion SET leida_en=%s WHERE user_id=%s "
                     "AND nota_id=%s AND leida_en IS NULL", (leida_en, user_id, int(nota_id)))

    def marcar_todas_leidas(self, conn, user_id: str, leida_en: str) -> None:
        conn.execute("UPDATE seguridad.nota_mencion SET leida_en=%s WHERE user_id=%s "
                     "AND leida_en IS NULL", (leida_en, user_id))
