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
        conn.execute("UPDATE nota SET texto=?, editada_en=? WHERE id=? AND borrada=0",
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
            where.append("(cf(texto) LIKE ? OR cf(etiqueta) LIKE ?)")
            params += [f"%{q.casefold()}%"] * 2
        wsql = " WHERE " + " AND ".join(where)
        with self.connect() as conn:
            # lower() de SQLite es solo ASCII; casefold da paridad con ILIKE de Postgres
            conn.create_function("cf", 1, lambda s: (s or "").casefold(), deterministic=True)
            total = conn.execute(f"SELECT COUNT(*) FROM nota{wsql}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM nota{wsql} ORDER BY creada_en DESC, id DESC LIMIT ? OFFSET ?",
                params + [int(limit), int(offset)]).fetchall()
        return [_fila(r) for r in rows], int(total)

    # ---- Fase 2: menciones ----
    def set_menciones(self, conn, nota_id: int, user_ids: list[str],
                      creada_en: str) -> list[str]:
        actuales = {r["user_id"] for r in conn.execute(
            "SELECT user_id FROM nota_mencion WHERE nota_id=?", (int(nota_id),))}
        deseados = list(dict.fromkeys(user_ids))            # dedup conservando el orden
        for u in actuales - set(deseados):
            conn.execute("DELETE FROM nota_mencion WHERE nota_id=? AND user_id=?",
                         (int(nota_id), u))
        nuevos = [u for u in deseados if u not in actuales]
        for u in nuevos:
            conn.execute("INSERT INTO nota_mencion (nota_id, user_id, creada_en) "
                         "VALUES (?,?,?)", (int(nota_id), u, creada_en))
        return nuevos

    def reasignar_mencionado(self, conn, viejo: str, nuevo: str) -> None:
        conn.execute("UPDATE nota_mencion SET user_id=? WHERE user_id=?", (nuevo, viejo))

    def menciones_de_notas(self, nota_ids: list[int]) -> dict[int, list[str]]:
        if not nota_ids:
            return {}
        marcas = ",".join("?" * len(nota_ids))
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT nota_id, user_id FROM nota_mencion WHERE nota_id IN ({marcas}) "
                f"ORDER BY nota_id, user_id", [int(i) for i in nota_ids]).fetchall()
        out: dict[int, list[str]] = {}
        for r in rows:
            out.setdefault(int(r["nota_id"]), []).append(r["user_id"])
        return out

    def contar_sin_leer(self, user_id: str) -> int:
        with self.connect() as conn:
            return int(conn.execute(
                "SELECT COUNT(*) FROM nota_mencion m JOIN nota n ON n.id = m.nota_id "
                "WHERE m.user_id=? AND m.leida_en IS NULL AND n.borrada=0",
                (user_id,)).fetchone()[0])

    def listar_menciones(self, user_id: str,
                         limit: int = 50) -> list[tuple[Nota, Optional[str]]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT n.*, m.leida_en AS mencion_leida_en FROM nota_mencion m "
                "JOIN nota n ON n.id = m.nota_id WHERE m.user_id=? AND n.borrada=0 "
                "ORDER BY m.creada_en DESC, n.id DESC LIMIT ?",
                (user_id, int(limit))).fetchall()
        return [(_fila(r), r["mencion_leida_en"]) for r in rows]

    def marcar_leida(self, conn, user_id: str, nota_id: int, leida_en: str) -> None:
        conn.execute("UPDATE nota_mencion SET leida_en=? WHERE user_id=? AND nota_id=? "
                     "AND leida_en IS NULL", (leida_en, user_id, int(nota_id)))

    def marcar_todas_leidas(self, conn, user_id: str, leida_en: str) -> None:
        conn.execute("UPDATE nota_mencion SET leida_en=? WHERE user_id=? "
                     "AND leida_en IS NULL", (leida_en, user_id))
